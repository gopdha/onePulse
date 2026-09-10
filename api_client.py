"""Thin HTTP client for the real BFF (`bff/main.py`), used by `Home.py`
for reviews (pending/approve/reject), report list/detail, chat query,
and — real now, Migration Plan Phase 3 — generation. `Home.py` no longer
calls `run_pipeline_cycle` directly at all: `trigger_report_via_api`
starts a real cycle (a separate worker process executes it) and
`get_cycle_via_api` polls its real progress from the `cycles` status
table, closing the two-path split Phase 1 deliberately left open.

Migration Plan Phase 2 (ADR-017): this now talks to the BFF, not the
core API directly — Streamlit itself never resolved a "real" identity
anyway (the old `actorId` it sent was always `default_actor_id`, a
plain, unauthenticated lookup of the first row in `actors`), so real
identity resolution moving server-side, into the BFF, changes nothing
about what Streamlit could actually prove about who was asking. The
`actor_id` parameters below are kept, unused, purely so `Home.py`'s own
existing call sites (`render_report_row`, `_ask()`, the `default_actor_
id` plumbing) don't need to change for this phase — the BFF determines
the real (today, stubbed) identity itself and forwards it to the core
API; nothing this module sends is used for that anymore. Real cleanup
of this now-vestigial parameter is natural, low-risk work for whenever
Phase 8's real identity work next touches this UI layer, not forced
here to keep this phase's own diff to Home.py at zero.

Every function here mirrors the exact return shape (snake_case keys,
real `date`/`datetime` objects where `Home.py`'s existing code already
calls `.isoformat()`/`.strftime()` on them) and exception-raising
behavior (`ActorIdRequiredError`, `NotesRequiredError` — the same real
classes `onepulse_common.human_governance` defines, re-raised here, not
duplicated) that `Home.py` already depended on when it called
`onepulse_common` directly.

Run the BFF (and the core API it depends on) first: `uvicorn core_api.
main:app --port 8000`, then `uvicorn bff.main:app --port 8100` (from
the repo root — see the Runbook). `ONEPULSE_BFF_BASE_URL` overrides the
default `http://127.0.0.1:8100` if it's running elsewhere.
"""

from __future__ import annotations

import datetime as dt
import os

import httpx
from azure.identity.aio import DefaultAzureCredential

from onepulse_common.human_governance import ActorIdRequiredError, NotesRequiredError

API_BASE_URL = os.environ.get("ONEPULSE_BFF_BASE_URL", "http://127.0.0.1:8100")

# Migration Plan Phase 7: the deployed bff has real, live built-in Entra
# authentication (Easy Auth) in front of it -- a plain, unauthenticated
# request now gets a genuine 401 from the platform itself before it ever
# reaches bff/main.py. This module's own caller (this developer's
# already-authenticated `az login` session, the same real credential
# every other local script in this project already uses) acquires a
# real bearer token for the bff-signin app registration's own
# `access_as_user` delegated scope and presents it on every request --
# not a static token pasted into .env, the identical live-credential
# pattern this project has used throughout. Against a plain local
# core_api/bff pair (no Easy Auth in front, Phase 1-6's own local dev
# shape), ONEPULSE_BFF_SIGNIN_APP_ID is simply unset and this becomes a
# real no-op (empty headers), so this file works unchanged either way.
_BFF_SIGNIN_APP_ID = os.environ.get("ONEPULSE_BFF_SIGNIN_APP_ID")
_credential: DefaultAzureCredential | None = None


async def _auth_headers() -> dict[str, str]:
    global _credential
    if not _BFF_SIGNIN_APP_ID:
        return {}
    if _credential is None:
        _credential = DefaultAzureCredential()
    token = await _credential.get_token(f"api://{_BFF_SIGNIN_APP_ID}/access_as_user")
    return {"Authorization": f"Bearer {token.token}"}


def _parse_date(value: str) -> dt.date:
    return dt.date.fromisoformat(value[:10])


def _parse_datetime(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value)


def _report_summary_from_api(r: dict) -> dict:
    return {
        "report_id": r["reportId"],
        "program_name": r["programName"],
        "week_of": _parse_date(r["weekOf"]),
        "rag_status": r["ragStatus"],
        "quality_gate_outcome": r["qualityGateOutcome"],
        "reviewed": r["reviewed"],
        "rendered_artifact_uri": r["renderedArtifactUri"],
        "created_at": _parse_datetime(r["createdAt"]),
        "decision": r["decision"],
        "finding_count": r["findingCount"],
    }


async def list_recent_reports_via_api(limit: int, program_id: str) -> list[dict]:
    """Real GET /api/v1/reports?programId=...&limit=... — same shape
    `onepulse_common.pipeline.list_recent_reports` already returned.
    """
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=30.0, headers=await _auth_headers()) as client:
        resp = await client.get("/api/v1/reports", params={"programId": program_id, "limit": limit})
        resp.raise_for_status()
    return [_report_summary_from_api(r) for r in resp.json()]


