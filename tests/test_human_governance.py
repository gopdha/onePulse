"""Phase 7 Human Governance API — real tests against the real
onepulse-pg-dev instance. No mocks: every test here writes a real row
and reads it back with a separate, direct query, and the REVOKE test
attempts a real UPDATE/DELETE over the real connection this project
uses everywhere else, to prove the database itself refuses it.

Prerequisite: `python scripts/seed_dev_data.py --target dev` must have
been run at least once, so the singleSlide program and the stand-in
reviewer actor (see seed_dev_data.py) already exist.

Each report-writing test inserts its own fresh report row with a random
week_of (avoiding the UNIQUE(program_id, week_of) constraint across
repeated runs) rather than cleaning up afterwards. Cleanup is not
possible in the general case: approval_records is append-only by design
(REVOKE UPDATE, DELETE — Phase 2), and reports rows that have an
approval_records row referencing them cannot be deleted without
deleting that row first. Accumulating a handful of clearly-marked test
rows in the dev database is the accepted cost of testing this for real
rather than mocking it away.
"""

from __future__ import annotations

import os
import random
from datetime import date, timedelta

import asyncpg
import pytest
import pytest_asyncio

from onepulse_common.config import PostgresSettings
from onepulse_common.db import PostgresClient
from onepulse_common.human_governance import (
    ActorIdRequiredError,
    NotesRequiredError,
    approve_report,
    list_pending_reviews,
    reject_report,
)

pytestmark = pytest.mark.asyncio

TEST_MARKER = "test_human_governance.py fixture row"


def _random_week_of() -> date:
    return date(2000, 1, 1) + timedelta(days=random.randint(0, 2_900_000))


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


@pytest_asyncio.fixture
async def program_id(conn) -> str:
    value = await conn.fetchval("SELECT program_id FROM programs WHERE name = 'singleSlide'")
    assert value is not None, "run scripts/seed_dev_data.py --target dev first"
    return str(value)


@pytest_asyncio.fixture
async def actor_id(conn) -> str:
    value = await conn.fetchval(
        "SELECT actor_id FROM actors WHERE entra_object_id = 'local-dev-standin-reviewer'"
    )
    assert value is not None, "run scripts/seed_dev_data.py --target dev first"
    return str(value)


async def _insert_test_report(conn, program_id: str) -> int:
    return await conn.fetchval(
        """
        INSERT INTO reports (program_id, week_of, rag_status, quality_gate_outcome, executive_summary, trend_line)
        VALUES ($1, $2, 'Amber', 'route_to_human_review', $3, '')
        RETURNING report_id
        """,
        program_id,
        _random_week_of(),
        TEST_MARKER,
    )


async def test_approve_report_end_to_end(conn, program_id, actor_id) -> None:
    report_id = await _insert_test_report(conn, program_id)

    result = await approve_report(conn, report_id, actor_id, notes="looks good")

    assert result["reportId"] == report_id
    assert result["decision"] == "approved"

    # Independent read-back — not trusting the function's own return value.
    row = await conn.fetchrow(
        "SELECT decision, actor_id, notes FROM approval_records WHERE report_id = $1", report_id
    )
    assert row["decision"] == "approved"
    assert str(row["actor_id"]) == actor_id
    assert row["notes"] == "looks good"

    reviewed = await conn.fetchval("SELECT reviewed FROM reports WHERE report_id = $1", report_id)
    assert reviewed is True


async def test_reject_report_end_to_end(conn, program_id, actor_id) -> None:
    report_id = await _insert_test_report(conn, program_id)

    result = await reject_report(conn, report_id, actor_id, notes="evidence for item 8 is stale")

    assert result["reportId"] == report_id
    assert result["decision"] == "rejected"

    row = await conn.fetchrow(
        "SELECT decision, actor_id, notes FROM approval_records WHERE report_id = $1", report_id
    )
    assert row["decision"] == "rejected"
    assert str(row["actor_id"]) == actor_id
    assert row["notes"] == "evidence for item 8 is stale"

    reviewed = await conn.fetchval("SELECT reviewed FROM reports WHERE report_id = $1", report_id)
    assert reviewed is True


async def test_reject_report_requires_notes(conn, program_id, actor_id) -> None:
    report_id = await _insert_test_report(conn, program_id)

    with pytest.raises(NotesRequiredError):
        await reject_report(conn, report_id, actor_id, notes="")

    # Confirm the real row-level consequence, not just the exception type:
    # no approval_records row was written, and the report is still unreviewed.
    count = await conn.fetchval(
        "SELECT count(*) FROM approval_records WHERE report_id = $1", report_id
    )
    assert count == 0
    reviewed = await conn.fetchval("SELECT reviewed FROM reports WHERE report_id = $1", report_id)
    assert reviewed is False


async def test_approve_report_requires_actor_id(conn, program_id) -> None:
    report_id = await _insert_test_report(conn, program_id)

    with pytest.raises(ActorIdRequiredError):
        await approve_report(conn, report_id, actor_id="")

    count = await conn.fetchval(
        "SELECT count(*) FROM approval_records WHERE report_id = $1", report_id
    )
    assert count == 0


async def test_list_pending_reviews_excludes_reviewed_reports(conn, program_id, actor_id) -> None:
    pending_report_id = await _insert_test_report(conn, program_id)
    reviewed_report_id = await _insert_test_report(conn, program_id)
    await approve_report(conn, reviewed_report_id, actor_id)

    result = await list_pending_reviews(conn, program_id)
    ids = {r["reportId"] for r in result["reports"]}

    assert pending_report_id in ids
    assert reviewed_report_id not in ids

    pending_entry = next(r for r in result["reports"] if r["reportId"] == pending_report_id)
    assert pending_entry["qualityGateOutcome"] == "route_to_human_review"


async def test_approval_records_update_is_rejected_by_the_database(conn, program_id, actor_id) -> None:
    """The real, load-bearing test: the REVOKE from Phase 2 must hold at
    the database level, over the exact role this project authenticates
    as locally.

    Note on role naming: the user's instruction named `app_role`
    specifically. This project's own established constraint (db.py's own
    docstring, create_app_role.sql) is that `app_role` is bound 1:1 to a
    deployed workload managed identity's object ID and cannot be
    authenticated locally — only `app_role_local_dev` can be, and it
    received the identical `REVOKE UPDATE, DELETE ON approval_records`
    in Phase 2's migration (0001_initial_schema.sql). This test runs
    against whichever role ONEPULSE_PG_ROLE resolves to (app_role_local_dev
    by default), which is the real, honest substitution for `app_role`
    in a local dev context — not a weaker stand-in.
    """
    report_id = await _insert_test_report(conn, program_id)
    await approve_report(conn, report_id, actor_id)

    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
        await conn.execute(
            "UPDATE approval_records SET notes = 'tampered' WHERE report_id = $1", report_id
        )

    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
        await conn.execute("DELETE FROM approval_records WHERE report_id = $1", report_id)

    # Confirm the row is genuinely untouched, not just that an exception
    # was raised for some unrelated reason.
    row = await conn.fetchrow(
        "SELECT decision, notes FROM approval_records WHERE report_id = $1", report_id
    )
    assert row["decision"] == "approved"
    assert row["notes"] == ""
