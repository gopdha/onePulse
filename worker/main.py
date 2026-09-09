"""OnePulse Worker — Migration Plan Phase 3 (ADR-021): executes
`run_pipeline_cycle()` out of the request path entirely.

Polls the real `cycles` status table in Postgres for queued work
(claimed via `FOR UPDATE SKIP LOCKED`, the standard Postgres job-queue
idiom — this project has exactly one worker process today, but the
claim is already correct if a second one is ever run, at zero extra
cost now), executes the real pipeline, and writes progress DURING
execution — not only at stage boundaries — by reusing the SAME
on_stage/on_detail hook the already-proven heartbeat mechanism (Task 39)
already relies on: that mechanism is completely unchanged in
`onepulse_common.pipeline`; it now also feeds a real Postgres row
(`onepulse_common.cycles.write_cycle_stages`) instead of only a log
file (the log file itself is unchanged too — still written here,
relocated from `Home.py`, still `logs/<project>_<timestamp>.log`,
nothing dropped, only relocated a second time).

No queue exists yet (ADR-019/Phase 4) — this is genuinely a local
process polling a table, the simplest real thing that gets execution
out of the request path per this phase's actual requirement. If this
worker is killed mid-run, the run is lost — there is no redelivery yet;
that is Phase 4's job, not this one's. Documented plainly, not hidden,
in CLAUDE.md Task 42.

Tracing: the core API's trigger endpoint captures the real W3C
traceparent for the request that created a cycle and stores it
(`cycles.trace_context`). This worker extracts it and creates its own
root span *inside* that extracted context — the same real mechanism
Phase 2 already proved across the BFF-to-core-API hop, now proved a
second time across a second process boundary, API-to-worker.

Run: python -m worker.main (from the repo root, alongside core_api and
bff — see the Runbook, main now needs 4 processes).
"""

from __future__ import annotations

import asyncio
import copy
import datetime as dt
import json
import logging
import os
import re
import time
from pathlib import Path

from azure.identity import DefaultAzureCredential
from arize.otel import set_routing_context
from dotenv import load_dotenv
from opentelemetry import trace
from opentelemetry.propagate import extract

from onepulse_common.config import PostgresSettings
from onepulse_common.cycle_progress import advance_stage, apply_detail, finalize_stage_state, mark_failed, new_stage_state
from onepulse_common.cycles import claim_next_queued_cycle, mark_cycle_failed, mark_cycle_terminal, terminal_status_from_result, write_cycle_stages
from onepulse_common.db import PostgresClient
from onepulse_common.observability import ARIZE_PROJECT_NAME, enable_observability
from onepulse_common.pipeline import TOTAL_STAGES, load_ado_pat, run_pipeline_cycle
from trace_debug import enable_debug_span_log

load_dotenv()

PG_SETTINGS = PostgresSettings(
    host="onepulse-pg-dev.postgres.database.azure.com",
    database="onepulse",
    role_name=os.environ.get("ONEPULSE_PG_ROLE", "app_role_local_dev"),
)
PROJECT_ENDPOINT = os.environ.get(
    "ONEPULSE_FOUNDRY_PROJECT_ENDPOINT",
    "https://onepulse-resource.services.ai.azure.com/api/projects/onepulse",
)
DEPLOYMENT_NAME = os.environ.get("ONEPULSE_FOUNDRY_DEPLOYMENT_NAME", "onePulse-gpt-5-mini")
ADO_ORG_NAME = os.environ.get("ONEPULSE_ADO_ORG", "gopdha")
OUTPUT_DIR = "output"
PPTX_MCP_SERVER_PATH = "scripts/pptx_mcp_server.py"
POLL_INTERVAL_SECONDS = 2.0

# Relocated from Home.py (Task 23) — the worker is now the only real
# caller of run_pipeline_cycle, so this mapping's only real home is
# here, not the UI.
STATUS_DECK_PATH_BY_PROJECT = {
    "singleSlide": "sample_status_deck.pptx",
    "Leave Tracker": "leave_tracker_status_deck.pptx",
}
DEFAULT_STATUS_DECK_PATH = os.environ.get("ONEPULSE_STATUS_DECK_PATH", "sample_status_deck.pptx")

_tracer = trace.get_tracer(__name__)


def _sanitize_for_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_") or "project"


def _log_exception_group(exc: BaseException, logger: logging.Logger, depth: int = 0) -> None:
    """Relocated unchanged from Home.py (Task 38) — the worker is now
    the only real caller that directly awaits run_pipeline_cycle, so
    it's the only place this real anyio-TaskGroup-flattening gotcha can
    still bite. See Task 38's own CLAUDE.md entry for the real bug this
    closes: a bare ExceptionGroup's own str() is uninformative
    ("unhandled errors in a TaskGroup (1 sub-exception)") — the real
    exception is one level down in `.exceptions`.
    """
    if isinstance(exc, BaseExceptionGroup):
        for sub in exc.exceptions:
            _log_exception_group(sub, logger, depth + 1)
    else:
        logger.error("  " * depth + "%s: %s", type(exc).__name__, exc, exc_info=exc)


async def _progress_writer(conn, cycle_id: str, queue: "asyncio.Queue[dict]") -> None:
    """One background task per real cycle execution, fed by on_stage/
    on_detail — coalesces to the latest queued snapshot (writing every
    single one of, say, 115 rapid-fire finding lines individually would
    be real, unnecessary DB pressure for a status table only ever meant
    to answer "what's the current state," not to be an event log; the
    full-fidelity event-by-event record is the log file, unchanged).
    """
    while True:
        snapshot = await queue.get()
        while not queue.empty():
            snapshot = queue.get_nowait()
        await write_cycle_stages(conn, cycle_id, snapshot)


