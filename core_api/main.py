"""OnePulse core API — Migration Plan Phase 2 (ADR-017): owns the
domain, every data connection, and dispatch. Everything that was in
`api/main.py` (Phase 1) lives here now, plus the real boundary Phase 2
adds: every route requires a real, validated service token (see
`security.py`), and identity is resolved server-side from a real
`actors` lookup — never accepted as an internal `actor_id` from the
caller. See `security.py`'s own module docstring for the full reasoning
and the real Entra App Registration this validates against
(`onepulse-core-api`), and CLAUDE.md Task 41 for the real setup process,
including a real consent-propagation delay found live.

One of the three original Phase 1 decisions still holds, unchanged,
restated so it isn't lost in the split (see the superseded
`api/main.py`'s own docstring, Task 40, for the full original
reasoning): `onepulse_common` is not modified by this file's own routes.
Reviewer authentication (the second) is real now, Migration Plan Phase 8
(ADR-027) — `get_current_actor` resolves a real role and a real,
RLS-enforced tenant/program scope for every route; see `security.py`'s
own module docstring for the full design. The third — no report-trigger
endpoint — is real now (Migration Plan Phase 3, ADR-021, made
queue-driven in a Phase 7 follow-up, ADR-026): `POST
/api/v1/programs/{programId}/reports` inserts a real `queued` row into
the `cycles` status table AND publishes a real, thin `report-cycles`
queue message (`cycle_id` only — `cycles` itself stays the source of
truth for everything else) so the Reporting service can be woken from a
real scaled-to-zero state, then returns `202` immediately; it does not
execute the pipeline itself. The Reporting service (`reporting/main.py`)
consumes that queue and does the real work — see its own module
docstring, including the real ADR-026 resume check that makes a
redelivered message skip re-dispatching Investigation when it already
completed.
Real deviation from LLD 2.1's literal body shape (`{"requestedBy":
"<actorId>"}`), stated plainly: identity here follows the same real
ADR-017 pattern as approve/reject/chat — resolved server-side from the
BFF-forwarded Entra object ID header, never accepted as a body field —
so this endpoint takes no meaningful request body at all.

Real, load-bearing design point: this service now has **internal-only**
meaning even though nothing locally enforces network isolation (that's
Phase 7, Container Apps ingress). `verify_service_token` is what
actually stands in for that boundary today — a request without a real,
valid token for this service's own audience is rejected regardless of
which port it arrives on.

Run: uvicorn core_api.main:app --port 8000 (from the repo root).
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Literal

import asyncpg
from agent_framework.foundry import FoundryChatClient
from arize.otel import set_routing_context
from azure.identity import DefaultAzureCredential
from azure.identity.aio import DefaultAzureCredential as AsyncDefaultAzureCredential
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from opentelemetry import trace
from opentelemetry.propagate import extract, inject
from pydantic import BaseModel, ConfigDict, field_validator

from core_api.security import CurrentActor, get_current_actor, verify_service_token
from onepulse_common.blob_storage import issue_download_sas, parse_blob_uri
from onepulse_common.chat_assistant import ask_question
from onepulse_common.config import PostgresSettings
from onepulse_common.constants import ON_DEMAND_RATE_LIMIT_PER_LEAD_PER_DAY
from onepulse_common.cycles import create_cycle, get_cycle
from onepulse_common.db import PostgresClient
from onepulse_common.embeddings import build_embedding_client
from onepulse_common.queues import REPORT_CYCLES_QUEUE, get_queue_client, send_json_message
from onepulse_common.human_governance import (
    NotesRequiredError,
    ReportNotFoundError,
    approve_report,
    get_report_detail,
    get_report_download_info,
    get_report_program_id,
    list_pending_reviews,
    reject_report,
)
from onepulse_common.observability import ARIZE_PROJECT_NAME, enable_observability
from onepulse_common.pipeline import list_recent_reports
from onepulse_common.search_index import build_search_client
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

# FR-11 (Migration Plan Phase 8): 2 on-demand triggers per actor per
# day. Buildable without a separate retrofit because Phase 4 (ADR-019)
# already threads `requested_by_actor_id` through `cycles`/the queue
# envelope specifically for this — counting real, already-recorded
# trigger requests against that column, grouped by actor and a rolling
# 24-hour window. Applies to every Owner-tier actor who can trigger at
# all, not narrowed to the literal legacy role value 'portfolio_lead' —
# a platform_admin or a new 'owner' actor triggering unlimited runs
# while a portfolio_lead alone was capped would be a real, silent gap
# in the same protection FR-11 exists for. NFR-6's own usage_ledger
# (cost-based governance) is a separate, real, NOT-built concern —
# this rate limit stands alone, keyed on a plain count of `cycles` rows,
# not on any real cost figure `usage_ledger` would need to carry.
#
# The default reads from the same canonical LLD §3 constant CLAUDE.md's
# own Configuration Values table reproduces verbatim
# (`ON_DEMAND_RATE_LIMIT_PER_LEAD_PER_DAY`), not a second, independently
# -typed "2" that would silently drift from it — the requirement is 2,
# stated once. `ONEPULSE_RATE_LIMIT_TRIGGERS_PER_DAY` exists ONLY as a
# real deployed testing override (see CLAUDE.md's dated open item); it
# must be reverted before this URL goes to anyone external — raising it
# here does not change FR-11 itself, only how it's enforced today.
RATE_LIMIT_TRIGGERS_PER_DAY = int(
    os.environ.get(
        "ONEPULSE_RATE_LIMIT_TRIGGERS_PER_DAY",
        str(ON_DEMAND_RATE_LIMIT_PER_LEAD_PER_DAY),
    )
)

_tracer = trace.get_tracer(__name__)


async def _count_recent_triggers(conn: asyncpg.Connection, actor_id: str) -> int:
    """The one real query FR-11's enforcement and its own status display
    both need — shared so the number a caller sees before clicking
    Generate (`GET /api/v1/me`) can never disagree with the number that
    actually gates the click (`_check_rate_limit`, below)."""
    return await conn.fetchval(
        "SELECT count(*) FROM cycles WHERE requested_by_actor_id = $1 AND created_at >= now() - interval '24 hours'",
        actor_id,
    )


async def _check_rate_limit(conn: asyncpg.Connection, actor_id: str) -> None:
    count = await _count_recent_triggers(conn, actor_id)
    if count >= RATE_LIMIT_TRIGGERS_PER_DAY:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "rate_limit_exceeded",
                "message": f"Limit of {RATE_LIMIT_TRIGGERS_PER_DAY} report triggers per 24 hours reached.",
            },
        )


def _require_owner(current_actor: CurrentActor) -> None:
    if not current_actor.is_owner:
        raise HTTPException(status_code=403, detail={"error": "visitor_cannot_generate_or_approve"})


def _require_program_in_scope(current_actor: CurrentActor, program_id: str) -> None:
    if program_id not in current_actor.authorized_program_ids:
        raise HTTPException(status_code=404, detail={"error": "program_not_found"})


@asynccontextmanager
async def lifespan(app: FastAPI):
    pg_client = await PostgresClient.connect(PG_SETTINGS, min_size=1, max_size=5)
    credential = DefaultAzureCredential()
    async_credential = AsyncDefaultAzureCredential()
    search_client = build_search_client(credential)
    embedding_client = build_embedding_client(credential)
    chat_client = FoundryChatClient(project_endpoint=PROJECT_ENDPOINT, model=DEPLOYMENT_NAME, credential=credential)

    # Real ADR-026 addition: the trigger endpoint's own queue client,
    # held open for the process lifetime (the same real pattern as
    # every other client here) rather than opened/closed per request.
    report_cycles_client = get_queue_client(REPORT_CYCLES_QUEUE, async_credential)
    await report_cycles_client.__aenter__()

    # Real dual-export observability (Application Insights + Arize),
    # the identical function every other real entry point in this
    # project uses — one TracerProvider per process, called once here
    # (this service's own lifespan runs once per process, same
    # guarantee run_pipeline.py's single-CLI-invocation shape gives).
    arize_space_id = enable_observability(credential, PROJECT_ENDPOINT)
    enable_debug_span_log("core_api")

    app.state.pg_client = pg_client
    app.state.search_client = search_client
    app.state.embedding_client = embedding_client
    app.state.chat_client = chat_client
    app.state.arize_space_id = arize_space_id
    app.state.report_cycles_client = report_cycles_client
    # Migration Plan Phase 8: the real user-delegation SAS mechanism
    # (onepulse_common.blob_storage) needs an async credential of its
    # own — stored here rather than constructed per-request, the same
    # real pattern as every other client this lifespan already builds
    # once per process.
    app.state.async_credential = async_credential

    try:
        yield
    finally:
        await report_cycles_client.__aexit__(None, None, None)
        await async_credential.close()
        await pg_client.close()
        await search_client.close()
        await embedding_client.close()
        trace.get_tracer_provider().force_flush(timeout_millis=30000)


app = FastAPI(title="OnePulse Core API", version="0.2.0", lifespan=lifespan)


@app.middleware("http")
async def tracing_middleware(request: Request, call_next):
    """The real cross-process half of Phase 2's own bar: extracts the
    W3C `traceparent` the BFF sent (via `opentelemetry.propagate.
    extract`, the standard mechanism, not hand-rolled header parsing)
    and uses it as the parent context for this service's own root span
    — this is what makes the core API's spans nest under the BFF's in
    the real trace tree, rather than appearing as a second, disconnected
    trace. `set_routing_context` is the OUTER manager (same real fix
    Task 30 already found and proved once: `ArizeRoutingSpanProcessor.
    on_start()` reads this contextvar at span-*creation* time, not
    on_end() — so it must already be active before `start_as_current_
    span` runs, not merely before the span finishes).
    """
    if request.url.path == "/health":
        # Real, load-bearing exclusion: Docker's own HEALTHCHECK polls
        # this every few seconds for as long as the container runs —
        # tracing it would mean permanent background noise in every
        # real trace tool this project uses, for a request that carries
        # no real work and no caller-supplied traceparent to extract.
        return await call_next(request)

    parent_ctx = extract(dict(request.headers))
    with set_routing_context(space_id=app.state.arize_space_id, project_name=ARIZE_PROJECT_NAME):
        with _tracer.start_as_current_span(
            f"core_api {request.method} {request.url.path}", context=parent_ctx
        ) as span:
            span.set_attribute("http.method", request.method)
            span.set_attribute("http.target", request.url.path)
            response = await call_next(request)
            span.set_attribute("http.status_code", response.status_code)
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Real bug found live during Phase 10 device testing (CLAUDE.md Task
    53), not by inspection: every `raise HTTPException(status_code=...,
    detail={"error": ..., "message": ...})` in this file — 403, 404,
    429, and the direct-HTTPException 400 for notes_required — was
    shipping a body shaped `{"detail": {"error": ..., "message": ...}}`,
    because FastAPI's own default HTTPException handler wraps whatever
    `detail` is passed as `{"detail": <detail>}`. It was never the flat
    `{"error": ..., "message": ...}` shape this API's own contract
    already uses everywhere else (see `validation_exception_handler`
    below, which reshapes into exactly that flat shape for its own
    Pydantic-validation branch). `frontend/src/api/client.ts` reads
    `body.error`/`body.message` at the top level — with the real extra
    `detail` nesting, `code` was always `undefined` for every
    HTTPException-raised error in this entire API, and every caller fell
    through to a generic "Request failed with {status}" message,
    collapsing a 403 (not permitted, ever) and a 429 (permitted, out of
    quota for now) into an identical, uninformative shape. Overriding the
    default handler here — one real fix, at the one real source, not a
    per-call-site patch — matches every raise site's own intended shape
    instead of asking each one to route around FastAPI's default.
    """
    content = exc.detail if isinstance(exc.detail, dict) else {"error": "http_error", "message": str(exc.detail)}
    return JSONResponse(status_code=exc.status_code, content=jsonable_encoder(content), headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Unchanged real behavior from Phase 1 — see the superseded
    `api/main.py`'s own docstring (Task 40) for the full reasoning,
    including the real `jsonable_encoder` bug found live there.
    """
    for err in exc.errors():
        loc = err.get("loc", ())
        if loc and loc[-1] == "notes":
            return JSONResponse(status_code=400, content={"error": "notes_required"})
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(exc.errors())})


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Real fix for the container-startup race Phase 5 only documented
    and BFF's own retry-on-failure absorbed silently (CLAUDE.md Task
    44/45): the BFF's first outbound call could land before this
    service's ASGI startup finished, on every cold `docker compose up`.
    Deliberately unauthenticated — Docker's own HEALTHCHECK has no way
    to present a real Entra service token, and doesn't need one to
    prove liveness. This route only becomes reachable once uvicorn
    finishes running `lifespan()`'s own startup half (the ASGI lifespan
    protocol does not begin accepting HTTP requests until that
    completes) — a real 200 here is genuine proof `app.state.pg_client`
    and every other lifespan-constructed client are already built, not
    an assumption about container readiness inferred from the process
    merely existing.
    """
    return {"status": "ok"}


# ---------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------

RagStatus = Literal["Red", "Amber", "Green", "Unknown"]
QualityGateOutcome = Literal["approved", "route_to_human_review"]
StatusLabel = Literal["On Track", "At Risk", "Blocked", "Needs Human Review"]
Decision = Literal["approved", "rejected"]


class RejectRequest(BaseModel):
    # Migration Plan Phase 8: `extra="forbid"` is a deliberate, real
    # enforcement of ADR-017's own rule, not incidental strictness — an
    # attempt to smuggle an `actorId` (or anything else) into this body
    # gets a real, visible 422 rather than being silently dropped by
    # Pydantic's default behavior. `actor_id` is derived server-side,
    # always, from the platform-verified identity header alone; this is
    # what makes that structurally true rather than merely undocumented.
    model_config = ConfigDict(extra="forbid")

    notes: str

    @field_validator("notes")
    @classmethod
    def notes_must_not_be_empty(cls, v: str) -> str:
        # Mirrors the real approval_records_rejected_notes_required
        # CHECK (migration 0002) — same "empty after trim" definition.
        if not v or not v.strip():
            raise ValueError("notes_required")
        return v


class ReviewDecisionResponse(BaseModel):
    reportId: int
    decision: Decision
    decidedAt: str


class PendingReviewItem(BaseModel):
    reportId: int
    weekOf: str
    ragStatus: RagStatus
    renderedArtifactUri: str | None
    qualityGateOutcome: QualityGateOutcome


class PendingReviewsResponse(BaseModel):
    reports: list[PendingReviewItem]


class ProgramItem(BaseModel):
    programId: str
    name: str


class MeResponse(BaseModel):
    role: str
    isOwner: bool
    authorizedProgramIds: list[str]
    # Real Migration Plan Phase 10 finding (CLAUDE.md Task 54): FR-11's
    # count already exists server-side on every trigger request — these
    # two fields surface it, not a new mechanism, computed the same way
    # `_check_rate_limit` computes it (`_count_recent_triggers`, above),
    # so the number shown here can never disagree with the number that
    # actually gates the click. `None` for a visitor, who can't trigger
    # a run regardless of quota, per `_require_owner`.
    remainingTriggersToday: int | None = None
    triggerLimitPerDay: int | None = None


class ReportSummary(BaseModel):
    reportId: int
    programName: str
    weekOf: str
    ragStatus: RagStatus
    qualityGateOutcome: QualityGateOutcome
    reviewed: bool
    renderedArtifactUri: str | None
    createdAt: str
    decision: Decision | None
    findingCount: int


class FindingItem(BaseModel):
    findingId: int
    sourceItemRef: str | None
    title: str
    statusLabel: StatusLabel
    evidence: str


class UntrackedItemModel(BaseModel):
    untrackedItemId: int
    description: str
    evidence: str | None
    possibleLinkedFindingId: int | None
    reasoning: str | None


class ReportDetail(BaseModel):
    reportId: int
    programName: str
    weekOf: str
    ragStatus: RagStatus
    qualityGateOutcome: QualityGateOutcome
    executiveSummary: str
    renderedArtifactUri: str | None
    reviewed: bool


class ReportDetailResponse(BaseModel):
    report: ReportDetail
    findings: list[FindingItem]
    untrackedItems: list[UntrackedItemModel]


class TriggerResponse(BaseModel):
    cycleId: str
    status: str


class DownloadResponse(BaseModel):
    downloadUrl: str
    expiresInMinutes: int


CycleStatus = Literal[
    "queued", "running",
    "persisted", "persisted_route_to_human_review",
    "not_persisted_already_exists", "hard_stop_defect",
    "failed",
]


class CycleStatusResponse(BaseModel):
    cycleId: str
    status: CycleStatus
    stages: dict
    reportId: int | None
    errorDetail: str | None
    createdAt: str
    startedAt: str | None
    finishedAt: str | None


class ChatQueryRequest(BaseModel):
    question: str
    programId: str | None = None

    @field_validator("question")
    @classmethod
    def question_must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("question_required")
        return v


class Citation(BaseModel):
    reportId: int
    programName: str
    weekOf: str
    sourceItemRef: str | None = None
    findingTitle: str | None = None


class ChatQueryResponse(BaseModel):
    answer: str
    citations: list[Citation]


# ---------------------------------------------------------------------
# Routes — every one requires a real, validated service token
# (verify_service_token), applied per-route via `Depends` rather than
# buried in middleware, so each route's real auth requirement is
# visible in its own signature.
# ---------------------------------------------------------------------


@app.get("/api/v1/me")
async def get_me(
    request: Request,
    _token=Depends(verify_service_token),
    current_actor: CurrentActor = Depends(get_current_actor),
) -> MeResponse:
    """Migration Plan Phase 9: the one real gap Phase 8 left — no route
    ever exposed the caller's own resolved role back to a client. React
    needs this to decide what to render (Generate/Approve/Reject show
    only for an owner); it changes nothing about what's actually
    enforced. `get_current_actor` already 403s an unprovisioned or
    unscoped identity before this line runs, so a response from here is
    itself proof of real access — hiding a control client-side is
    usability, not security, and stays true with this route in place:
    every mutating route still runs its own real `_require_owner`/scope
    check server-side regardless of what this response says.

    Migration Plan Phase 10 (CLAUDE.md Task 54): also surfaces FR-11's
    real remaining-trigger count for an owner, computed via the same
    `_count_recent_triggers` query `_check_rate_limit` itself uses — one
    real number, read here and enforced there, never two. Real cost:
    one extra `SELECT count(*)` on this route, only for an owner (a
    visitor can never trigger regardless of quota, so it isn't computed
    for one) — cheap against a `cycles` row count this small, and this
    route is already a real Postgres round trip for `current_actor`
    itself.
    """
    remaining_today: int | None = None
    limit_per_day: int | None = None
    if current_actor.is_owner:
        limit_per_day = RATE_LIMIT_TRIGGERS_PER_DAY
        async with request.app.state.pg_client.pool.acquire() as conn:
            used = await _count_recent_triggers(conn, current_actor.actor_id)
        remaining_today = max(0, limit_per_day - used)
    return MeResponse(
        role=current_actor.role,
        isOwner=current_actor.is_owner,
        authorizedProgramIds=list(current_actor.authorized_program_ids),
        remainingTriggersToday=remaining_today,
        triggerLimitPerDay=limit_per_day,
    )


@app.get("/api/v1/programs")
async def list_programs(
    request: Request,
    _token=Depends(verify_service_token),
    current_actor: CurrentActor = Depends(get_current_actor),
) -> list[ProgramItem]:
    """Migration Plan Phase 8: scoped to the caller's own resolved
    `authorized_program_ids` — previously every program name in the
    database, tenant boundary or not, was visible to any authenticated
    caller. An actor with no scope never reaches this line at all
    (`get_current_actor` already 403s), so an empty scope here would
    only ever mean a real, if unusual, zero-program grant.
    """
    if not current_actor.authorized_program_ids:
        return []
    async with request.app.state.pg_client.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT program_id, name FROM programs WHERE program_id = ANY($1::uuid[]) ORDER BY name",
            list(current_actor.authorized_program_ids),
        )
    return [ProgramItem(programId=str(r["program_id"]), name=r["name"]) for r in rows]


