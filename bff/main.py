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
narrower — determine *who is asking* and forward that, plus a real
service-to-service token, to the core API on every request. It never
decides *what that identity may do* — that's the core API's job,
because it's the component that owns the data the answer depends on.

Migration Plan Phase 8: *who is asking* is now real. Container Apps'
built-in Entra auth (Easy Auth, Phase 7) injects the platform-verified
signed-in user's claims into every request that reaches this service via
the real `X-MS-CLIENT-PRINCIPAL` header (base64-encoded JSON, the same
real mechanism App Service Easy Auth uses) — `_resolve_entra_object_id`
decodes it and extracts the real `objectidentifier` claim. Only for
local dev, where no Easy Auth sits in front of this service at all, does
the stub (`ONEPULSE_STUB_ENTRA_OBJECT_ID`) still apply — a real,
deliberate fallback for exactly that one case, not a live shortcut.

Response shaping: every route below proxies the identical real
camelCase JSON shape `core_api/main.py` already returns — the frontend
contract Phase 1 established. There is nothing left to reshape today
(no example of the BFF needing a materially different view of the same
data has come up yet); this file is where that would happen if one did,
not a promise that reshaping is currently happening.

Migration Plan Phase 9: this service now also serves the real React
build (`frontend/dist`, `StaticFiles` mount at the bottom of this file)
from this exact origin — a real, live-checked finding, not a design
preference, forced by how Easy Auth actually behaves: it intercepts
every request, including CORS preflight OPTIONS, before this app's own
code ever runs, and its own unauthenticated 401 carries no CORS headers
at all. That defeats every credentialed, preflight-requiring
cross-origin POST (trigger/approve/reject/chat, every one of which
sends a JSON body) regardless of sign-in state — no CORSMiddleware
inside this app can fix it, because Easy Auth sits in front of it, not
behind it. Same-origin serving sidesteps the problem entirely: one real
browser session cookie, one real origin, no preflight involved. This is
genuinely what Migration Plan Phase 10 formalizes (build/deploy
pipeline, cache headers); this is its minimal version, built here
because real Phase 9 end-to-end verification needed it, not a claim
that Phase 10 itself is done.

Run: uvicorn bff.main:app --port 8100 (from the repo root). Requires
core_api running first (`uvicorn core_api.main:app --port 8000`) — see
the Runbook.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
from contextlib import asynccontextmanager

import httpx
from azure.identity.aio import DefaultAzureCredential
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from opentelemetry import trace
from opentelemetry.propagate import inject

from bff.observability import ARIZE_PROJECT_NAME, enable_bff_observability
from trace_debug import enable_debug_span_log

load_dotenv()

CORE_API_BASE_URL = os.environ.get("ONEPULSE_CORE_API_BASE_URL", "http://127.0.0.1:8000")
CORE_API_IDENTIFIER_URI = os.environ.get("ONEPULSE_CORE_API_IDENTIFIER_URI", "")

# Migration Plan Phase 9: real, live-checked finding, not assumed — a
# cross-origin CORS approach (dev server on one origin, this service on
# another, browser fetches with `credentials: "include"`) was tried
# first and found structurally broken: Container Apps' own Easy Auth
# intercepts every request, including CORS preflight OPTIONS, BEFORE it
# ever reaches this app's own code — an unauthenticated preflight gets a
# bare 401 with no Access-Control-* headers at all, since Easy Auth has
# no CORS awareness of its own. That defeats every credentialed,
# preflight-requiring cross-origin request (every real POST this app
# makes — trigger/approve/reject/chat all send a JSON body) regardless
# of sign-in state; CORSMiddleware inside this app can never run early
# enough to fix it, because Easy Auth sits in front of this app, not
# behind it. The real, working fix is same-origin serving — see the
# `StaticFiles` mount at the bottom of this file, which is genuinely
# what Migration Plan Phase 10 formalizes; this is the minimal version
# of it, built here because real end-to-end verification needed it now.
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


_OID_CLAIM_TYPES = frozenset(
    {"http://schemas.microsoft.com/identity/claims/objectidentifier", "oid"}
)


def _resolve_entra_object_id(request: Request) -> str:
    """Migration Plan Phase 8: the real, platform-verified signed-in
    identity, from Easy Auth's own `X-MS-CLIENT-PRINCIPAL` header when
    present (a real request that passed through Container Apps' Entra
    auth layer) — decoded here, not trusted as an opaque string, since
    only the real `objectidentifier` claim inside it is what `core_api`
    needs. Falls back to the local-dev stub only when this header is
    genuinely absent (no Easy Auth in front of this process at all,
    e.g. `docker compose`/bare `uvicorn`) — never when it's present but
    malformed, which is a real, distinct failure worth its own error
    rather than a silent, wrong fallback to another identity.
    """
    raw = request.headers.get("X-MS-CLIENT-PRINCIPAL")
    if raw is None:
        return STUB_ENTRA_OBJECT_ID
    try:
        principal = json.loads(base64.b64decode(raw))
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise ValueError(f"X-MS-CLIENT-PRINCIPAL present but not valid base64 JSON: {exc}") from exc
    for claim in principal.get("claims", []):
        if claim.get("typ") in _OID_CLAIM_TYPES:
            return claim["val"]
    raise ValueError("X-MS-CLIENT-PRINCIPAL present but carries no objectidentifier claim")


