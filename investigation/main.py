"""OnePulse Investigation service — Migration Plan Phase 4 (ADR-019,
ADR-020).

The one process in this system with a Node runtime and ADO PAT access
(see the module docstring in `investigation/investigate.py` for the
real numbers driving this split: 302 of 378 seconds on a real full-scope
run — 80% of runtime — living in one stage). Runs as a real FastAPI
service whose `lifespan` starts a background asyncio task
(`_consume_loop`) polling the real `investigation-requests` Azure
Storage Queue, alongside a real HTTP route
(`GET /internal/investigations/{cycle_id}`) the Reporting service calls
to fetch results — the Migration Plan's own structural rule: Reporting
obtains findings over HTTP, never by connecting to the `investigation`
schema directly (enforced by real Postgres GRANTs, see
`scripts/investigation_migrations/0001_initial_schema.sql` and
`tests/test_investigation_schema_isolation.py`, not by discipline alone).

QUEUE SEMANTICS, deliberately designed for, not discovered:
  - At-least-once delivery: a redelivered message re-runs `investigate()`
    for the same `cycle_id`. `investigation.store.upsert_investigation_run`
    is keyed on `cycle_id` (`ON CONFLICT DO UPDATE`) so redelivery
    OVERWRITES the prior row rather than accumulating a second one.
  - Poison messages: a message received more than `MAX_DEQUEUE_COUNT`
    times without ever being deleted is moved to
    `investigation-requests-poison` and removed from the real queue
    (`onepulse_common.queues.is_poison`/`deadletter`) — a deliberate
    dead-letter path, not an assumption that redelivery always
    eventually succeeds.
  - Lease renewal: `receive_messages(visibility_timeout=...)` is Azure
    Storage Queues' real analog of `FOR UPDATE SKIP LOCKED`'s row lock,
    but with an automatic timeout instead of holding until COMMIT/
    ROLLBACK. A background `_renew_lease` task calls `update_message()`
    on a fixed cadence while `investigate()` is still running, so a
    genuinely-still-working consumer never loses its claim mid-run (real
    Investigation runs at full scope take minutes — Task 27/28). A
    consumer that dies (the kill test) simply stops renewing; the
    queue's own visibility timeout then expires on schedule and the
    message becomes visible again for a fresh consumer to redeliver and
    reprocess — no self-health-check needed on this side.

    Carried forward from Phase 3 (the MCP-child stall, CLAUDE.md Task
    42): a worker stalled with a dead MCP child process is a consumer
    that is still technically alive (the Python process never exits)
    but genuinely makes no more progress. Under this queue design, such
    a consumer KEEPS RENEWING its own lease forever (the renewal task
    has no way to know the MCP child is dead) — the message would never
    become visible again on its own. This is WORSE than Phase 3's
    already-documented baseline (a permanently-`running` cycle, at least
    visible as stuck in the `cycles` table) only in the sense that the
    queue message itself looks perfectly healthy from the outside too;
    it is NOT worse in any way that changes operational recourse — both
    require an operator to notice a cycle stuck at "running" for too
    long and intervene (kill the process). Not chased further here, per
    the Migration Plan's own explicit instruction — documented, not
    fixed.

TRACING ACROSS THE QUEUE HOP: `traceparent` does not cross a queue on
its own — it must ride in the message envelope. This service extracts
it from the inbound `investigation-requests` message
(`opentelemetry.propagate.extract`) and creates its own root span
*inside* that extracted context (the same real ordering fix already
proven twice — Phase 2 BFF-to-core-API, Phase 3 core-API-to-worker: the
routing context must be the OUTER manager, since Arize's router reads
it at span-*creation* time, not on_end()). A NEW `traceparent` is then
injected into the outbound `findings-ready` notification so the
Reporting service can continue the same trace on its own side of that
second queue hop.

Run: python -m investigation.main (alongside core_api, bff, reporting —
see the Runbook).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sys
from contextlib import asynccontextmanager

from agent_framework.foundry import FoundryChatClient
from arize.otel import set_routing_context
from azure.identity import DefaultAzureCredential
from azure.identity.aio import DefaultAzureCredential as AsyncDefaultAzureCredential
from azure.storage.queue import QueueMessage
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from opentelemetry import trace
from opentelemetry.propagate import extract, inject

from investigation.investigate import fetch_ado_pat_from_keyvault, investigate, load_ado_pat
from investigation.store import get_investigation_run, upsert_investigation_run
from onepulse_common.config import PostgresSettings
from onepulse_common.db import PostgresClient
from onepulse_common.observability import ARIZE_PROJECT_NAME, enable_observability
from trace_debug import enable_debug_span_log
from onepulse_common.queues import (
    FINDINGS_READY_QUEUE,
    INVESTIGATION_REQUESTS_POISON_QUEUE,
    INVESTIGATION_REQUESTS_QUEUE,
    deadletter,
    get_queue_client,
    is_poison,
    parse_message,
    send_json_message,
)

load_dotenv()

PG_SETTINGS = PostgresSettings(
    host="onepulse-pg-dev.postgres.database.azure.com",
    database="onepulse",
    role_name=os.environ.get("ONEPULSE_INVESTIGATION_PG_ROLE", "investigation_role_local_dev"),
)
PROJECT_ENDPOINT = os.environ.get(
    "ONEPULSE_FOUNDRY_PROJECT_ENDPOINT",
    "https://onepulse-resource.services.ai.azure.com/api/projects/onepulse",
)
DEPLOYMENT_NAME = os.environ.get("ONEPULSE_FOUNDRY_DEPLOYMENT_NAME", "onePulse-gpt-5-mini")
ADO_ORG_NAME = os.environ.get("ONEPULSE_ADO_ORG", "gopdha")

# Real, deliberate values, not defaults left unconsidered: full-scope
# real Investigation runs have taken up to ~4 minutes (Task 39's
# heartbeat-verified 4m06s run) — VISIBILITY_TIMEOUT_SECONDS is set well
# under that so the kill test (below) demonstrates redelivery in a
# reasonable, real, human-observable window, while LEASE_RENEWAL
# extends it well before it would expire on a genuinely still-running
# consumer.
VISIBILITY_TIMEOUT_SECONDS = 90
LEASE_RENEWAL_INTERVAL_SECONDS = 45
POLL_INTERVAL_SECONDS = 2.0

# Migration Plan Phase 5: explicit stdout, not basicConfig's own default
# stream (stderr) — real container log collection (docker logs,
# Application Insights in Phase 7) treats stdout/stderr differently
# enough that this project's own real per-tool-call detail should be
# unambiguous rather than incidentally caught by "stderr also gets
# collected." No file destination existed here to move away from — this
# service's own detail was always process-output only.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stdout)
logger = logging.getLogger("onepulse.investigation")
_tracer = trace.get_tracer(__name__)


async def _renew_lease(queue_client, message_holder: list[QueueMessage]) -> None:
    """Background task: extends the real Storage Queue visibility lease
    on a fixed cadence for as long as this task keeps running. Cancelled
    the instant the wrapped `investigate()` call returns (success or
    failure) — see the module docstring for why a genuinely dead
    consumer (this task itself cancelled with it, since it's cancelled
    from the same asyncio task tree) correctly stops renewing rather
    than holding the lease forever.
    """
    while True:
        await asyncio.sleep(LEASE_RENEWAL_INTERVAL_SECONDS)
        message_holder[0] = await queue_client.update_message(
            message_holder[0], visibility_timeout=VISIBILITY_TIMEOUT_SECONDS
        )
        logger.info("renewed lease on cycle request (message id=%s)", message_holder[0].id)


async def _handle_message(
    queue_client,
    poison_queue_client,
    findings_queue_client,
    message: QueueMessage,
    pg_client: PostgresClient,
    credential: DefaultAzureCredential,
    async_credential: AsyncDefaultAzureCredential,
    arize_space_id: str,
) -> None:
    if await is_poison(message):
        logger.error("poison message detected (dequeue_count=%d) — dead-lettering", message.dequeue_count)
        await deadletter(queue_client, poison_queue_client, message, reason=f"exceeded max dequeue count ({message.dequeue_count})")
        return

    envelope = parse_message(message)
    cycle_id = envelope["cycle_id"]
    program_name = envelope["program_name"]
    requested_by_actor_id = envelope.get("requested_by_actor_id")
    trace_context = envelope.get("trace_context")

    logger.info("received investigation request: cycle_id=%s program_name=%r", cycle_id, program_name)

    message_holder = [message]
    renewal_task = asyncio.create_task(_renew_lease(queue_client, message_holder))

    parent_ctx = extract({"traceparent": trace_context}) if trace_context else None
    try:
        with set_routing_context(space_id=arize_space_id, project_name=ARIZE_PROJECT_NAME):
            with _tracer.start_as_current_span("investigation POST investigation-requests", context=parent_ctx) as span:
                span.set_attribute("onepulse.cycle_id", cycle_id)
                span.set_attribute("onepulse.ado_project", program_name)
                try:
                    raw_pat = await fetch_ado_pat_from_keyvault(async_credential)
                    ado_pat_b64 = load_ado_pat(raw_pat)
                    chat_client = FoundryChatClient(
                        project_endpoint=PROJECT_ENDPOINT, model=DEPLOYMENT_NAME, credential=credential
                    )
                    findings, queried_item_count, tower_hierarchy = await investigate(
                        chat_client, ado_pat_b64, ADO_ORG_NAME, program_name,
                        lambda m: logger.info("  %s", m),
                    )
                    async with pg_client.pool.acquire() as conn:
                        await upsert_investigation_run(
                            conn,
                            cycle_id=cycle_id,
                            program_name=program_name,
                            requested_by_actor_id=requested_by_actor_id,
                            status="completed",
                            queried_item_count=queried_item_count,
                            findings=findings,
                            tower_hierarchy=tower_hierarchy,
                            trace_context=trace_context,
                        )
                    logger.info("cycle %s completed: %d finding(s)", cycle_id, len(findings))
                except Exception as e:  # noqa: BLE001 - a real, expected failure state (see store.py's
                    # status field) — recorded, not swallowed; the outer finally still cancels
                    # the renewal task and the message is still deleted below so it isn't
                    # redelivered forever for a failure Investigation has already recorded.
                    logger.exception("investigation failed for cycle %s", cycle_id)
                    async with pg_client.pool.acquire() as conn:
                        await upsert_investigation_run(
                            conn,
                            cycle_id=cycle_id,
                            program_name=program_name,
                            requested_by_actor_id=requested_by_actor_id,
                            status="failed",
                            error_detail=str(e),
                            trace_context=trace_context,
                        )

                # New traceparent for the outbound findings-ready hop —
                # injected from the still-active span above, so Reporting's
                # own extract() on the other side nests under this span,
                # not under the original inbound one.
                outbound_headers: dict[str, str] = {}
                inject(outbound_headers)
                await send_json_message(
                    findings_queue_client,
                    {"cycle_id": cycle_id, "trace_context": outbound_headers.get("traceparent")},
                )
    finally:
        renewal_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await renewal_task

    # Only deleted after both the investigation_runs row AND the
    # findings-ready notification are real and durable — a crash any
    # time before this line leaves the message undeleted, so it becomes
    # visible again after its lease expires and gets redelivered
    # (the kill test's whole point).
    await queue_client.delete_message(message_holder[0])


async def _consume_loop(app: FastAPI) -> None:
    credential: AsyncDefaultAzureCredential = app.state.async_credential
    queue_client = get_queue_client(INVESTIGATION_REQUESTS_QUEUE, credential)
    poison_queue_client = get_queue_client(INVESTIGATION_REQUESTS_POISON_QUEUE, credential)
    findings_queue_client = get_queue_client(FINDINGS_READY_QUEUE, credential)
    async with queue_client, poison_queue_client, findings_queue_client:
        logger.info("investigation service polling '%s' every %.1fs", INVESTIGATION_REQUESTS_QUEUE, POLL_INTERVAL_SECONDS)
        while True:
            received_any = False
            async for message in queue_client.receive_messages(
                messages_per_page=1, visibility_timeout=VISIBILITY_TIMEOUT_SECONDS
            ):
                received_any = True
                await _handle_message(
                    queue_client,
                    poison_queue_client,
                    findings_queue_client,
                    message,
                    app.state.pg_client,
                    app.state.credential,
                    credential,
                    app.state.arize_space_id,
                )
            if not received_any:
                await asyncio.sleep(POLL_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.credential = DefaultAzureCredential()
    app.state.async_credential = AsyncDefaultAzureCredential()
    app.state.arize_space_id = enable_observability(app.state.credential, PROJECT_ENDPOINT)
    enable_debug_span_log("investigation")
    app.state.pg_client = await PostgresClient.connect(PG_SETTINGS, min_size=1, max_size=3)

    consume_task = asyncio.create_task(_consume_loop(app))
    try:
        yield
    finally:
        consume_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await consume_task
        await app.state.pg_client.close()
        await app.state.async_credential.close()
        trace.get_tracer_provider().force_flush(timeout_millis=30000)


app = FastAPI(title="OnePulse Investigation Service", lifespan=lifespan)


@app.get("/internal/investigations/{cycle_id}")
async def get_investigation(cycle_id: str) -> dict:
    """Real HTTP route the Reporting service calls to fetch results —
    the ONLY way Reporting ever learns Investigation's real findings,
    per the Migration Plan's structural rule. Never reads
    `investigation.investigation_runs` on the caller's behalf; this
    process is the only one holding a role with grants on that schema.
    """
    async with app.state.pg_client.pool.acquire() as conn:
        run = await get_investigation_run(conn, cycle_id)
    if run is None:
        raise HTTPException(status_code=404, detail="investigation_run_not_found")
    return run


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
