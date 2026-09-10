"""Real Phase 8-shaped orchestration, moved here from
scripts/run_pipeline.py (Task 18). This module is the REPORTING half of
the pipeline as of Migration Plan Phase 4 (ADR-019/ADR-020) — Status
Update Analysis through Postgres persistence (`run_reporting_stages`).
Investigation itself (FR-1) moved to its own real service
(`investigation/investigate.py`), coordinated by real Azure Storage
Queues, because it is 302 of a real 378-second full-scope run (~80% of
total runtime), the only stage needing the Node runtime, and the only
real consumer of the ADO PAT — none of which is true of anything left
in this file. This module is imported by core_api, bff, and the
Reporting service (`reporting/main.py`); it has zero import of anything
Investigation/Node/ADO-PAT-adjacent, by design, so none of those
services' import graphs ever touch it either.

Status Update Analysis -> Deterministic Status Rollup -> Synthesis ->
Self-critique -> [exactly one revision if needed] -> Rendering ->
Postgres persistence (Phase 2 schema), in the order High-Level Design
Section 2 specifies (stages 2-7 of its real 7-stage numbering — stage 1,
Investigation, runs entirely in the separate service described above).

Requirement traceability (convention #3 — traced to the PRD, not
inferred from the ID):
  FR-1: Investigation classifies each real work item into On Track / At
        Risk / Blocked / Needs Human Review, grounded in cited evidence.
  FR-2: Status Update Analysis parses a real team-lead .pptx (via a real
        custom PPTX-parsing MCP server — Physical Architecture Section 2
        names this exact component) to flag untracked initiatives and
        possible connections to tracked work.
  FR-3: Synthesis merges/curates investigated findings into an executive
        narrative. (No "prior period continuity" — trend_line/
        prior_report_id are left at their schema defaults; this run
        does not fabricate continuity that isn't built yet.)
  FR-4: Self-critique evaluates the draft; exactly one bounded revision
        is attempted before HLD Section 3's decision applies.
  FR-5: Rendering lays out finalized content into a locked, hard-coded
        visual template — deterministic, no model call.
  FR-7: Every persisted report keeps `reviewed=FALSE` regardless of
        `quality_gate_outcome` — Phase 7's own confirmed finding: FR-7
        requires Program Lead approval for every rendered report, not
        only ones the QA gate routes to human review. This module never
        marks anything approved itself; `onepulse_common.human_governance`
        is the separate real path that acts on what's persisted here.
  FR-8: The headline Red/Amber/Green/Unknown status is computed by
        onepulse_common.status_rollup's fixed rule, never by the model.

Real database constraint, checked against the actual migration before
`persist_report()` was written (not assumed): the app role has only
SELECT+INSERT on `findings`/`untracked_items` — no UPDATE, no DELETE.
A second real run for the same (program, week_of) cannot safely
reconcile findings in place, so `persist_report()` does a plain INSERT,
never an upsert; see its own docstring.

NOTE: agent_framework.MCPStdioTool (the native MCP client) is
deliberately NOT used here. Three real, confirmed compatibility bugs
were found live in agent-framework-core==1.17.0's MCP client code, all
the same shape: it reads pre-mcp-2.0 camelCase attribute names
(protocolVersion, McpError, tool.inputSchema) against mcp>=2.0's real
snake_case API (protocol_version, MCPError, tool.input_schema) — the
same rename already hit and fixed in scripts/ado_investigation_spike.py.
Decision: bypass agent_framework's native MCP client entirely and reuse
this project's own already-proven mcp.ClientSession bridge (see
`onepulse_common.mcp_bridge.build_mcp_function_tools`, imported below —
shared with the Investigation service's identical real need), wrapping
each real MCP tool as a plain agent_framework.FunctionTool instead.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import asyncpg
from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient
from azure.identity import DefaultAzureCredential
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from onepulse_common.config import PostgresSettings
from onepulse_common.db import PostgresClient
from onepulse_common.heartbeat import heartbeat, noop_detail, noop_stage
from onepulse_common.mcp_bridge import build_mcp_function_tools
from onepulse_common.quality_gate import code_enforced_risk_floor_check, decide_revision_outcome
from onepulse_common.report_rendering import Finding, render_status_report, render_tower_report
from onepulse_common.report_rendering import week_of as monday_of_week
from onepulse_common.status_rollup import compute_overall_status
from onepulse_common.tower_rollup import build_tower_rollups, program_health as compute_program_health

# Real persistence target (Phase 2's schema, onepulse-pg-dev) — same
# host/database/role convention every other script in this project uses
# (migrate.py, seed_dev_data.py, review_cli.py, etc.), duplicated
# locally per that established, intentional convention rather than
# factored into a shared "target registry" nothing else has needed.
PG_SETTINGS = PostgresSettings(
    host="onepulse-pg-dev.postgres.database.azure.com",
    database="onepulse",
    role_name=os.environ.get("ONEPULSE_PG_ROLE", "app_role_local_dev"),
)

STATUS_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "untracked_initiatives": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": ["description", "evidence"],
                "additionalProperties": False,
            },
        },
        "possible_connections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "mentioned_initiative": {"type": "string"},
                    "likely_related_work_item_id": {"type": "integer"},
                    "reasoning": {"type": "string"},
                },
                "required": ["mentioned_initiative", "likely_related_work_item_id", "reasoning"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["untracked_initiatives", "possible_connections"],
    "additionalProperties": False,
}

SYNTHESIS_SCHEMA = {
    "type": "object",
    "properties": {"executive_summary": {"type": "string"}},
    "required": ["executive_summary"],
    "additionalProperties": False,
}

SELF_CRITIQUE_SCHEMA = {
    "type": "object",
    "properties": {
        "tone_conciseness_pass": {"type": "boolean"},
        "feedback": {"type": "string"},
    },
    "required": ["tone_conciseness_pass", "feedback"],
    "additionalProperties": False,
}


STATUS_ANALYSIS_INSTRUCTIONS = """You are a Status Update Analysis agent for OnePulse (FR-2).
You will be given the real path to a team lead's status deck (.pptx) and a JSON list of real Azure DevOps work items already tracked for this program.
Use the tools available to you to read the real content of the deck — never guess or fabricate its contents.
For each initiative mentioned in the deck:
1. If it does not correspond to any tracked work item, list it under untracked_initiatives with a description and the exact evidence text from the deck.
2. If it appears to relate to a tracked work item by topic overlap, list it under possible_connections with the related work_item_id and your reasoning.
Respond only with JSON matching the required schema."""

SYNTHESIS_INSTRUCTIONS = """You are a Narrative Synthesis agent for OnePulse (FR-3).
You will be given a JSON list of real, already-investigated findings for a program.
Merge and curate them into a single, coherent executive summary paragraph (3-5 sentences) suitable for a status report read by a Program Lead.
Do not invent findings beyond what you are given. Do not state or imply an overall RAG status yourself — the overall status is computed separately by a fixed, deterministic rule (FR-8), never by you.
For every finding whose status is "Blocked" or "Needs Human Review", you MUST cite its real work item ID directly in the text wherever you reference it — e.g. "(WI 362)" or "work item 362". Describing or paraphrasing the item is not sufficient on its own; the literal numeric ID must appear next to it, every time, for every such item.
Respond only with JSON matching the required schema."""

SELF_CRITIQUE_INSTRUCTIONS = """You are a Self-critique agent for OnePulse (FR-4).
You will be given a draft executive summary. Judge ONLY its tone and conciseness for an executive audience (a Program Lead reading a status report): is it professional, clear, and appropriately brief — not padded, and not so terse it loses meaning?
Do not judge factual completeness or accuracy — a separate deterministic rule checks that, not you.
Respond only with JSON matching the required schema: tone_conciseness_pass (true/false) and feedback (specific and actionable if false; a brief acknowledgment if true)."""


# No-op defaults so every callback parameter below is always callable —
# callers (CLI, Streamlit) opt in to progress reporting by passing their
# own, rather than this module ever printing or touching UI state itself.
async def analyze_status_deck(
    chat_client: FoundryChatClient,
    findings: list[dict],
    status_deck_path: str,
    pptx_mcp_server_path: str,
    on_detail: Callable[[str], None] = noop_detail,
) -> dict:
    server_params = StdioServerParameters(command=sys.executable, args=[pptx_mcp_server_path])
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as mcp_session:
            await mcp_session.initialize()
            tools, tool_call_progress = await build_mcp_function_tools(mcp_session, on_detail)

            async with Agent(
                client=chat_client,
                name="onepulse-status-analysis-agent",
                instructions=STATUS_ANALYSIS_INSTRUCTIONS,
                tools=tools,
                default_options={"response_format": STATUS_ANALYSIS_SCHEMA},
            ) as agent:
                async with heartbeat(on_detail, "Status Update Analysis agent"):
                    result = await agent.run(
                        f"Analyze the status deck at '{status_deck_path}' against these tracked work items:\n"
                        f"{json.dumps(findings, indent=2)}"
                    )
            on_detail(
                f"Status Update Analysis tool calls complete: {tool_call_progress['completed']} of "
                f"{tool_call_progress['dispatched']} real tool call(s) resolved."
            )

    return json.loads(result.text)


async def synthesize(
    chat_client: FoundryChatClient,
    findings: list[dict],
    ado_project_name: str,
    feedback: str | None = None,
    on_detail: Callable[[str], None] = noop_detail,
) -> str:
    content = (
        f"Real investigated findings for program '{ado_project_name}':\n"
        f"{json.dumps(findings, indent=2)}\n\n"
        "Write the executive summary."
    )
    if feedback:
        content += f"\n\nThis is a revision. Address this real feedback from the prior draft: {feedback}"

    async with Agent(
        client=chat_client,
        name="onepulse-synthesis-agent",
        instructions=SYNTHESIS_INSTRUCTIONS,
        default_options={"response_format": SYNTHESIS_SCHEMA},
    ) as agent:
        async with heartbeat(on_detail, "Synthesis agent"):
            result = await agent.run(content)

    return json.loads(result.text)["executive_summary"]


async def self_critique(
    chat_client: FoundryChatClient, draft: str, on_detail: Callable[[str], None] = noop_detail
) -> dict:
    async with Agent(
        client=chat_client,
        name="onepulse-self-critique-agent",
        instructions=SELF_CRITIQUE_INSTRUCTIONS,
        default_options={"response_format": SELF_CRITIQUE_SCHEMA},
    ) as agent:
        async with heartbeat(on_detail, "Self-critique agent"):
            result = await agent.run(f"Draft executive summary:\n{draft}")

    return json.loads(result.text)


async def run_quality_gate(
    chat_client: FoundryChatClient,
    findings: list[dict],
    initial_draft: str,
    ado_project_name: str,
    queried_item_count: int,
    on_detail: Callable[[str], None] = noop_detail,
) -> tuple[str, str, int]:
    """Runs the real HLD Section 3 gate: code-enforced risk floor +
    subjective self-critique on the initial draft; if either fails,
    exactly one revision; re-check both; decide. Returns
    (outcome, final_narrative, attempts) — `attempts` is 1 if the
    initial draft passed both checks, 2 if the one permitted revision
    fired (persisted as reports.attempts).

    `queried_item_count` (Task 28/Part 1) is how many real items were
    actually in scope for Investigation to cover — required so
    `code_enforced_risk_floor_check` can tell a genuine coverage
    shortfall (a real defect) apart from a legitimate zero-scope run.
    See quality_gate.py's own docstring for the real bug this closes.
    """
    code_ok_before = code_enforced_risk_floor_check(findings, initial_draft, queried_item_count)
    critique_before = await self_critique(chat_client, initial_draft, on_detail)
    subjective_ok_before = critique_before["tone_conciseness_pass"]

    on_detail(f'Draft: "{initial_draft}"')
    on_detail(f"Code-enforced risk floor: {'PASS' if code_ok_before else 'FAIL'}")
    on_detail(f"Subjective tone/conciseness: {'PASS' if subjective_ok_before else 'FAIL'}")

    if code_ok_before and subjective_ok_before:
        return "approved", initial_draft, 1

    feedback_parts = []
    if not code_ok_before:
        if len(findings) < queried_item_count:
            feedback_parts.append(
                f"Only {len(findings)} of {queried_item_count} real items actually queried were "
                "represented in findings — coverage is incomplete."
            )
        dropped = [
            f
            for f in findings
            if f["status"] in ("Blocked", "Needs Human Review")
            and str(f["work_item_id"]) not in initial_draft
            and f["title"] not in initial_draft
        ]
        if dropped:
            # Real, specific fix (found from two consecutive real
            # hard_stop_defect runs against Agentic AI Observability
            # Platform): the base SYNTHESIS_INSTRUCTIONS ID-citation rule
            # alone wasn't reliable across revisions either — both the
            # initial AND revised draft paraphrased these items in prose
            # without ever writing the literal ID, satisfying neither of
            # code_enforced_risk_floor_check's two accepted forms (exact
            # title text or the ID). Naming the exact real ID next to each
            # dropped title here, at the moment the violation is detected,
            # reinforces the same rule with the specific real data needed
            # to fix it, rather than relying on the static system prompt
            # alone to be followed a second time under revision pressure.
            cited = "; ".join(f"WI {f['work_item_id']} ({f['title']})" for f in dropped)
            feedback_parts.append(
                f"You dropped critical item(s) that must be mentioned, AND you must cite each one's real "
                f"work item ID directly in the text (e.g. \"(WI {dropped[0]['work_item_id']})\") — describing "
                f"it without the literal ID does not count: {cited}."
            )
    if not subjective_ok_before:
        feedback_parts.append(critique_before["feedback"])

    on_detail("Triggering the one permitted revision (HLD Section 3 / FR-4)...")
    revised_draft = await synthesize(
        chat_client, findings, ado_project_name, feedback=" ".join(feedback_parts), on_detail=on_detail
    )

    code_ok_after = code_enforced_risk_floor_check(findings, revised_draft, queried_item_count)
    critique_after = await self_critique(chat_client, revised_draft, on_detail)
    subjective_ok_after = critique_after["tone_conciseness_pass"]

    on_detail(f'Revised draft: "{revised_draft}"')
    on_detail(f"Code-enforced risk floor: {'PASS' if code_ok_after else 'FAIL'}")
    on_detail(f"Subjective tone/conciseness: {'PASS' if subjective_ok_after else 'FAIL'}")

    outcome = decide_revision_outcome(
        code_enforced_ok_before_revision=code_ok_before,
        code_enforced_ok_after_revision=code_ok_after,
        subjective_ok_after_revision=subjective_ok_after,
    )
    return outcome, revised_draft, 2


async def persist_report(
    program_name: str,
    week_of: dt.date,
    overall_status: str,
    quality_gate_outcome: str,
    executive_summary: str,
    attempts: int,
    rendered_path: str,
    findings: list[dict],
    status_analysis: dict,
) -> tuple[int, bool]:
    """Real persistence, Phase 2's schema (onepulse-pg-dev) — the
    pipeline's own genuine output, not seeded/test data.

    `week_of` must be the real Monday-of-week bucket (see
    `run_pipeline_cycle`'s use of `report_rendering.week_of()`), not the
    raw run date — Task 20 found and Task 21 fixed a real bug where the
    raw date was passed here instead, letting three separate reports
    (ids 29, 51, 118) get persisted for what was actually one real ISO
    week, silently defeating this table's own `UNIQUE(program_id,
    week_of)` weekly-dedup guarantee. This function itself does no
    bucketing — it trusts the caller to pass the real week-start, same
    as it always has; the caller is what changed.

    Real column names confirmed this session, not the LLD's literal
    ones: `findings.source_item_ref` (not `work_item_id`).
    `reports.quality_gate_outcome` (Phase 2/Task 14) records the real
    HLD Section 3 outcome. Every non-hard_stop_defect outcome is
    persisted with `reviewed` at its schema default (FALSE) — per
    Phase 7's own confirmed finding, FR-7 requires Program Lead approval
    for every rendered report, not only ones the QA gate routed to
    human review, so this never sets `reviewed=TRUE` itself.

    Real database constraint, checked against the actual migration
    before writing this (not assumed): the app role has only
    SELECT+INSERT on `findings`/`untracked_items` — no UPDATE, no
    DELETE. So a second real run for the same (program, week_of) cannot
    safely reconcile findings in place; this function does not attempt
    an upsert. If `reports`' own UNIQUE(program_id, week_of) rejects the
    insert, the existing report_id is returned with `persisted=False` so
    the caller can report honestly that this run's fresh findings were
    NOT written, rather than silently duplicating or corrupting rows.

    Returns (report_id, persisted) — `persisted` is False when a report
    for this program/week already existed and nothing new was written.
    """
    client = await PostgresClient.connect(PG_SETTINGS, min_size=1, max_size=1)
    try:
        async with client.pool.acquire() as conn:
            program_id = await conn.fetchval("SELECT program_id FROM programs WHERE name = $1", program_name)
            if program_id is None:
                raise RuntimeError(
                    f"Program '{program_name}' not found in Postgres — "
                    "run `python scripts/seed_dev_data.py --target dev` first."
                )

            rendered_uri = Path(rendered_path).resolve().as_uri()

            try:
                async with conn.transaction():
                    report_id = await conn.fetchval(
                        """
                        INSERT INTO reports (program_id, week_of, rag_status, quality_gate_outcome,
                                              executive_summary, attempts, rendered_artifact_uri)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                        RETURNING report_id
                        """,
                        program_id,
                        week_of,
                        overall_status,
                        quality_gate_outcome,
                        executive_summary,
                        attempts,
                        rendered_uri,
                    )

                    finding_id_by_item_ref: dict[str, int] = {}
                    for f in findings:
                        source_item_ref = str(f["work_item_id"])
                        finding_id = await conn.fetchval(
                            """
                            INSERT INTO findings (report_id, source_item_ref, title, status_label, evidence)
                            VALUES ($1, $2, $3, $4, $5)
                            RETURNING finding_id
                            """,
                            report_id,
                            source_item_ref,
                            f["title"],
                            f["status"],
                            f["evidence"],
                        )
                        finding_id_by_item_ref[source_item_ref] = finding_id

                    for item in status_analysis.get("untracked_initiatives", []):
                        await conn.execute(
                            "INSERT INTO untracked_items (report_id, description, evidence) VALUES ($1, $2, $3)",
                            report_id,
                            item["description"],
                            item["evidence"],
                        )

                    for connection in status_analysis.get("possible_connections", []):
                        linked_finding_id = finding_id_by_item_ref.get(
                            str(connection["likely_related_work_item_id"])
                        )
                        await conn.execute(
                            """
                            INSERT INTO untracked_items (report_id, description, possible_linked_finding_id, reasoning)
                            VALUES ($1, $2, $3, $4)
                            """,
                            report_id,
                            connection["mentioned_initiative"],
                            linked_finding_id,
                            connection["reasoning"],
                        )

                return report_id, True
            except asyncpg.exceptions.UniqueViolationError:
                existing_report_id = await conn.fetchval(
                    "SELECT report_id FROM reports WHERE program_id = $1 AND week_of = $2",
                    program_id,
                    week_of,
                )
                return existing_report_id, False
    finally:
        await client.close()


async def list_recent_reports(limit: int = 20, program_id: str | None = None) -> list[dict]:
    """Real recent-runs listing for the UI Home page — most recent first,
    optionally scoped to one real program (Task 23: the real design
    reference's "Previous Status Reports" list and "Last run" indicator
    are both per-selected-project, not global — `program_id=None` keeps
    the original Task 18 global behavior for any other caller).
    `onepulse_common.human_governance.list_pending_reviews` is
    deliberately program-scoped and reviewed=FALSE-only per its real LLD
    contract, neither of which fits this dashboard view.

    Real, minimal, additive enhancement (Task 31): the Ops Console design
    needs the real approve/reject *decision*, not just the existing
    `reviewed` boolean (`reports` has no decision column of its own —
    the real decision lives in `approval_records`, a separate table),
    plus a real "N sources" count. Both are read-only SQL additions to
    this same query, not new logic — a `LEFT JOIN LATERAL` picks the
    most recent real `approval_records.decision` per report (defensive
    against more than one row ever existing for a report, even though
    today's UI never re-reviews one), and a real subquery counts each
    report's actual `findings` rows. Existing callers that only read the
    previously-existing keys are unaffected.
    """
    client = await PostgresClient.connect(PG_SETTINGS, min_size=1, max_size=1)
    try:
        async with client.pool.acquire() as conn:
            if program_id is None:
                rows = await conn.fetch(
                    """
                    SELECT r.report_id, p.name AS program_name, r.week_of, r.rag_status,
                           r.quality_gate_outcome, r.reviewed, r.rendered_artifact_uri, r.created_at,
                           ar.decision,
                           (SELECT count(*) FROM findings f WHERE f.report_id = r.report_id) AS finding_count
                    FROM reports r
                    JOIN programs p ON p.program_id = r.program_id
                    LEFT JOIN LATERAL (
                        SELECT decision FROM approval_records
                        WHERE report_id = r.report_id
                        ORDER BY decided_at DESC LIMIT 1
                    ) ar ON true
                    ORDER BY r.created_at DESC
                    LIMIT $1
                    """,
                    limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT r.report_id, p.name AS program_name, r.week_of, r.rag_status,
                           r.quality_gate_outcome, r.reviewed, r.rendered_artifact_uri, r.created_at,
                           ar.decision,
                           (SELECT count(*) FROM findings f WHERE f.report_id = r.report_id) AS finding_count
                    FROM reports r
                    JOIN programs p ON p.program_id = r.program_id
                    LEFT JOIN LATERAL (
                        SELECT decision FROM approval_records
                        WHERE report_id = r.report_id
                        ORDER BY decided_at DESC LIMIT 1
                    ) ar ON true
                    WHERE r.program_id = $2
                    ORDER BY r.created_at DESC
                    LIMIT $1
                    """,
                    limit,
                    program_id,
                )
            return [dict(row) for row in rows]
    finally:
        await client.close()


def build_output_path(ado_project_name: str, as_of: dt.date, output_dir: str = "output") -> str:
    """Real per-project, per-date artifact path (Task 20): `<output_dir>/
    <ProjectName>/<ProjectName>_<Date>.pptx` — e.g.
    `output/singleSlide/singleSlide_2026-09-06.pptx`, replacing the old
    flat, generic `onepulse_status_report_demo.pptx` every run used to
    overwrite. Both `scripts/run_pipeline.py` and `Home.py` get this
    from the one real place it's computed, not two copies that could
    drift.

    `ado_project_name` reaches here from a trusted, operator-set env var
    (`ONEPULSE_ADO_PROJECT`), not end-user request input — but it still
    becomes a real filesystem path segment, so path separators are
    stripped defensively rather than trusted blindly.
    """
    safe_name = ado_project_name.replace("/", "_").replace("\\", "_").strip()
    project_dir = Path(output_dir) / safe_name
    project_dir.mkdir(parents=True, exist_ok=True)
    return str(project_dir / f"{safe_name}_{as_of.isoformat()}.pptx")


TOTAL_STAGES = 7


@dataclass
class PipelineResult:
    findings: list[dict] = field(default_factory=list)
    status_analysis: dict = field(default_factory=dict)
    overall_status: str = ""
    outcome: str = ""
    final_summary: str = ""
    attempts: int = 0
    rendered_path: str | None = None
    report_id: int | None = None
    persisted: bool = False


async def run_reporting_stages(
    *,
    findings: list[dict],
    queried_item_count: int,
    tower_hierarchy: dict,
    project_endpoint: str,
    deployment_name: str,
    credential: DefaultAzureCredential,
    ado_project_name: str,
    status_deck_path: str,
    pptx_mcp_server_path: str,
    output_dir: str = "output",
    on_stage: Callable[[int, int, str], None] = noop_stage,
    on_detail: Callable[[str], None] = noop_detail,
) -> PipelineResult:
    """Stages 2-7 of the real pipeline — Status Update Analysis through
    Postgres persistence. Migration Plan Phase 4: stage 1 (Investigation)
    no longer happens here, or anywhere in this process. It runs in the
    separate Investigation service, coordinated via the
    investigation-requests/findings-ready Storage Queues; the Reporting
    service's own `reporting/main.py` performs that real round trip and
    fetches the real findings over HTTP (never from Investigation's own
    schema) before calling this function with the results already in
    hand. `scripts/run_pipeline.py` (the CLI's own standalone, un-queued
    entry point) instead calls `investigation.investigate.investigate`
    directly, in-process, then this function — see its own module
    docstring for why that composition lives there and not here: this
    module (`onepulse_common.pipeline`) is imported by core_api, bff,
    and the Reporting service, and must never import anything
    Investigation/Node/ADO-PAT-adjacent, so the composition of "real
    investigation, then real reporting" can only happen in a caller that
    is allowed to import both — the CLI script, not this shared module.

    `on_stage(n, total, message)` fires once per stage (see
    `TOTAL_STAGES` — stage numbers here still count from 1, matching the
    real 7-stage progress model every UI/status-table consumer already
    expects; this function's own first call is on_stage(2, ...)).
    `on_detail(message)` fires for finer-grained real-time detail within
    a stage (tool calls, draft text, pass/fail checks). Both default to
    no-ops.
    """
    chat_client = FoundryChatClient(project_endpoint=project_endpoint, model=deployment_name, credential=credential)

    if queried_item_count == 0:
        # Task 28/Part 2: a real, honest "nothing in scope" state — no
        # Features are tagged Committed for this project (yet). This is
        # NOT the empty-findings bug Part 1 fixes (N>0 items queried, 0
        # reported); here 0 items were ever in scope, so there is
        # genuinely nothing for Status Analysis/Synthesis/the quality
        # gate to do against. Skip them rather than run real agent calls
        # against an empty context, and say so plainly in the report
        # itself rather than silently investigating the whole project or
        # silently shipping a vague "approved" narrative.
        on_stage(2, TOTAL_STAGES, "Status Update Analysis — SKIPPED (no committed scope)")
        on_stage(3, TOTAL_STAGES, "Deterministic Status Rollup — SKIPPED (no committed scope)")
        on_stage(4, TOTAL_STAGES, "Synthesis — SKIPPED (no committed scope)")
        on_stage(5, TOTAL_STAGES, "Self-critique — SKIPPED (no committed scope)")
        status_analysis = {"untracked_initiatives": [], "possible_connections": []}
        overall_status = "Unknown"
        final_summary = "No committed features found for this project."
        outcome = "approved"
        attempts = 1
    else:
        on_stage(2, TOTAL_STAGES, f"Status Update Analysis — parsing '{status_deck_path}'")
        status_analysis = await analyze_status_deck(
            chat_client, findings, status_deck_path, pptx_mcp_server_path, on_detail
        )
        on_detail(f"{len(status_analysis['untracked_initiatives'])} untracked initiative(s) found")
        on_detail(f"{len(status_analysis['possible_connections'])} possible connection(s) found")

        on_stage(3, TOTAL_STAGES, "Deterministic Status Rollup (no model call)")
        statuses = [f["status"] for f in findings]
        overall_status = compute_overall_status(statuses)
        on_detail(f"Overall status: {overall_status.upper()}")

        on_stage(4, TOTAL_STAGES, "Synthesis — drafting executive summary")
        initial_summary = await synthesize(chat_client, findings, ado_project_name, on_detail=on_detail)

        on_stage(5, TOTAL_STAGES, "Self-critique — evaluating draft against the revision-cap gate")
        outcome, final_summary, attempts = await run_quality_gate(
            chat_client, findings, initial_summary, ado_project_name, queried_item_count, on_detail
        )
        on_detail(f"Revision-cap decision (HLD Section 3, no model call): {outcome}")

    if outcome == "hard_stop_defect":
        on_stage(6, TOTAL_STAGES, "Rendering — SKIPPED (hard stop: code-enforced check failed twice independently)")
        on_detail("Treated as a software defect, not a content issue. Nothing rendered or persisted.")
        return PipelineResult(
            findings=findings,
            status_analysis=status_analysis,
            overall_status=overall_status,
            outcome=outcome,
            final_summary=final_summary,
            attempts=attempts,
        )

    as_of = dt.date.today()
    # Real fix (Task 21): persist the SAME week-bucket already printed on
    # the rendered slide (render_status_report's own header text calls
    # this identical helper via report_rendering.week_of(as_of)) rather
    # than the raw run date. Reusing the one real implementation, not a
    # second copy of "Monday of the week" logic here.
    report_week_of = monday_of_week(as_of)
    output_path = build_output_path(ado_project_name, as_of, output_dir)

    # Task 36: real, deterministic Tower (Epic) rollup — empty when this
    # project's Committed Features have no real Epic parent above them
    # (singleSlide, Leave Tracker today). Computed here, not inside
    # investigate(), since it needs `findings` (the agent's own real FR-1
    # classification), which only exists after Investigation returns.
    towers = build_tower_rollups(findings, tower_hierarchy)

    on_stage(6, TOTAL_STAGES, f"Rendering final report -> {output_path}")
    if towers:
        on_detail(f"Real Tower View: {len(towers)} real Epic tower(s) found — using the executive Tower layout.")
        render_tower_report(
            program_name=ado_project_name,
            as_of=as_of,
            program_health_status=compute_program_health(towers),
            towers=towers,
            untracked_initiatives=status_analysis["untracked_initiatives"],
            output_path=output_path,
        )
    else:
        render_status_report(
            program_name=ado_project_name,
            as_of=as_of,
            overall_status=overall_status,
            executive_summary=final_summary,
            findings=[Finding(**f) for f in findings],
            output_path=output_path,
        )
    if outcome == "route_to_human_review":
        on_detail(
            "NOTE: subjective check still failed at the revision cap. This artifact requires human "
            "review before it would be considered approved (FR-7/FR-13, Human Governance)."
        )

    on_stage(7, TOTAL_STAGES, "Persisting report to Postgres (Phase 2 schema)")
    report_id, persisted = await persist_report(
        program_name=ado_project_name,
        week_of=report_week_of,
        overall_status=overall_status,
        quality_gate_outcome=outcome,
        executive_summary=final_summary,
        attempts=attempts,
        rendered_path=output_path,
        findings=findings,
        status_analysis=status_analysis,
    )
    if persisted:
        on_detail(f"Persisted as report_id={report_id} (reviewed=FALSE — Human Governance, FR-7, still applies).")
    else:
        on_detail(
            f"NOT persisted: a report for '{ado_project_name}', week of {report_week_of}, already exists "
            f"(report_id={report_id}). findings/untracked_items are INSERT-only at the database "
            "level (Phase 2's grants), so this run's fresh output cannot be safely reconciled into "
            "it — nothing was written or corrupted."
        )

    return PipelineResult(
        findings=findings,
        status_analysis=status_analysis,
        overall_status=overall_status,
        outcome=outcome,
        final_summary=final_summary,
        attempts=attempts,
        rendered_path=output_path,
        report_id=report_id,
        persisted=persisted,
    )
