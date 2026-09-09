"""Thin HTTP client for the real BFF (`bff/main.py`), used by `Home.py`
for reviews (pending/approve/reject), report list/detail, and chat
query. Generation still calls `run_pipeline_cycle` directly; the
trigger endpoint isn't real until Phase 3, when a worker and a status
table exist behind it — that split is intentional, not something this
module works around.

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

from onepulse_common.human_governance import ActorIdRequiredError, NotesRequiredError

API_BASE_URL = os.environ.get("ONEPULSE_BFF_BASE_URL", "http://127.0.0.1:8100")


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
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=30.0) as client:
        resp = await client.get("/api/v1/reports", params={"programId": program_id, "limit": limit})
        resp.raise_for_status()
    return [_report_summary_from_api(r) for r in resp.json()]


async def get_report_detail_via_api(report_id: int) -> dict:
    """Real GET /api/v1/reports/{reportId}. A 404 (real report not
    found) maps back to `get_report_detail`'s own original
    `{"report": None, ...}` shape rather than raising — `show_report_
    dialog` already checks `report is None` and handles it.
    """
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=30.0) as client:
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
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=30.0) as client:
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
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=30.0) as client:
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
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=120.0) as client:
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
