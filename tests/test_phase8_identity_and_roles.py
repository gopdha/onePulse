"""Migration Plan Phase 8 (ADR-027): real tests against the real
onepulse-pg-dev instance for the identity/role/RLS-scope resolution
`core_api.security.get_current_actor` performs, and for
`onepulse_common.roles`'s pure owner/visitor logic.

Prerequisite: `python scripts/seed_dev_data.py --target dev` and
`python scripts/seed_phase8_test_data.py --target dev` must both have
been run at least once — the latter creates the real second tenant
("Meridian Health") and the real Tenant-A visitor/Tenant-B owner actors
these tests resolve against.

Same transactional-rollback discipline as tests/test_human_governance.py
(Task 40)/tests/test_cycles.py: every test runs inside one real
transaction rolled back on teardown.
"""

from __future__ import annotations

import os

import asyncpg
import pytest
import pytest_asyncio

from core_api.security import resolve_authorized_program_ids, resolve_tenant_id
from onepulse_common.config import PostgresSettings
from onepulse_common.db import PostgresClient
from onepulse_common.human_governance import (
    ReportNotFoundError,
    approve_report,
    get_report_program_id,
)
from onepulse_common.roles import is_owner_role

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
        tx = c.transaction()
        await tx.start()
        try:
            yield c
        finally:
            await tx.rollback()
    await client.close()


async def _actor_id_for(conn, entra_object_id: str) -> str:
    value = await conn.fetchval("SELECT actor_id FROM actors WHERE entra_object_id = $1", entra_object_id)
    assert value is not None, "run scripts/seed_phase8_test_data.py --target dev first"
    return str(value)


# --- onepulse_common.roles: pure, no DB needed ---


def test_is_owner_role_true_for_every_legacy_role() -> None:
    assert is_owner_role("platform_admin") is True
    assert is_owner_role("portfolio_lead") is True
    assert is_owner_role("program_lead") is True


def test_is_owner_role_true_for_the_new_owner_value() -> None:
    assert is_owner_role("owner") is True


def test_is_owner_role_false_only_for_visitor() -> None:
    assert is_owner_role("visitor") is False


# --- Real tenant/scope resolution against the real seeded second tenant ---


async def test_resolve_tenant_id_for_tenant_a_visitor(conn) -> None:
    actor_id = await _actor_id_for(conn, "local-dev-tenant-a-visitor")
    tenant_a_id = await conn.fetchval("SELECT tenant_id FROM tenants WHERE name = 'OnePulse Dev Tenant'")
    resolved = await resolve_tenant_id(conn, actor_id)
    assert resolved == str(tenant_a_id)


async def test_resolve_tenant_id_for_tenant_b_owner_is_a_different_real_tenant(conn) -> None:
    actor_a_id = await _actor_id_for(conn, "local-dev-tenant-a-visitor")
    actor_b_id = await _actor_id_for(conn, "local-dev-tenant-b-owner")
    tenant_a = await resolve_tenant_id(conn, actor_a_id)
    tenant_b = await resolve_tenant_id(conn, actor_b_id)
    assert tenant_a is not None and tenant_b is not None
    assert tenant_a != tenant_b


async def test_resolve_tenant_id_returns_none_for_an_actor_with_no_scope(conn) -> None:
    # A real actors row with zero actor_scope rows — inserted and rolled
    # back within this test's own transaction, never committed.
    tenant_id = await conn.fetchval("SELECT tenant_id FROM tenants WHERE name = 'OnePulse Dev Tenant'")
    actor_id = await conn.fetchval(
        "INSERT INTO actors (tenant_id, role, entra_object_id) VALUES ($1, 'visitor', 'phase8-test-unscoped') "
        "RETURNING actor_id",
        tenant_id,
    )
    resolved = await resolve_tenant_id(conn, str(actor_id))
    assert resolved is None


async def test_resolve_authorized_program_ids_for_tenant_b_owner_includes_the_real_meridian_program(
    conn,
) -> None:
    actor_id = await _actor_id_for(conn, "local-dev-tenant-b-owner")
    meridian_program_id = await conn.fetchval("SELECT program_id FROM programs WHERE name = 'Meridian Patient Portal'")
    program_ids = await resolve_authorized_program_ids(conn, actor_id)
    assert str(meridian_program_id) in program_ids


async def test_resolve_authorized_program_ids_for_tenant_a_visitor_excludes_meridian(conn) -> None:
    # The real, direct proof of scope isolation at the resolution layer
    # itself: Tenant A's visitor is scoped to Tenant A's own portfolio
    # only — Meridian's real program_id must never appear in its
    # resolved set, regardless of what RLS separately does downstream.
    actor_id = await _actor_id_for(conn, "local-dev-tenant-a-visitor")
    meridian_program_id = await conn.fetchval("SELECT program_id FROM programs WHERE name = 'Meridian Patient Portal'")
    program_ids = await resolve_authorized_program_ids(conn, actor_id)
    assert str(meridian_program_id) not in program_ids


# --- Real RLS enforcement against the real second tenant's real data ---


async def test_get_report_program_id_is_none_for_a_report_outside_the_given_tenant(conn) -> None:
    """The real, direct RLS proof: report 997 is real, seeded, genuine
    Tenant-B data (Meridian) — asking for it under Tenant A's own real
    tenant context must come back invisible (None), not merely
    "application code didn't show it".
    """
    tenant_a_id = await conn.fetchval("SELECT tenant_id FROM tenants WHERE name = 'OnePulse Dev Tenant'")
    result = await get_report_program_id(conn, 997, str(tenant_a_id))
    assert result is None


async def test_get_report_program_id_is_visible_under_its_own_real_tenant(conn) -> None:
    tenant_b_id = await conn.fetchval(
        "SELECT tenant_id FROM tenants WHERE name LIKE 'Meridian Health%'"
    )
    result = await get_report_program_id(conn, 997, str(tenant_b_id))
    assert result is not None


async def test_approve_report_is_rejected_for_a_report_outside_the_caller_tenant(conn) -> None:
    """The real, load-bearing negative proof for approve_report itself
    (not just the read-side helper): a Tenant-A actor attempting to
    approve a genuine Tenant-B report_id (997) must be refused —
    ReportNotFoundError, indistinguishable from a report that never
    existed — and must leave zero trace in approval_records.
    """
    tenant_a_id = await conn.fetchval("SELECT tenant_id FROM tenants WHERE name = 'OnePulse Dev Tenant'")
    actor_id = await _actor_id_for(conn, "local-dev-standin-reviewer")

    with pytest.raises(ReportNotFoundError):
        await approve_report(conn, 997, actor_id, str(tenant_a_id))

    count = await conn.fetchval("SELECT count(*) FROM approval_records WHERE report_id = 997")
    assert count == 0