@app.post("/api/v1/programs/{program_id}/reports", status_code=202)
async def trigger_report(
    request: Request,
    program_id: str,
    _token=Depends(verify_service_token),
    current_actor: CurrentActor = Depends(get_current_actor),
) -> TriggerResponse:
    """LLD 2.1's real trigger contract, real now (Migration Plan Phase
    3): inserts a real `queued` row and returns immediately — execution
    happens in `worker/main.py`, entirely out of this request. Identity
    resolved the same real ADR-017 way as approve/reject/chat; see the
    module docstring for why this deviates from the LLD's literal
    body-supplied `requestedBy` field.

    Migration Plan Phase 8: three real, distinct new checks, in order —
    (1) Owner-tier only (`_require_owner`, real 403 for a visitor — this
    IS the actual enforcement of "a visitor role cannot trigger a run",
    not a hidden button); (2) the requested `program_id` must be in this
    actor's own resolved scope (real 404, indistinguishable from a
    program that doesn't exist, per the same no-existence-leak
    discipline as `ReportNotFoundError`); (3) FR-11's real rate limit
    (real 429 once exceeded).

    Real API-to-Reporting tracing (Phase 3's own bar, unaffected by the
    ADR-026 queue-driven trigger): captures the current active span's
    context (this route's own span, nested under whatever
    `tracing_middleware` already extracted from the BFF) as a real W3C
    traceparent via `opentelemetry.propagate.inject`, stored on the
    cycle row so Reporting can nest its own root span under this exact
    request — the same real mechanism Phase 2 already proved across the
    BFF-to-core-API hop, now proved a third time.

    ADR-026: after the real `cycles` INSERT, publishes a real, thin
    `report-cycles` message (`cycle_id` only) so the Reporting service
    can be woken from a real scaled-to-zero state — `cycles` itself
    stays the source of truth for program_name/requested_by_actor_id/
    trace_context, so nothing needs duplicating into the envelope.
    Real, disclosed, accepted gap: if the publish itself fails after the
    INSERT already committed, the cycle row is left `queued` with
    nothing to ever wake Reporting for it — no distributed transaction
    exists between Postgres and Storage Queues to prevent this, and no
    sweep/retry mechanism was built for it here, since it wasn't asked
    for and the failure window is real but narrow.
    """
    _require_owner(current_actor)
    _require_program_in_scope(current_actor, program_id)

    carrier: dict[str, str] = {}
    inject(carrier)
    trace_context = carrier.get("traceparent")

    async with request.app.state.pg_client.pool.acquire() as conn:
        await _check_rate_limit(conn, current_actor.actor_id)
        try:
            result = await create_cycle(conn, program_id, current_actor.actor_id, trace_context)
        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(status_code=404, detail={"error": "program_not_found"})

    await send_json_message(request.app.state.report_cycles_client, {"cycle_id": str(result["cycle_id"])})
    return TriggerResponse(cycleId=str(result["cycle_id"]), status=result["status"])


