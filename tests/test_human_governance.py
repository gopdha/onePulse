"""Phase 7 Human Governance API — real tests against the real
onepulse-pg-dev instance. No mocks: every test here writes a real row
and reads it back with a separate query on the same connection, and the
REVOKE test attempts a real UPDATE/DELETE over the real connection this
project uses everywhere else, to prove the database itself refuses it.

Prerequisite: `python scripts/seed_dev_data.py --target dev` must have
been run at least once, so the singleSlide program and the stand-in
reviewer actor (see seed_dev_data.py) already exist.

Real fix (2026-09-10): every test used to insert a real, committed
`reports` row with a deliberately random (non-Monday) `week_of`, purely
to dodge `UNIQUE(program_id, week_of)` across repeated runs — the header
here used to describe this as "accumulating a handful of clearly-marked
test rows... the accepted cost of testing this for real." That framing
undersold the real consequence: by 2026-09-10 it was 439 of 459 rows in
the live `reports` table (95%+), still growing with every test run,
`list_recent_reports` returning 20/20 fixture rows for singleSlide ahead
of any real pipeline output, and `ingest_reports_to_search.py` (no
filter at all) ready to index every one of them into the real RAG
corpus. Not a handful, and not anticipated when the cost was accepted.

Fixed by wrapping each test in one real transaction, rolled back in the
fixture's own teardown — the intent (test against the real database, not
a mock) is fully preserved: every real constraint, the real `REVOKE`,
and every real error still fire, on the real schema, over the real
connection this project authenticates with everywhere else. Nothing a
test writes is ever actually committed, so nothing is left behind for
list_recent_reports, ingest_reports_to_search, or a future
`UNIQUE`/CHECK collision to trip over. `approve_report`/`reject_report`'s
own internal `conn.transaction()` calls nest correctly as real
SAVEPOINTs under the fixture's outer transaction (asyncpg's standard
behavior for a transaction started while already inside one) — a
savepoint commit (release) or rollback never escapes to a real COMMIT,
which only the (never-called) outer commit could do.

One test (`test_approval_records_update_is_rejected_by_the_database`)
runs two statements that are *expected* to fail with a real database
error. Each is wrapped in its own `async with conn.transaction():` (a
real SAVEPOINT) so the expected, caught failure only rolls back to that
savepoint — not the whole outer test transaction, which would otherwise
be left aborted for every statement after it in the same test.

`_random_week_of()` no longer needs to be random: with nothing ever
committed, there is no cross-run collision to dodge, and migration 0002
added a real `reports.week_of` Monday-only CHECK (found necessary by the
same investigation that found this pollution) that a random date would
violate 6 days out of 7. Replaced with one fixed, real Monday.
"""

from __future__ import annotations

import itertools
import os
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

# Real, distinct Mondays, satisfying migration 0002's
# reports_week_of_is_monday CHECK. A single fixed date isn't enough — a
# test needing two real reports for the same program (e.g.
# test_list_pending_reviews_excludes_reviewed_reports) would collide on
# UNIQUE(program_id, week_of) — so this hands out a fresh, monotonically
# increasing real Monday on every call instead. Deterministic, not
# random: nothing ever persists (see module docstring), so there is no
# cross-run collision to dodge, only a real within-test one to avoid.
_week_of_counter = itertools.count()


def _next_test_week_of() -> date:
    return date(2000, 1, 3) + timedelta(weeks=next(_week_of_counter))


@pytest_asyncio.fixture
async def conn():
    """One real connection, wrapped in one real transaction that is
    always rolled back on teardown — see module docstring for why, and
    for how approve_report/reject_report's own internal transactions
    nest correctly underneath it as real SAVEPOINTs.
    """
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


