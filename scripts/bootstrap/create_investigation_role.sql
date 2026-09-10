-- Creates the Entra-ID-mapped, non-admin Postgres role the real
-- Investigation service workload connects as (Migration Plan Phase 4,
-- ADR-020: database-per-service). Run once per environment, manually,
-- by a human holding the Microsoft Entra Administrator role on that
-- environment's Azure Database for PostgreSQL Flexible Server instance
-- — identical process to create_app_role.sql, a separate role for a
-- separate service.
--
-- Real, deliberate boundary this role exists to enforce: it is granted
-- access to the `investigation` schema ONLY (migration
-- 0004_add_investigation_schema.sql) — never `public`, where `reports`/
-- `findings`/`cycles`/etc. live. The Reporting service's own role
-- (app_role / app_role_local_dev) is the mirror image: granted on
-- `public` only, never on `investigation`. Neither role is ever granted
-- USAGE on the other service's schema — Postgres's own default (no
-- schema access without an explicit GRANT) is what makes this a real,
-- structural boundary rather than a discipline one, the same standard
-- already proven for the BFF's "no data store" guarantee in Phase 2.
--
-- Not run by the application, CI, or any automated pipeline. Gets zero
-- grants here — only identity and existence; migration
-- 0004_add_investigation_schema.sql does the real GRANT/REVOKE work.
--
-- This role is mapped to one specific object ID (the workload managed
-- identity's) and will NOT authenticate a developer's personal `az
-- login` session — see create_investigation_role_local_dev.sql for
-- local development.
--
-- Connect to the `postgres` database as the Entra ID admin first, then
-- run this script.
--
-- Usage:
--   psql "host=<server>.postgres.database.azure.com dbname=postgres sslmode=require" \
--     -v workload_identity_oid='<object-id-of-the-per-environment-Investigation-managed-identity>' \
--     -f create_investigation_role.sql
--
-- Real, honest status as of Phase 4: no real deployed Investigation
-- workload identity exists yet (nothing is containerized or deployed —
-- Migration Plan Phases 5-7). This script is a real, ready-to-run
-- template for when one does, matching the exact precedent app_role
-- itself set (bootstrapped ahead of real deployment) — not run against
-- real infrastructure in this phase. Local development and all of this
-- phase's real verification uses investigation_role_local_dev instead.

SELECT * FROM pgaadauth_create_principal_with_oid(
    'investigation_role',   -- roleName: distinct from app_role — a real,
                              -- separate database role for a real,
                              -- separate service, per ADR-020
    :'workload_identity_oid',
    'service',                -- objectType: managed identity, not a human user
    false,                    -- isAdmin: false
    false                     -- isMfa: not applicable to non-interactive service auth
);

-- Expected output: "Created role for investigation_role"
--
-- Verify it landed as non-admin:
--   SELECT rolname, principaltype, isadmin
--   FROM pg_catalog.pgaadauth_list_principals(false)
--   WHERE rolname = 'investigation_role';
-- isadmin must be 0.
