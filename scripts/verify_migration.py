"""Independently confirms the real schema exists in a live Azure
Database for PostgreSQL Flexible Server instance by querying
information_schema (and pg_catalog for the pieces information_schema
doesn't cover: generated-column expressions, RLS policies, and role
grants) directly — never by trusting migrate.py's exit code.

DevOps Setup Section 2.1: "A migration tool reporting success is not,
by itself, evidence a change actually took effect — this exact gap
caused two real, separate incidents in the proof of concept." Every
check function here is written to be independently testable against a
real, deliberately-missing object — see tests/test_verify_migration.py,
which forces the exact failure mode this script exists to catch.

Run: python scripts/verify_migration.py --target dev
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

import asyncpg
from dotenv import load_dotenv

from onepulse_common.config import PostgresSettings
from onepulse_common.db import PostgresClient

load_dotenv()

TARGETS: dict[str, PostgresSettings] = {
    "dev": PostgresSettings(
        host="onepulse-pg-dev.postgres.database.azure.com",
        database="onepulse",
        role_name=os.environ.get("ONEPULSE_PG_ROLE", "app_role_local_dev"),
    ),
}

EXPECTED_TABLES = [
    "tenants",
    "portfolios",
    "programs",
    "configurations",
    "reports",
    "findings",
    "untracked_items",
    "actors",
    "approval_records",
    "actor_scope",
    "usage_ledger",
    "cycles",
]

# The real, intended table-level grant profile per 0004_reassert_public_
# schema_ownership_and_grants.sql (ADR-023) — the single source this
# file's new positive/negative privilege checks are both built from, so
# the two can never silently drift apart from each other. 9 tables get
# SELECT+INSERT only; configurations/reports/cycles additionally need
# UPDATE for their own real update paths (config changes, approve/
# reject, cycle status writes). Column-level UPDATE grants on 5 FK-
# referenced tables (the FOR KEY SHARE fix) are deliberately NOT
# reflected here — has_table_privilege's table-level OID form does not
# count a column-scoped grant as satisfying it (confirmed empirically
# before writing this file: tenants shows UPDATE=false via this form
# even though `GRANT UPDATE (tenant_id) ON tenants` is real and live),
# so checking against this profile cannot false-flag that real,
# narrower grant as an unintended excess.
PUBLIC_TABLE_PROFILES: dict[str, list[str]] = {
    "tenants": ["SELECT", "INSERT"],
    "portfolios": ["SELECT", "INSERT"],
    "programs": ["SELECT", "INSERT"],
    "configurations": ["SELECT", "INSERT", "UPDATE"],
    "reports": ["SELECT", "INSERT", "UPDATE"],
    "findings": ["SELECT", "INSERT"],
    "untracked_items": ["SELECT", "INSERT"],
    "actors": ["SELECT", "INSERT"],
    "approval_records": ["SELECT", "INSERT"],
    "actor_scope": ["SELECT", "INSERT"],
    "usage_ledger": ["SELECT", "INSERT"],
    "cycles": ["SELECT", "INSERT", "UPDATE"],
}

# investigation_migrations/0001_initial_schema.sql's own real grant:
# GRANT SELECT, INSERT, UPDATE ON investigation.investigation_runs.
INVESTIGATION_TABLE_PROFILES: dict[str, list[str]] = {
    "investigation_runs": ["SELECT", "INSERT", "UPDATE"],
}

# The real privileges PostgreSQL's ACL system tracks separately from
# ownership but that a naive "make the workload role the owner" fix
# (ADR-023) silently confers via the automatic owner ACL entry unless
# explicitly revoked — confirmed empirically, not assumed: none of
# these are actually "owner-implicit and unrevokable" (a real,
# necessary check before writing this constant, since if they were, no
# REVOKE-based check against the owner role could ever pass). UPDATE is
# handled separately per-table below since it IS part of several
# tables' real intended profile, unlike these five.
OWNERSHIP_IMPLIED_PRIVILEGES = ["DELETE", "TRUNCATE", "REFERENCES", "TRIGGER", "MAINTAIN"]


async def check_table_exists(conn: asyncpg.Connection, table_name: str) -> bool:
    """Real information_schema.tables query — the exact technique DevOps
    Setup Section 2.1 specifies.
    """
    result = await conn.fetchval(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = $1",
        table_name,
    )
    return result is not None


async def check_table_exists_in_schema(conn: asyncpg.Connection, schema_name: str, table_name: str) -> bool:
    """Same real check as check_table_exists, generalized past the
    hardcoded `public` schema — needed for Phase 4's own `investigation`
    schema (Migration Plan Phase 4/ADR-020), a separate function rather
    than changing check_table_exists's signature so every existing call
    site (and its own regression tests) is unaffected. Uses
    pg_catalog.pg_class/pg_namespace directly rather than
    information_schema.tables, for the identical real reason
    check_schema_exists does — the connecting role may legitimately have
    zero access to this schema (the exact boundary this phase proves),
    and existence should be answerable independent of that.
    """
    result = await conn.fetchval(
        "SELECT 1 FROM pg_catalog.pg_class c "
        "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = $1 AND c.relname = $2 AND c.relkind = 'r'",
        schema_name,
        table_name,
    )
    return result is not None


async def check_column_exists(conn: asyncpg.Connection, table_name: str, column_name: str) -> bool:
    result = await conn.fetchval(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = $1 AND column_name = $2",
        table_name,
        column_name,
    )
    return result is not None


async def check_column_exists_in_schema(
    conn: asyncpg.Connection, schema_name: str, table_name: str, column_name: str
) -> bool:
    """Same real check as check_column_exists, generalized past the
    hardcoded `public` schema — needed for Phase 4's own `investigation`
    schema, for the identical real reason check_table_exists_in_schema
    exists rather than reusing check_table_exists: information_schema.
    columns is itself visibility-filtered by the connecting role's own
    grants, and the whole point of this schema is that the role
    verify_migration.py normally connects as (app_role_local_dev) has
    zero access to it. Uses pg_catalog.pg_attribute directly (every role
    can read it, regardless of schema-level grants), not
    information_schema.columns.
    """
    result = await conn.fetchval(
        "SELECT 1 FROM pg_catalog.pg_attribute a "
        "JOIN pg_catalog.pg_class c ON c.oid = a.attrelid "
        "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = $1 AND c.relname = $2 AND a.attname = $3 AND a.attnum > 0 AND NOT a.attisdropped",
        schema_name,
        table_name,
        column_name,
    )
    return result is not None


async def check_generated_column(conn: asyncpg.Connection, table_name: str, column_name: str) -> bool:
    """information_schema.columns.is_generated is 'ALWAYS' for a real
    GENERATED ALWAYS AS (...) STORED column — distinguishes a genuine
    generated column from a plain one that merely happens to exist.
    """
    result = await conn.fetchval(
        "SELECT is_generated FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = $1 AND column_name = $2",
        table_name,
        column_name,
    )
    return result == "ALWAYS"


async def check_check_constraint_values(
    conn: asyncpg.Connection, table_name: str, column_name: str, expected_values: list[str]
) -> bool:
    """Confirms every expected value literal appears in the named
    column's real CHECK constraint expression text.

    Real, live-discovered gap (Task 44 follow-up, ownership-model
    decision): `information_schema.check_constraints` joined to
    `constraint_column_usage` used to work, but silently started
    returning zero rows for `app_role_local_dev` the moment `cycles`
    stopped being owned by it — confirmed directly, not assumed: as the
    real Entra Administrator the query returns 2 rows; as
    `app_role_local_dev` (same query, same grants otherwise) it returns
    0. `information_schema`'s constraint views filter by the querying
    role's relationship to the object (ownership-adjacent), not merely
    schema USAGE — a different, narrower gap than the
    regclass-needs-USAGE issue `check_constraint_exists_in_schema`
    already found and fixed. Same real fix pattern: read `pg_catalog`
    directly. `pg_get_constraintdef` returns the same expression text
    (wrapped in `CHECK (...)`, harmless for the substring check below),
    and the join here finds every CHECK constraint whose `conkey`
    includes the named column's real `attnum` — no ownership-based
    filtering anywhere in `pg_catalog`.
    """
    rows = await conn.fetch(
        """
        SELECT pg_get_constraintdef(co.oid) AS check_clause
        FROM pg_catalog.pg_constraint co
        JOIN pg_catalog.pg_class c ON c.oid = co.conrelid
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY(co.conkey)
        WHERE n.nspname = 'public' AND c.relname = $1 AND a.attname = $2 AND co.contype = 'c'
        """,
        table_name,
        column_name,
    )
    if not rows:
        return False
    combined = " ".join(r["check_clause"] for r in rows)
    return all(f"'{v}'" in combined for v in expected_values)


async def check_constraint_exists(conn: asyncpg.Connection, table_name: str, constraint_name: str) -> bool:
    """True iff a constraint with this exact name exists on this table —
    for constraints like a Monday-only CHECK or a cross-column CHECK that
    aren't a simple value-list (check_check_constraint_values's shape),
    so are looked up by name against pg_constraint directly instead.
    """
    result = await conn.fetchval(
        "SELECT 1 FROM pg_constraint WHERE conrelid = $1::regclass AND conname = $2",
        table_name,
        constraint_name,
    )
    return result is not None


async def check_constraint_exists_in_schema(
    conn: asyncpg.Connection, schema_name: str, table_name: str, constraint_name: str
) -> bool:
    """Same real check as check_constraint_exists, but for a table
    outside `public` reached by a role with zero USAGE on that schema.
    Real, live-discovered gap (Migration Plan Phase 4 merge review):
    check_constraint_exists's `$1::regclass` cast is NOT safe here —
    unlike a plain pg_catalog WHERE-clause scan (what
    check_table_exists_in_schema/check_column_exists_in_schema use),
    regclass identifier RESOLUTION itself checks schema USAGE privilege,
    and fails with a real `InsufficientPrivilegeError: permission denied
    for schema investigation` for app_role_local_dev against
    `'investigation.investigation_runs'::regclass` — confirmed live, not
    assumed. Joins pg_constraint directly against pg_class/pg_namespace
    instead, exactly like the other schema-safe checks above, so
    verifying a constraint on a schema this role is deliberately locked
    out of doesn't itself require access to that schema.
    """
    result = await conn.fetchval(
        "SELECT 1 FROM pg_catalog.pg_constraint co "
        "JOIN pg_catalog.pg_class c ON c.oid = co.conrelid "
        "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = $1 AND c.relname = $2 AND co.conname = $3",
        schema_name,
        table_name,
        constraint_name,
    )
    return result is not None


async def check_rls_enabled(conn: asyncpg.Connection, table_name: str) -> bool:
    result = await conn.fetchval(
        "SELECT relrowsecurity FROM pg_class WHERE relname = $1 AND relnamespace = 'public'::regnamespace",
        table_name,
    )
    return result is True


async def check_force_rls_enabled(conn: asyncpg.Connection, table_name: str) -> bool:
    """True iff FORCE ROW LEVEL SECURITY is set — distinct from, and
    checked separately from, check_rls_enabled. Real, load-bearing
    reason (ADR-023 follow-up, 2026-09-10): `reports` had
    relrowsecurity=True the entire time RLS was never actually
    evaluated (Task 44's own finding) — RLS being "enabled" proves
    nothing about whether the table's current OWNER is exempt from it,
    which is exactly what FORCE controls. `app_role` now owns `reports`
    (ADR-023's own ownership transfer); without FORCE, the real
    production role would be exempt from the very policy meant to
    constrain it — the identical bug one level up. This check exists so
    that fact is asserted directly, not re-derived by reading
    pg_class by hand the next time someone needs to know.
    """
    result = await conn.fetchval(
        "SELECT relforcerowsecurity FROM pg_class WHERE relname = $1 AND relnamespace = 'public'::regnamespace",
        table_name,
    )
    return result is True


async def check_policy_exists(conn: asyncpg.Connection, table_name: str, policy_name: str) -> bool:
    result = await conn.fetchval(
        "SELECT 1 FROM pg_policies WHERE schemaname = 'public' AND tablename = $1 AND policyname = $2",
        table_name,
        policy_name,
    )
    return result is not None


async def check_policy_definition_contains(
    conn: asyncpg.Connection, table_name: str, policy_name: str, expected_substring: str
) -> bool:
    """Migration 0008: `check_policy_exists` alone only proves a policy
    with this NAME exists — it would pass identically for the real,
    live-discovered-broken 0005 version of `tenant_isolation` (`IS NULL`
    only, not `NULLIF(...) IS NULL`) and the fixed 0008 one. This checks
    the real `qual` (USING expression) text itself for the fix's own
    marker, so a future regression back to the 0005 shape is caught here
    rather than only by re-discovering the empty-string GUC bug live
    again.
    """
    qual = await conn.fetchval(
        "SELECT qual FROM pg_policies WHERE schemaname = 'public' AND tablename = $1 AND policyname = $2",
        table_name,
        policy_name,
    )
    return qual is not None and expected_substring in qual


async def check_index_definition_contains(
    conn: asyncpg.Connection, table_name: str, index_name: str, expected_substring: str
) -> bool:
    """Task 55: `reports_program_id_week_of_key` (a plain table-level
    `UNIQUE`) was replaced with a partial unique index scoped `WHERE NOT
    is_test_fixture`, so a real forced/test re-run never collides with
    the real weekly report and vice versa. A bare existence check would
    pass for a index of this name with any definition at all — this
    checks the real `indexdef` text for the partial-index marker itself,
    the same discipline `check_policy_definition_contains` already
    applies to a policy that could silently regress to a weaker shape.
    """
    indexdef = await conn.fetchval(
        "SELECT indexdef FROM pg_indexes WHERE schemaname = 'public' AND tablename = $1 AND indexname = $2",
        table_name,
        index_name,
    )
    return indexdef is not None and expected_substring in indexdef


async def check_schema_exists(conn: asyncpg.Connection, schema_name: str) -> bool:
    """Real, live-discovered subtlety (Phase 4): information_schema.schemata
    is itself subject to the connecting role's own USAGE visibility —
    once app_role_local_dev genuinely has zero access to `investigation`
    (the real boundary this phase builds), that schema stops appearing
    in information_schema.schemata for this connection at all, which
    would make this check wrongly report "missing" rather than "exists,
    but correctly inaccessible". pg_catalog.pg_namespace is a real
    system catalog every role can read regardless of schema-level grants
    (it has to be — the ACL info itself lives there), so it answers the
    real existence question independent of the very permission boundary
    this migration exists to prove.
    """
    result = await conn.fetchval(
        "SELECT 1 FROM pg_catalog.pg_namespace WHERE nspname = $1", schema_name
    )
    return result is not None


async def check_no_schema_privilege(conn: asyncpg.Connection, schema_name: str, role_name: str) -> bool:
    """True iff role_name has NO USAGE privilege on schema_name — the
    real, structural proof one service's role cannot even see into the
    other's schema (Migration Plan Phase 4/ADR-020). Uses has_schema_privilege
    directly rather than information_schema, since a schema with zero
    grants at all produces no rows in the grant-listing views to query
    (there's no "explicit absence" row) — has_schema_privilege answers
    the real yes/no question directly against Postgres's own ACL check.
    """
    result = await conn.fetchval("SELECT has_schema_privilege($1, $2, 'USAGE')", role_name, schema_name)
    return result is False


async def check_privilege_revoked(
    conn: asyncpg.Connection, table_name: str, role_name: str, privileges: list[str]
) -> bool:
    """True iff NONE of the given privileges are granted to role_name on
    table_name — the real proof the LLD's REVOKE actually held, not
    merely that it was never granted in the first place (both produce
    the same absence, which is exactly what matters here).

    Real, load-bearing limitation, found live (Migration Plan Phase 8
    follow-up): this reads `information_schema.role_table_grants`, which
    reflects ONLY the explicit ACL layer — a genuine, effective privilege
    reaching a role via membership in a PostgreSQL *predefined* role
    (`pg_write_all_data`, granting INSERT/UPDATE/DELETE on every table in
    every schema to every member, with no per-table ACL entry ever
    created) is real and enforced by Postgres, but invisible to this
    query. `azure_pg_admin` is a member of `pg_write_all_data` — this
    check reports "safe" for it on `approval_records` while `has_table_
    privilege('azure_pg_admin', 'approval_records', 'DELETE')` correctly
    reports `True`. Use `check_real_privilege_denied` (below) for any
    claim that actually needs to hold against every real grant path, not
    only the ACL one — this function is kept for the checks that
    specifically are about the ACL layer (e.g. confirming `app_role`'s
    own explicit grant profile), where it remains correct.
    """
    rows = await conn.fetch(
        "SELECT privilege_type FROM information_schema.role_table_grants "
        "WHERE table_schema = 'public' AND table_name = $1 AND grantee = $2",
        table_name,
        role_name,
    )
    granted = {r["privilege_type"] for r in rows}
    return not (granted & set(privileges))


async def check_real_privilege_denied(
    conn: asyncpg.Connection, table_name: str, role_name: str, privileges: list[str]
) -> bool:
    """True iff `role_name` genuinely cannot exercise any of `privileges`
    on `table_name` — via `has_table_privilege`, the real Postgres
    function that accounts for every actual grant path (explicit ACL,
    ownership, AND predefined-role membership like `pg_write_all_data`),
    not just the ACL layer `check_privilege_revoked` reads. The real
    proof the append-only guarantee on `approval_records` holds against
    a given role, not merely that no `GRANT` statement targets it by
    name.
    """
    for priv in privileges:
        allowed = await conn.fetchval(
            "SELECT has_table_privilege($1, $2, $3)", role_name, f"public.{table_name}", priv
        )
        if allowed:
            return False
    return True


async def check_trigger_exists_and_enabled(conn: asyncpg.Connection, table_name: str, trigger_name: str) -> bool:
    """Migration 0011 (ADR-028): the real, ACL-independent enforcement
    mechanism for `approval_records`' append-only guarantee against
    `pg_write_all_data`-derived privilege (which `check_real_privilege_
    denied` correctly reports as present for `azure_pg_admin` and always
    will — that check proves the privilege exists, not that it's
    effective; this one proves the trigger that makes it ineffective
    actually exists and is armed). `tgenabled != 'D'` — Postgres's own
    real encoding for "not disabled" (a trigger's enabled state has more
    than two values — origin/replica/always — `'D'` is the only one that
    means off).
    """
    row = await conn.fetchrow(
        "SELECT tgenabled FROM pg_trigger WHERE tgrelid = $1::regclass AND tgname = $2 AND NOT tgisinternal",
        f"public.{table_name}",
        trigger_name,
    )
    # asyncpg returns pg_catalog's "char" type as raw bytes (confirmed
    # live: b'O' for "origin"/enabled) — comparing against b"D", not "D".
    return row is not None and row["tgenabled"] != b"D"


async def check_has_table_privileges(
    conn: asyncpg.Connection, schema_name: str, table_name: str, role_name: str, privileges: list[str]
) -> bool:
    """The positive counterpart to check_privilege_revoked — true iff
    role_name genuinely holds EVERY given privilege on table_name. No
    prior check in this file asserts a positive grant anywhere (every
    existing check is either structural existence or a negative/REVOKE
    proof); Migration Plan Phase 4 needs one for the first time, since
    "the split is real" depends not only on Reporting's role having NO
    access to the investigation schema, but also on Investigation's own
    role genuinely being ABLE to use its own schema — a fact nothing
    upstream currently proves.

    Real, live-discovered gap, found only by actually running this check
    against the real database (not assumed from `has_schema_privilege`'s
    own text-argument behavior just above): `has_table_privilege(role,
    'schema.table'::text, privilege)` fails with the identical real
    `InsufficientPrivilegeError: permission denied for schema
    investigation` check_constraint_exists hit — text-identifier
    resolution for a table needs to see the schema; asking about the
    schema's own USAGE privilege by name apparently doesn't. The real
    fix is the OID-based overload: resolve the table's OID via the same
    safe pg_catalog join used everywhere else in this file, then pass
    that OID (not the name) to `has_table_privilege` — resolving by OID
    performs no further name lookup, so it isn't gated on schema
    visibility the same way.
    """
    oid = await conn.fetchval(
        "SELECT c.oid FROM pg_catalog.pg_class c "
        "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = $1 AND c.relname = $2",
        schema_name,
        table_name,
    )
    if oid is None:
        return False
    for privilege in privileges:
        result = await conn.fetchval(
            "SELECT has_table_privilege($1, $2::oid, $3)", role_name, oid, privilege
        )
        if not result:
            return False
    return True


async def check_object_owner(
    conn: asyncpg.Connection, schema_name: str, object_name: str, expected_owner: str
) -> bool:
    """The positive-ownership counterpart to check_has_table_privileges —
    true iff object_name (a table OR a sequence; relkind is not
    constrained here on purpose, since both matter) is genuinely OWNED
    by expected_owner, not merely reachable via some GRANT.

    Real, load-bearing gap this closes (Task 44 follow-up, ownership-
    model decision, 2026-09-10): every check in this file before this
    one proved either existence or a GRANT — none of them would have
    caught the real bug that motivated this whole investigation, all 12
    `public` tables and their 6 sequences being silently owned by
    app_role_local_dev instead of app_role, since ownership grants
    access regardless of any GRANT/REVOKE layered on top of it. The
    exact same class of gap already found and fixed twice before this
    (app_role_local_dev's undocumented excess privileges, Task 39;
    investigation.investigation_runs's wrong table owner, Task 43) — the
    difference here is this check exists BEFORE the next instance of
    this bug class ships silently, not after.

    Uses pg_catalog directly, not information_schema — ownership is a
    plain pg_class.relowner column, no view-level privilege filtering to
    route around (unlike check_check_constraint_values's real,
    separately-found information_schema gap).
    """
    result = await conn.fetchval(
        "SELECT r.rolname FROM pg_catalog.pg_class c "
        "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
        "JOIN pg_catalog.pg_roles r ON r.oid = c.relowner "
        "WHERE n.nspname = $1 AND c.relname = $2",
        schema_name,
        object_name,
    )
    return result == expected_owner


async def check_schema_owner(conn: asyncpg.Connection, schema_name: str, expected_owner: str) -> bool:
    """The schema-level counterpart to check_object_owner (which only
    covers pg_class objects — tables and sequences, not schemas
    themselves). Real, load-bearing gap this closes (pre-Phase-7 audit,
    2026-09-10): investigation_migrations/0001's own header comment
    documents fixing a schema-ownership bug live once already (`ALTER
    SCHEMA investigation OWNER TO investigation_role_local_dev`) and a
    SEPARATE table-ownership bug on investigation_runs found only at
    Phase 4's merge review — nothing before this function ever asserted
    the schema's own ownership stays correct going forward; the
    investigation.investigation_runs check below covers the table, this
    covers the schema, and neither substitutes for the other (Postgres
    tracks them independently — see 0001's own comment on exactly this
    point).
    """
    result = await conn.fetchval(
        "SELECT r.rolname FROM pg_catalog.pg_namespace n "
        "JOIN pg_catalog.pg_roles r ON r.oid = n.nspowner "
        "WHERE n.nspname = $1",
        schema_name,
    )
    return result == expected_owner


async def check_no_excess_table_privileges(
    conn: asyncpg.Connection, schema_name: str, table_name: str, role_name: str, intended_privileges: list[str]
) -> bool:
    """The negative counterpart to check_has_table_privileges — true iff
    role_name holds NONE of the privileges that a bare ownership
    transfer silently confers beyond intended_privileges: DELETE,
    TRUNCATE, REFERENCES, TRIGGER, MAINTAIN always, plus UPDATE when
    intended_privileges doesn't include it. This is the specific check
    this project's own history has now needed twice for the identical
    reason before this function existed to catch it automatically:
    ADR-023's own finding (2) — app_role, as the new owner of all 12
    public tables, silently picked up every one of these — and its
    exact recurrence in the investigation schema at Phase 6's first
    opportunity (investigation_role, as the new owner of
    investigation_runs, picked up the identical set the moment its own
    Managed Identity existed to map it to). Five real instances of this
    bug class have been found by a person looking (Task 39, Task 43
    twice, ADR-023 twice); this check exists so the sixth is found
    automatically instead.

    Verified empirically before this function was written, not assumed
    from Postgres documentation: has_table_privilege's table-level OID
    form correctly reflects REVOKE against these privileges even for
    the object's own owner — none of DELETE/TRUNCATE/REFERENCES/
    TRIGGER/MAINTAIN are "owner-implicit and unrevokable" the way DDL
    actions (ALTER/DROP/GRANT) are, so this check is genuinely
    satisfiable, not structurally doomed to always fail for whichever
    role happens to own the object.

    Same OID-resolution technique as check_has_table_privileges, for
    the identical real reason: has_table_privilege's text-identifier
    overload fails against a schema the connecting role has no USAGE
    on.
    """
    forbidden = list(OWNERSHIP_IMPLIED_PRIVILEGES)
    if "UPDATE" not in intended_privileges:
        forbidden.append("UPDATE")
    oid = await conn.fetchval(
        "SELECT c.oid FROM pg_catalog.pg_class c "
        "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = $1 AND c.relname = $2",
        schema_name,
        table_name,
    )
    if oid is None:
        return False
    for privilege in forbidden:
        result = await conn.fetchval(
            "SELECT has_table_privilege($1, $2::oid, $3)", role_name, oid, privilege
        )
        if result:
            return False
    return True


async def run_all_checks(conn: asyncpg.Connection) -> list[tuple[str, bool]]:
    results: list[tuple[str, bool]] = []

    for table in EXPECTED_TABLES:
        results.append((f"table exists: {table}", await check_table_exists(conn, table)))

    results.append(("column exists: findings.title", await check_column_exists(conn, "findings", "title")))
    results.append(("column exists: findings.evidence", await check_column_exists(conn, "findings", "evidence")))
    results.append(
        ("column exists: reports.quality_gate_outcome", await check_column_exists(conn, "reports", "quality_gate_outcome"))
    )
    results.append(
        ("column dropped: reports.curated_features", not await check_column_exists(conn, "reports", "curated_features"))
    )
    results.append(
        ("column exists: reports.is_test_fixture (0009)", await check_column_exists(conn, "reports", "is_test_fixture"))
    )

    results.append(
        ("generated column: configurations.manifest_complete",
         await check_generated_column(conn, "configurations", "manifest_complete"))
    )

    results.append(
        ("CHECK constraint: reports.rag_status",
         await check_check_constraint_values(conn, "reports", "rag_status", ["Red", "Amber", "Green", "Unknown"]))
    )
    results.append(
        ("CHECK constraint: findings.status_label",
         await check_check_constraint_values(
             conn, "findings", "status_label", ["On Track", "At Risk", "Blocked", "Needs Human Review"]
         ))
    )
    results.append(
        ("CHECK constraint: reports.quality_gate_outcome",
         await check_check_constraint_values(
             conn, "reports", "quality_gate_outcome", ["approved", "route_to_human_review"]
         ))
    )
    results.append(
        ("CHECK constraint: actors.role",
         await check_check_constraint_values(
             conn, "actors", "role",
             ["portfolio_lead", "program_lead", "platform_admin", "owner", "visitor"],
         ))
    )

    results.append(
        ("CHECK constraint: reports.week_of is Monday-only (0002, NOT VALID)",
         await check_constraint_exists(conn, "reports", "reports_week_of_is_monday"))
    )
    results.append(
        ("Partial unique index (0014): reports(program_id, week_of) real-only, is_test_fixture rows excluded",
         await check_index_definition_contains(
             conn, "reports", "reports_program_id_week_of_real_key", "WHERE (NOT is_test_fixture)"
         ))
    )
    results.append(
        ("CHECK constraint: approval_records rejected decisions require notes (0002)",
         await check_constraint_exists(conn, "approval_records", "approval_records_rejected_notes_required"))
    )

    results.append(("RLS enabled: reports", await check_rls_enabled(conn, "reports")))
    results.append(("RLS policy exists: reports.tenant_isolation", await check_policy_exists(conn, "reports", "tenant_isolation")))
    results.append(
        ("RLS policy (0008): tenant_isolation treats both NULL and '' as unset (NULLIF fix)",
         await check_policy_definition_contains(conn, "reports", "tenant_isolation", "NULLIF"))
    )
    results.append(
        ("FORCE ROW LEVEL SECURITY: reports (app_role, its owner, is not exempt from tenant_isolation)",
         await check_force_rls_enabled(conn, "reports"))
    )

    for role in ("app_role", "app_role_local_dev"):
        results.append(
            (f"approval_records append-only for {role}",
             await check_privilege_revoked(conn, "approval_records", role, ["UPDATE", "DELETE"]))
        )

    # Migration Plan Phase 8 follow-up, real live finding, then a real
    # fix (ADR-028): the two ACL-based checks above prove nothing about
    # a role that reaches real UPDATE/DELETE via predefined-role
    # membership (`pg_write_all_data`) rather than an explicit GRANT.
    # `azure_pg_admin` (this server's real Entra Administrator role, and
    # every identity that is a member of it) is a member of
    # `pg_write_all_data`, which grants UPDATE/DELETE/INSERT/TRUNCATE on
    # every table in every schema unconditionally, with zero
    # corresponding row in information_schema.role_table_grants —
    # confirmed live: `has_table_privilege('azure_pg_admin', ...)`
    # reports `true`, and a direct `REVOKE` runs with no error and
    # changes nothing. `check_real_privilege_denied` (below, kept as a
    # reusable, correct function) will therefore always, permanently,
    # correctly report `False` for azure_pg_admin here — that is not a
    # bug to chase, it is the real, structural fact a REVOKE cannot
    # reach. The actual guarantee now rests on a trigger (migration
    # 0011), which fires regardless of which privilege path let the
    # statement reach the table — confirmed live, adversarially, as the
    # raw admin identity: a real DELETE and a real UPDATE against a real
    # existing row both raise `approval_records is append-only`, and the
    # row is confirmed unchanged afterward (CLAUDE.md Task 49 follow-up;
    # ADR-028 has the full account). The check that matters now is
    # whether that trigger genuinely exists and is armed, not whether
    # the underlying privilege is absent — it never can be.
    results.append(
        ("approval_records append-only enforcement: real trigger exists and is armed (ADR-028, migration 0011)",
         await check_trigger_exists_and_enabled(conn, "approval_records", "approval_records_append_only"))
    )

    results.append(
        ("CHECK constraint: cycles.status covers all 4 ADR-021 terminal outcomes + queued/running/failed (0003)",
         await check_check_constraint_values(
             conn, "cycles", "status",
             ["queued", "running", "persisted", "persisted_route_to_human_review",
              "not_persisted_already_exists", "hard_stop_defect", "failed"],
         ))
    )
    results.append(("column exists: cycles.trace_context", await check_column_exists(conn, "cycles", "trace_context")))
    results.append(("column exists: cycles.stages", await check_column_exists(conn, "cycles", "stages")))
    results.append(("column exists: cycles.force (0015)", await check_column_exists(conn, "cycles", "force")))

    results.append(("schema exists: investigation (0004)", await check_schema_exists(conn, "investigation")))
    results.append(
        ("table exists: investigation.investigation_runs",
         await check_table_exists_in_schema(conn, "investigation", "investigation_runs"))
    )

    # Real column-level shape of investigation.investigation_runs — every
    # column the Investigation service's own store.py reads/writes,
    # checked individually (not just "the table exists"), same rigor
    # every other real table in this schema already gets.
    for column in (
        "cycle_id", "program_name", "requested_by_actor_id", "status",
        "queried_item_count", "findings", "tower_hierarchy", "error_detail",
        "trace_context", "created_at", "updated_at",
    ):
        results.append(
            (f"column exists: investigation.investigation_runs.{column}",
             await check_column_exists_in_schema(conn, "investigation", "investigation_runs", column))
        )
    results.append(
        ("CHECK constraint: investigation.investigation_runs.status (running/completed/failed)",
         await check_constraint_exists_in_schema(
             conn, "investigation", "investigation_runs", "investigation_runs_status_check"
         ))
    )

    results.append(
        ("Reporting role (app_role_local_dev) has NO access to investigation schema",
         await check_no_schema_privilege(conn, "investigation", "app_role_local_dev"))
    )
    results.append(
        ("Investigation role (investigation_role_local_dev) has NO access to public schema",
         await check_no_schema_privilege(conn, "public", "investigation_role_local_dev"))
    )

    # Pre-Phase-7 audit (2026-09-10): the investigation schema had NO
    # ownership check at all before this, and its one privilege check
    # targeted only investigation_role_local_dev — never
    # investigation_role, the role that actually carries load on
    # deployed compute from Phase 7 on. Both gaps closed here, mirroring
    # the exact positive-ownership/positive-grant/negative-excess triple
    # the public schema gets below, for BOTH roles, not just the local
    # one.
    #
    # Precise, checked scope of what the two ownership checks below can
    # currently catch, found while demonstrating them against a
    # deliberately wrong state: Postgres's ALTER TABLE/SCHEMA ... OWNER TO
    # refuses to let a role become an owner inside a schema it has no
    # CREATE privilege on (confirmed live — `app_role_local_dev` has zero
    # privilege of any kind on `investigation`, including CREATE, and a
    # direct attempt to hand it ownership here fails with a real
    # InsufficientPrivilegeError before the ALTER even runs). That means
    # the exact historical bug this check exists to catch (a
    # cross-service role silently ending up as owner) is not reachable
    # TODAY via that path for this schema specifically — it was only
    # reachable, and only ever actually happened, via `migrate.py`
    # connecting under the WRONG role at CREATE time (the real root cause
    # both this schema's ownership bug and ADR-023's did originate from),
    # not via a later ALTER. The check is not redundant, though: it
    # guards against a real, plausible future change — anyone later
    # granting CREATE on `investigation` to `app_role`/`app_role_local_dev`
    # for some unrelated reason would silently reopen this exact path,
    # and this check would be the thing that notices. Demonstrating it
    # required working within the investigation role family instead
    # (`investigation_role` <-> `investigation_role_local_dev`, which
    # does have real CREATE on its own schema) — see ADR-023's own
    # Consequences for what that demonstration then found.
    results.append(
        ("schema owner: investigation is owned by investigation_role",
         await check_schema_owner(conn, "investigation", "investigation_role"))
    )
    for table, profile in INVESTIGATION_TABLE_PROFILES.items():
        results.append(
            (f"table owner: investigation.{table} is owned by investigation_role",
             await check_object_owner(conn, "investigation", table, "investigation_role"))
        )
        for role in ("investigation_role", "investigation_role_local_dev"):
            results.append(
                (f"investigation.{table}: {role} has the intended grant profile {profile}",
                 await check_has_table_privileges(conn, "investigation", table, role, profile))
            )
            results.append(
                (f"investigation.{table}: {role} has NO ownership-implied excess privileges "
                 f"(DELETE/TRUNCATE/REFERENCES/TRIGGER/MAINTAIN" +
                 ("" if "UPDATE" in profile else "/UPDATE") + ")",
                 await check_no_excess_table_privileges(conn, "investigation", table, role, profile))
            )

    # Real, positive ownership assertion (Task 44 follow-up) for every
    # table and sequence in `public` — closes the exact gap that let all
    # 12 tables + 6 sequences silently belong to app_role_local_dev for
    # this entire project's history, invisible to every check above.
    for table in EXPECTED_TABLES:
        results.append(
            (f"table owner: public.{table} is owned by app_role",
             await check_object_owner(conn, "public", table, "app_role"))
        )
    for sequence in (
        "actor_scope_scope_id_seq", "approval_records_approval_id_seq",
        "findings_finding_id_seq", "reports_report_id_seq",
        "untracked_items_untracked_item_id_seq", "usage_ledger_usage_id_seq",
    ):
        results.append(
            (f"sequence owner: public.{sequence} is owned by app_role",
             await check_object_owner(conn, "public", sequence, "app_role"))
        )

    # Pre-Phase-7 audit (2026-09-10): ownership alone (above) doesn't
    # prove the ACTUAL grant profile is correct — a table can be owned
    # correctly and still carry a silently-widened ACL if REVOKE ALL was
    # never re-run, or a future migration change reintroduces it.
    # Positive (has the intended set) and negative (has none of what
    # ownership transfer silently confers beyond it) checks together are
    # what actually proves the profile app_role/app_role_local_dev
    # documented in 0004 is what's real today, for every table, for both
    # roles — the same triple just added for the investigation schema
    # above, applied here for the schema this bug was first found in.
    for table, profile in PUBLIC_TABLE_PROFILES.items():
        for role in ("app_role", "app_role_local_dev"):
            results.append(
                (f"public.{table}: {role} has the intended grant profile {profile}",
                 await check_has_table_privileges(conn, "public", table, role, profile))
            )
            results.append(
                (f"public.{table}: {role} has NO ownership-implied excess privileges "
                 f"(DELETE/TRUNCATE/REFERENCES/TRIGGER/MAINTAIN" +
                 ("" if "UPDATE" in profile else "/UPDATE") + ")",
                 await check_no_excess_table_privileges(conn, "public", table, role, profile))
            )

    return results


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True, choices=list(TARGETS))
    args = parser.parse_args()

    settings = TARGETS[args.target]
    client = await PostgresClient.connect(settings, min_size=1, max_size=2)
    try:
        async with client.pool.acquire() as conn:
            results = await run_all_checks(conn)
    finally:
        await client.close()

    failed = [name for name, ok in results if not ok]
    for name, ok in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")

    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed.")
    if failed:
        print(f"\nFAILED: {failed}")
        sys.exit(1)
    print("Migration verified against live information_schema/pg_catalog — not just a clean migrate.py exit code.")


if __name__ == "__main__":
    asyncio.run(main())