@app.get("/api/v1/cycles/{cycle_id}")
async def get_cycle_status(
    request: Request,
    cycle_id: str,
    _token=Depends(verify_service_token),
    current_actor: CurrentActor = Depends(get_current_actor),
) -> CycleStatusResponse:
    """ADR-021: the real polling read — answers from the database alone,
    regardless of which process (if any) is currently executing the
    cycle.

    Migration Plan Phase 8: now requires a real, resolved identity and
    program-scope check — a cycle's `stages` JSON can carry real report
    content (finding titles, counts) mid-run, so this is no longer
    treated as carrying nothing worth protecting. A cycle for a program
    outside the caller's scope reads as `404`, identical to a genuinely
    nonexistent `cycle_id` — no existence leak.
    """
    async with request.app.state.pg_client.pool.acquire() as conn:
        result = await get_cycle(conn, cycle_id)
    if result is None or str(result["program_id"]) not in current_actor.authorized_program_ids:
        raise HTTPException(status_code=404, detail={"error": "cycle_not_found"})
    return CycleStatusResponse(
        cycleId=str(result["cycle_id"]),
        status=result["status"],
        stages=result["stages"],
        reportId=result["report_id"],
        errorDetail=result["error_detail"],
        createdAt=result["created_at"].isoformat(),
        startedAt=result["started_at"].isoformat() if result["started_at"] else None,
        finishedAt=result["finished_at"].isoformat() if result["finished_at"] else None,
    )


