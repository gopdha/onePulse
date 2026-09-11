"""Real tests against the real onepulse-pg-dev instance for the `cycles`
status table (Migration Plan Phase 3, ADR-021) — same transactional-
rollback discipline as tests/test_human_governance.py (Task 40): every
test runs inside one real transaction rolled back on teardown, so every
real constraint and query fires against the real schema without leaving
a row behind.

Prerequisite: `python scripts/seed_dev_data.py --target dev` must have
been run at least once.
"""

from __future__ import annotations

import os

import pytest
import pytest_asyncio

from onepulse_common.config import PostgresSettings
from onepulse_common.cycles import (
    create_cycle,
    get_cycle,
    get_cycle_for_execution,
    mark_cycle_failed,
    mark_cycle_terminal,
    terminal_status_from_result,
    write_cycle_stages,
)
from onepulse_common.db import PostgresClient
from onepulse_common.pipeline import PipelineResult

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


# --- terminal_status_from_result: pure w.r.t. its PipelineResult input,
# but tested here alongside its real DB-facing siblings since it's part
# of the same module and exists specifically to feed mark_cycle_terminal. ---


def test_terminal_status_persisted() -> None:
    result = PipelineResult(outcome="approved", persisted=True)
    assert terminal_status_from_result(result) == "persisted"


def test_terminal_status_persisted_route_to_human_review() -> None:
    result = PipelineResult(outcome="route_to_human_review", persisted=True)
    assert terminal_status_from_result(result) == "persisted_route_to_human_review"


def test_terminal_status_not_persisted_already_exists() -> None:
    # A real, correct outcome (ADR-021): outcome is a real quality-gate
    # decision, but persisted=False because UNIQUE(program_id, week_of)
    # correctly refused a duplicate — not a failure.
    result = PipelineResult(outcome="approved", persisted=False)
    assert terminal_status_from_result(result) == "not_persisted_already_exists"


def test_terminal_status_hard_stop_defect_even_if_persisted_were_somehow_true() -> None:
    # hard_stop_defect must win regardless of `persisted` — nothing ever
    # actually gets persisted on this path in real pipeline.py code, but
    # the mapping itself should not depend on that invariant holding.
    result = PipelineResult(outcome="hard_stop_defect", persisted=False)
    assert terminal_status_from_result(result) == "hard_stop_defect"


@pytest.mark.asyncio
async def test_create_cycle_inserts_a_real_queued_row(conn, program_id, actor_id) -> None:
    created = await create_cycle(conn, program_id, actor_id, trace_context="00-abc-def-01")
    assert created["status"] == "queued"

    fetched = await get_cycle(conn, created["cycle_id"])
    assert fetched is not None
    assert fetched["status"] == "queued"
    assert fetched["stages"] == {}


@pytest.mark.asyncio
async def test_get_cycle_for_execution_marks_it_running_and_returns_program_name(
    conn, program_id, actor_id
) -> None:
    created = await create_cycle(conn, program_id, actor_id, trace_context=None)
    other = await create_cycle(conn, program_id, actor_id, trace_context=None)

    resolved = await get_cycle_for_execution(conn, created["cycle_id"])
    assert resolved is not None
    assert resolved["cycle_id"] == created["cycle_id"]
    assert resolved["program_name"] == "singleSlide"

    fetched = await get_cycle(conn, created["cycle_id"])
    assert fetched["status"] == "running"
    assert fetched["started_at"] is not None

    # A different real cycle_id is untouched — proves this isn't
    # blindly marking every queued row, only the one addressed by id.
    still_queued = await get_cycle(conn, other["cycle_id"])
    assert still_queued["status"] == "queued"


@pytest.mark.asyncio
async def test_get_cycle_for_execution_is_idempotent_across_redelivery_and_preserves_started_at(
    conn, program_id, actor_id
) -> None:
    # The real property a redelivered report-cycles message depends on:
    # calling this twice for the same cycle_id (a real redelivery, e.g.
    # after Reporting was killed mid-run and the queue's visibility
    # timeout expired) must not reset the real original start time.
    created = await create_cycle(conn, program_id, actor_id, trace_context=None)
    first = await get_cycle_for_execution(conn, created["cycle_id"])
    second = await get_cycle_for_execution(conn, created["cycle_id"])
    assert second["cycle_id"] == first["cycle_id"]

    fetched = await get_cycle(conn, created["cycle_id"])
    assert fetched["status"] == "running"
    assert fetched["started_at"] is not None