@pytest_asyncio.fixture
async def tenant_id(conn, program_id) -> str:
    """Migration Plan Phase 8: the real tenant `program_id` belongs to —
    every `human_governance` function under test now needs this for its
    own `SET LOCAL`-equivalent `app.current_tenant_id`, so RLS actually
    lets these real test writes/reads through rather than falling back
    to the (also real, but less interesting) unset-permissive case.
    """
    value = await conn.fetchval(
        "SELECT pf.tenant_id FROM portfolios pf JOIN programs p ON p.portfolio_id = pf.portfolio_id "
        "WHERE p.program_id = $1",
        program_id,
    )
    assert value is not None
    return str(value)


async def _insert_test_report(conn, program_id: str) -> int:
    return await conn.fetchval(
        """
        INSERT INTO reports (program_id, week_of, rag_status, quality_gate_outcome, executive_summary, trend_line)
        VALUES ($1, $2, 'Amber', 'route_to_human_review', $3, '')
        RETURNING report_id
        """,
        program_id,
        _next_test_week_of(),
        TEST_MARKER,
    )


async def test_approve_report_end_to_end(conn, program_id, actor_id, tenant_id) -> None:
    report_id = await _insert_test_report(conn, program_id)

    result = await approve_report(conn, report_id, actor_id, tenant_id, notes="looks good")

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


async def test_reject_report_end_to_end(conn, program_id, actor_id, tenant_id) -> None:
    report_id = await _insert_test_report(conn, program_id)

    result = await reject_report(conn, report_id, actor_id, tenant_id, notes="evidence for item 8 is stale")

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


async def test_reject_report_requires_notes(conn, program_id, actor_id, tenant_id) -> None:
    report_id = await _insert_test_report(conn, program_id)

    with pytest.raises(NotesRequiredError):
        await reject_report(conn, report_id, actor_id, tenant_id, notes="")

    # Confirm the real row-level consequence, not just the exception type:
    # no approval_records row was written, and the report is still unreviewed.
    count = await conn.fetchval(
        "SELECT count(*) FROM approval_records WHERE report_id = $1", report_id
    )
    assert count == 0
    reviewed = await conn.fetchval("SELECT reviewed FROM reports WHERE report_id = $1", report_id)
    assert reviewed is False


async def test_reject_report_with_empty_notes_is_also_refused_by_the_database(
    conn, program_id, actor_id
) -> None:
    """Migration 0002's real CHECK constraint
    (approval_records_rejected_notes_required) — proves empty-notes
    rejection is refused at the database level too, independent of
    reject_report's own application-level NotesRequiredError check
    above. Goes around that function deliberately, via a direct INSERT,
    so this cannot pass merely because the Python-level guard happened
    to run first.
    """
    report_id = await _insert_test_report(conn, program_id)

    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO approval_records (report_id, decision, actor_id, notes) "
                "VALUES ($1, 'rejected', $2, '')",
                report_id,
                actor_id,
            )

    count = await conn.fetchval(
        "SELECT count(*) FROM approval_records WHERE report_id = $1", report_id
    )
    assert count == 0


async def test_approve_report_requires_actor_id(conn, program_id, tenant_id) -> None:
    report_id = await _insert_test_report(conn, program_id)

    with pytest.raises(ActorIdRequiredError):
        await approve_report(conn, report_id, actor_id="", tenant_id=tenant_id)

    count = await conn.fetchval(
        "SELECT count(*) FROM approval_records WHERE report_id = $1", report_id
    )
    assert count == 0


async def test_list_pending_reviews_excludes_reviewed_reports(conn, program_id, actor_id, tenant_id) -> None:
    pending_report_id = await _insert_test_report(conn, program_id)
    reviewed_report_id = await _insert_test_report(conn, program_id)
    await approve_report(conn, reviewed_report_id, actor_id, tenant_id)

    result = await list_pending_reviews(conn, program_id, tenant_id)
    ids = {r["reportId"] for r in result["reports"]}

    assert pending_report_id in ids
    assert reviewed_report_id not in ids

    pending_entry = next(r for r in result["reports"] if r["reportId"] == pending_report_id)
    assert pending_entry["qualityGateOutcome"] == "route_to_human_review"