@app.get("/api/v1/reviews/pending")
async def get_pending_reviews(
    request: Request,
    programId: str,
    _token=Depends(verify_service_token),
    current_actor: CurrentActor = Depends(get_current_actor),
) -> PendingReviewsResponse:
    """Migration Plan Phase 8: viewing pending reviews is allowed for
    both roles (a "view" action, not generate/approve) but still
    requires `programId` to be in the caller's own resolved scope —
    real 404 for a program outside it, same no-existence-leak framing
    as every other scope check in this file.
    """
    _require_program_in_scope(current_actor, programId)
    async with request.app.state.pg_client.pool.acquire() as conn:
        result = await list_pending_reviews(conn, programId, current_actor.tenant_id)
    return PendingReviewsResponse(**result)


@app.post("/api/v1/reviews/{report_id}/approve")
async def approve(
    request: Request,
    report_id: int,
    _token=Depends(verify_service_token),
    current_actor: CurrentActor = Depends(get_current_actor),
) -> ReviewDecisionResponse:
    """Real ADR-017 resolution: the real internal actor_id used for the
    approval is always looked up server-side, never accepted from the
    request.

    Migration Plan Phase 8: Owner-tier only (`_require_owner`); the
    report's own program must be in the caller's resolved scope, checked
    via the real, RLS-respecting `get_report_program_id` (a report
    outside the caller's tenant is already invisible to that query —
    this adds the finer program-level check RLS's tenant-only policy
    can't express, and gives a uniform, no-existence-leak 404 for both
    real "gone"/never-existed and real "not yours" cases).
    """
    _require_owner(current_actor)
    async with request.app.state.pg_client.pool.acquire() as conn:
        program_id = await get_report_program_id(conn, report_id, current_actor.tenant_id)
        if program_id is None or program_id not in current_actor.authorized_program_ids:
            raise HTTPException(status_code=404, detail={"error": "report_not_found"})
        try:
            result = await approve_report(conn, report_id, current_actor.actor_id, current_actor.tenant_id)
        except ReportNotFoundError:
            raise HTTPException(status_code=404, detail={"error": "report_not_found"})
    return ReviewDecisionResponse(**result)


