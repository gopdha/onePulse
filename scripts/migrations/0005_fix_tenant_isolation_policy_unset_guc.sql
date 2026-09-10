-- Real, previously-invisible bug exposed directly by 0004's ownership
-- fix, not by any code change to this policy itself: `reports` has had
-- RLS enabled (ALTER TABLE reports ENABLE ROW LEVEL SECURITY, 0001)
-- since Phase 2, but `FORCE ROW LEVEL SECURITY` was never set
-- (confirmed live: relforcerowsecurity = false) — meaning the table's
-- OWNER has always been exempt from its own policy. Before 0004,
-- app_role_local_dev owned `reports` and was therefore silently exempt
-- from ever actually evaluating tenant_isolation's USING clause. Once
-- 0004 moved ownership to app_role, app_role_local_dev stopped being
-- exempt — and the policy itself turned out to be genuinely broken the
-- moment it was ever actually evaluated:
--
--   current_setting('app.current_tenant_id')::uuid
--
-- called with no `missing_ok` argument, so a session that has never SET
-- app.current_tenant_id (every real session in this project's history
-- — confirmed by repo-wide grep, nothing anywhere ever sets this GUC)
-- raises `unrecognized configuration parameter`, not merely returns an
-- empty result. This was never caught before because nothing has ever
-- queried `reports` as a genuinely non-owner, RLS-subject role: app_role
-- has never had a real Managed Identity session to connect with, and
-- app_role_local_dev was exempt via ownership the entire time.
--
-- Fix, matching Build Plan's own Scoping Notes (Task 14: "Build Plan's
-- own Scoping Notes mark *active enforcement* as Next-scope — one real
-- tenant/portfolio/program row is sufficient for Now; the policy itself
-- is installed now per explicit direction"): when no tenant context has
-- been set, the policy is permissive rather than erroring or silently
-- filtering every row to zero. This is the behavior every real query in
-- this project's history has always implicitly depended on (via the
-- ownership-bypass accident) — now made real and explicit, without
-- pre-emptively implementing actual multi-tenant enforcement, which
-- remains genuinely out of Now-scope. Whatever sets app.current_tenant_id
-- for real, per-request tenant enforcement is Next-scope work, not this
-- migration's job.

DROP POLICY IF EXISTS tenant_isolation ON reports;
CREATE POLICY tenant_isolation ON reports USING (
    current_setting('app.current_tenant_id', true) IS NULL
    OR program_id IN (
        SELECT p.program_id FROM programs p
        JOIN portfolios pf ON p.portfolio_id = pf.portfolio_id
        -- Real, live-discovered subtlety: SQL's OR does not guarantee
        -- short-circuit evaluation of its second operand — Postgres
        -- still evaluated this subquery (and this exact call) even
        -- when the first branch above was true, reproducing the
        -- identical "unrecognized configuration parameter" error this
        -- migration exists to fix. Both occurrences need the same
        -- missing_ok=true guard, not just the first.
        WHERE pf.tenant_id = current_setting('app.current_tenant_id', true)::uuid
    )
);
