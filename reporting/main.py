"""OnePulse Reporting service — Migration Plan Phase 4 (ADR-019, ADR-020),
made queue-driven at its own outer trigger in Phase 7 follow-up
(ADR-026).

**Phase 7 follow-up: no longer polls the `cycles` status table.**
Phase 3-4's DB-polling claim (`claim_next_queued_cycle`, `FOR UPDATE
SKIP LOCKED`) is retired — this was the last service in the deployment
still forced to `minReplicas: 1` (Phase 7's own disclosed, ~$22/month
exception), since nothing in the platform could ever wake a DB-poller
from zero. This service is now a real Azure Storage Queue consumer on
`report-cycles` (core_api's trigger endpoint publishes to it right
after the real `cycles` INSERT), the identical consumer shape already
proven for Investigation since Phase 4 — lease renewal, poison
dead-lettering, delete-only-after-terminal. `reporting` now scales to
zero like every other service in this deployment; see ADR-026 for the
full reasoning and the real KEDA queue-depth scale rule.

**The real new property, not just "redelivery is safe" — "redelivery
is cheap" (ADR-026):** a redelivered `report-cycles` message (this
process killed mid-cycle) now checks, before ever dispatching to
Investigation again, whether Investigation's own store already has a
real result for this `cycle_id` (`GET /internal/investigations/
{cycle_id}`, the same real HTTP route already used to fetch results —
see `_resolve_investigation_result`). If it does, the ~80%-of-runtime,
real-Foundry/ADO-cost Investigation dispatch is skipped entirely and
this service resumes straight into rendering off the already-real
findings. Investigation's own store is already keyed on `cycle_id`
(`ON CONFLICT DO UPDATE`, Phase 4) specifically so this kind of resume
check has one real, authoritative place to ask — no new state was
added to the `cycles` table for this.

Investigation itself is still reached over two real named Azure Storage
Queues, unchanged since Phase 4:
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
process is currently awaiting are left undeleted (a mismatched message
becomes visible again after its own timeout and is reconsidered on a
later poll — real, deliberately defensive design for however many
Reporting replicas KEDA is running concurrently, since `report-cycles`
can now genuinely deliver different cycles to different replicas at
once). A real, generous overall wait (`FINDINGS_READY_TIMEOUT_SECONDS`)
bounds how long this service waits before honestly failing the cycle —
covering Investigation's own dead-letter threshold (`MAX_DEQUEUE_COUNT`
redeliveries x `VISIBILITY_TIMEOUT_SECONDS` each) plus real processing
time, so a message that is never going to be answered (e.g. genuinely
dead-lettered) doesn't hang this process forever.

Run: python -m reporting.main (alongside core_api, bff, investigation —
see the Runbook).
"""

from __future__ import annotations

import asyncio
import contextlib
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
from azure.storage.queue import QueueMessage
from dotenv import load_dotenv
from opentelemetry import trace
from opentelemetry.propagate import extract, inject