@app.post("/api/v1/reviews/{report_id}/reject")
async def reject(
    request: Request,
    report_id: int,
    body: RejectRequest,
    _token=Depends(verify_service_token),
    current_actor: CurrentActor = Depends(get_current_actor),
) -> ReviewDecisionResponse:
    """Migration Plan Phase 8: same real Owner-tier + scope checks as
    `approve` — see its own docstring.
    """
    _require_owner(current_actor)
    async with request.app.state.pg_client.pool.acquire() as conn:
        program_id = await get_report_program_id(conn, report_id, current_actor.tenant_id)
        if program_id is None or program_id not in current_actor.authorized_program_ids:
            raise HTTPException(status_code=404, detail={"error": "report_not_found"})
        try:
            result = await reject_report(
                conn, report_id, current_actor.actor_id, current_actor.tenant_id, body.notes
            )
        except NotesRequiredError:
            raise HTTPException(status_code=400, detail={"error": "notes_required"})
        except ReportNotFoundError:
            raise HTTPException(status_code=404, detail={"error": "report_not_found"})
    return ReviewDecisionResponse(**result)


@app.get("/api/v1/reports")
async def get_reports(
    request: Request,
    programId: str | None = None,
    limit: int = 20,
    _token=Depends(verify_service_token),
    current_actor: CurrentActor = Depends(get_current_actor),
) -> list[ReportSummary]:
    """Migration Plan Phase 8: real tenant + program scoping. A given
    `programId` outside scope is a real 404 (no existence leak); with no
    `programId`, results are still narrowed to the caller's own resolved
    `authorized_program_ids` (RLS's tenant-only policy alone would show
    every program in the tenant, not just the ones this specific actor
    is scoped to).
    """
    if programId is not None:
        _require_program_in_scope(current_actor, programId)
    async with request.app.state.pg_client.pool.acquire() as conn:
        rows = await list_recent_reports(
            conn, current_actor.tenant_id, current_actor.authorized_program_ids, limit=limit, program_id=programId
        )
    return [
        ReportSummary(
            reportId=r["report_id"],
            programName=r["program_name"],
            weekOf=r["week_of"].isoformat(),
            ragStatus=r["rag_status"],
            qualityGateOutcome=r["quality_gate_outcome"],
            reviewed=r["reviewed"],
            renderedArtifactUri=r["rendered_artifact_uri"],
            createdAt=r["created_at"].isoformat(),
            decision=r["decision"],
            findingCount=r["finding_count"],
        )
        for r in rows
    ]


