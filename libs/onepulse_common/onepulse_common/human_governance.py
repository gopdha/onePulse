"""Human Governance API (LLD Section 2.2; closes FR-7, FR-13, reviewer
attribution NFR-11).

Real target, confirmed against FR-7/FR-13 before writing this — corrects
a premise, doesn't just accept it: this acts on every report with
`reviewed = FALSE`, not only ones whose `quality_gate_outcome` is
'route_to_human_review'. FR-7: "No report shall be considered final
without explicit Program Lead approval" — no carve-out for reports the
QA gate itself marked 'approved'. `reviewed` and `quality_gate_outcome`
are deliberately orthogonal columns: `reviewed` is the real gate on
whether a decision has been recorded at all; `quality_gate_outcome` is
context surfaced to the reviewer about why a report might warrant extra
scrutiny, not a filter on which reports need action.

Implemented as real, directly-testable async functions against a real
asyncpg connection — not an HTTP server. This phase is about the API
contract and the database's own guarantees (the real REVOKE from Phase 2
holding), not standing up a web framework, which nothing in this project
has needed yet and wasn't asked for here.

Reviewer identity: a real, explicit shortcut, not a full auth system —
actor_id is trusted as given (by a CLI arg today, see
scripts/review_cli.py). A real auth integration would replace this by
resolving the caller's identity from a verified Entra ID token/session
and looking up the corresponding `actors` row by `entra_object_id`,
never trusting a raw actor_id supplied by the caller.
"""

from __future__ import annotations

import asyncpg


class NotesRequiredError(ValueError):
    """Raised when a rejection is attempted with empty/missing notes.
    Mirrors LLD Section 2.2's 400 Bad Request { "error": "notes_required" }.
    """


class ActorIdRequiredError(ValueError):
    """Raised when actor_id is missing — reviewer attribution is the
    point of approval_records, not optional metadata (NFR-11).
    """


async def count_pending_reviews(conn: asyncpg.Connection) -> int:
    """Global unreviewed-report count, across every program — added for
    Task 18's UI Home page. Deliberately NOT program-scoped, unlike
    `list_pending_reviews`'s real LLD contract: this is a dashboard
    metric for Now-scope's single-tenant reality, not the reviewer
    action itself. A real multi-tenant Home page would need this scoped
    to the caller's authorized programs (Next-scope, same shortcut
    already accepted in `onepulse_common.chat_assistant`).
    """
    return await conn.fetchval("SELECT count(*) FROM reports WHERE reviewed = FALSE")


async def get_report_detail(conn: asyncpg.Connection, report_id: int) -> dict:
    """Full real content for one report — added for Task 18's UI Review
    page, which needs to show a reviewer the executive summary and
    per-finding evidence `list_pending_reviews`'s LLD-defined response
    doesn't carry (that contract is deliberately a thin summary list).
    Real gap this closes: FR-13 requires a Program Lead be able to
    "preview a fully rendered report" before deciding — this is the
    data behind that preview.
    """
    report = await conn.fetchrow(
        """
        SELECT r.report_id, p.name AS program_name, r.week_of, r.rag_status,
               r.quality_gate_outcome, r.executive_summary, r.rendered_artifact_uri, r.reviewed
        FROM reports r
        JOIN programs p ON p.program_id = r.program_id
        WHERE r.report_id = $1
        """,
        report_id,
    )
    if report is None:
        return {"report": None, "findings": [], "untracked_items": []}

    findings = await conn.fetch(
        """
        SELECT finding_id, source_item_ref, title, status_label, evidence
        FROM findings WHERE report_id = $1 ORDER BY finding_id
        """,
        report_id,
    )
    untracked_items = await conn.fetch(
        """
        SELECT untracked_item_id, description, evidence, possible_linked_finding_id, reasoning
        FROM untracked_items WHERE report_id = $1 ORDER BY untracked_item_id
        """,
        report_id,
    )
    return {
        "report": dict(report),
        "findings": [dict(f) for f in findings],
        "untracked_items": [dict(u) for u in untracked_items],
    }


async def list_pending_reviews(conn: asyncpg.Connection, program_id: str) -> dict:
    """GET /api/v1/reviews/pending?programId={programId} (LLD 2.2).
    Every unreviewed report for the program, regardless of
    quality_gate_outcome — see this module's docstring for why.
    """
    rows = await conn.fetch(
        """
        SELECT report_id, week_of, rag_status, rendered_artifact_uri, quality_gate_outcome
        FROM reports
        WHERE program_id = $1 AND reviewed = FALSE
        ORDER BY week_of
        """,
        program_id,
    )
    return {
        "reports": [
            {
                "reportId": r["report_id"],
                "weekOf": r["week_of"].isoformat(),
                "ragStatus": r["rag_status"],
                "renderedArtifactUri": r["rendered_artifact_uri"],
                # Not in the LLD's literal example response — added
                # deliberately as real, useful reviewer context now that
                # the schema carries this signal (Phase 2/Task 14).
                "qualityGateOutcome": r["quality_gate_outcome"],
            }
            for r in rows
        ]
    }


async def approve_report(conn: asyncpg.Connection, report_id: int, actor_id: str, notes: str = "") -> dict:
    """POST /api/v1/reviews/{reportId}/approve (LLD 2.2)."""
    if not actor_id:
        raise ActorIdRequiredError("actor_id is required")

    async with conn.transaction():
        approval = await conn.fetchrow(
            """
            INSERT INTO approval_records (report_id, decision, actor_id, notes)
            VALUES ($1, 'approved', $2, $3)
            RETURNING report_id, decided_at
            """,
            report_id,
            actor_id,
            notes or "",
        )
        await conn.execute("UPDATE reports SET reviewed = TRUE WHERE report_id = $1", report_id)

    return {
        "reportId": approval["report_id"],
        "decision": "approved",
        "decidedAt": approval["decided_at"].isoformat(),
    }


async def reject_report(conn: asyncpg.Connection, report_id: int, actor_id: str, notes: str) -> dict:
    """POST /api/v1/reviews/{reportId}/reject (LLD 2.2). notes is
    required and non-empty, enforced here server-side — not merely a UI
    nicety, per FR-7/FR-13's own wording.
    """
    if not actor_id:
        raise ActorIdRequiredError("actor_id is required")
    if not notes or not notes.strip():
        raise NotesRequiredError("notes_required")

    async with conn.transaction():
        approval = await conn.fetchrow(
            """
            INSERT INTO approval_records (report_id, decision, actor_id, notes)
            VALUES ($1, 'rejected', $2, $3)
            RETURNING report_id, decided_at
            """,
            report_id,
            actor_id,
            notes,
        )
        # Rejection is not another automated revision opportunity (HLD
        # Section 4.1) — it flags the report for manual follow-up. A
        # decision has still been recorded, so it no longer counts as
        # "pending" a decision.
        await conn.execute("UPDATE reports SET reviewed = TRUE WHERE report_id = $1", report_id)

    return {
        "reportId": approval["report_id"],
        "decision": "rejected",
        "decidedAt": approval["decided_at"].isoformat(),
    }
