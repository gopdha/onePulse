-- Migration Plan Phase 8 (ADR-018/027): the real Owner/Visitor
-- authorization model. `actors.role` previously carried only
-- organizational-title values (portfolio_lead/program_lead/
-- platform_admin) with no capability distinction — every seeded actor
-- was implicitly full-capability. This phase introduces a real
-- restricted tier ('visitor': view + chat, no generate/approve) without
-- disturbing any existing row's real, historical value.
--
-- Deliberate design choice, not a new column: every existing legacy
-- value (portfolio_lead/program_lead/platform_admin) is treated as
-- Owner-tier by the application (onepulse_common.roles.is_owner_role —
-- "not literally 'visitor'"), so this migration only needs to WIDEN the
-- existing CHECK, not backfill or reinterpret any historical row. A
-- separate `access_level` column was considered and rejected: it would
-- have meant two role-shaped columns with an unclear precedence rule
-- between them for no real benefit Now-scope needs.
--
-- Idempotent: DROP CONSTRAINT IF EXISTS + ADD CONSTRAINT, safe to re-run.

ALTER TABLE actors DROP CONSTRAINT IF EXISTS actors_role_check;
ALTER TABLE actors ADD CONSTRAINT actors_role_check
    CHECK (role IN ('portfolio_lead', 'program_lead', 'platform_admin', 'owner', 'visitor'));
