"""Build Plan Phase 2's explicit demand: prove verify_migration.py would
actually fail if a migration silently didn't apply — not just that its
checks pass against a schema that's already correct. Every test here
forces the exact failure mode against the real onepulse-pg-dev database:
checking for something that genuinely does not exist, live, over the
real connection this project's Managed Identity client uses everywhere
else — not a mock, and not a check against a name that merely happens
to look wrong.
"""

from __future__ import annotations

import os

import pytest
import pytest_asyncio

from onepulse_common.config import PostgresSettings
from onepulse_common.db import PostgresClient
from verify_migration import (
    check_check_constraint_values,
    check_column_exists,
    check_constraint_exists,
    check_generated_column,
    check_policy_exists,
    check_privilege_revoked,
    check_rls_enabled,
    check_table_exists,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def conn():
    settings = PostgresSettings(
        host="onepulse-pg-dev.postgres.database.azure.com",
        database="onepulse",
        role_name=os.environ.get("ONEPULSE_PG_ROLE", "app_role_local_dev"),
    )
    client = await PostgresClient.connect(settings, min_size=1, max_size=1)
    async with client.pool.acquire() as c:
        yield c
    await client.close()


async def test_real_table_is_detected(conn) -> None:
    assert await check_table_exists(conn, "reports") is True


async def test_forced_failure_missing_table_is_detected(conn) -> None:
    """Forces the exact drift scenario: a table that was never created
    (or a migration that silently didn't apply). Proves the check
    queries information_schema for real rather than always returning
    True.
    """
    assert await check_table_exists(conn, "this_table_does_not_exist_1a2b3c") is False


async def test_forced_failure_missing_column_is_detected(conn) -> None:
    assert await check_column_exists(conn, "reports", "this_column_does_not_exist") is False


async def test_forced_failure_non_generated_column_is_not_reported_as_generated(conn) -> None:
    # reports.executive_summary is a real, plain column — proves the
    # generated-column check distinguishes GENERATED ALWAYS from an
    # ordinary column that simply exists, not just column presence.
    assert await check_generated_column(conn, "reports", "executive_summary") is False


async def test_forced_failure_wrong_check_constraint_values_detected(conn) -> None:
    # The real constraint only allows Red/Amber/Green/Unknown — asking
    # for a value that was never in it must fail, proving this reads
    # the real constraint text rather than just confirming a
    # constraint object exists under that name.
    assert (
        await check_check_constraint_values(conn, "reports", "rag_status", ["Purple"])
        is False
    )


async def test_forced_failure_rls_not_enabled_on_unprotected_table_detected(conn) -> None:
    # tenants has no RLS enabled by design — proves this isn't hardcoded
    # to always return True for any table name.
    assert await check_rls_enabled(conn, "tenants") is False


async def test_forced_failure_missing_policy_detected(conn) -> None:
    assert await check_policy_exists(conn, "reports", "this_policy_does_not_exist") is False


async def test_forced_failure_revoke_check_detects_a_real_grant(conn) -> None:
    # findings genuinely grants INSERT to app_role_local_dev (Task 2's
    # own migration) — using it here as the real "still granted" case
    # proves check_privilege_revoked can actually detect a live grant,
    # not just report True unconditionally.
    assert (
        await check_privilege_revoked(conn, "findings", "app_role_local_dev", ["INSERT"])
        is False
    )


async def test_real_week_of_monday_check_constraint_is_detected(conn) -> None:
    # Migration 0002's real constraint — proves the check queries
    # pg_constraint for real rather than always returning True.
    assert await check_constraint_exists(conn, "reports", "reports_week_of_is_monday") is True


async def test_forced_failure_missing_named_constraint_is_detected(conn) -> None:
    assert (
        await check_constraint_exists(conn, "reports", "this_constraint_does_not_exist_1a2b3c")
        is False
    )


async def test_real_rejected_notes_required_check_constraint_is_detected(conn) -> None:
    assert (
        await check_constraint_exists(
            conn, "approval_records", "approval_records_rejected_notes_required"
        )
        is True
    )


async def test_real_cycles_table_is_detected(conn) -> None:
    # Migration 0003 (Phase 3 status table) — proves the check queries
    # information_schema for real, same discipline as every table above.
    assert await check_table_exists(conn, "cycles") is True


async def test_real_cycles_status_check_constraint_covers_all_terminal_outcomes(conn) -> None:
    assert (
        await check_check_constraint_values(
            conn, "cycles", "status",
            ["queued", "running", "persisted", "persisted_route_to_human_review",
             "not_persisted_already_exists", "hard_stop_defect", "failed"],
        )
        is True
    )


async def test_forced_failure_cycles_status_check_rejects_a_value_never_in_the_constraint(conn) -> None:
    assert (
        await check_check_constraint_values(conn, "cycles", "status", ["purple_haze"])
        is False
    )
