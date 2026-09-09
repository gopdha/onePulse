"""OnePulse BFF — Migration Plan Phase 2 (ADR-017): session, identity
resolution, and response shaping for the frontend. Owns **no data
stores** — this file, and everything it imports, must never be able to
reach Postgres, Azure AI Search, or Foundry, "not even for one
convenient query." That boundary is enforced structurally here, not by
discipline: grep this file's own imports (and see
`tests/test_bff_no_data_access.py`, which asserts it automatically) —
there is no `onepulse_common.db`, `onepulse_common.search_index`,
`onepulse_common.embeddings`, `onepulse_common.chat_assistant`,
`onepulse_common.pipeline`, `onepulse_common.human_governance`, or
`asyncpg` import anywhere in this module's own source. The one
Azure-facing import here (`azure.identity`) is for acquiring this
service's own outbound service-to-service token, not for reaching any
data store. Real observability is `bff/observability.py`, deliberately
not `onepulse_common.observability` — see its own docstring for why
(that function itself makes a real Foundry call).

ADR-017's open question, now answered: the core API resolves identity,
never accepts an internal `actor_id`. This service's real job is
narrower — determine *who is asking* (today, always a stubbed Entra
object ID; a real session is Phase 8) and forward that, plus a real
service-to-service token, to the core API on every request. It never
decides *what that identity may do* — that's the core API's job,
because it's the component that owns the data the answer depends on.

Response shaping: every route below proxies the identical real
camelCase JSON shape `core_api/main.py` already returns — the frontend
contract Phase 1 established. There is nothing left to reshape today
(no example of the BFF needing a materially different view of the same
data has come up yet); this file is where that would happen if one did,
not a promise that reshaping is currently happening.

Run: uvicorn bff.main:app --port 8100 (from the repo root). Requires
core_api running first (`uvicorn core_api.main:app --port 8000`) — see
the Runbook.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

import httpx
from azure.identity.aio import DefaultAzureCredential
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from opentelemetry import trace
from opentelemetry.propagate import inject

from bff.observability import ARIZE_PROJECT_NAME, enable_bff_observability
from trace_debug import enable_debug_span_log

load_dotenv()

CORE_API_BASE_URL = os.environ.get("ONEPULSE_CORE_API_BASE_URL", "http://127.0.0.1:8000")
CORE_API_IDENTIFIER_URI = os.environ.get("ONEPULSE_CORE_API_IDENTIFIER_URI", "")
STUB_ENTRA_OBJECT_ID = os.environ.get("ONEPULSE_STUB_ENTRA_OBJECT_ID", "local-dev-standin-reviewer")

_tracer = trace.get_tracer(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    credential = DefaultAzureCredential()
    http_client = httpx.AsyncClient(base_url=CORE_API_BASE_URL, timeout=120.0)

    arize_space_id = enable_bff_observability()
    enable_debug_span_log("bff")

    app.state.credential = credential
    app.state.http_client = http_client
    app.state.arize_space_id = arize_space_id

    try:
        yield
    finally:
        await http_client.aclose()
        await credential.close()
        trace.get_tracer_provider().force_flush(timeout_millis=30000)


app = FastAPI(title="OnePulse BFF", version="0.1.0", lifespan=lifespan)


async def _core_headers(request: Request) -> dict:
    """Every real header this service asserts on the caller's behalf:
    a real Entra token for the core API's own app registration (service
    auth — proves this really is the BFF, not a shared secret and not a
    trusted-by-convention header), the real (stubbed, pending Phase 8)
    identity, and a real injected W3C `traceparent` derived from the
    *current* active span (set by `tracing_middleware` below, already
    running by the time any route handler calls this).
    """
    token = await request.app.state.credential.get_token(f"{CORE_API_IDENTIFIER_URI}/.default")
    headers = {
        "Authorization": f"Bearer {token.token}",
        "X-Onepulse-Entra-Object-Id": STUB_ENTRA_OBJECT_ID,
    }
    inject(headers)  # adds traceparent (+ tracestate) for the current span
    return headers


@app.middleware("http")
async def tracing_middleware(request: Request, call_next):
    """This service's own root span per real incoming request — the
    real start of every trace this migration is being asked to prove
    stays connected across the HTTP hop into the core API. No incoming
    `traceparent` is extracted here (Streamlit itself does not
    participate in W3C trace propagation) — this genuinely is the root.
    """
    from arize.otel import set_routing_context

    with set_routing_context(space_id=app.state.arize_space_id, project_name=ARIZE_PROJECT_NAME):
        with _tracer.start_as_current_span(f"bff {request.method} {request.url.path}") as span:
            span.set_attribute("http.method", request.method)
            span.set_attribute("http.target", request.url.path)
            response = await call_next(request)
            span.set_attribute("http.status_code", response.status_code)
    return response


def _proxy_response(upstream: httpx.Response) -> Response:
    return Response(content=upstream.content, status_code=upstream.status_code, media_type="application/json")


# ---------------------------------------------------------------------
# Routes — identical real paths and response shapes to core_api/main.py
# (Streamlit's own api_client.py needs no change beyond which base URL
# it targets). Every one forwards a real service token + the real
# (stubbed) identity; none of them touch a data store directly.
# ---------------------------------------------------------------------


@app.get("/api/v1/programs")
async def list_programs(request: Request) -> Response:
    headers = await _core_headers(request)
    resp = await request.app.state.http_client.get("/api/v1/programs", headers=headers)
    return _proxy_response(resp)


@app.post("/api/v1/programs/{program_id}/reports")
async def trigger_report(request: Request, program_id: str) -> Response:
    """Migration Plan Phase 3: proxies the real trigger endpoint. No
    request body forwarded — identity travels via the same real header
    _core_headers() already sets on every route (see core_api/main.py's
    own docstring for why this deviates from the LLD's literal
    body-supplied requestedBy field). The real `202` status the core API
    returns is preserved as-is by _proxy_response, not silently
    rewritten to `200`.
    """
    headers = await _core_headers(request)
    resp = await request.app.state.http_client.post(
        f"/api/v1/programs/{program_id}/reports", headers=headers
    )
    return _proxy_response(resp)


@app.get("/api/v1/cycles/{cycle_id}")
async def get_cycle_status(request: Request, cycle_id: str) -> Response:
    headers = await _core_headers(request)
    resp = await request.app.state.http_client.get(f"/api/v1/cycles/{cycle_id}", headers=headers)
    return _proxy_response(resp)


@app.get("/api/v1/reviews/pending")
async def get_pending_reviews(request: Request, programId: str) -> Response:
    headers = await _core_headers(request)
    resp = await request.app.state.http_client.get(
        "/api/v1/reviews/pending", params={"programId": programId}, headers=headers
    )
    return _proxy_response(resp)


@app.post("/api/v1/reviews/{report_id}/approve")
async def approve(request: Request, report_id: int) -> Response:
    headers = await _core_headers(request)
    resp = await request.app.state.http_client.post(
        f"/api/v1/reviews/{report_id}/approve", headers=headers
    )
    return _proxy_response(resp)


@app.post("/api/v1/reviews/{report_id}/reject")
async def reject(request: Request, report_id: int) -> Response:
    body = await request.json()
    headers = await _core_headers(request)
    resp = await request.app.state.http_client.post(
        f"/api/v1/reviews/{report_id}/reject", json={"notes": body.get("notes", "")}, headers=headers
    )
    return _proxy_response(resp)


@app.get("/api/v1/reports")
async def get_reports(request: Request, programId: str | None = None, limit: int = 20) -> Response:
    headers = await _core_headers(request)
    params: dict = {"limit": limit}
    if programId is not None:
        params["programId"] = programId
    resp = await request.app.state.http_client.get("/api/v1/reports", params=params, headers=headers)
    return _proxy_response(resp)


@app.get("/api/v1/reports/{report_id}")
async def get_report(request: Request, report_id: int) -> Response:
    headers = await _core_headers(request)
    resp = await request.app.state.http_client.get(f"/api/v1/reports/{report_id}", headers=headers)
    return _proxy_response(resp)


@app.post("/api/v1/chat/query")
async def chat_query(request: Request) -> Response:
    body = await request.json()
    headers = await _core_headers(request)
    resp = await request.app.state.http_client.post(
        "/api/v1/chat/query",
        json={"question": body.get("question", ""), "programId": body.get("programId")},
        headers=headers,
    )
    return _proxy_response(resp)
