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
    check_force_rls_enabled,
    check_generated_column,
    check_has_table_privileges,
    check_no_excess_table_privileges,
    check_no_schema_privilege,
    check_object_owner,
    check_policy_definition_contains,
    check_policy_exists,
    check_privilege_revoked,
    check_real_privilege_denied,
    check_rls_enabled,
    check_schema_exists,
    check_schema_owner,
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


async def test_real_force_rls_is_enabled_on_reports(conn) -> None:
    # ADR-023 follow-up: FORCE was enabled specifically because app_role
    # now owns `reports` and would otherwise be exempt from its own
    # tenant_isolation policy — the same owner-exemption bug one level
    # up. Real, current state, not assumed from the migration file alone.
    assert await check_force_rls_enabled(conn, "reports") is True


async def test_forced_failure_force_rls_not_enabled_on_unprotected_table_detected(conn) -> None:
    # tenants has no RLS/FORCE at all — proves this isn't hardcoded to
    # always return True for any table name.
    assert await check_force_rls_enabled(conn, "tenants") is False


async def test_real_tenant_isolation_policy_has_the_0008_nullif_fix(conn) -> None:
    # Migration 0008: check_policy_exists alone can't distinguish the
    # real, live-broken 0005 shape (IS NULL only) from the fixed 0008
    # one (NULLIF(..., '') IS NULL) — both satisfy "a policy named
    # tenant_isolation exists". This reads the real qual text.
    assert await check_policy_definition_contains(conn, "reports", "tenant_isolation", "NULLIF") is True


async def test_forced_failure_policy_definition_missing_substring_detected(conn) -> None:
    assert (
        await check_policy_definition_contains(
            conn, "reports", "tenant_isolation", "this substring is not in the real policy text"
        )
        is False
    )


async def test_forced_failure_revoke_check_detects_a_real_grant(conn) -> None:
    # findings genuinely grants INSERT to app_role_local_dev (Task 2's
    # own migration) — using it here as the real "still granted" case
    # proves check_privilege_revoked can actually detect a live grant,
    # not just report True unconditionally.
    assert (
        await check_privilege_revoked(conn, "findings", "app_role_local_dev", ["INSERT"])
        is False
    )


async def test_real_privilege_denied_check_passes_for_app_role_local_dev(conn) -> None:
    # The real, still-correct case: app_role_local_dev's own ACL grant
    # on approval_records is genuinely SELECT+INSERT only.
    assert (
        await check_real_privilege_denied(conn, "approval_records", "app_role_local_dev", ["UPDATE", "DELETE"])
        is True
    )


async def test_real_privilege_denied_check_detects_the_real_azure_pg_admin_gap(conn) -> None:
    # The real, live gap this task found (ADR-028): azure_pg_admin
    # reaches real DELETE/UPDATE via predefined-role membership
    # (pg_write_all_data), invisible to check_privilege_revoked's own
    # information_schema-based query. This must FAIL today, honestly —
    # it is the exact assertion the fix (once decided) needs to flip.
    assert (
        await check_real_privilege_denied(conn, "approval_records", "azure_pg_admin", ["UPDATE", "DELETE"])
        is False
    )