from onepulse_common.config import PostgresSettings
from onepulse_common.cycle_progress import advance_stage, apply_detail, finalize_stage_state, mark_failed, new_stage_state
from onepulse_common.cycles import get_cycle_for_execution, mark_cycle_failed, mark_cycle_terminal, terminal_status_from_result, write_cycle_stages
from onepulse_common.db import PostgresClient
from onepulse_common.heartbeat import heartbeat
from onepulse_common.observability import ARIZE_PROJECT_NAME, enable_observability
from onepulse_common.pipeline import TOTAL_STAGES, run_reporting_stages
from onepulse_common.queues import (
    FINDINGS_READY_POISON_QUEUE,
    FINDINGS_READY_QUEUE,
    INVESTIGATION_REQUESTS_QUEUE,
    MAX_DEQUEUE_COUNT,
    REPORT_CYCLES_POISON_QUEUE,
    REPORT_CYCLES_QUEUE,
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

# Real, deliberate values (ADR-026), matching Investigation's own
# already-proven cadence exactly (Phase 4): a full real cycle can run
# several minutes (the AOP full-scope runs this project has repeatedly
# measured at 3-6 minutes end to end), so the visibility timeout alone
# would expire mid-run without renewal — CYCLE_LEASE_RENEWAL_INTERVAL_
# SECONDS extends it well before that, and a genuinely dead consumer
# (the kill test) simply stops renewing, letting the real timeout
# expire on schedule and the message become visible again.
CYCLE_VISIBILITY_TIMEOUT_SECONDS = 90
CYCLE_LEASE_RENEWAL_INTERVAL_SECONDS = 45

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


async def _fetch_investigation_result(http_client: httpx.AsyncClient, cycle_id: str) -> dict | None:
    """The one and only real path Reporting ever uses to obtain
    Investigation's findings — a real HTTP GET, never a direct query
    against the `investigation` schema (there is no grant that would
    even allow one — see `tests/test_investigation_schema_isolation.py`).

    Returns `None` on a real 404 (no result exists for this cycle_id
    yet) instead of raising — this doubles as the real ADR-026 resume
    check: a caller can ask "has Investigation already finished this
    cycle" before deciding whether to dispatch at all.
    """
    response = await http_client.get(f"/internal/investigations/{cycle_id}")
    if response.status_code == 404:
        return None
    response.raise_for_status()
    run = response.json()
    if run["status"] == "failed":
        raise InvestigationFailedError(run.get("error_detail") or "Investigation reported a failure with no detail.")
    return run


async def _resolve_investigation_result(
    investigation_requests_client,
    findings_ready_client,
    findings_ready_poison_client,
    http_client: httpx.AsyncClient,
    cycle_id: str,
    program_name: str,
    requested_by_actor_id: str,
    on_stage,
    on_detail,
) -> dict:
    """The real resume check (ADR-026): before ever dispatching to
    Investigation, ask whether it has already completed this cycle_id —
    Investigation's own store is keyed on `cycle_id` (Phase 4's real
    `ON CONFLICT DO UPDATE` upsert) and is the single, already-existing
    source of truth for this, over the same real HTTP route Reporting
    already uses to fetch results — no second tracking mechanism, no
    new state added to `cycles`. A redelivered `report-cycles` message
    (this process killed mid-run, the same real property Investigation's
    own kill test proved for itself in Phase 4) now skips the expensive
    ~80%-of-runtime, real-Foundry/ADO-cost re-dispatch entirely when
    Investigation already has a real answer — turning "redelivery is
    safe" into "redelivery is cheap."
    """
    existing = await _fetch_investigation_result(http_client, cycle_id)
    if existing is not None:
        on_stage(
            1, TOTAL_STAGES,
            f"Investigation — already completed for this cycle, resuming for '{program_name}' (no re-dispatch)",
        )
        return existing

    on_stage(1, TOTAL_STAGES, f"Investigation — dispatched to Investigation service for '{program_name}'")
    await _dispatch_investigation_request(investigation_requests_client, cycle_id, program_name, requested_by_actor_id)
    await _await_findings(findings_ready_client, findings_ready_poison_client, cycle_id, on_detail)
    result = await _fetch_investigation_result(http_client, cycle_id)
    if result is None:
        # Real, unexpected inconsistency, not a normal path: a real
        # findings-ready notification arrived, but Investigation's own
        # store still has nothing for this cycle_id. Fail the cycle
        # honestly rather than silently retry or proceed with no data.
        raise RuntimeError(
            f"Investigation result still missing for cycle {cycle_id} after a real "
            f"findings-ready notification — a real, unexpected inconsistency between "
            f"the queue notification and Investigation's own store."
        )
    return result


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
                    investigation_run = await _resolve_investigation_result(
                        investigation_requests_client, findings_ready_client, findings_ready_poison_client,
                        http_client, cycle_id, program_name, requested_by_actor_id, on_stage, on_detail,
                    )
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


async def _renew_cycle_lease(queue_client, message_holder: list[QueueMessage]) -> None:
    """Background task: extends the real Storage Queue visibility lease
    on the `report-cycles` message on a fixed cadence for as long as
    this task keeps running — the identical real mechanism already
    proven for Investigation (Phase 4). Cancelled the instant
    `_execute_cycle` returns (success or a real, recorded application
    failure); a genuinely dead consumer (the kill test) simply stops
    renewing, and the queue's own visibility timeout expires on its own
    schedule, making the message visible again for a fresh consumer.
    """
    while True:
        await asyncio.sleep(CYCLE_LEASE_RENEWAL_INTERVAL_SECONDS)
        message_holder[0] = await queue_client.update_message(
            message_holder[0], visibility_timeout=CYCLE_VISIBILITY_TIMEOUT_SECONDS
        )
        print(f"[reporting] renewed lease on report-cycles message (id={message_holder[0].id})")


async def _handle_report_cycle_message(
    queue_client,
    poison_queue_client,
    message: QueueMessage,
    pg_client: PostgresClient,
    credential: DefaultAzureCredential,
    arize_space_id: str,
    investigation_requests_client,
    findings_ready_client,
    findings_ready_poison_client,
    http_client: httpx.AsyncClient,
) -> None:
    if await is_poison(message):
        print(f"[reporting] poison message detected (dequeue_count={message.dequeue_count}) — dead-lettering")
        await deadletter(
            queue_client, poison_queue_client, message,
            reason=f"exceeded max dequeue count ({message.dequeue_count})",
        )
        return

    envelope = parse_message(message)
    cycle_id = envelope["cycle_id"]

    async with pg_client.pool.acquire() as conn:
        cycle = await get_cycle_for_execution(conn, cycle_id)
    if cycle is None:
        # Real, defensive case, not expected in normal operation: a
        # cycle_id with no matching real `cycles` row — core_api's
        # trigger endpoint always INSERTs before publishing, so this
        # should never happen. Dead-letter rather than loop forever on
        # a message that can never resolve.
        print(f"[reporting] no cycles row found for cycle_id={cycle_id} — dead-lettering")
        await deadletter(queue_client, poison_queue_client, message, reason=f"no cycles row for cycle_id={cycle_id}")
        return

    message_holder = [message]
    renewal_task = asyncio.create_task(_renew_cycle_lease(queue_client, message_holder))
    try:
        await _execute_cycle(
            pg_client, cycle, credential, arize_space_id,
            investigation_requests_client, findings_ready_client, findings_ready_poison_client,
            http_client,
        )
    finally:
        renewal_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await renewal_task

    # Deleted only after _execute_cycle reaches a real terminal outcome
    # (mark_cycle_terminal on success, or mark_cycle_failed on a real,
    # recorded application failure — both real terminal states
    # _execute_cycle already wrote to `cycles` before returning here). A
    # genuine crash/kill before this line leaves the message undeleted,
    # so it becomes visible again after its lease expires and is
    # redelivered — the kill test's whole point, now proven for
    # Reporting the same way Phase 4 proved it for Investigation, with
    # the added ADR-026 resume check making the redelivery cheap, not
    # just safe.
    await queue_client.delete_message(message_holder[0])


async def _consume_loop(
    report_cycles_client, report_cycles_poison_client,
    investigation_requests_client, findings_ready_client, findings_ready_poison_client,
    pg_client: PostgresClient, credential: DefaultAzureCredential, arize_space_id: str,
    http_client: httpx.AsyncClient,
) -> None:
    print(f"[reporting] polling '{REPORT_CYCLES_QUEUE}' every {POLL_INTERVAL_SECONDS}s (Ctrl+C to stop)")
    while True:
        received_any = False
        async for message in report_cycles_client.receive_messages(
            messages_per_page=1, visibility_timeout=CYCLE_VISIBILITY_TIMEOUT_SECONDS
        ):
            received_any = True
            await _handle_report_cycle_message(
                report_cycles_client, report_cycles_poison_client, message,
                pg_client, credential, arize_space_id,
                investigation_requests_client, findings_ready_client, findings_ready_poison_client,
                http_client,
            )
        if not received_any:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def main() -> None:
    credential = DefaultAzureCredential()
    async_credential = AsyncDefaultAzureCredential()
    arize_space_id = enable_observability(credential, PROJECT_ENDPOINT)
    enable_debug_span_log("reporting")

    pg_client = await PostgresClient.connect(PG_SETTINGS, min_size=1, max_size=3)
    report_cycles_client = get_queue_client(REPORT_CYCLES_QUEUE, async_credential)
    report_cycles_poison_client = get_queue_client(REPORT_CYCLES_POISON_QUEUE, async_credential)
    investigation_requests_client = get_queue_client(INVESTIGATION_REQUESTS_QUEUE, async_credential)
    findings_ready_client = get_queue_client(FINDINGS_READY_QUEUE, async_credential)
    findings_ready_poison_client = get_queue_client(FINDINGS_READY_POISON_QUEUE, async_credential)

    try:
        async with report_cycles_client, report_cycles_poison_client, \
                investigation_requests_client, findings_ready_client, findings_ready_poison_client, \
                httpx.AsyncClient(base_url=INVESTIGATION_BASE_URL, timeout=30.0) as http_client:
            await _consume_loop(
                report_cycles_client, report_cycles_poison_client,
                investigation_requests_client, findings_ready_client, findings_ready_poison_client,
                pg_client, credential, arize_space_id, http_client,
            )
    finally:
        await pg_client.close()
        await async_credential.close()
        trace.get_tracer_provider().force_flush(timeout_millis=30000)


if __name__ == "__main__":
    asyncio.run(main())
