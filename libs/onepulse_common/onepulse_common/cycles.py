"""Real Phase 3 status table (ADR-021) — DB-facing functions over the
`cycles` table (see `scripts/migrations/0003_add_cycles_table.sql`).
Pure curation logic lives in `onepulse_common.cycle_progress`; this
module is the actual Postgres I/O, same split as
`onepulse_common.human_governance` (I/O) vs. `onepulse_common.
quality_gate` (pure) elsewhere in this project.

The real job this closes: pipeline execution moves out of the request
path into a service (Reporting) reached over a real queue, not a
request. `create_cycle` is what the core API's trigger endpoint calls
to enqueue real work and return `202` immediately without executing
anything; `get_cycle_for_execution` is what Reporting calls when a real
`report-cycles` queue message is delivered (ADR-026, Phase 7 follow-up
— the outer trigger's own DB-polling claim,
`claim_next_queued_cycle`/`FOR UPDATE SKIP LOCKED`, is retired: the
queue's own visibility-timeout lease is now the real concurrency
control, the same role it already plays for Investigation since Phase
4); `write_cycle_stages`/`mark_cycle_terminal`/`mark_cycle_failed` are
what Reporting calls to persist real progress DURING execution and the
real terminal outcome; `get_cycle` is what the core API's polling
endpoint calls to answer a client's status question from the database,
not from whatever process happens to be running the work.
"""

from __future__ import annotations

import json

import asyncpg

from onepulse_common.pipeline import PipelineResult


def terminal_status_from_result(result: PipelineResult) -> str:
    """Maps `run_pipeline_cycle`'s real `PipelineResult` onto ADR-021's
    four real terminal outcomes — derived directly from the same two
    fields `Home.py` used to inspect for its own UI text (`outcome`,
    `persisted`), not a new classification invented for this table.
    """
    if result.outcome == "hard_stop_defect":
        return "hard_stop_defect"
    if not result.persisted:
        return "not_persisted_already_exists"
    if result.outcome == "route_to_human_review":
        return "persisted_route_to_human_review"
    return "persisted"


async def create_cycle(
    conn: asyncpg.Connection, program_id: str, requested_by_actor_id: str, trace_context: str | None
) -> dict:
    """LLD 2.1's real trigger contract: inserts a real `queued` row and
    returns immediately — this function itself never executes the
    pipeline; that's the worker's job, entirely out of the request path.
    """
    row = await conn.fetchrow(
        """
        INSERT INTO cycles (program_id, requested_by_actor_id, trace_context)
        VALUES ($1, $2, $3)
        RETURNING cycle_id, status
        """,
        program_id,
        requested_by_actor_id,
        trace_context,
    )
    return {"cycle_id": row["cycle_id"], "status": row["status"]}


async def get_cycle_for_execution(conn: asyncpg.Connection, cycle_id: str) -> dict | None:
    """Real read-and-mark-running for the queue-driven Reporting
    consumer (ADR-026, Phase 7 follow-up) — called every time a real
    `report-cycles` message is delivered, including redeliveries.
    Unlike the retired `claim_next_queued_cycle`, concurrency is no
    longer a SQL row lock (`FOR UPDATE SKIP LOCKED`): the queue's own
    visibility-timeout lease is what guarantees only one consumer holds
    a given message at a time, the same real mechanism already proven
    for Investigation since Phase 4. This function therefore marks the
    row 'running' unconditionally on every delivery — idempotent, not
    exclusive — so `cycles` stays an accurate live status mirror
    regardless of how many times the same cycle_id is redelivered.
    `started_at` uses `COALESCE` so a redelivery does not reset the
    real original start time.

    `requested_by_actor_id` is returned too (Migration Plan Phase 4):
    the Reporting service carries it into the real
    `investigation-requests` message envelope.
    """
    row = await conn.fetchrow(
        """
        UPDATE cycles c
        SET status = 'running', started_at = COALESCE(c.started_at, now()), updated_at = now()
        FROM programs p
        WHERE c.cycle_id = $1 AND p.program_id = c.program_id
        RETURNING c.cycle_id, c.program_id, p.name AS program_name, c.trace_context,
                  c.requested_by_actor_id
        """,
        cycle_id,
    )
    if row is None:
        return None
    return dict(row)


async def write_cycle_stages(conn: asyncpg.Connection, cycle_id: str, stages: dict) -> None:
    """Real progress write, called from the worker's on_stage/on_detail
    hook — the same hook the already-proven heartbeat mechanism (Task
    39) already fires every ~10s during the longest real stage, so this
    reuses that existing cadence rather than inventing a second one.
    JSONB keys are always strings on the wire regardless of the Python
    dict's int keys, and are read back as strings by `get_cycle`/the
    core API — both `str(int)` round-trip cleanly through `json.loads`.
    """
    await conn.execute(
        "UPDATE cycles SET stages = $1::jsonb, updated_at = now() WHERE cycle_id = $2",
        json.dumps(stages),
        cycle_id,
    )


async def mark_cycle_terminal(
    conn: asyncpg.Connection, cycle_id: str, status: str, stages: dict, report_id: int | None
) -> None:
    await conn.execute(
        """
        UPDATE cycles
        SET status = $1, stages = $2::jsonb, report_id = $3, finished_at = now(), updated_at = now()
        WHERE cycle_id = $4
        """,
        status,
        json.dumps(stages),
        report_id,
        cycle_id,
    )


async def mark_cycle_failed(conn: asyncpg.Connection, cycle_id: str, stages: dict, error_text: str) -> None:
    """A real, unexpected worker-side exception — distinct from
    `hard_stop_defect` (a real, expected quality-gate outcome that
    `mark_cycle_terminal` handles like every other real result).
    """
    await conn.execute(
        """
        UPDATE cycles
        SET status = 'failed', stages = $1::jsonb, error_detail = $2, finished_at = now(), updated_at = now()
        WHERE cycle_id = $3
        """,
        json.dumps(stages),
        error_text,
        cycle_id,
    )


async def get_cycle(conn: asyncpg.Connection, cycle_id: str) -> dict | None:
    """Real polling read — GET /api/v1/cycles/{cycleId}'s own backing
    query. Answers from the database alone; does not touch whatever
    process (if any) is currently executing the work.
    """
    row = await conn.fetchrow(
        """
        SELECT cycle_id, program_id, status, stages, report_id, error_detail,
               created_at, started_at, finished_at
        FROM cycles WHERE cycle_id = $1
        """,
        cycle_id,
    )
    if row is None:
        return None
    result = dict(row)
    # asyncpg returns JSONB as a raw JSON string, not an auto-parsed
    # dict, since this project's PostgresClient sets up no type codec
    # (checked directly, not assumed) — parse it here so every real
    # caller (the core API's polling endpoint) gets a real Python dict.
    result["stages"] = json.loads(result["stages"]) if result["stages"] else {}
    return result
