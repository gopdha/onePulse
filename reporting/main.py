"""OnePulse Reporting service — Migration Plan Phase 4 (ADR-019, ADR-020).

Renamed from `worker/` (Phase 3): still polls the real `cycles` status
table for queued work via `FOR UPDATE SKIP LOCKED` — that claim
mechanism is UNCHANGED, per the Migration Plan's own instruction ("that
isn't broken, it's being replaced by something that also survives a
dead consumer" — referring to the *Investigation* dispatch mechanism,
not this one). What changes here: Investigation is no longer an
in-process function call. This service now round-trips it over two real
named Azure Storage Queues:
  1. sends a real `investigation-requests` message (cycle_id,
     program_name, requested_by_actor_id, a fresh injected
     `traceparent`) instead of calling `investigate()` directly;
  2. polls `findings-ready` for the matching `cycle_id`;
  3. fetches the real findings/queried_item_count/tower_hierarchy over
     a real HTTP call to the Investigation service's own
     `GET /internal/investigations/{cycle_id}` route — NEVER by
     connecting to the `investigation` schema directly (there is no
     grant that would even allow it — see
     `tests/test_investigation_schema_isolation.py`);
  4. then calls `run_reporting_stages()` (stages 2-7, unchanged) with
     the fetched results.

Honest, disclosed consequence of the split: the granular per-tool-call
`on_detail` progress that used to stream live out of `investigate()`
itself (Task 39's heartbeat, real tool-call lines) now happens inside
the Investigation service's own process/log, not visible to this one.
While waiting for `findings-ready`, this service ticks its own
heartbeat (`onepulse_common.heartbeat.heartbeat`) with real elapsed-time
detail, so the `cycles` status table and log file still show real,
frequent progress (same Task 39 "no gap over 20s" bar) — just "still
waiting on Investigation (Ns elapsed)" rather than the real tool-call
text Investigation itself is logging.

QUEUE SEMANTICS: `findings-ready` messages not matching the cycle this
process is currently awaiting are left undeleted (there is only one
Reporting process today; a mismatched message becomes visible again
after its own timeout and is reconsidered on a later poll — a real,
deliberately defensive design for whenever a second Reporting instance
runs, not a case exercised today). A real, generous overall wait
(`FINDINGS_READY_TIMEOUT_SECONDS`) bounds how long this service waits
before honestly failing the cycle — covering Investigation's own
dead-letter threshold (`MAX_DEQUEUE_COUNT` redeliveries x
`VISIBILITY_TIMEOUT_SECONDS` each) plus real processing time, so a
message that is never going to be answered (e.g. genuinely
dead-lettered) doesn't hang this process forever.

Run: python -m reporting.main (alongside core_api, bff, investigation —
see the Runbook, main now needs 5 processes).
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import os
import sys
import time
from pathlib import Path

import httpx
from arize.otel import set_routing_context
from azure.identity import DefaultAzureCredential
from azure.identity.aio import DefaultAzureCredential as AsyncDefaultAzureCredential
from dotenv import load_dotenv
from opentelemetry import trace
from opentelemetry.propagate import extract, inject

from onepulse_common.config import PostgresSettings
from onepulse_common.cycle_progress import advance_stage, apply_detail, finalize_stage_state, mark_failed, new_stage_state
from onepulse_common.cycles import claim_next_queued_cycle, mark_cycle_failed, mark_cycle_terminal, terminal_status_from_result, write_cycle_stages
from onepulse_common.db import PostgresClient
from onepulse_common.heartbeat import heartbeat
from onepulse_common.observability import ARIZE_PROJECT_NAME, enable_observability
from onepulse_common.pipeline import TOTAL_STAGES, run_reporting_stages
from onepulse_common.queues import (
    FINDINGS_READY_POISON_QUEUE,
    FINDINGS_READY_QUEUE,
    INVESTIGATION_REQUESTS_QUEUE,
    MAX_DEQUEUE_COUNT,
    deadletter,
    get_queue_client,
    is_poison,
    parse_message,
    send_json_message,
)
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
INVESTIGATION_BASE_URL = os.environ.get("ONEPULSE_INVESTIGATION_BASE_URL", "http://localhost:8200")
OUTPUT_DIR = "output"
PPTX_MCP_SERVER_PATH = "scripts/pptx_mcp_server.py"
POLL_INTERVAL_SECONDS = 2.0

# Real, deliberate value: MAX_DEQUEUE_COUNT (5) redeliveries x
# Investigation's own VISIBILITY_TIMEOUT_SECONDS (90) is 450s worst-case
# before a message is even dead-lettered; add real processing time and
# margin. Not indefinite — a message that is never going to be answered
# must still fail this cycle honestly rather than hang forever.
FINDINGS_READY_TIMEOUT_SECONDS = 1200
FINDINGS_READY_POLL_VISIBILITY_SECONDS = 60

STATUS_DECK_PATH_BY_PROJECT = {
    "singleSlide": "sample_status_deck.pptx",
    "Leave Tracker": "leave_tracker_status_deck.pptx",
    # Real, pre-existing gap found incidentally while auditing this
    # service's file dependencies for containerization (Migration Plan
    # Phase 5) — Agentic AI Observability Platform has had its own real
    # status deck (aiobs_status_deck.pptx, Task 27) sitting at the repo
    # root this whole time, never actually wired in here. Every real AOP
    # run before this fix silently fell through to
    # DEFAULT_STATUS_DECK_PATH (singleSlide's own deck) for Status Update
    # Analysis instead — a real correctness gap, unrelated to
    # containerization itself, fixed because it would otherwise make this
    # phase's own full-scope verification silently test the wrong file.
    "Agentic AI Observability Platform": "aiobs_status_deck.pptx",
}
DEFAULT_STATUS_DECK_PATH = os.environ.get("ONEPULSE_STATUS_DECK_PATH", "sample_status_deck.pptx")

# Task 44 follow-up (2026-09-10): the mapping above was never the only
# thing that could go wrong. `sample_status_deck.pptx` — singleSlide's
# own mapped file — was found to be silently holding a different
# project's real content (most likely a stale artifact from real AOP
# deck-preparation work, per docs/build-journey/03_Build_Timeline.md's
# Phase 15, that saved to the wrong filename) for days, with nothing
# ever checking that the bytes on disk still matched what the mapping
# above intended. A dict entry pointing at the right PATH says nothing
# about whether that path's CONTENT is still what it was when the
# mapping was written. This is a real, deterministic content-hash pin,
# not a text-search heuristic — deliberately NOT "does the deck mention
# its own project name," since singleSlide's own real, original,
# correct deck (scripts/create_sample_status_deck.py) never has and
# still doesn't. Recompute and update the expected hash here ONLY as a
# deliberate act (a real new deck was authored and reviewed), never as
# a way to make a failing check pass.
STATUS_DECK_SHA256_BY_PROJECT = {
    "singleSlide": "b7384f261f4762927f96a9feee3b0063e6137d221555782145c05d3a6416bf10",
    "Leave Tracker": "54edbb7c3898fb7fc72597a567d545723652a6f53c319cb0207b07172d95755f",
    "Agentic AI Observability Platform": "c21ff3ee35ed2bf411ca55be575ba744473773528e2c560ca225a63b6a70d68c",
}


class StatusDeckIntegrityError(RuntimeError):
    """Raised when the deck a run is about to read doesn't correspond to
    the project it's supposedly for — either no known-good hash is
    registered at all, or the file's real bytes have drifted since one
    was. The failure mode this exists to eliminate: wrong input, no
    error, believable output (Task 44's original finding)."""


def _verify_status_deck_integrity(program_name: str, deck_path: str) -> None:
    expected = STATUS_DECK_SHA256_BY_PROJECT.get(program_name)
    if expected is None:
        raise StatusDeckIntegrityError(
            f"No known-good status deck hash registered for {program_name!r} — "
            f"refusing to read {deck_path!r} unverified. Register its real sha256 "
            f"in STATUS_DECK_SHA256_BY_PROJECT once its content has been reviewed "
            f"and confirmed correct for this project."
        )
    actual = hashlib.sha256(Path(deck_path).read_bytes()).hexdigest()
    if actual != expected:
        raise StatusDeckIntegrityError(
            f"Status deck integrity check failed for {program_name!r}: {deck_path!r} "
            f"does not match its registered content (expected sha256 {expected}, got "
            f"{actual}). Its bytes have changed since this mapping was established — "
            f"do not trust its content until you've confirmed why and, if the new "
            f"content is deliberate and correct, re-registered the new hash."
        )


_tracer = trace.get_tracer(__name__)


def _log_exception_group(exc: BaseException, logger: logging.Logger, depth: int = 0) -> None:
    if isinstance(exc, BaseExceptionGroup):
        for sub in exc.exceptions:
            _log_exception_group(sub, logger, depth + 1)
    else:
        logger.error("  " * depth + "%s: %s", type(exc).__name__, exc, exc_info=exc)


async def _progress_writer(conn, cycle_id: str, queue: "asyncio.Queue[dict]") -> None:
    while True:
        snapshot = await queue.get()
        while not queue.empty():
            snapshot = queue.get_nowait()
        await write_cycle_stages(conn, cycle_id, snapshot)


class InvestigationFailedError(RuntimeError):
    """Raised when the Investigation service itself recorded a real
    failure for this cycle (`investigation.investigation_runs.status ==
    'failed'`) — a distinct, honest failure mode from a real timeout
    (Investigation never responded at all).
    """


async def _dispatch_investigation_request(
    queue_client, cycle_id: str, program_name: str, requested_by_actor_id: str
) -> None:
    """Sends the real investigation-requests message. The traceparent
    injected here rides the queue hop — Investigation extracts it and
    nests its own root span underneath the currently-active span (this
    function must be called from inside that span's `with` block).
    """
    outbound_headers: dict[str, str] = {}
    inject(outbound_headers)
    await send_json_message(
        queue_client,
        {
            "cycle_id": cycle_id,
            "program_name": program_name,
            "requested_by_actor_id": requested_by_actor_id,
            "trace_context": outbound_headers.get("traceparent"),
        },
    )


async def _await_findings(
    findings_queue_client, poison_queue_client, cycle_id: str, on_detail
) -> None:
    """Polls findings-ready for the message matching cycle_id, deleting
    it once found. Real, deliberate design for at-least-once delivery:
    a message for a DIFFERENT cycle is left undeleted (becomes visible
    again after its own visibility timeout) rather than discarded.
    """
    deadline = time.monotonic() + FINDINGS_READY_TIMEOUT_SECONDS
    async with heartbeat(on_detail, "Investigation round trip"):
        while time.monotonic() < deadline:
            async for message in findings_queue_client.receive_messages(
                messages_per_page=5, visibility_timeout=FINDINGS_READY_POLL_VISIBILITY_SECONDS
            ):
                if await is_poison(message):
                    await deadletter(
                        findings_queue_client, poison_queue_client, message,
                        reason=f"exceeded max dequeue count ({message.dequeue_count})",
                    )
                    continue
                envelope = parse_message(message)
                if envelope.get("cycle_id") == cycle_id:
                    await findings_queue_client.delete_message(message)
                    return
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
    raise TimeoutError(
        f"Investigation did not respond for cycle {cycle_id} within {FINDINGS_READY_TIMEOUT_SECONDS}s "
        f"(no matching findings-ready message received — possibly dead-lettered after "
        f"{MAX_DEQUEUE_COUNT} redeliveries, or the Investigation service is down)."
    )


async def _fetch_investigation_result(http_client: httpx.AsyncClient, cycle_id: str) -> dict:
    """The one and only real path Reporting ever uses to obtain
    Investigation's findings — a real HTTP GET, never a direct query
    against the `investigation` schema (there is no grant that would
    even allow one — see `tests/test_investigation_schema_isolation.py`).
    """
    response = await http_client.get(f"/internal/investigations/{cycle_id}")
    response.raise_for_status()
    run = response.json()
    if run["status"] == "failed":
        raise InvestigationFailedError(run.get("error_detail") or "Investigation reported a failure with no detail.")
    return run


async def _execute_cycle(
    pg_client: PostgresClient,
    cycle: dict,
    credential: DefaultAzureCredential,
    arize_space_id: str,
    investigation_requests_client,
    findings_ready_client,
    findings_ready_poison_client,
    http_client: httpx.AsyncClient,
) -> None:
    cycle_id = str(cycle["cycle_id"])
    program_name = cycle["program_name"]
    requested_by_actor_id = str(cycle["requested_by_actor_id"])
    status_deck_path = STATUS_DECK_PATH_BY_PROJECT.get(program_name, DEFAULT_STATUS_DECK_PATH)

    # Migration Plan Phase 5: logs move to stdout, not a per-cycle file.
    # Container filesystems are ephemeral — Trade-off #12 made
    # logs/<project>_<timestamp>.log the ONLY route to real per-tool-call
    # detail, so that detail would otherwise simply vanish on a container
    # restart. stdout is what `docker logs` collects today and what
    # Application Insights will pick up in Phase 7 — same real content
    # (every tool call, the full draft/revision text, every PASS/FAIL
    # check), only the destination changes. The logger name still
    # carries the real cycle_id so multiple cycles' output stays
    # attributable in one shared stream, even though this project's
    # single-consumer design means only one cycle is ever actually
    # in flight at a time.
    file_logger = logging.getLogger(f"onepulse.reporting.{cycle_id}")
    file_logger.setLevel(logging.INFO)
    file_logger.propagate = False
    file_logger.handlers.clear()
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(message)s"))
    file_logger.addHandler(stream_handler)

    print(f"[reporting] claimed cycle {cycle_id} — program={program_name!r}, log=stdout")

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

    parent_ctx = extract({"traceparent": cycle["trace_context"]}) if cycle.get("trace_context") else None
    with set_routing_context(space_id=arize_space_id, project_name=ARIZE_PROJECT_NAME):
        with _tracer.start_as_current_span("reporting run_cycle", context=parent_ctx) as root_span:
            root_span.set_attribute("onepulse.ado_project", program_name)
            root_span.set_attribute("onepulse.cycle_id", cycle_id)

            async with pg_client.pool.acquire() as writer_conn:
                writer_task = asyncio.create_task(_progress_writer(writer_conn, cycle_id, queue))
                try:
                    # Checked before dispatching to Investigation at all —
                    # fail fast and cheap rather than spend a real
                    # Investigation run (Foundry cost, ADO calls) only to
                    # find at Stage 2 that the deck it's about to read
                    # doesn't correspond to this project (Task 44 follow-up).
                    _verify_status_deck_integrity(program_name, status_deck_path)
                    on_stage(1, TOTAL_STAGES, f"Investigation — dispatched to Investigation service for '{program_name}'")
                    await _dispatch_investigation_request(
                        investigation_requests_client, cycle_id, program_name, requested_by_actor_id
                    )
                    await _await_findings(findings_ready_client, findings_ready_poison_client, cycle_id, on_detail)
                    investigation_run = await _fetch_investigation_result(http_client, cycle_id)
                    findings = investigation_run["findings"] or []
                    queried_item_count = investigation_run["queried_item_count"] or 0
                    tower_hierarchy = investigation_run["tower_hierarchy"] or {"features": {}, "children": {}, "epics": {}}

                    # Real, deliberate reconstruction, not an estimate: the
                    # per-tool-call on_detail text `_query_committed_scope`
                    # emits inside `investigate()` (the exact message
                    # `onepulse_common.cycle_progress.apply_detail` parses
                    # for stage 1's "N item(s) across M committed
                    # feature(s)" summary) is generated INSIDE the
                    # Investigation service now — it never reaches this
                    # process live. `tower_hierarchy["features"]` has
                    # exactly one real entry per real Committed Feature
                    # (computed deterministically by `_query_tower_hierarchy`,
                    # Task 36), so its length is the real feature count,
                    # not a guess — reproducing the identical message text
                    # here keeps the existing curation logic working
                    # unchanged, off real data fetched over HTTP.
                    if queried_item_count == 0:
                        on_detail(f"No Features tagged 'Committed' found for '{program_name}' — nothing to investigate.")
                    else:
                        feature_count = len(tower_hierarchy.get("features", {}))
                        on_detail(
                            f"· real tool call (deterministic scoping): wit_query(real children of "
                            f"{feature_count} Committed Feature(s) via System.Parent)"
                        )
                    for f in findings:
                        on_detail(f"#{f['work_item_id']} {f['title']} — {f['status']}")

                    result = await run_reporting_stages(
                        findings=findings,
                        queried_item_count=queried_item_count,
                        tower_hierarchy=tower_hierarchy,
                        project_endpoint=PROJECT_ENDPOINT,
                        deployment_name=DEPLOYMENT_NAME,
                        credential=credential,
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
            print(f"[reporting] cycle {cycle_id} finished: status={status} report_id={result.report_id}")


async def main() -> None:
    credential = DefaultAzureCredential()
    async_credential = AsyncDefaultAzureCredential()
    arize_space_id = enable_observability(credential, PROJECT_ENDPOINT)
    enable_debug_span_log("reporting")

    pg_client = await PostgresClient.connect(PG_SETTINGS, min_size=1, max_size=3)
    investigation_requests_client = get_queue_client(INVESTIGATION_REQUESTS_QUEUE, async_credential)
    findings_ready_client = get_queue_client(FINDINGS_READY_QUEUE, async_credential)
    findings_ready_poison_client = get_queue_client(FINDINGS_READY_POISON_QUEUE, async_credential)

    print("[reporting] started, polling for queued cycles every "
          f"{POLL_INTERVAL_SECONDS}s (Ctrl+C to stop)")
    try:
        async with investigation_requests_client, findings_ready_client, findings_ready_poison_client, \
                httpx.AsyncClient(base_url=INVESTIGATION_BASE_URL, timeout=30.0) as http_client:
            while True:
                async with pg_client.pool.acquire() as conn:
                    cycle = await claim_next_queued_cycle(conn)
                if cycle is None:
                    await asyncio.sleep(POLL_INTERVAL_SECONDS)
                    continue
                await _execute_cycle(
                    pg_client, cycle, credential, arize_space_id,
                    investigation_requests_client, findings_ready_client, findings_ready_poison_client,
                    http_client,
                )
    finally:
        await pg_client.close()
        await async_credential.close()
        trace.get_tracer_provider().force_flush(timeout_millis=30000)


if __name__ == "__main__":
    asyncio.run(main())
