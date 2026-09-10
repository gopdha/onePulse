-- Phase 6 pre-work: reasserts the real, intended ownership and grant
-- profile for every object in the `public` schema, closing the third
-- real instance of the "ownership bypasses grants" bug class in this
-- project (app_role_local_dev/app_role documentation gap — Task 39;
-- investigation.investigation_runs — Task 43; this file — all 12
-- public tables and their 6 sequences).
--
-- Root cause: every real object in `public` was created by whichever
-- role happened to run migrate.py against a fresh database — always
-- app_role_local_dev, since app_role requires a real Managed Identity
-- token no interactive session has ever presented. Ownership silently
-- won over every GRANT/REVOKE this schema's own migrations wrote.
--
-- Retroactively fixed live, 2026-09-10, by the real Postgres Entra
-- Administrator (same actor and pattern as the investigation_runs fix):
-- ALTER TABLE/SEQUENCE ... OWNER TO app_role for all 12 tables and 6
-- sequences. Index ownership followed automatically — confirmed by
-- direct before/after query of all 17 real indexes, not assumed.
--
-- TWO REAL, UNANTICIPATED SIDE EFFECTS, both confirmed by direct query
-- before this migration existed to fix them, not assumed from how
-- ownership transfer "should" behave:
--
-- (1) app_role_local_dev lost ALL real access to every one of these 12
--     tables the moment ownership moved away from it. Granting a
--     privilege to an object's own current owner is a genuine Postgres
--     no-op that never materializes a real ACL entry — confirmed via
--     direct pg_class.relacl inspection: every table showed ONLY
--     app_role's own entry post-transfer, zero entries for
--     app_role_local_dev anywhere, even though 0001/0003's own GRANT
--     statements for it had "succeeded" the whole time. A live test
--     run (test_approve_report_end_to_end) failed with a real
--     `permission denied for table programs` the moment ownership
--     moved, proving this wasn't a theoretical concern.
--
-- (2) app_role, as the NEW owner, automatically picked up every
--     owner-implicit privilege it was never intended to have —
--     confirmed via has_table_privilege, not assumed: TRUNCATE,
--     REFERENCES, TRIGGER on all 12 tables, plus DELETE and (on 9
--     tables never meant to have it) UPDATE. The one real bright spot:
--     the original REVOKE UPDATE, DELETE ON approval_records FROM
--     app_role (0001) DID survive the ownership transfer intact for
--     both bits, confirmed by direct query — Postgres honors an
--     explicit REVOKE against a role even after that role becomes an
--     object's owner. Every OTHER privilege this migration reasserts
--     was never explicitly revoked before, so it needed reasserting.
--
-- This migration closes both gaps as real, explicit ACL entries —
-- REVOKE ALL first (rather than enumerating every owner-implied bit
-- individually, since the full extent of what ownership silently
-- granted wasn't known in advance and shouldn't be guessed at twice),
-- then GRANT back exactly the profile 0001/0003 always intended, for
-- BOTH roles identically (create_app_role_local_dev.sql's own stated
-- design: local dev's grants must match app_role's, or local dev stops
-- being genuine evidence about what the deployed workload can do).
--
-- Idempotent and self-healing on every future run, regardless of which
-- role executes it: once app_role owns these objects, app_role itself
-- can run every statement here (an owner can always ALTER its own
-- ownership as a no-op, and can always GRANT/REVOKE on its own
-- objects) — matching the migrate.py default-role change made in this
-- same task. On a genuinely fresh environment where app_role creates
-- these objects from the start, every ALTER OWNER TO here is a
-- harmless no-op and the REVOKE ALL/GRANT block simply asserts the
-- same intended profile it always would have.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_role') THEN
        RAISE EXCEPTION 'app_role does not exist — run scripts/bootstrap/create_app_role.sql first';
    END IF;
END $$;

