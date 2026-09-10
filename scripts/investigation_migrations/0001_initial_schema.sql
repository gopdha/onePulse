-- Migration Plan Phase 4 (ADR-019/ADR-020): database-per-service. The
-- Investigation service gets its own real Postgres schema and its own
-- real role — never `public`, where `reports`/`findings`/`cycles`/etc.
-- live, and never granted to the Reporting service's role either. This
-- is the same structural (not disciplinary) enforcement already proven
-- for the BFF's "no data store" guarantee in Phase 2, applied to a
-- second, independent boundary — see
-- tests/test_investigation_schema_isolation.py for the real, adversarial
-- proof (both directions fail with a genuine InsufficientPrivilegeError).
--
-- REAL, LOAD-BEARING DIFFERENCE FROM 0001-0003: this file is NOT applied
-- by scripts/migrate.py (which always connects as app_role/
-- app_role_local_dev — the Reporting role). It is applied by the
-- companion scripts/migrate_investigation.py, connecting as
-- investigation_role/investigation_role_local_dev instead. This is a
-- real, deliberate, load-bearing choice, not an accident of file
-- placement: `CREATE SCHEMA investigation` run by the Reporting role
-- would make the REPORTING role the schema's OWNER, and Postgres
-- ownership grants full access regardless of any GRANT/REVOKE placed on
-- top of it afterward — the exact same class of gap Task 31 already
-- found once for RLS (table ownership bypasses `FORCE ROW LEVEL
-- SECURITY`). Having the Investigation role create (and therefore own)
-- its own schema from the very first `CREATE SCHEMA` avoids that trap
-- entirely, rather than requiring a manual ALTER SCHEMA OWNER TO /
-- REVOKE ALL FROM cleanup afterward (both real, both needed, both
-- already performed once by hand against onepulse-pg-dev before this
-- file reached its current, correct shape — kept here as the honest
-- record of a real mistake made and fixed, not smoothed over).
--
-- SECOND, MORE SUBTLE INSTANCE OF THE SAME TRAP, found only at merge
-- review by adding the first positive-grant check this project's
-- verify_migration.py has ever had (Migration Plan Phase 4, CLAUDE.md
-- Task 43 merge follow-up): fixing the SCHEMA's owner does NOT fix the
-- owner of any TABLE already created inside it — schema ownership and
-- table ownership are independent in Postgres. `investigation.
-- investigation_runs` itself was still owned by `app_role_local_dev`
-- (from the same original pre-migrate_investigation.py run that caused
-- the schema-ownership bug above), silently giving the Reporting role
-- full implicit access to the very table this whole phase exists to
-- wall off — undetected by every existence/negative-privilege check
-- already in place, since none of them asked "can this role positively
-- use this object" for the table itself. Fixed live via `ALTER TABLE
-- investigation.investigation_runs OWNER TO investigation_role_local_dev`
-- (as the real Postgres Entra Administrator — `app_role_local_dev`
-- cannot run it: it lacks USAGE on the schema, and ownership alone
-- doesn't let it reference a schema-qualified name it can't resolve).
-- Not a defect in this migration file's own SQL: a genuinely fresh
-- environment applying this file via `migrate_investigation.py`
-- (connecting as the Investigation role throughout) gets correct
-- ownership on both the schema AND the table from the very first
-- `CREATE SCHEMA`/`CREATE TABLE` — this was purely residue from the one
-- historical bad run, now cleaned up. The lesson generalizes: after any
-- ownership-transfer cleanup, verify ownership of every object the
-- schema contains individually, not just the schema itself.
--
-- Real, deliberate consequence of the split (ADR-020's own accepted
-- trade-off, implemented as such, not worked around): `findings`
-- (public schema) has a real FK to `reports`. Across the service
-- boundary that FK cannot exist — Investigation cannot reference a
-- `reports` row it has no access to. `investigation.investigation_runs`
-- stores raw per-item results keyed on the real cycle_id (a plain
-- value, not a foreign key to `cycles`, for the identical reason), and
-- the Reporting service fetches them over HTTP, then persists its own,
-- separate copy into the real `findings` table linked to a real
-- `report_id`. The same real finding data now legitimately lives in two
-- places — referential integrity traded for real service autonomy, per
-- ADR-020, not an oversight.
--
-- Keyed on cycle_id with ON CONFLICT DO UPDATE, not a plain INSERT:
-- Storage Queues are at-least-once delivery, so Investigation can
-- legitimately process the same real request twice — redelivery must
-- overwrite, never accumulate, per the Migration Plan's own explicit
-- instruction.
--
-- Idempotent: every statement can be re-run safely. Run via
-- scripts/migrate_investigation.py, never applied by hand and never via
-- scripts/migrate.py.

CREATE SCHEMA IF NOT EXISTS investigation;

CREATE TABLE IF NOT EXISTS investigation.investigation_runs (
    cycle_id UUID PRIMARY KEY,
    program_name TEXT NOT NULL,
    requested_by_actor_id UUID,
    status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'completed', 'failed')),
    queried_item_count INT,
    findings JSONB,
    tower_hierarchy JSONB,
    error_detail TEXT,
    trace_context TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Real, explicit, self-asserting ownership — not left implicit in "this
-- file is only ever run by migrate_investigation.py, connecting as the
-- Investigation role" (true today, but Phase 7 provisions from scratch
-- and that invariant is a fact about operational discipline, not
-- something this SQL file itself enforces). Prefers the real deployed
-- `investigation_role` once it exists (Phase 6+), falling back to
-- `investigation_role_local_dev` today. For the intended path (this
-- role already owns what it just created, or is re-running the same
-- idempotent migration), asserting ownership of yourself is a real
-- Postgres no-op — safe to run every time. If ownership has ever drifted
-- to a different role (the exact live bug this statement exists to
-- prevent recurring — see the header comment above), this correctly
-- FAILS LOUDLY with a permission error instead of silently leaving bad
-- ownership in place: `ALTER ... OWNER TO` requires the connecting role
-- to already be the current owner (or a superuser), which
-- investigation_role(_local_dev) is not if some other role created the
-- object first. That failure is the desired outcome — it surfaces the
-- exact class of drift a positive-grant check would otherwise be the
-- only way to catch, the very next time this migration runs, rather
-- than waiting for someone to think to check.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'investigation_role') THEN
        EXECUTE 'ALTER SCHEMA investigation OWNER TO investigation_role';
        EXECUTE 'ALTER TABLE investigation.investigation_runs OWNER TO investigation_role';
    ELSIF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'investigation_role_local_dev') THEN
        EXECUTE 'ALTER SCHEMA investigation OWNER TO investigation_role_local_dev';
        EXECUTE 'ALTER TABLE investigation.investigation_runs OWNER TO investigation_role_local_dev';
    END IF;
END $$;

-- Real, honest accommodation, not a workaround: investigation_role (the
-- real deployed-workload role) does not exist yet as of Phase 4 —
-- nothing is deployed (Migration Plan Phases 5-7). Only
-- investigation_role_local_dev is real today. This loop grants to
-- whichever of the two already exists (both are, by construction, the
-- same role or a role this schema's owner — investigation_role_local_dev
-- itself — can freely grant to, since granting on an object you own
-- needs no special privilege), so this migration runs cleanly now AND
-- later, once create_investigation_role.sql is actually run against a
-- real workload identity — no second migration needed then.
DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['investigation_role', 'investigation_role_local_dev']
    LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('GRANT USAGE ON SCHEMA investigation TO %I', r);
            EXECUTE format('GRANT SELECT, INSERT, UPDATE ON investigation.investigation_runs TO %I', r);
        END IF;
    END LOOP;
END $$;

-- Explicit, real, adversarial-proof-ready statement of the mirror half
-- of the boundary: app_role / app_role_local_dev (the Reporting
-- service's own role) is never granted USAGE on `investigation` — no
-- GRANT statement for it exists anywhere in this file, or anywhere else
-- in this project. A second, separate real gap closed by hand once,
-- documented here so it is never silently reintroduced: Postgres grants
-- USAGE on the `public` schema to the PUBLIC pseudo-role by default,
-- which would silently hand investigation_role(_local_dev) access to
-- `public` with no explicit grant at all. The one-time real fix —
-- `REVOKE USAGE ON SCHEMA public FROM PUBLIC` followed by
-- `GRANT USAGE ON SCHEMA public TO app_role, app_role_local_dev` — must
-- be applied once per real environment (it lives in
-- scripts/migrations/0001_initial_schema.sql's own real deployment
-- runbook step now, not repeated per-migration-run, since REVOKE FROM
-- PUBLIC is a database-wide default, not a per-object grant this file
-- would otherwise naturally re-assert on every run).