@app.get("/api/v1/reports/{report_id}")
async def get_report(
    request: Request,
    report_id: int,
    _token=Depends(verify_service_token),
    current_actor: CurrentActor = Depends(get_current_actor),
) -> ReportDetailResponse:
    """Migration Plan Phase 8: real tenant-scoped read (`get_report_
    detail` now sets `app.current_tenant_id`) plus the same
    program-level scope check every report_id-based route performs —
    both roles may view (no `_require_owner` here), within scope.
    """
    async with request.app.state.pg_client.pool.acquire() as conn:
        program_id = await get_report_program_id(conn, report_id, current_actor.tenant_id)
        if program_id is None or program_id not in current_actor.authorized_program_ids:
            raise HTTPException(status_code=404, detail={"error": "report_not_found"})
        result = await get_report_detail(conn, report_id, current_actor.tenant_id)
    if result["report"] is None:
        raise HTTPException(status_code=404, detail={"error": "report_not_found"})
    r = result["report"]
    return ReportDetailResponse(
        report=ReportDetail(
            reportId=r["report_id"],
            programName=r["program_name"],
            weekOf=r["week_of"].isoformat(),
            ragStatus=r["rag_status"],
            qualityGateOutcome=r["quality_gate_outcome"],
            executiveSummary=r["executive_summary"],
            renderedArtifactUri=r["rendered_artifact_uri"],
            reviewed=r["reviewed"],
        ),
        findings=[
            FindingItem(
                findingId=f["finding_id"],
                sourceItemRef=f["source_item_ref"],
                title=f["title"],
                statusLabel=f["status_label"],
                evidence=f["evidence"],
            )
            for f in result["findings"]
        ],
        untrackedItems=[
            UntrackedItemModel(
                untrackedItemId=u["untracked_item_id"],
                description=u["description"],
                evidence=u["evidence"],
                possibleLinkedFindingId=u["possible_linked_finding_id"],
                reasoning=u["reasoning"],
            )
            for u in result["untracked_items"]
        ],
    )


