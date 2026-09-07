-- OnePulse initial schema — Low-Level Design Section 1, with five real
-- deviations found and confirmed 2026-09-05 via a direct cross-check
-- against the live pipeline's actual JSON output before this file was
-- written (not implemented from the abstract design and hoped to fit):
--
--   1. findings.evidence is TEXT, not TEXT[] — real Investigation
--      output (INVESTIGATION_SCHEMA) produces one evidence string per
--      finding, never an array.
--   2. findings.status_label has an explicit CHECK for FR-1's real
--      four-level taxonomy — the LLD's own summary table didn't spell
--      this out, but the real schema (INVESTIGATION_SCHEMA) already
--      enforces exactly these four values.
--   3. untracked_items.reasoning (TEXT) replaces match_confidence
--      (NUMERIC) — real Status Update Analysis output never produces a
--      numeric score; possible_connections carries free-text reasoning
--      instead.
--   4. reports.curated_features / curated_initiatives (JSONB) are
--      DROPPED. No real curation step exists in the Now-scope pipeline
--      — Synthesis produces one narrative string, and Rendering reads
--      raw findings directly. Populating these with raw data would
--      mislabel uncurated JSON as curated; re-add via a real migration
--      once a genuine curation phase is actually scoped.
--   5. reports.quality_gate_outcome (TEXT, new) captures the real,
--      already-proven HLD Section 3 / FR-4 revision-cap outcome
--      (approved vs. route_to_human_review — hard_stop_defect never
--      reaches this table at all, since nothing is persisted when it
--      fires, per Task 7's own regression tests). The LLD's literal
--      column list predates this pipeline's real behavior; not adding
--      this would silently discard signal the pipeline already
--      generates every run.
--
-- Also added, found missing during DDL design itself (not from the
-- JSON cross-check, but real all the same): findings.title. The LLD's
-- key-columns summary for `findings` never lists a title column, but
-- real Investigation output and real Rendering (report_rendering.py's
-- Finding dataclass) both require it — dropping it would mean losing
-- exactly the field the rendered slide displays for every finding.
--
-- Idempotent: every statement can be re-run safely. Run via
-- scripts/migrate.py, never applied by hand.

-- -- Tenant hierarchy (resolves Step 2 Gap 1: no portfolio layer)
CREATE TABLE IF NOT EXISTS tenants (
    tenant_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS portfolios (
    portfolio_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id),
    name TEXT NOT NULL,
    UNIQUE (tenant_id, name)
);

CREATE TABLE IF NOT EXISTS programs (
    program_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id UUID NOT NULL REFERENCES portfolios(portfolio_id),
    name TEXT NOT NULL,
    source_system_ref TEXT,
    UNIQUE (portfolio_id, name)
);

-- Configuration completeness is a DATABASE GUARANTEE, not app logic
-- (closes the HLD Step 7 onboarding mechanism at the schema level)
CREATE TABLE IF NOT EXISTS configurations (
    program_id UUID PRIMARY KEY REFERENCES programs(program_id),
    feature_agent_config JSONB,
    status_report_agent_config JSONB,
    synthesis_agent_config JSONB,
    critique_agent_config JSONB,
    slide_generation_agent_config JSONB,
    manifest_complete BOOLEAN GENERATED ALWAYS AS (
        feature_agent_config IS NOT NULL AND
        status_report_agent_config IS NOT NULL AND
        synthesis_agent_config IS NOT NULL AND
        critique_agent_config IS NOT NULL AND
        slide_generation_agent_config IS NOT NULL
    ) STORED
);

-- reports: real deviations 4 (curated_features/curated_initiatives
-- dropped) and 5 (quality_gate_outcome added) applied below.
CREATE TABLE IF NOT EXISTS reports (
    report_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    program_id UUID NOT NULL REFERENCES programs(program_id),
    week_of DATE NOT NULL,
    rag_status TEXT NOT NULL CHECK (rag_status IN ('Red','Amber','Green','Unknown')),
    quality_gate_outcome TEXT NOT NULL CHECK (quality_gate_outcome IN ('approved','route_to_human_review')),
    executive_summary TEXT NOT NULL,
    trend_line TEXT NOT NULL DEFAULT '',
    prior_report_id BIGINT REFERENCES reports(report_id),
    rendered_artifact_uri TEXT,
    attempts INT NOT NULL DEFAULT 1,
    reviewed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (program_id, week_of)
);

-- findings: real deviations 1, 2, and the added `title` column.
-- Per-item evidence trail (NFR-11).
CREATE TABLE IF NOT EXISTS findings (
    finding_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    report_id BIGINT NOT NULL REFERENCES reports(report_id),
    source_item_ref TEXT NOT NULL,
    title TEXT NOT NULL,
    status_label TEXT NOT NULL CHECK (status_label IN ('On Track','At Risk','Blocked','Needs Human Review')),
    evidence TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- untracked_items: real deviation 3 (reasoning replaces
-- match_confidence). One table for both real Status Update Analysis
-- shapes: plain untracked initiatives (possible_linked_finding_id and
-- reasoning both NULL) and possible connections to tracked work
-- (both set).
CREATE TABLE IF NOT EXISTS untracked_items (
    untracked_item_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    report_id BIGINT NOT NULL REFERENCES reports(report_id),
    description TEXT NOT NULL,
    evidence TEXT,
    possible_linked_finding_id BIGINT REFERENCES findings(finding_id),
    reasoning TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Append-only by GRANT, not by convention (resolves Step 2 Gap 5:
-- reviewer attribution)
CREATE TABLE IF NOT EXISTS actors (
    actor_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id),
    role TEXT NOT NULL CHECK (role IN ('portfolio_lead','program_lead','platform_admin')),
    entra_object_id TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS approval_records (
    approval_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    report_id BIGINT NOT NULL REFERENCES reports(report_id),
    decision TEXT NOT NULL CHECK (decision IN ('approved','rejected')),
    actor_id UUID NOT NULL REFERENCES actors(actor_id),
    notes TEXT NOT NULL DEFAULT '',
    decided_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- What each actor is authorized to see: exactly one of portfolio-level
-- or program-level scope per row.
CREATE TABLE IF NOT EXISTS actor_scope (
    scope_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor_id UUID NOT NULL REFERENCES actors(actor_id),
    portfolio_id UUID REFERENCES portfolios(portfolio_id),
    program_id UUID REFERENCES programs(program_id),
    CHECK (num_nonnulls(portfolio_id, program_id) = 1)
);

-- Cost-based governance (resolves Step 2 Gap 3: was request-count, not cost)
CREATE TABLE IF NOT EXISTS usage_ledger (
    usage_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id),
    program_id UUID REFERENCES programs(program_id),
    estimated_cost_usd NUMERIC(10,4),
    actual_cost_usd NUMERIC(10,4),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Tenant isolation (resolves Step 2 Gap 1: enforced at the database,
-- not app code). Build Plan Scoping Notes mark *active enforcement* as
-- Next-scope (one real tenant/portfolio/program row is sufficient for
-- Now); the policy itself is installed now per explicit direction.
ALTER TABLE reports ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON reports;
CREATE POLICY tenant_isolation ON reports USING (
    program_id IN (
        SELECT p.program_id FROM programs p
        JOIN portfolios pf ON p.portfolio_id = pf.portfolio_id
        WHERE pf.tenant_id = current_setting('app.current_tenant_id')::uuid
    )
);

-- Least-privilege grants: SELECT + INSERT baseline for both the
-- deployed workload identity and the local-dev identity, per
-- create_app_role_local_dev.sql's own requirement that the two roles
-- carry identical table-level privileges. UPDATE added only where the
-- real pipeline (now or in the immediately-next phase) actually needs
-- it: configurations (re-onboarding) and reports (Human Governance
-- setting `reviewed`, Phase 7). No DELETE grant anywhere — nothing in
-- the real pipeline deletes rows.
DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['app_role', 'app_role_local_dev']
    LOOP
        EXECUTE format('GRANT SELECT, INSERT ON tenants, portfolios, programs, findings, untracked_items, actors, actor_scope, usage_ledger, approval_records TO %I', r);
        EXECUTE format('GRANT SELECT, INSERT, UPDATE ON configurations, reports TO %I', r);
        EXECUTE format('GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO %I', r);
    END LOOP;
END $$;

-- Append-only by GRANT, not by convention (resolves Step 2 Gap 5):
-- REVOKE explicitly, even though UPDATE/DELETE were never granted above
-- — this is the actual enforcement mechanism LLD Section 1 specifies,
-- and guards against a future blanket GRANT elsewhere silently
-- reopening it. Applied to both roles per create_app_role_local_dev.sql's
-- own requirement that local dev be genuine evidence of what the
-- deployed workload can do.
REVOKE UPDATE, DELETE ON approval_records FROM app_role;
REVOKE UPDATE, DELETE ON approval_records FROM app_role_local_dev;
