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

Three Phase 1 decisions still hold, unchanged, restated so they aren't
lost in the split (see the superseded `api/main.py`'s own docstring,
Task 40, for the full original reasoning): no report-trigger endpoint
(Phase 3); still no *reviewer* authentication (Phase 8) — what Phase 2
adds is *service* authentication (proving the caller is really the
BFF) and real identity *resolution* (turning a forwarded object ID into
a real actor), neither of which is reviewer auth; `onepulse_common` is
not modified by this file's own routes.

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
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from opentelemetry import trace
from opentelemetry.propagate import extract
from pydantic import BaseModel, field_validator

from core_api.security import ActorNotFoundError, get_entra_object_id, resolve_actor, verify_service_token
from onepulse_common.chat_assistant import ask_question
from onepulse_common.config import PostgresSettings
from onepulse_common.db import PostgresClient
from onepulse_common.embeddings import build_embedding_client
from onepulse_common.human_governance import (
    NotesRequiredError,
    approve_report,
    get_report_detail,
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

_tracer = trace.get_tracer(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    pg_client = await PostgresClient.connect(PG_SETTINGS, min_size=1, max_size=5)
    credential = DefaultAzureCredential()
    search_client = build_search_client(credential)
    embedding_client = build_embedding_client(credential)
    chat_client = FoundryChatClient(project_endpoint=PROJECT_ENDPOINT, model=DEPLOYMENT_NAME, credential=credential)

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

    try:
        yield
    finally:
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


# ---------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------

RagStatus = Literal["Red", "Amber", "Green", "Unknown"]
QualityGateOutcome = Literal["approved", "route_to_human_review"]
StatusLabel = Literal["On Track", "At Risk", "Blocked", "Needs Human Review"]
Decision = Literal["approved", "rejected"]


class RejectRequest(BaseModel):
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


@app.get("/api/v1/programs")
async def list_programs(request: Request, _token=Depends(verify_service_token)) -> list[ProgramItem]:
    async with request.app.state.pg_client.pool.acquire() as conn:
        rows = await conn.fetch("SELECT program_id, name FROM programs ORDER BY name")
    return [ProgramItem(programId=str(r["program_id"]), name=r["name"]) for r in rows]


@app.get("/api/v1/reviews/pending")
async def get_pending_reviews(
    request: Request, programId: str, _token=Depends(verify_service_token)
) -> PendingReviewsResponse:
    async with request.app.state.pg_client.pool.acquire() as conn:
        result = await list_pending_reviews(conn, programId)
    return PendingReviewsResponse(**result)


@app.post("/api/v1/reviews/{report_id}/approve")
async def approve(
    request: Request,
    report_id: int,
    _token=Depends(verify_service_token),
    entra_object_id: str = Depends(get_entra_object_id),
) -> ReviewDecisionResponse:
    """Real ADR-017 resolution: the caller (BFF) supplies only an Entra
    object ID; the real internal actor_id used for the approval is
    always looked up here, never accepted from the request.
    """
    async with request.app.state.pg_client.pool.acquire() as conn:
        try:
            actor = await resolve_actor(conn, entra_object_id)
        except ActorNotFoundError:
            raise HTTPException(status_code=401, detail={"error": "actor_not_found"})
        try:
            result = await approve_report(conn, report_id, str(actor["actor_id"]))
        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(status_code=404, detail={"error": "report_not_found"})
    return ReviewDecisionResponse(**result)


@app.post("/api/v1/reviews/{report_id}/reject")
async def reject(
    request: Request,
    report_id: int,
    body: RejectRequest,
    _token=Depends(verify_service_token),
    entra_object_id: str = Depends(get_entra_object_id),
) -> ReviewDecisionResponse:
    async with request.app.state.pg_client.pool.acquire() as conn:
        try:
            actor = await resolve_actor(conn, entra_object_id)
        except ActorNotFoundError:
            raise HTTPException(status_code=401, detail={"error": "actor_not_found"})
        try:
            result = await reject_report(conn, report_id, str(actor["actor_id"]), body.notes)
        except NotesRequiredError:
            raise HTTPException(status_code=400, detail={"error": "notes_required"})
        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(status_code=404, detail={"error": "report_not_found"})
    return ReviewDecisionResponse(**result)


@app.get("/api/v1/reports")
async def get_reports(
    programId: str | None = None, limit: int = 20, _token=Depends(verify_service_token)
) -> list[ReportSummary]:
    rows = await list_recent_reports(limit=limit, program_id=programId)
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
    request: Request, report_id: int, _token=Depends(verify_service_token)
) -> ReportDetailResponse:
    async with request.app.state.pg_client.pool.acquire() as conn:
        result = await get_report_detail(conn, report_id)
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


@app.post("/api/v1/chat/query")
async def chat_query(
    request: Request,
    body: ChatQueryRequest,
    _token=Depends(verify_service_token),
    entra_object_id: str = Depends(get_entra_object_id),
) -> ChatQueryResponse:
    """`entra_object_id` is resolved for real (proving the identity is
    real and known) but not yet used to scope retrieval — the same
    real, already-documented shortcut `ask_question` itself states
    (`actor_scope` resolution is Phase 8 work). Resolving it here now,
    even unused for scoping yet, means Phase 8 only has to change what
    this does with the result, not add the resolution step itself.
    """
    async with request.app.state.pg_client.pool.acquire() as conn:
        try:
            await resolve_actor(conn, entra_object_id)
        except ActorNotFoundError:
            raise HTTPException(status_code=401, detail={"error": "actor_not_found"})

    state = request.app.state
    result = await ask_question(
        state.chat_client, state.search_client, state.embedding_client, body.question, body.programId
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
