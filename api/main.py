"""OnePulse API — Migration Plan Phase 1 (LLD Section 2's endpoint
contract, never built until now; ADR-015's real, direct justification).

Real scope, three decisions made explicitly rather than left as buried
assumptions — see CLAUDE.md Task 40 for the full reasoning behind each,
and treat all three as adjustable defaults, not fixed constraints:

1. NO report-trigger endpoint in this phase. LLD 2.1's `POST
   /api/v1/programs/{programId}/reports` returns `202` with a cycle
   handle — that only becomes real in Phase 3, once execution moves to a
   worker with a real status table behind it (ADR-021). An in-memory
   cycle registry built now would be pure throwaway work. Streamlit
   keeps calling `run_pipeline_cycle` directly for generation until then.
2. NO authentication in this phase. `actorId` is a trusted request
   field, exactly as it is today in `scripts/review_cli.py` and
   `Home.py`. Real reviewer identity is Phase 8, and gates public
   ingress (Migration Plan, ADR-018) — inventing an interim auth scheme
   here would just be something Phase 8 has to unpick.
3. `onepulse_common` is NOT modified. Every route below wraps an
   already-proven function; none of their own signatures or behavior
   changed to get here. Pydantic models mirror constraints the database
   already enforces (the real four-level `findings.status_label`
   taxonomy; non-empty rejection notes, matching the real
   `approval_records_rejected_notes_required` CHECK added this same
   task) — so a violation fails at this edge *as well as* at the
   database, never *instead of* it; both layers are proven directly, not
   assumed from each other (see the bar-for-done evidence in Task 40).

One connection pattern, deliberately kept honest rather than smoothed
over: `human_governance.py`'s functions all take a `conn` they don't
open themselves — this app opens one real, long-lived pool at startup
(the lifespan below) and acquires from it per request, which is the
correct pattern for a long-lived service (unlike Streamlit's
open-a-connection-per-rerun `with_connection` helper, which exists
specifically because Streamlit has no persistent process to hold a pool
in). `onepulse_common.pipeline.list_recent_reports`, by contrast, opens
and closes its own dedicated one-shot connection internally on every
call — a real, pre-existing inconsistency in `onepulse_common` this
phase's own constraint (do not modify it) means living with, not fixing
here.

Not wired in this phase, deliberately: the dual Application
Insights/Arize observability every CLI agentic entry point carries.
Not asked for, and Phase 2's BFF/core-API split changes the process
boundary anyway — wiring it now risks doing it twice.

Run: uvicorn api.main:app --reload --port 8000 (from the repo root, same
CWD convention as every other script in this project).
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Literal

import asyncpg
from azure.identity import DefaultAzureCredential
from agent_framework.foundry import FoundryChatClient
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

from onepulse_common.chat_assistant import ask_question
from onepulse_common.config import PostgresSettings
from onepulse_common.db import PostgresClient
from onepulse_common.embeddings import build_embedding_client
from onepulse_common.human_governance import (
    ActorIdRequiredError,
    NotesRequiredError,
    approve_report,
    get_report_detail,
    list_pending_reviews,
    reject_report,
)
from onepulse_common.pipeline import list_recent_reports
from onepulse_common.search_index import build_search_client

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Every real client this service needs, constructed once and reused
    across requests — not once per call, matching a long-lived service
    rather than Streamlit's per-rerun reconstruction.
    """
    pg_client = await PostgresClient.connect(PG_SETTINGS, min_size=1, max_size=5)
    credential = DefaultAzureCredential()
    search_client = build_search_client(credential)
    embedding_client = build_embedding_client(credential)
    chat_client = FoundryChatClient(project_endpoint=PROJECT_ENDPOINT, model=DEPLOYMENT_NAME, credential=credential)

    app.state.pg_client = pg_client
    app.state.search_client = search_client
    app.state.embedding_client = embedding_client
    app.state.chat_client = chat_client

    try:
        yield
    finally:
        await pg_client.close()
        await search_client.close()
        await embedding_client.close()


app = FastAPI(title="OnePulse API", version="0.1.0", lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """LLD 2.2's real, specified error shape for a rejection with empty
    notes is `400 { "error": "notes_required" }`, not FastAPI's default
    `422` validation-error body. RejectRequest's own field_validator
    (below) raises exactly this on empty/whitespace-only notes — this
    handler recognizes that specific case by which field failed and
    reshapes the response to match the real contract; `actorId`'s own
    validator gets the same treatment for consistency. Any other
    validation failure keeps FastAPI's normal 422 behavior, using
    `jsonable_encoder` rather than passing `exc.errors()` to
    `JSONResponse` directly — a real bug found live: Pydantic's own
    error dicts carry the raw exception object under `ctx`, which
    `json.dumps` cannot serialize on its own (confirmed live: a bare
    empty actorId crashed this handler with `TypeError: Object of type
    ValueError is not JSON serializable` before this fix).
    """
    for err in exc.errors():
        loc = err.get("loc", ())
        if loc and loc[-1] == "notes":
            return JSONResponse(status_code=400, content={"error": "notes_required"})
        if loc and loc[-1] == "actorId":
            return JSONResponse(status_code=400, content={"error": "actor_id_required"})
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(exc.errors())})


# ---------------------------------------------------------------------
# Pydantic models — request bodies validate at the edge; response models
# mirror the real column-level constraints the database already
# enforces (Literal types for the real CHECK-constrained taxonomies),
# not because Pydantic is a substitute for those CHECKs, but so a
# genuine mismatch is caught here too, not only much further downstream.
# ---------------------------------------------------------------------

