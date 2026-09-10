-- Real, direct repeat of ADR-023's own finding, one schema over: the
-- retroactive ownership transfer in 0001's self-asserting OWNER TO
-- block (investigation_role_local_dev -> investigation_role, applied
-- for real for the first time in Migration Plan Phase 6, once
-- investigation_role's real Managed Identity existed to map it to)
-- gave investigation_role every owner-implicit privilege on
-- investigation_runs it was never meant to have — confirmed via direct
-- has_table_privilege query, not assumed: DELETE, TRUNCATE, REFERENCES,
-- TRIGGER, MAINTAIN, none of which 0001's own GRANT statements ever
-- name for either role.
--
-- investigation_runs has no foreign keys in or out (no REFERENCES
-- clause in its own definition, and nothing else references it), so
-- the separate "FOR KEY SHARE needs UPDATE on the referenced table"
-- finding from ADR-023 does not apply here — this table needed only
-- the ownership-widening fix, not a column-level UPDATE grant.
--
-- REVOKE ALL then re-GRANT exactly the intended profile (SELECT,
-- INSERT, UPDATE — 0001's own real grant set), for both roles
-- identically, same pattern as 0004_reassert_public_schema_ownership_
-- and_grants.sql. Idempotent, safe to re-run under either role once
-- investigation_role owns this table (an owner can always GRANT/REVOKE
-- on its own objects).

DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['investigation_role', 'investigation_role_local_dev']
    LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON investigation.investigation_runs FROM %I', r);
            EXECUTE format('GRANT SELECT, INSERT, UPDATE ON investigation.investigation_runs TO %I', r);
        END IF;
    END LOOP;
END $$;