async def _execute_cycle(pg_client: PostgresClient, cycle: dict, credential, arize_space_id: str) -> None:
    cycle_id = str(cycle["cycle_id"])
    program_name = cycle["program_name"]
    status_deck_path = STATUS_DECK_PATH_BY_PROJECT.get(program_name, DEFAULT_STATUS_DECK_PATH)

    logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"{_sanitize_for_filename(program_name)}_{dt.datetime.now():%Y%m%d_%H%M%S}.log"
    file_logger = logging.getLogger(f"onepulse.worker.{cycle_id}")
    file_logger.setLevel(logging.INFO)
    file_logger.propagate = False
    file_logger.handlers.clear()
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    file_logger.addHandler(file_handler)

    print(f"[worker] claimed cycle {cycle_id} — program={program_name!r}, log={log_path}")

    stages = new_stage_state(TOTAL_STAGES)
    shared: dict = {}
    queue: "asyncio.Queue[dict]" = asyncio.Queue()

    def on_stage(n: int, total: int, message: str) -> None:
        file_logger.info("[STAGE %d/%d] %s", n, total, message)
        advance_stage(stages, shared, n, total, message, now_ts=time.time())
        queue.put_nowait(copy.deepcopy(stages))

    def on_detail(message: str) -> None:
        file_logger.info("  %s", message)
        apply_detail(stages, shared, shared.get("current_stage", 0), message)
        queue.put_nowait(copy.deepcopy(stages))

    # Real API-to-worker tracing (Phase 3's own bar, same mechanism
    # Phase 2 proved across the BFF-to-core-API hop): extract the real
    # traceparent the core API captured at enqueue time and nest this
    # process's own root span inside it, so Arize shows one connected
    # trace, not two siblings. set_routing_context is the OUTER manager
    # — the same real, already-proven ordering fix (Task 30): Arize's
    # router reads it at span-*creation* time, not on_end().
    parent_ctx = extract({"traceparent": cycle["trace_context"]}) if cycle.get("trace_context") else None
    with set_routing_context(space_id=arize_space_id, project_name=ARIZE_PROJECT_NAME):
        with _tracer.start_as_current_span("worker run_pipeline_cycle", context=parent_ctx) as root_span:
            root_span.set_attribute("onepulse.ado_project", program_name)
            root_span.set_attribute("onepulse.cycle_id", cycle_id)

            async with pg_client.pool.acquire() as writer_conn:
                writer_task = asyncio.create_task(_progress_writer(writer_conn, cycle_id, queue))
                try:
                    ado_pat_b64 = load_ado_pat()
                    result = await run_pipeline_cycle(
                        ado_pat_b64=ado_pat_b64,
                        project_endpoint=PROJECT_ENDPOINT,
                        deployment_name=DEPLOYMENT_NAME,
                        credential=credential,
                        ado_org_name=ADO_ORG_NAME,
                        ado_project_name=program_name,
                        status_deck_path=status_deck_path,
                        pptx_mcp_server_path=PPTX_MCP_SERVER_PATH,
                        output_dir=OUTPUT_DIR,
                        on_stage=on_stage,
                        on_detail=on_detail,
                    )
                except Exception as e:  # noqa: BLE001 - real failure-state design, see module docstring;
                    # deliberately NOT BaseException — asyncio.CancelledError (a real graceful-shutdown
                    # signal, not a pipeline failure) must propagate, not be recorded as status='failed'.
                    file_logger.error("run failed: %s", e)
                    _log_exception_group(e, file_logger)
                    mark_failed(stages, shared, now_ts=time.time(), error_text=str(e))
                    async with pg_client.pool.acquire() as conn:
                        await mark_cycle_failed(conn, cycle_id, stages, str(e))
                    return
                finally:
                    writer_task.cancel()
                    try:
                        await writer_task
                    except asyncio.CancelledError:
                        pass

            root_span.set_attribute("onepulse.overall_status", result.overall_status)
            root_span.set_attribute("onepulse.revision_outcome", result.outcome)

            finalize_stage_state(stages, shared, now_ts=time.time(), total=TOTAL_STAGES, outcome=result.outcome)
            status = terminal_status_from_result(result)
            async with pg_client.pool.acquire() as conn:
                await mark_cycle_terminal(conn, cycle_id, status, stages, result.report_id)
            print(f"[worker] cycle {cycle_id} finished: status={status} report_id={result.report_id}")


async def main() -> None:
    credential = DefaultAzureCredential()
    arize_space_id = enable_observability(credential, PROJECT_ENDPOINT)
    enable_debug_span_log("worker")

    pg_client = await PostgresClient.connect(PG_SETTINGS, min_size=1, max_size=3)
    print("[worker] started, polling for queued cycles every "
          f"{POLL_INTERVAL_SECONDS}s (Ctrl+C to stop)")
    try:
        while True:
            async with pg_client.pool.acquire() as conn:
                cycle = await claim_next_queued_cycle(conn)
            if cycle is None:
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
                continue
            await _execute_cycle(pg_client, cycle, credential, arize_space_id)
    finally:
        await pg_client.close()
        trace.get_tracer_provider().force_flush(timeout_millis=30000)


if __name__ == "__main__":
    asyncio.run(main())