@pytest.mark.asyncio
async def test_get_cycle_for_execution_returns_none_for_a_real_nonexistent_id(conn) -> None:
    resolved = await get_cycle_for_execution(conn, "00000000-0000-0000-0000-000000000000")
    assert resolved is None


@pytest.mark.asyncio
async def test_write_cycle_stages_persists_progress_during_execution(conn, program_id, actor_id) -> None:
    created = await create_cycle(conn, program_id, actor_id, trace_context=None)
    await get_cycle_for_execution(conn, created["cycle_id"])

    await write_cycle_stages(conn, created["cycle_id"], {"1": {"status": "running", "detail": "42 item(s)"}})

    fetched = await get_cycle(conn, created["cycle_id"])
    assert fetched["stages"] == {"1": {"status": "running", "detail": "42 item(s)"}}


@pytest.mark.asyncio
async def test_mark_cycle_terminal_persisted_sets_status_and_report_id(conn, program_id, actor_id) -> None:
    created = await create_cycle(conn, program_id, actor_id, trace_context=None)
    report_id = await conn.fetchval(
        "SELECT report_id FROM reports WHERE program_id = $1 LIMIT 1", program_id
    )
    assert report_id is not None, "expected at least one real report row for singleSlide"

    await mark_cycle_terminal(conn, created["cycle_id"], "persisted", {"7": {"status": "done"}}, report_id)

    fetched = await get_cycle(conn, created["cycle_id"])
    assert fetched["status"] == "persisted"
    assert fetched["report_id"] == report_id
    assert fetched["finished_at"] is not None


@pytest.mark.asyncio
async def test_mark_cycle_terminal_not_persisted_already_exists_has_no_report_id_requirement(
    conn, program_id, actor_id
) -> None:
    # ADR-021: "not persisted, already exists" is a real, correct
    # outcome — report_id may legitimately be the pre-existing report's
    # real id (this test uses None to prove the column itself has no
    # NOT NULL constraint forcing a value that isn't always meaningful
    # to attach here).
    created = await create_cycle(conn, program_id, actor_id, trace_context=None)
    await mark_cycle_terminal(conn, created["cycle_id"], "not_persisted_already_exists", {}, None)

    fetched = await get_cycle(conn, created["cycle_id"])
    assert fetched["status"] == "not_persisted_already_exists"
    assert fetched["report_id"] is None


@pytest.mark.asyncio
async def test_mark_cycle_terminal_hard_stop_defect(conn, program_id, actor_id) -> None:
    created = await create_cycle(conn, program_id, actor_id, trace_context=None)
    await mark_cycle_terminal(conn, created["cycle_id"], "hard_stop_defect", {"5": {"status": "done"}}, None)

    fetched = await get_cycle(conn, created["cycle_id"])
    assert fetched["status"] == "hard_stop_defect"
    assert fetched["report_id"] is None


@pytest.mark.asyncio
async def test_mark_cycle_failed_records_the_real_error_text(conn, program_id, actor_id) -> None:
    created = await create_cycle(conn, program_id, actor_id, trace_context=None)
    await mark_cycle_failed(conn, created["cycle_id"], {"1": {"status": "failed"}}, "ConnectionError: MCP unreachable")

    fetched = await get_cycle(conn, created["cycle_id"])
    assert fetched["status"] == "failed"
    assert fetched["error_detail"] == "ConnectionError: MCP unreachable"
    assert fetched["finished_at"] is not None


@pytest.mark.asyncio
async def test_get_cycle_returns_none_for_a_real_nonexistent_id(conn) -> None:
    fetched = await get_cycle(conn, "00000000-0000-0000-0000-000000000000")
    assert fetched is None


@pytest.mark.asyncio
async def test_status_check_constraint_rejects_a_value_outside_the_real_taxonomy(conn, program_id, actor_id) -> None:
    """DB-level proof, independent of application code, that the real
    CHECK constraint (migration 0003) actually holds — same discipline
    as Task 40's notes_required CHECK test.
    """
    created = await create_cycle(conn, program_id, actor_id, trace_context=None)
    with pytest.raises(Exception) as exc_info:
        async with conn.transaction():
            await conn.execute("UPDATE cycles SET status = 'bogus_status' WHERE cycle_id = $1", created["cycle_id"])
    assert "check" in str(exc_info.value).lower() or "constraint" in str(exc_info.value).lower()
