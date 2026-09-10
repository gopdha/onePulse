"""Investigation service's own Postgres access — deliberately NOT in
`onepulse_common`, so the schema-access boundary (ADR-020) holds at the
Python import-graph level too, mirroring the BFF-no-data-access
precedent (Phase 2). Only this module, and the Investigation service
that imports it, ever connects with a role holding grants on the
`investigation` schema (`investigation_role`/`investigation_role_local_dev`
— see `scripts/investigation_migrations/0001_initial_schema.sql`). The
Reporting service never imports this module and never connects with
that role; it fetches results over the real HTTP route in
`investigation/main.py` instead (Migration Plan Phase 4's own rule).

`upsert_investigation_run` is keyed on `cycle_id` (the real Postgres
primary key on `investigation.investigation_runs`) rather than doing a
plain INSERT — a deliberate design for at-least-once queue delivery: if
`investigation-requests` redelivers the same cycle (a genuine, expected
outcome under Azure Storage Queues' delivery guarantee, e.g. after a
visibility-timeout expiry from a dead consumer), re-running
`investigate()` and calling this function again OVERWRITES the prior
row for that cycle rather than accumulating a second one.
"""

from __future__ import annotations

import json

import asyncpg


async def upsert_investigation_run(
    conn: asyncpg.Connection,
    *,
    cycle_id: str,
    program_name: str,
    requested_by_actor_id: str | None,
    status: str,
    queried_item_count: int | None = None,
    findings: list[dict] | None = None,
    tower_hierarchy: dict | None = None,
    error_detail: str | None = None,
    trace_context: str | None = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO investigation.investigation_runs
            (cycle_id, program_name, requested_by_actor_id, status,
             queried_item_count, findings, tower_hierarchy, error_detail,
             trace_context, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, $9, now())
        ON CONFLICT (cycle_id) DO UPDATE SET
            program_name = EXCLUDED.program_name,
            requested_by_actor_id = EXCLUDED.requested_by_actor_id,
            status = EXCLUDED.status,
            queried_item_count = EXCLUDED.queried_item_count,
            findings = EXCLUDED.findings,
            tower_hierarchy = EXCLUDED.tower_hierarchy,
            error_detail = EXCLUDED.error_detail,
            trace_context = EXCLUDED.trace_context,
            updated_at = now()
        """,
        cycle_id,
        program_name,
        requested_by_actor_id,
        status,
        queried_item_count,
        json.dumps(findings) if findings is not None else None,
        json.dumps(tower_hierarchy) if tower_hierarchy is not None else None,
        error_detail,
        trace_context,
    )


async def get_investigation_run(conn: asyncpg.Connection, cycle_id: str) -> dict | None:
    """Real backing query for `GET /internal/investigations/{cycle_id}`
    — the one and only way the Reporting service ever learns Investigation
    results, per the Migration Plan's structural rule (never a direct
    connection to this schema).
    """
    row = await conn.fetchrow(
        """
        SELECT cycle_id, program_name, requested_by_actor_id, status,
               queried_item_count, findings, tower_hierarchy, error_detail,
               trace_context, created_at, updated_at
        FROM investigation.investigation_runs WHERE cycle_id = $1
        """,
        cycle_id,
    )
    if row is None:
        return None
    result = dict(row)
    result["findings"] = json.loads(result["findings"]) if result["findings"] else None
    result["tower_hierarchy"] = json.loads(result["tower_hierarchy"]) if result["tower_hierarchy"] else None
    return result
