-- Creates the Entra-ID-mapped, non-admin Postgres role that individual
-- developers authenticate as when running the application locally
-- against the shared onepulse-pg-dev instance.
--
-- RUN THIS AGAINST onepulse-pg-dev ONLY. NEVER RUN THIS AGAINST
-- onepulse-pg-staging OR onepulse-pg-production. A developer's personal
-- Entra credential must never be able to authenticate to any Postgres
-- instance other than Development — see Physical Architecture Section 4
-- and DevOps Setup Section 4 for why environments are fully separate
-- server instances in the first place.
--
-- Why this role exists at all, and why it is NOT the same role as
-- app_role: app_role (create_app_role.sql) is mapped to the per-
-- environment workload managed identity's object ID. A developer's
-- personal `az login` session presents a token for their own, different
-- object ID, which Flexible Server will not accept as app_role — Entra
-- role mapping is a 1:1 binding between a Postgres role name and one
-- specific object ID, not "any valid token names the role you ask for."
-- This role maps instead to an Entra ID *group* (not one person's
-- object ID), so any developer added to that group can authenticate —
-- onboarding a new developer is a group-membership change, not a new
-- bootstrap run.
--
-- Prerequisite: create the Entra ID security group first (e.g.
-- "OnePulse-Dev-Local-DB-Access"), add developers who need local DB
-- access to it, and retrieve the group's object ID.
--
-- Connect to the `postgres` database on onepulse-pg-dev as the Entra ID
-- admin first (pgaadauth_* functions must run there), then run this
-- script.
--
-- Usage:
--   psql "host=onepulse-pg-dev.postgres.database.azure.com dbname=postgres sslmode=require" \
--     -v dev_group_oid='<object-id-of-the-OnePulse-Dev-Local-DB-Access-group>' \
--     -f create_app_role_local_dev.sql

SELECT * FROM pgaadauth_create_principal_with_oid(
    'app_role_local_dev',    -- roleName: distinct from app_role on purpose,
                              -- so audit logs unambiguously distinguish a
                              -- deployed workload connection from a
                              -- developer's local machine
    :'dev_group_oid',
    'group',                  -- objectType: an Entra security group, not
                              -- one individual's object ID
    false,                    -- isAdmin: false — same non-admin boundary as
                              -- app_role; local dev should hit the real
                              -- permission boundary, not a looser one
    true                      -- isMfa: true — this maps human interactive
                              -- logins, unlike app_role's service identity
);

-- Expected output: "Created role for app_role_local_dev"
--
-- Verify it landed as non-admin, not merely that the call returned
-- success:
--   SELECT rolname, principaltype, isadmin
--   FROM pg_catalog.pgaadauth_list_principals(false)
--   WHERE rolname = 'app_role_local_dev';
-- isadmin must be 0.
--
-- Phase 2's migration script must grant this role the identical
-- table-level privileges it grants app_role (including the same
-- REVOKE UPDATE, DELETE ON approval_records) — divergence here would
-- mean local dev stops being genuine evidence about what the deployed
-- workload can actually do.
