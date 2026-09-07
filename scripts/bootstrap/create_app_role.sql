-- Creates the Entra-ID-mapped, non-admin Postgres role the application
-- workload connects as. Run once per environment, manually, by a human
-- holding the Microsoft Entra Administrator role on that environment's
-- Azure Database for PostgreSQL Flexible Server instance.
--
-- Not run by the application, CI, or any automated pipeline: the role
-- this script creates deliberately has no CREATEROLE privilege, so it
-- cannot create itself or any other role. This is the specific,
-- purpose-built role that Low-Level Design Section 1's
--   REVOKE UPDATE, DELETE ON approval_records FROM app_role;
-- targets, and the specific role Phase 2's migration script grants
-- table-level access to. It gets zero grants here — only identity and
-- existence.
--
-- This role is mapped to one specific object ID (the workload managed
-- identity's) and will NOT authenticate a developer's personal `az
-- login` session — Entra role mapping is a 1:1 binding to one object
-- ID, not "any valid token names the role you ask for." For local
-- development against onepulse-pg-dev, use
-- create_app_role_local_dev.sql instead, which maps a separate role to
-- an Entra group rather than to app_role's object ID.
--
-- Connect to the `postgres` database as the Entra ID admin first (the
-- pgaadauth_* functions must be run there, not against the application
-- database), then run this script.
--
-- Usage:
--   psql "host=<server>.postgres.database.azure.com dbname=postgres sslmode=require" \
--     -v workload_identity_oid='<object-id-of-the-per-environment-managed-identity>' \
--     -f create_app_role.sql
--
-- <object-id-of-the-per-environment-managed-identity> is the Entra ID
-- object ID of that environment's dedicated user-assigned managed
-- identity (e.g. id-onepulse-app-dev), NOT the identity's client ID and
-- NOT the ADO pipeline's deployment identity or the server's own Entra
-- Administrator identity.

SELECT * FROM pgaadauth_create_principal_with_oid(
    'app_role',              -- roleName: matches LLD Section 1 verbatim
    :'workload_identity_oid',
    'service',                -- objectType: managed identity, not a human user
    false,                    -- isAdmin: false — not azure_pg_admin, no CREATEROLE/CREATEDB
    false                     -- isMfa: not applicable to non-interactive service auth
);

-- Expected output: "Created role for app_role"
--
-- Verify it landed as non-admin, not merely that the call returned
-- success (this project's standing rule: a tool reporting success is
-- not evidence by itself):
--   SELECT rolname, principaltype, isadmin
--   FROM pg_catalog.pgaadauth_list_principals(false)
--   WHERE rolname = 'app_role';
-- isadmin must be 0.