@app.get("/api/v1/reports/{report_id}/download")
async def download_report(
    request: Request,
    report_id: int,
    _token=Depends(verify_service_token),
    current_actor: CurrentActor = Depends(get_current_actor),
) -> DownloadResponse:
    """Migration Plan Phase 8 (ADR-021/027): the real, working SAS
    mechanism ADR-021 designed but never built until this bar-for-done
    required it — a visitor role cannot retrieve a SAS for a report
    outside its scope; this route is what that sentence actually means.

    Authorization happens BEFORE issuance, per ADR-021's own stated
    constraint (`get_report_download_info` is real, tenant-scoped RLS;
    the program-membership check is the finer half). Both roles may
    download within scope (view is a Visitor capability) — no
    `_require_owner` here. A report whose `rendered_artifact_uri` isn't
    a real `blob://` URI (every report rendered before this phase, and
    any rendered since without a real blob upload) has no SAS-
    downloadable artifact — a real, honest `404`, not a broken link.
    """
    async with request.app.state.pg_client.pool.acquire() as conn:
        info = await get_report_download_info(conn, report_id, current_actor.tenant_id)
    if info is None or info["program_id"] not in current_actor.authorized_program_ids:
        raise HTTPException(status_code=404, detail={"error": "report_not_found"})

    parsed = parse_blob_uri(info["rendered_artifact_uri"]) if info["rendered_artifact_uri"] else None
    if parsed is None:
        raise HTTPException(status_code=404, detail={"error": "artifact_not_available"})
    container, blob_name = parsed

    sas_url = await issue_download_sas(request.app.state.async_credential, container, blob_name)
    return DownloadResponse(downloadUrl=sas_url, expiresInMinutes=5)


