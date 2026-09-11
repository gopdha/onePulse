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

Migration Plan Phase 8 (ADR-027): every function below that reads or
writes `reports` now takes a real `tenant_id` and sets it via `SET
LOCAL app.current_tenant_id` inside its own transaction, so `reports`'
own `tenant_isolation` RLS policy (installed since Phase 2, `FORCE`d
since pre-Phase-6) actually filters for the first time in this
project's history. `scripts/review_cli.py` — a local, single-tenant CLI
tool with no real caller identity to resolve a tenant from — passes the
one real tenant every existing seeded row belongs to; a genuinely
multi-tenant CLI caller doesn't exist yet.
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


class ReportNotFoundError(Exception):
    """Migration Plan Phase 8: raised when a report_id does not resolve
    under the caller's own tenant-scoped RLS context — indistinguishable,
    deliberately, from a report_id that never existed at all. Real
    isolation, not merely a "no results" UI nicety: a caller must not be
    able to tell "this report is real but not yours" from "this report
    doesn't exist" (that distinction alone would leak the existence of
    other tenants' reports).
    """

    def __init__(self, report_id: int) -> None:
        self.report_id = report_id
        super().__init__(f"No report_id={report_id} visible under the current tenant scope")


async def get_report_program_id(conn: asyncpg.Connection, report_id: int, tenant_id: str) -> str | None:
    """Migration Plan Phase 8: the real, RLS-respecting existence check
    every report_id-based route (approve/reject/detail/download) performs
    before doing anything else — sets the real tenant context, then asks
    whether this report_id is visible at all. Returns `program_id` (as a
    string, for a caller to further check against its own resolved
    `authorized_program_ids` — the program-granular half of scope RLS's
    own tenant-only policy cannot express) or `None` if the report is
    either genuinely nonexistent or simply invisible under this tenant.
    """
    async with conn.transaction():
        await conn.execute("SELECT set_config('app.current_tenant_id', $1, true)", tenant_id)
        row = await conn.fetchrow("SELECT program_id FROM reports WHERE report_id = $1", report_id)
    return str(row["program_id"]) if row else None


async def get_report_download_info(conn: asyncpg.Connection, report_id: int, tenant_id: str) -> dict | None:
    """Migration Plan Phase 8 (ADR-027): the one real, RLS-respecting
    query the SAS download route needs — `program_id` (for the caller's
    own additional `authorized_program_ids` check) and
    `rendered_artifact_uri` (to know whether a real blob artifact even
    exists for this report), in one round trip. Returns `None` for
    exactly the same two real cases `get_report_program_id` does:
    genuinely nonexistent, or invisible under this tenant.
    """
    async with conn.transaction():
        await conn.execute("SELECT set_config('app.current_tenant_id', $1, true)", tenant_id)
        row = await conn.fetchrow(
            "SELECT program_id, rendered_artifact_uri FROM reports WHERE report_id = $1", report_id
        )
    if row is None:
        return None
    return {"program_id": str(row["program_id"]), "rendered_artifact_uri": row["rendered_artifact_uri"]}


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


async def get_report_detail(conn: asyncpg.Connection, report_id: int, tenant_id: str) -> dict:
    """Full real content for one report — added for Task 18's UI Review
    page, which needs to show a reviewer the executive summary and
    per-finding evidence `list_pending_reviews`'s LLD-defined response
    doesn't carry (that contract is deliberately a thin summary list).
    Real gap this closes: FR-13 requires a Program Lead be able to
    "preview a fully rendered report" before deciding — this is the
    data behind that preview.

    Migration Plan Phase 8: wrapped in a real transaction with `SET
    LOCAL app.current_tenant_id` — a report outside the caller's own
    tenant is now genuinely invisible to this query (RLS), not merely
    unlinked from the UI.
    """
    async with conn.transaction():
        await conn.execute("SELECT set_config('app.current_tenant_id', $1, true)", tenant_id)
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


async def list_pending_reviews(conn: asyncpg.Connection, program_id: str, tenant_id: str) -> dict:
    """GET /api/v1/reviews/pending?programId={programId} (LLD 2.2).
    Every unreviewed report for the program, regardless of
    quality_gate_outcome — see this module's docstring for why.

    Migration Plan Phase 8: real `SET LOCAL app.current_tenant_id` — a
    `program_id` belonging to a different tenant now returns nothing
    (RLS), never another tenant's real pending reviews.
    """
    async with conn.transaction():
        await conn.execute("SELECT set_config('app.current_tenant_id', $1, true)", tenant_id)
        rows = await conn.fetch(
            """
            SELECT report_id, week_of, rag_status, rendered_artifact_uri, quality_gate_outcome
            FROM reports
            WHERE program_id = $1 AND reviewed = FALSE AND NOT is_test_fixture
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


async def approve_report(
    conn: asyncpg.Connection, report_id: int, actor_id: str, tenant_id: str, notes: str = ""
) -> dict:
    """POST /api/v1/reviews/{reportId}/approve (LLD 2.2).

    Migration Plan Phase 8: real `SET LOCAL app.current_tenant_id`, and
    the `UPDATE` (not the `INSERT`) is the real existence check now —
    `approval_records` itself carries no RLS of its own (it's an audit
    log, not tenant-scoped data), so checking `reports` first, inside
    the same tenant-scoped transaction, is what actually stops an
    out-of-tenant `report_id` from being approved; a genuine crash-proof
    ordering (report visibility confirmed before any approval row is
    ever written), not merely a check-then-hope.
    """
    if not actor_id:
        raise ActorIdRequiredError("actor_id is required")

    async with conn.transaction():
        await conn.execute("SELECT set_config('app.current_tenant_id', $1, true)", tenant_id)
        updated = await conn.fetchrow(
            "UPDATE reports SET reviewed = TRUE WHERE report_id = $1 RETURNING report_id", report_id
        )
        if updated is None:
            raise ReportNotFoundError(report_id)
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

    return {
        "reportId": approval["report_id"],
        "decision": "approved",
        "decidedAt": approval["decided_at"].isoformat(),
    }


async def reject_report(
    conn: asyncpg.Connection, report_id: int, actor_id: str, tenant_id: str, notes: str
) -> dict:
    """POST /api/v1/reviews/{reportId}/reject (LLD 2.2). notes is
    required and non-empty, enforced here server-side — not merely a UI
    nicety, per FR-7/FR-13's own wording. See `approve_report`'s own
    docstring for why the real tenant-scoped `UPDATE` happens before the
    `INSERT`, unchanged reasoning here.
    """
    if not actor_id:
        raise ActorIdRequiredError("actor_id is required")
    if not notes or not notes.strip():
        raise NotesRequiredError("notes_required")

    async with conn.transaction():
        await conn.execute("SELECT set_config('app.current_tenant_id', $1, true)", tenant_id)
        updated = await conn.fetchrow(
            "UPDATE reports SET reviewed = TRUE WHERE report_id = $1 RETURNING report_id", report_id
        )
        if updated is None:
            raise ReportNotFoundError(report_id)
        # Rejection is not another automated revision opportunity (HLD
        # Section 4.1) — it flags the report for manual follow-up. A
        # decision has still been recorded, so it no longer counts as
        # "pending" a decision.
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

    return {
        "reportId": approval["report_id"],
        "decision": "rejected",
        "decidedAt": approval["decided_at"].isoformat(),
    }
