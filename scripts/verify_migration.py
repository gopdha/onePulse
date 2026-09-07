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


async def check_column_exists(conn: asyncpg.Connection, table_name: str, column_name: str) -> bool:
    result = await conn.fetchval(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = $1 AND column_name = $2",
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

    results.append(("RLS enabled: reports", await check_rls_enabled(conn, "reports")))
    results.append(("RLS policy exists: reports.tenant_isolation", await check_policy_exists(conn, "reports", "tenant_isolation")))

    for role in ("app_role", "app_role_local_dev"):
        results.append(
            (f"approval_records append-only for {role}",
             await check_privilege_revoked(conn, "approval_records", role, ["UPDATE", "DELETE"]))
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