async def _core_headers(request: Request) -> dict:
    """Every real header this service asserts on the caller's behalf:
    a real Entra token for the core API's own app registration (service
    auth — proves this really is the BFF, not a shared secret and not a
    trusted-by-convention header), the real signed-in identity (Migration
    Plan Phase 8 — see `_resolve_entra_object_id`), and a real injected
    W3C `traceparent` derived from the *current* active span (set by
    `tracing_middleware` below, already running by the time any route
    handler calls this).
    """
    token = await request.app.state.credential.get_token(f"{CORE_API_IDENTIFIER_URI}/.default")
    headers = {
        "Authorization": f"Bearer {token.token}",
        "X-Onepulse-Entra-Object-Id": _resolve_entra_object_id(request),
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


@app.get("/api/v1/me")
async def get_me(request: Request) -> Response:
    headers = await _core_headers(request)
    resp = await request.app.state.http_client.get("/api/v1/me", headers=headers)
    return _proxy_response(resp)


@app.get("/api/v1/programs")
async def list_programs(request: Request) -> Response:
    headers = await _core_headers(request)
    resp = await request.app.state.http_client.get("/api/v1/programs", headers=headers)
    return _proxy_response(resp)


@app.get("/api/v1/programs/{program_id}/reports/this-week")
async def get_this_week_status(request: Request, program_id: str) -> Response:
    """Task 56: proxies the real pre-click collision check."""
    headers = await _core_headers(request)
    resp = await request.app.state.http_client.get(
        f"/api/v1/programs/{program_id}/reports/this-week", headers=headers
    )
    return _proxy_response(resp)


@app.post("/api/v1/programs/{program_id}/reports")
async def trigger_report(request: Request, program_id: str, force: bool = False) -> Response:
    """Migration Plan Phase 3: proxies the real trigger endpoint. No
    request body forwarded — identity travels via the same real header
    _core_headers() already sets on every route (see core_api/main.py's
    own docstring for why this deviates from the LLD's literal
    body-supplied requestedBy field). The real `202` status the core API
    returns is preserved as-is by _proxy_response, not silently
    rewritten to `200`.

    `force` (Task 55): forwarded as-is — core_api's own `_require_owner`
    is the real enforcement for who can use it, not anything checked
    here.
    """
    headers = await _core_headers(request)
    resp = await request.app.state.http_client.post(
        f"/api/v1/programs/{program_id}/reports", headers=headers, params={"force": force}
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


@app.get("/api/v1/reports/{report_id}/download")
async def download_report(request: Request, report_id: int) -> Response:
    """Migration Plan Phase 9: a real, previously-unnoticed gap closed —
    core_api's own real SAS download route (Phase 8, ADR-021) never had
    a BFF proxy, since nothing reachable only through the BFF (the real
    React frontend didn't exist yet) had needed it. Phase 8's own SAS
    verification reached core_api directly (its own internal-only
    ingress, reachable via `az containerapp exec`) — the real gap only
    surfaced once a real browser client, which can only ever reach the
    BFF's public ingress, needed this specific call.
    """
    headers = await _core_headers(request)
    resp = await request.app.state.http_client.get(f"/api/v1/reports/{report_id}/download", headers=headers)
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


# ---------------------------------------------------------------------
# The real React build, served from this exact origin — see the module
# docstring's own real finding for why this exists in Phase 9 rather
# than waiting for Phase 10: cross-origin CORS cannot work here at all,
# since Easy Auth intercepts and 401s every preflight OPTIONS request
# before this app's own code ever runs, defeating every credentialed
# POST regardless of sign-in state. Serving same-origin sidesteps the
# problem entirely — no preflight, no cross-site cookie question, the
# browser just has one real session cookie for one real origin. Must
# stay the LAST route registered: FastAPI/Starlette match routes in
# registration order, and a mount at "/" would otherwise shadow every
# `/api/v1/...` route above it. `html=True` serves `index.html` for any
# path that isn't a real static file — the SPA's own client-side
# routing (none exists yet; this just means a hard refresh on any real
# future deep link still resolves to the app instead of a 404).
_frontend_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(_frontend_dist):
    app.mount("/", StaticFiles(directory=_frontend_dist, html=True), name="spa")