RagStatus = Literal["Red", "Amber", "Green", "Unknown"]
QualityGateOutcome = Literal["approved", "route_to_human_review"]
StatusLabel = Literal["On Track", "At Risk", "Blocked", "Needs Human Review"]
Decision = Literal["approved", "rejected"]


class ApproveRequest(BaseModel):
    actorId: str

    @field_validator("actorId")
    @classmethod
    def actor_id_must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("actor_id_required")
        return v


class RejectRequest(BaseModel):
    actorId: str
    notes: str

    @field_validator("actorId")
    @classmethod
    def actor_id_must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("actor_id_required")
        return v

    @field_validator("notes")
    @classmethod
    def notes_must_not_be_empty(cls, v: str) -> str:
        # Mirrors the real approval_records_rejected_notes_required CHECK
        # (migration 0002: decision != 'rejected' OR length(trim(notes)) > 0)
        # — same "empty after trim" definition, at the edge as well.
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
    actorId: str
    question: str
    programId: str | None = None

    @field_validator("actorId")
    @classmethod
    def actor_id_must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("actor_id_required")
        return v

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
# Routes
# ---------------------------------------------------------------------


@app.get("/api/v1/programs")
async def list_programs(request: Request) -> list[ProgramItem]:
    """Not in LLD 2's literal contract — added because every other route
    below needs a real programId, and nothing else in this API exposes
    how to find one. Wraps the same real `programs` table Home.py's own
    project selector already reads.
    """
    async with request.app.state.pg_client.pool.acquire() as conn:
        rows = await conn.fetch("SELECT program_id, name FROM programs ORDER BY name")
    return [ProgramItem(programId=str(r["program_id"]), name=r["name"]) for r in rows]


@app.get("/api/v1/reviews/pending")
async def get_pending_reviews(request: Request, programId: str) -> PendingReviewsResponse:
    """LLD 2.2: GET /api/v1/reviews/pending?programId={programId}."""
    async with request.app.state.pg_client.pool.acquire() as conn:
        result = await list_pending_reviews(conn, programId)
    return PendingReviewsResponse(**result)


@app.post("/api/v1/reviews/{report_id}/approve")
async def approve(request: Request, report_id: int, body: ApproveRequest) -> ReviewDecisionResponse:
    """LLD 2.2: POST /api/v1/reviews/{reportId}/approve."""
    async with request.app.state.pg_client.pool.acquire() as conn:
        try:
            result = await approve_report(conn, report_id, body.actorId)
        except ActorIdRequiredError:
            raise HTTPException(status_code=400, detail={"error": "actor_id_required"})
        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(status_code=404, detail={"error": "report_not_found"})
    return ReviewDecisionResponse(**result)


@app.post("/api/v1/reviews/{report_id}/reject")
async def reject(request: Request, report_id: int, body: RejectRequest) -> ReviewDecisionResponse:
    """LLD 2.2: POST /api/v1/reviews/{reportId}/reject. 400 notes_required
    on empty notes — RejectRequest's own field_validator already catches
    this before the handler runs (see the RequestValidationError handler
    above for the response-shape mapping); the NotesRequiredError catch
    here is real defense in depth, not the primary path, for the same
    reason `reject_report` keeps its own internal check regardless of
    what calls it.
    """
    async with request.app.state.pg_client.pool.acquire() as conn:
        try:
            result = await reject_report(conn, report_id, body.actorId, body.notes)
        except NotesRequiredError:
            raise HTTPException(status_code=400, detail={"error": "notes_required"})
        except ActorIdRequiredError:
            raise HTTPException(status_code=400, detail={"error": "actor_id_required"})
        except asyncpg.exceptions.ForeignKeyViolationError:
            raise HTTPException(status_code=404, detail={"error": "report_not_found"})
    return ReviewDecisionResponse(**result)


@app.get("/api/v1/reports")
async def get_reports(programId: str | None = None, limit: int = 20) -> list[ReportSummary]:
    """Not in LLD 2's literal contract — the real report history view
    Home.py's "Previous Status Reports" panel already needs. Wraps
    `list_recent_reports` unchanged; that function manages its own
    connection internally (see module docstring).
    """
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
async def get_report(request: Request, report_id: int) -> ReportDetailResponse:
    """Not in LLD 2's literal contract — FR-13's "preview a fully
    rendered report" requirement, already served by
    `get_report_detail`. 404 when the report genuinely doesn't exist,
    matching REST convention — `get_report_detail` itself returns
    `report: None` rather than raising, so that translation happens here.
    """
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
async def chat_query(request: Request, body: ChatQueryRequest) -> ChatQueryResponse:
    """LLD 2.3: POST /api/v1/chat/query. `programId` is accepted directly
    as a filter, the same real, explicitly-flagged shortcut
    `ask_question` itself already documents (real server-side
    `actor_scope` resolution is Phase 8 work, not built anywhere yet) —
    not invented at this edge, just passed through unchanged.
    """
    state = request.app.state
    result = await ask_question(
        state.chat_client, state.search_client, state.embedding_client, body.question, body.programId
    )
    # ask_question's real CHAT_SCHEMA returns snake_case citation keys
    # (report_id, program_name, week_of, source_item_ref, finding_title)
    # — mapped explicitly here, same as every other route, rather than
    # assuming Pydantic's **result would line up with the camelCase
    # response contract.
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