async def test_approval_records_update_is_rejected_by_the_database(conn, program_id, actor_id, tenant_id) -> None:
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

    Each expected-failure statement below is wrapped in its own
    `async with conn.transaction():` (a real SAVEPOINT, since the `conn`
    fixture already has an outer transaction open) — otherwise the first
    caught failure would leave the whole outer test transaction aborted,
    and every statement after it (including the second expected failure
    and the final confirming SELECT) would fail with
    `InFailedSQLTransactionError` instead of actually exercising anything.
    """
    report_id = await _insert_test_report(conn, program_id)
    await approve_report(conn, report_id, actor_id, tenant_id)

    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
        async with conn.transaction():
            await conn.execute(
                "UPDATE approval_records SET notes = 'tampered' WHERE report_id = $1", report_id
            )

    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
        async with conn.transaction():
            await conn.execute("DELETE FROM approval_records WHERE report_id = $1", report_id)

    # Confirm the row is genuinely untouched, not just that an exception
    # was raised for some unrelated reason.
    row = await conn.fetchrow(
        "SELECT decision, notes FROM approval_records WHERE report_id = $1", report_id
    )
    assert row["decision"] == "approved"
    assert row["notes"] == ""


@pytest_asyncio.fixture
async def admin_conn():
    """A real connection authenticated as this server's own real Entra
    Administrator role (Migration Plan Phase 8 follow-up, ADR-028) — the
    exact identity `test_approval_records_update_is_rejected_by_the_
    database` above never covered, since it (correctly) tests what the
    *application* can do via `app_role_local_dev`. `azure_pg_admin`'s own
    real membership in PostgreSQL's built-in `pg_write_all_data` role
    means this identity genuinely holds real UPDATE/DELETE on
    `approval_records` at the ACL/predefined-role level — a REVOKE cannot
    reach it (confirmed live, ADR-028). What this test proves is that the
    real trigger (migration 0011) enforces the guarantee anyway. Same
    real-transaction-rolled-back discipline as the `conn` fixture above.
    """
    settings = PostgresSettings(
        host="onepulse-pg-dev.postgres.database.azure.com",
        database="onepulse",
        role_name="gopi@gopdhagmail.onmicrosoft.com",
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


async def test_approval_records_append_only_holds_against_the_real_admin_identity(admin_conn) -> None:
    """The real, adversarial proof ADR-028 exists to record: the
    identity Task 31's own tests never covered. `azure_pg_admin` (this
    connection's real role) genuinely has UPDATE/DELETE privilege on
    `approval_records` — `has_table_privilege` confirms it, and no
    `REVOKE` can remove it (it arrives via `pg_write_all_data`
    membership, not any ACL entry). The real trigger
    (`approval_records_append_only`, migration 0011) is what actually
    stops it — fires regardless of which privilege path let the
    statement reach the table at all.
    """
    real_row = await admin_conn.fetchrow(
        "SELECT approval_id, decision, notes FROM approval_records LIMIT 1"
    )
    assert real_row is not None, "expects at least one real approval_records row to exist"
    approval_id = real_row["approval_id"]

    with pytest.raises(asyncpg.exceptions.RaiseError, match="approval_records is append-only"):
        async with admin_conn.transaction():
            await admin_conn.execute(
                "UPDATE approval_records SET notes = 'tampered-by-admin-test' WHERE approval_id = $1",
                approval_id,
            )

    with pytest.raises(asyncpg.exceptions.RaiseError, match="approval_records is append-only"):
        async with admin_conn.transaction():
            await admin_conn.execute("DELETE FROM approval_records WHERE approval_id = $1", approval_id)

    # Confirm the real row is genuinely untouched — not just that some
    # exception fired for an unrelated reason.
    after = await admin_conn.fetchrow(
        "SELECT decision, notes FROM approval_records WHERE approval_id = $1", approval_id
    )
    assert after["decision"] == real_row["decision"]
    assert after["notes"] == real_row["notes"]
