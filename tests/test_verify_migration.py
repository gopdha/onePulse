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
    check_column_exists_in_schema,
    check_constraint_exists,
    check_constraint_exists_in_schema,
    check_generated_column,
    check_has_table_privileges,
    check_no_schema_privilege,
    check_policy_exists,
    check_privilege_revoked,
    check_rls_enabled,
    check_schema_exists,
    check_table_exists,
    check_table_exists_in_schema,
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


async def test_real_investigation_schema_is_detected(conn) -> None:
    # Migration Plan Phase 4 — proves this reads pg_catalog.pg_namespace
    # for real, not information_schema.schemata (which the connecting
    # role's own real, structural lack of access to `investigation`
    # would otherwise make wrongly report "missing" — see
    # check_schema_exists's own docstring).
    assert await check_schema_exists(conn, "investigation") is True


async def test_forced_failure_missing_schema_is_detected(conn) -> None:
    assert await check_schema_exists(conn, "this_schema_does_not_exist_1a2b3c") is False


async def test_real_investigation_runs_table_is_detected_in_its_own_schema(conn) -> None:
    assert await check_table_exists_in_schema(conn, "investigation", "investigation_runs") is True


async def test_forced_failure_table_in_wrong_schema_is_not_detected(conn) -> None:
    # investigation_runs genuinely does not live in `public` — proves
    # this check is schema-scoped, not just table-name matching.
    assert await check_table_exists_in_schema(conn, "public", "investigation_runs") is False


async def test_real_reporting_role_has_no_investigation_schema_privilege(conn) -> None:
    assert await check_no_schema_privilege(conn, "investigation", "app_role_local_dev") is True


async def test_forced_failure_schema_privilege_check_detects_a_real_grant(conn) -> None:
    # app_role_local_dev genuinely does have USAGE on `public` (its own
    # real schema) — proves this check can detect a real grant, not just
    # report True unconditionally.
    assert await check_no_schema_privilege(conn, "public", "app_role_local_dev") is False


async def test_real_investigation_runs_columns_are_detected(conn) -> None:
    # Merge-review finding: the original Phase 4 checks only proved the
    # TABLE exists, never its actual column shape — every other real
    # table in this schema gets column-level checks; this one hadn't.
    # Run over the SAME app_role_local_dev connection every other check
    # here uses, which has zero USAGE on `investigation` — proves this
    # reads pg_catalog.pg_attribute directly, not information_schema.
    # columns (which would be empty for this connection, same real
    # visibility trap check_schema_exists's own docstring documents).
    for column in ("cycle_id", "program_name", "status", "findings", "tower_hierarchy"):
        assert await check_column_exists_in_schema(conn, "investigation", "investigation_runs", column) is True


async def test_forced_failure_missing_column_in_schema_is_detected(conn) -> None:
    assert await check_column_exists_in_schema(
        conn, "investigation", "investigation_runs", "this_column_does_not_exist_1a2b3c"
    ) is False


async def test_forced_failure_column_in_wrong_schema_is_not_detected(conn) -> None:
    # cycle_id genuinely does not live on any public.* table.
    assert await check_column_exists_in_schema(conn, "public", "reports", "cycle_id") is False


async def test_real_investigation_runs_status_check_constraint_is_detected(conn) -> None:
    # Real, live-discovered gap fixed at merge review: check_constraint_
    # exists's own `$1::regclass` cast fails with a real
    # InsufficientPrivilegeError for this connection against a schema it
    # has no USAGE on (identifier resolution itself needs schema
    # visibility, unlike a plain pg_catalog WHERE-clause scan) — this is
    # the schema-safe replacement, proven against the real constraint.
    assert await check_constraint_exists_in_schema(
        conn, "investigation", "investigation_runs", "investigation_runs_status_check"
    ) is True


async def test_forced_failure_missing_constraint_in_schema_is_detected(conn) -> None:
    assert await check_constraint_exists_in_schema(
        conn, "investigation", "investigation_runs", "this_constraint_does_not_exist_1a2b3c"
    ) is False


async def test_real_investigation_role_can_use_its_own_schema(conn) -> None:
    # The first positive-grant check anywhere in this file — every other
    # check here is structural existence or a negative/REVOKE proof.
    # Proves investigation_role_local_dev genuinely holds real
    # SELECT/INSERT/UPDATE on its own table, over the SAME
    # app_role_local_dev connection every other test here uses (which
    # cannot see the investigation schema at all) — proving the OID-
    # based resolution this check uses is unaffected by the connecting
    # role's own lack of access to the schema being asked about.
    assert await check_has_table_privileges(
        conn, "investigation", "investigation_runs", "investigation_role_local_dev",
        ["SELECT", "INSERT", "UPDATE"],
    ) is True


async def test_forced_failure_has_table_privileges_detects_a_real_missing_grant(conn) -> None:
    # app_role_local_dev genuinely has no grant at all on
    # investigation.investigation_runs (the whole point of this
    # boundary) — proves the check can report False, not just True
    # unconditionally.
    assert await check_has_table_privileges(
        conn, "investigation", "investigation_runs", "app_role_local_dev", ["SELECT"]
    ) is False