@app.post("/api/v1/chat/query")
async def chat_query(
    request: Request,
    body: ChatQueryRequest,
    _token=Depends(verify_service_token),
    current_actor: CurrentActor = Depends(get_current_actor),
) -> ChatQueryResponse:
    """Migration Plan Phase 8 (ADR-022/027): the real, mandatory
    server-side retrieval filter LLD Section 2.3 always required —
    `current_actor.authorized_program_ids` is passed to `ask_question`
    unconditionally, so the model is never even shown a chunk from a
    program outside the caller's scope (filtering an already-generated
    answer would be too late). A caller-supplied `programId` narrows
    within that already-authorized set; one outside it is a real 404,
    the same no-existence-leak framing as every other scope check here.
    Both roles may chat within scope — no `_require_owner`.
    """
    if body.programId is not None:
        _require_program_in_scope(current_actor, body.programId)

    state = request.app.state
    result = await ask_question(
        state.chat_client,
        state.search_client,
        state.embedding_client,
        body.question,
        current_actor.authorized_program_ids,
        body.programId,
    )
    return ChatQueryResponse(
        answer=result["answer"],
        citations=[
            Citation(
                reportId=c["report_id"],
                programName=c["program_name"],
                weekOf=c["week_of"],
                sourceItemRef=c["source_item_ref"],
                findingTitle=c["finding_title"],
            )
            for c in result["citations"]
        ],
    )
