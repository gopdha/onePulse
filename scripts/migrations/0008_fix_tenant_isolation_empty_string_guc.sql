-- Real, live-discovered second variant of the exact bug 0005 already
-- fixed once, found while seeding Migration Plan Phase 8's own test
-- data (the first real workload to call `set_config('app.current_
-- tenant_id', ..., true)` more than once on the same pooled
-- connection): `current_setting('app.current_tenant_id', true)`
-- returns real SQL NULL only the FIRST time it is ever referenced in a
-- session that has never touched this GUC. Once ANY `SET LOCAL`/
-- `set_config(..., true)` call has EVER set it — even transactionally,
-- even if that transaction committed and the LOCAL value reverted —
-- Postgres has now created a real placeholder variable for this custom
-- GUC in the current backend, and its "reverted" value is the empty
-- string '', not NULL. Confirmed live, directly:
--
--   current_setting('app.current_tenant_id', true) -> NULL   (fresh session)
--   -- one SET LOCAL ... / commit later, same session --
--   current_setting('app.current_tenant_id', true) -> ''     (not NULL)
--
-- 0005's own `IS NULL` check is therefore only correct for a
-- connection's very first tenant-scoped query — every subsequent
-- unscoped query on the SAME pooled connection (exactly what a real
-- connection pool with min_size>1/reused connections does, in every
-- one of core_api's and reporting's real deployed processes) would hit
-- the second branch and error on `''::uuid`, rather than falling back
-- permissively as 0005 intended. Not caught by 0005's own verification
-- because nothing before this task ever called set_config twice on the
-- same real connection outside a single request's own transaction.
--
-- Fix: treat both real "unset" representations identically.

DROP POLICY IF EXISTS tenant_isolation ON reports;
CREATE POLICY tenant_isolation ON reports USING (
    NULLIF(current_setting('app.current_tenant_id', true), '') IS NULL
    OR program_id IN (
        SELECT p.program_id FROM programs p
        JOIN portfolios pf ON p.portfolio_id = pf.portfolio_id
        WHERE pf.tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    )
);
