"""Real, adversarial proof of Migration Plan Phase 4's own database-per-
service boundary (ADR-020) — the Investigation service's schema and the
Reporting service's schema are mutually inaccessible, enforced by real
Postgres grants, not by discipline. Same evidentiary standard as
tests/test_bff_no_data_access.py (structural, adversarial) and the
approval_records append-only guarantee (a real cross-role query, shown
failing with a real permission error, not "no connection string
configured").

Real, live-found subtlety this migration had to correct, not assumed
away: `CREATE SCHEMA investigation` run by app_role_local_dev (whichever
role happens to run scripts/migrate.py) makes that role the schema
OWNER, and ownership grants full access regardless of any GRANT/REVOKE
— the exact same class of gap Task 31 already found once for RLS
(`FORCE ROW LEVEL SECURITY`/table ownership). Fixed by transferring real
ownership to investigation_role_local_dev and revoking the leftover
creator ACL entry. A second, separate real gap: Postgres grants USAGE
on the `public` schema to the PUBLIC pseudo-role by default — silently
giving investigation_role_local_dev access to `public` with no explicit
grant at all. Fixed by revoking that ambient grant and re-granting
USAGE on `public` explicitly to the real Reporting roles only. Both
fixes are real, one-time admin actions (documented in
scripts/migrations/0004_add_investigation_schema.sql's own comments),
not something a migration run as a non-admin role can perform itself.
"""

from __future__ import annotations

import os

import asyncpg
import pytest
import pytest_asyncio

from onepulse_common.config import PostgresSettings
from onepulse_common.db import PostgresClient

PG_HOST = "onepulse-pg-dev.postgres.database.azure.com"
PG_DATABASE = "onepulse"


@pytest_asyncio.fixture
async def reporting_conn():
    settings = PostgresSettings(
        host=PG_HOST, database=PG_DATABASE,
        role_name=os.environ.get("ONEPULSE_PG_ROLE", "app_role_local_dev"),
    )
    client = await PostgresClient.connect(settings, min_size=1, max_size=1)
    async with client.pool.acquire() as conn:
        yield conn
    await client.close()


@pytest_asyncio.fixture
async def investigation_conn():
    settings = PostgresSettings(
        host=PG_HOST, database=PG_DATABASE,
        role_name=os.environ.get("ONEPULSE_INVESTIGATION_PG_ROLE", "investigation_role_local_dev"),
    )
    client = await PostgresClient.connect(settings, min_size=1, max_size=1)
    async with client.pool.acquire() as conn:
        yield conn
    await client.close()


@pytest.mark.asyncio
async def test_reporting_role_cannot_query_investigation_schema(reporting_conn) -> None:
    """The rule that decides whether the split is real: the Reporting
    role must be structurally unable to read the Investigation
    service's own schema, not merely never told to.
    """
    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError, match="permission denied for schema investigation"):
        await reporting_conn.fetch("SELECT * FROM investigation.investigation_runs LIMIT 1")


@pytest.mark.asyncio
async def test_investigation_role_cannot_query_public_reports(investigation_conn) -> None:
    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError, match="permission denied for schema public"):
        await investigation_conn.fetch("SELECT * FROM public.reports LIMIT 1")


@pytest.mark.asyncio
async def test_investigation_role_cannot_query_public_cycles(investigation_conn) -> None:
    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError, match="permission denied for schema public"):
        await investigation_conn.fetch("SELECT * FROM public.cycles LIMIT 1")


@pytest.mark.asyncio
async def test_reporting_role_can_still_use_its_own_schema(reporting_conn) -> None:
    """Confirms the boundary is real isolation, not a blanket lockout —
    the Reporting role's own real access is unaffected by the fixes
    above (in particular, revoking PUBLIC's ambient USAGE on `public`
    and re-granting it explicitly).
    """
    result = await reporting_conn.fetchval("SELECT count(*) FROM public.reports")
    assert result is not None


@pytest.mark.asyncio
async def test_investigation_role_can_still_use_its_own_schema(investigation_conn) -> None:
    result = await investigation_conn.fetchval("SELECT count(*) FROM investigation.investigation_runs")
    assert result is not None