async def get_report_detail_via_api(report_id: int) -> dict:
    """Real GET /api/v1/reports/{reportId}. A 404 (real report not
    found) maps back to `get_report_detail`'s own original
    `{"report": None, ...}` shape rather than raising — `show_report_
    dialog` already checks `report is None` and handles it.
    """
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=30.0, headers=await _auth_headers()) as client:
        resp = await client.get(f"/api/v1/reports/{report_id}")
        if resp.status_code == 404:
            return {"report": None, "findings": [], "untracked_items": []}
        resp.raise_for_status()
        data = resp.json()

    r = data["report"]
    return {
        "report": {
            "report_id": r["reportId"],
            "program_name": r["programName"],
            "week_of": _parse_date(r["weekOf"]),
            "rag_status": r["ragStatus"],
            "quality_gate_outcome": r["qualityGateOutcome"],
            "executive_summary": r["executiveSummary"],
            "rendered_artifact_uri": r["renderedArtifactUri"],
            "reviewed": r["reviewed"],
        },
        "findings": [
            {
                "finding_id": f["findingId"],
                "source_item_ref": f["sourceItemRef"],
                "title": f["title"],
                "status_label": f["statusLabel"],
                "evidence": f["evidence"],
            }
            for f in data["findings"]
        ],
        "untracked_items": [
            {
                "untracked_item_id": u["untrackedItemId"],
                "description": u["description"],
                "evidence": u["evidence"],
                "possible_linked_finding_id": u["possibleLinkedFindingId"],
                "reasoning": u["reasoning"],
            }
            for u in data["untrackedItems"]
        ],
    }


async def trigger_report_via_api(program_id: str) -> dict:
    """Real POST /api/v1/programs/{programId}/reports, via the BFF —
    Migration Plan Phase 3. Returns {"cycle_id": ..., "status":
    "queued"} immediately; the real pipeline runs in a separate worker
    process, not in this request. Home.py polls get_cycle_via_api for
    progress instead of blocking on this call.
    """
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=30.0, headers=await _auth_headers()) as client:
        resp = await client.post(f"/api/v1/programs/{program_id}/reports")
        resp.raise_for_status()
        data = resp.json()
    return {"cycle_id": data["cycleId"], "status": data["status"]}


async def get_cycle_via_api(cycle_id: str) -> dict:
    """Real GET /api/v1/cycles/{cycleId}, via the BFF — the real ADR-021
    polling read. `stages` keys arrive as JSON strings ("1".."7"); kept
    as strings here too (Home.py's own rendering already normalizes),
    since re-keying to int here would just be undone by the JSON
    round-trip the next poll anyway.
    """
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=30.0, headers=await _auth_headers()) as client:
        resp = await client.get(f"/api/v1/cycles/{cycle_id}")
        resp.raise_for_status()
        data = resp.json()
    return {
        "cycle_id": data["cycleId"],
        "status": data["status"],
        "stages": data["stages"],
        "report_id": data["reportId"],
        "error_detail": data["errorDetail"],
        "created_at": data["createdAt"],
        "started_at": data["startedAt"],
        "finished_at": data["finishedAt"],
    }


async def approve_report_via_api(report_id: int, actor_id: str | None) -> dict:
    """Real POST /api/v1/reviews/{reportId}/approve, via the BFF.
    `actor_id` is accepted but not sent — see module docstring: the BFF
    resolves the real (today, stubbed) identity itself now and forwards
    it to the core API; nothing sent from here is used for that. If the
    BFF's own stubbed identity doesn't resolve to a real `actors` row,
    the core API returns `401 {"error": "actor_not_found"}`, surfaced
    here as `ActorIdRequiredError` so `Home.py`'s existing exception
    handling (unchanged since Phase 1) still catches it correctly.
    """
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=30.0, headers=await _auth_headers()) as client:
        resp = await client.post(f"/api/v1/reviews/{report_id}/approve")
    if resp.status_code == 401 and resp.json().get("error") == "actor_not_found":
        raise ActorIdRequiredError("the BFF's identity did not resolve to a real actor")
    resp.raise_for_status()
    return resp.json()


async def reject_report_via_api(report_id: int, actor_id: str | None, notes: str) -> dict:
    """Real POST /api/v1/reviews/{reportId}/reject, via the BFF. See
    `approve_report_via_api` for why `actor_id` is accepted but not
    sent.
    """
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=30.0, headers=await _auth_headers()) as client:
        resp = await client.post(f"/api/v1/reviews/{report_id}/reject", json={"notes": notes})
    if resp.status_code == 400 and resp.json().get("error") == "notes_required":
        raise NotesRequiredError("notes_required")
    if resp.status_code == 401 and resp.json().get("error") == "actor_not_found":
        raise ActorIdRequiredError("the BFF's identity did not resolve to a real actor")
    resp.raise_for_status()
    return resp.json()


async def ask_question_via_api(question: str, program_id: str | None, actor_id: str | None) -> dict:
    """Real POST /api/v1/chat/query, via the BFF. Same real citation
    shape `onepulse_common.chat_assistant.ask_question` already returned
    (`report_id`, `program_name`, `week_of` as a plain string — the
    original response never turned that one into a `date` object
    either, so this doesn't start now). See `approve_report_via_api` for
    why `actor_id` is accepted but not sent.
    """
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=120.0, headers=await _auth_headers()) as client:
        resp = await client.post(
            "/api/v1/chat/query",
            json={"question": question, "programId": program_id},
        )
        resp.raise_for_status()
        data = resp.json()

    return {
        "answer": data["answer"],
        "citations": [
            {
                "report_id": c["reportId"],
                "program_name": c["programName"],
                "week_of": c["weekOf"],
                "source_item_ref": c["sourceItemRef"],
                "finding_title": c["findingTitle"],
            }
            for c in data["citations"]
        ],
    }
