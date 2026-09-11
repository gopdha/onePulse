-- Migration Plan Phase 8 follow-up (ADR-028): real, ACL-independent
-- enforcement of the append-only guarantee on `approval_records`,
-- closing the one gap the existing REVOKE cannot reach — a role that
-- carries real UPDATE/DELETE via PostgreSQL's built-in `pg_write_all_data`
-- predefined role (which every member of `azure_pg_admin`, this
-- server's real Entra Administrator role, has), rather than via any
-- per-table ACL grant.
--
-- Why a trigger actually closes this and a REVOKE cannot: a BEFORE
-- trigger fires for every role executing DML against the table,
-- regardless of which privilege path (explicit ACL, ownership, or
-- predefined-role membership) let the statement reach the table at
-- all — it is not itself an ACL check. Disabling or dropping a trigger
-- requires ALTER TABLE, which requires table ownership (`app_role`,
-- confirmed the real current owner) or genuine superuser
-- (`azure_pg_admin` is confirmed `rolsuper = false`) — `azure_pg_admin`
-- has neither, so it cannot route around this the way it routes around
-- a plain REVOKE.
--
-- Idempotent: DROP ... IF EXISTS before each CREATE, safe to re-run.

-- Real, live-discovered requirement, a SECOND real consequence of
-- ADR-023's own "REVOKE ALL then re-GRANT exact intended profile" fix,
-- not previously noticed: CREATE TRIGGER needs the table's real ACL
-- TRIGGER bit, which is NOT implied by ownership alone once ownership's
-- own default ALL-PRIVILEGES grant has been explicitly reset — confirmed
-- live: `has_table_privilege('app_role', 'approval_records', 'TRIGGER')`
-- is `false` even though `app_role` is the real, current table owner.
-- `gopi` is a real, confirmed member of `app_role` (`pg_auth_members`),
-- so `SET ROLE` (session-level, no interactive AAD auth needed) reaches
-- ownership-adjacent rights — unlike connecting AS `app_role` directly,
-- which cannot authenticate interactively at all (ADR-023/Task 45's own
-- finding) — but TRIGGER creation still needs the ACL bit granted
-- first, which the owner itself can always do for its own object
-- (a real, structural owner-right, separate from currently holding the
-- privilege). Granted, used, and revoked again in the same migration —
-- `app_role`'s own real, intended, minimal profile
-- (`verify_migration.py`'s `PUBLIC_TABLE_PROFILES`) is unchanged by
-- this; only the trigger's continued existence and firing persists,
-- which needs no ongoing privilege once created.
SET ROLE app_role;
GRANT TRIGGER ON approval_records TO app_role;

CREATE OR REPLACE FUNCTION reject_approval_records_mutation() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'approval_records is append-only: % is not permitted (role=%)', TG_OP, current_user;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS approval_records_append_only ON approval_records;
CREATE TRIGGER approval_records_append_only
    BEFORE UPDATE OR DELETE ON approval_records
    FOR EACH ROW
    EXECUTE FUNCTION reject_approval_records_mutation();

REVOKE TRIGGER ON approval_records FROM app_role;
RESET ROLE;
