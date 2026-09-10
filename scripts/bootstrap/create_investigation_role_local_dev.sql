-- Creates the Entra-ID-mapped, non-admin Postgres role individual
-- developers authenticate as when running the Investigation service
-- locally against onepulse-pg-dev (Migration Plan Phase 4).
--
-- RUN THIS AGAINST onepulse-pg-dev ONLY — see create_app_role_local_dev.sql
-- for the full reasoning; this is the identical pattern, a second role
-- for a second service. Maps to the SAME real Entra group as
-- app_role_local_dev (OnePulse-Dev-Local-DB-Access,
-- 9b02cc58-b063-401a-ab62-7089594f37dd) — the same developer identity
-- authenticates as either role depending on which local service they're
-- running; Postgres role selection is a property of the connection's
-- requested role name, not the token's identity alone, so one real
-- Entra login can legitimately present as app_role_local_dev in one
-- terminal and investigation_role_local_dev in another.
--
-- Connect to the `postgres` database on onepulse-pg-dev as the Entra ID
-- admin first, then run this script.
--
-- Usage:
--   psql "host=onepulse-pg-dev.postgres.database.azure.com dbname=postgres sslmode=require" \
--     -v dev_group_oid='9b02cc58-b063-401a-ab62-7089594f37dd' \
--     -f create_investigation_role_local_dev.sql

SELECT * FROM pgaadauth_create_principal_with_oid(
    'investigation_role_local_dev',
    :'dev_group_oid',
    'group',
    false,                    -- isAdmin: false
    true                      -- isMfa: true — human interactive login
);

-- Expected output: "Created role for investigation_role_local_dev"
--
-- Migration 0004_add_investigation_schema.sql must grant this role the
-- identical schema-level privileges it grants investigation_role
-- (GRANT on `investigation` only, never `public`) — divergence here
-- would mean local dev stops being genuine evidence about what the
-- deployed workload can actually do, the same standing rule
-- create_app_role_local_dev.sql already states for its own pair.