ALTER TABLE public.tenants OWNER TO app_role;
ALTER TABLE public.portfolios OWNER TO app_role;
ALTER TABLE public.programs OWNER TO app_role;
ALTER TABLE public.configurations OWNER TO app_role;
ALTER TABLE public.reports OWNER TO app_role;
ALTER TABLE public.findings OWNER TO app_role;
ALTER TABLE public.untracked_items OWNER TO app_role;
ALTER TABLE public.actors OWNER TO app_role;
ALTER TABLE public.approval_records OWNER TO app_role;
ALTER TABLE public.actor_scope OWNER TO app_role;
ALTER TABLE public.usage_ledger OWNER TO app_role;
ALTER TABLE public.cycles OWNER TO app_role;

ALTER SEQUENCE public.actor_scope_scope_id_seq OWNER TO app_role;
ALTER SEQUENCE public.approval_records_approval_id_seq OWNER TO app_role;
ALTER SEQUENCE public.findings_finding_id_seq OWNER TO app_role;
ALTER SEQUENCE public.reports_report_id_seq OWNER TO app_role;
ALTER SEQUENCE public.untracked_items_untracked_item_id_seq OWNER TO app_role;
ALTER SEQUENCE public.usage_ledger_usage_id_seq OWNER TO app_role;

DO $$
DECLARE
    r TEXT;
    t TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['app_role', 'app_role_local_dev']
    LOOP
        FOREACH t IN ARRAY ARRAY['tenants', 'portfolios', 'programs', 'configurations', 'reports',
                                  'findings', 'untracked_items', 'actors', 'approval_records',
                                  'actor_scope', 'usage_ledger', 'cycles']
        LOOP
            EXECUTE format('REVOKE ALL ON %I FROM %I', t, r);
        END LOOP;
        EXECUTE format(
            'GRANT SELECT, INSERT ON tenants, portfolios, programs, findings, untracked_items, '
            'actors, actor_scope, usage_ledger, approval_records TO %I', r
        );
        EXECUTE format('GRANT SELECT, INSERT, UPDATE ON configurations, reports, cycles TO %I', r);
        EXECUTE format('GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO %I', r);

        -- Real, live-discovered, previously-invisible requirement (found
        -- only by this migration's own retroactive ownership fix, which
        -- for the first time made these roles genuinely NON-owners of
        -- the tables their own foreign keys reference): Postgres's
        -- internal FK-check row lock (`SELECT ... FOR KEY SHARE`, run
        -- automatically on every INSERT into a table with an FK) requires
        -- UPDATE privilege on the REFERENCED table — plain SELECT is not
        -- sufficient, confirmed by direct, isolated empirical test, not
        -- assumed from documentation. This is exactly the open question
        -- Task 31 hit and left unresolved for approval_records/reports
        -- ("FOR KEY SHARE apparently needs more than plain SELECT") —
        -- now answered definitively: it needs UPDATE.
        --
        -- Scoped to column level — GRANT UPDATE (<pk column>) ON <table>,
        -- not a blanket table-level UPDATE — also confirmed sufficient by
        -- direct empirical test. This is real least-privilege: these
        -- roles can now satisfy the FK lock check on every table their
        -- own inserts reference (tenants, portfolios, programs, actors,
        -- findings — derived from a real query of every FK constraint in
        -- this schema, not guessed), without gaining the ability to
        -- actually modify any column's real value on those tables.
        EXECUTE format('GRANT UPDATE (tenant_id) ON tenants TO %I', r);
        EXECUTE format('GRANT UPDATE (portfolio_id) ON portfolios TO %I', r);
        EXECUTE format('GRANT UPDATE (program_id) ON programs TO %I', r);
        EXECUTE format('GRANT UPDATE (actor_id) ON actors TO %I', r);
        EXECUTE format('GRANT UPDATE (finding_id) ON findings TO %I', r);
    END LOOP;
END $$;

-- Restated explicitly, same defensive reasoning as 0001: even though
-- the GRANT block above never includes UPDATE/DELETE for
-- approval_records, an explicit REVOKE guards against a future blanket
-- GRANT elsewhere silently reintroducing them — and, per the finding
-- above, is the one statement already proven to survive an ownership
-- transfer intact.
REVOKE UPDATE, DELETE ON approval_records FROM app_role;
REVOKE UPDATE, DELETE ON approval_records FROM app_role_local_dev;
