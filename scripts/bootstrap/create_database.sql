-- Creates the real OnePulse application database and grants the
-- app roles (created by create_app_role.sql / create_app_role_local_dev.sql)
-- enough schema-level privilege to run migrate.py themselves going
-- forward. Run once per environment, manually, by a human holding the
-- Microsoft Entra Administrator role on that environment's Azure
-- Database for PostgreSQL Flexible Server instance — same convention as
-- the two role-bootstrap scripts in this directory.
--
-- Why the GRANT CREATE step matters: PostgreSQL 18 (this project's real
-- server version) revokes CREATE on the public schema from PUBLIC by
-- default (a security hardening change from pre-15 versions). Without
-- this one-time grant, app_role/app_role_local_dev could connect but
-- could not create a single table — migrate.py would need to run as an
-- admin identity forever, which this project's roles are deliberately
-- built to avoid (see create_app_role.sql's isAdmin: false).
--
-- Connect to the `postgres` database as the Entra ID admin first
-- (CREATE DATABASE cannot run inside a transaction block or against the
-- database being created), then run this script. It then reconnects
-- itself to the new database via \c for the GRANT step.
--
-- Usage:
--   psql "host=onepulse-pg-dev.postgres.database.azure.com dbname=postgres sslmode=require" \
--     -f create_database.sql

SELECT 'CREATE DATABASE onepulse'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'onepulse')
\gexec

\c onepulse

GRANT CREATE ON SCHEMA public TO app_role;
GRANT CREATE ON SCHEMA public TO app_role_local_dev;

-- Verify, not just trust the exit code:
--   SELECT grantee, privilege_type FROM information_schema.role_table_grants
--   -- (schema-level CREATE isn't in role_table_grants; check instead via)
--   SELECT nspname, r.rolname, has_schema_privilege(r.rolname, nspname, 'CREATE')
--   FROM pg_namespace, pg_roles r
--   WHERE nspname = 'public' AND r.rolname IN ('app_role', 'app_role_local_dev');
-- both rows must show has_schema_privilege = true.
