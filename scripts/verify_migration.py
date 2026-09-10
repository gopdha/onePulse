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
    """information_schema.check_constraints stores the raw constraint
    expression text; confirm every expected value literal appears in it
    for the named column's CHECK.
    """
    rows = await conn.fetch(
        """
        SELECT cc.check_clause
        FROM information_schema.check_constraints cc
        JOIN information_schema.constraint_column_usage ccu
          ON cc.constraint_name = ccu.constraint_name
        WHERE ccu.table_schema = 'public' AND ccu.table_name = $1 AND ccu.column_name = $2
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


async def check_policy_exists(conn: asyncpg.Connection, table_name: str, policy_name: str) -> bool:
    result = await conn.fetchval(
        "SELECT 1 FROM pg_policies WHERE schemaname = 'public' AND tablename = $1 AND policyname = $2",
        table_name,
        policy_name,
    )
    return result is not None


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
    """
    rows = await conn.fetch(
        "SELECT privilege_type FROM information_schema.role_table_grants "
        "WHERE table_schema = 'public' AND table_name = $1 AND grantee = $2",
        table_name,
        role_name,
    )
    granted = {r["privilege_type"] for r in rows}
    return not (granted & set(privileges))


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
             conn, "actors", "role", ["portfolio_lead", "program_lead", "platform_admin"]
         ))
    )

    results.append(
        ("CHECK constraint: reports.week_of is Monday-only (0002, NOT VALID)",
         await check_constraint_exists(conn, "reports", "reports_week_of_is_monday"))
    )
    results.append(
        ("CHECK constraint: approval_records rejected decisions require notes (0002)",
         await check_constraint_exists(conn, "approval_records", "approval_records_rejected_notes_required"))
    )

    results.append(("RLS enabled: reports", await check_rls_enabled(conn, "reports")))
    results.append(("RLS policy exists: reports.tenant_isolation", await check_policy_exists(conn, "reports", "tenant_isolation")))

    for role in ("app_role", "app_role_local_dev"):
        results.append(
            (f"approval_records append-only for {role}",
             await check_privilege_revoked(conn, "approval_records", role, ["UPDATE", "DELETE"]))
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
    results.append(
        ("Investigation role (investigation_role_local_dev) genuinely CAN use its own schema "
         "(SELECT/INSERT/UPDATE on investigation.investigation_runs)",
         await check_has_table_privileges(
             conn, "investigation", "investigation_runs", "investigation_role_local_dev",
             ["SELECT", "INSERT", "UPDATE"],
         ))
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