async def test_real_privilege_denied_check_can_report_a_genuine_pass(conn) -> None:
    # Proves this isn't hardcoded to always return False for
    # azure_pg_admin-like inputs: a privilege it genuinely lacks
    # (a role with no real access to a completely unrelated,
    # nonexistent-for-it privilege combination) still reports True.
    # tenants has no CHECK/RLS/anything special — app_role_local_dev's
    # own real grant there is SELECT+INSERT, same shape as
    # approval_records, confirming the function isn't just special-cased.
    assert (
        await check_real_privilege_denied(conn, "tenants", "app_role_local_dev", ["UPDATE", "DELETE"])
        is True
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


async def test_real_public_table_is_owned_by_app_role(conn) -> None:
    # Task 44 follow-up: the first positive-OWNERSHIP check in this file
    # — every check above proves existence or a GRANT, none of them
    # would have caught the real bug that motivated this (all 12 public
    # tables silently owned by app_role_local_dev instead of app_role).
    # Real, retroactively-fixed state, confirmed over the same
    # app_role_local_dev connection every other test here uses.
    assert await check_object_owner(conn, "public", "programs", "app_role") is True


async def test_forced_failure_object_owner_detects_the_real_wrong_owner(conn) -> None:
    # app_role_local_dev genuinely does NOT own `programs` anymore (the
    # whole point of the retroactive fix) — proves the check reports
    # False for the exact wrong-owner state this project's real history
    # had for months, not just True unconditionally.
    assert await check_object_owner(conn, "public", "programs", "app_role_local_dev") is False


# --- Pre-Phase-7 audit (2026-09-10): schema owner, negative-excess- ---
# --- privilege, and the investigation-role (not just local_dev)    ---
# --- positive-grant checks — closing the exact gap the user named:  ---
# --- the investigation schema had no ownership check at all, and    ---
# --- its one privilege check targeted the local-dev role instead of ---
# --- the role that actually carries load once deployed.             ---


async def test_real_investigation_schema_is_owned_by_investigation_role(conn) -> None:
    assert await check_schema_owner(conn, "investigation", "investigation_role") is True


async def test_forced_failure_schema_owner_detects_a_wrong_owner(conn) -> None:
    # investigation_role_local_dev genuinely does not own the schema
    # (investigation_role does) — proves this reports False for a real,
    # plausible-but-wrong role name, not just True unconditionally.
    assert await check_schema_owner(conn, "investigation", "investigation_role_local_dev") is False


async def test_real_investigation_runs_table_is_owned_by_investigation_role(conn) -> None:
    # The exact gap the user's message named directly: no ownership
    # check existed for this schema at all before this task. Real,
    # live-fixed state (Task 43's merge-review finding, Phase 6's own
    # re-transfer) — not assumed correct, queried directly.
    assert await check_object_owner(conn, "investigation", "investigation_runs", "investigation_role") is True


async def test_forced_failure_investigation_table_owner_detects_a_wrong_owner(conn) -> None:
    # investigation_role_local_dev is a real, plausible wrong answer —
    # it held this exact ownership by mistake once, historically (Task
    # 43's own merge-review finding) — proves the check distinguishes
    # it from the real current owner, not just True unconditionally.
    assert await check_object_owner(conn, "investigation", "investigation_runs", "investigation_role_local_dev") is False


async def test_real_investigation_role_has_intended_grant_profile(conn) -> None:
    # The role gap the user named directly: the one prior privilege
    # check in this file targeted investigation_role_local_dev only.
    # investigation_role is the real production role Phase 7 deploys —
    # this proves it genuinely holds the intended SELECT/INSERT/UPDATE,
    # not merely that its local-dev mirror does.
    assert await check_has_table_privileges(
        conn, "investigation", "investigation_runs", "investigation_role",
        ["SELECT", "INSERT", "UPDATE"],
    ) is True


async def test_real_public_table_has_no_ownership_implied_excess_privileges(conn) -> None:
    # The specific bug class this task closes: app_role, as programs'
    # new owner (ADR-023), silently picked up TRUNCATE/REFERENCES/
    # TRIGGER/MAINTAIN/DELETE — this proves the current, fixed state
    # genuinely has none of them, not just that the positive profile
    # check above happens to pass.
    assert await check_no_excess_table_privileges(
        conn, "public", "programs", "app_role", ["SELECT", "INSERT"]
    ) is True


async def test_forced_failure_no_excess_check_detects_a_real_excess_without_mutating_the_database(conn) -> None:
    # app_role genuinely DOES have real, intended UPDATE on `reports`
    # (0004's own grant) — asking this check whether app_role has "no
    # excess beyond SELECT alone" must report False, since UPDATE is
    # then treated as an unintended excess under that narrower profile.
    # Real, live data proves the check can detect an excess without any
    # database mutation — the same discipline check_privilege_revoked's
    # own forced-failure test above already uses.
    assert (
        await check_no_excess_table_privileges(conn, "public", "reports", "app_role", ["SELECT"])
        is False
    )


async def test_real_investigation_runs_has_no_ownership_implied_excess_privileges(conn) -> None:
    # Mirrors the public-schema check above for the exact schema the
    # bug recurred in (Task 43/Phase 6's own re-discovery of the
    # identical class). Uses investigation_role_local_dev, over the
    # same app_role_local_dev connection every other test here uses —
    # proves the OID-based resolution works for this schema too,
    # regardless of the connecting role's own lack of access to it.
    assert await check_no_excess_table_privileges(
        conn, "investigation", "investigation_runs", "investigation_role_local_dev",
        ["SELECT", "INSERT", "UPDATE"],
    ) is True
