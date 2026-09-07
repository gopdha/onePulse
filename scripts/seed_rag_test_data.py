"""Seeds ONE real, representative reports/findings/untracked_items row
set so the Chat Assistant has genuine, meaningful content to retrieve
from.

Honest gap this fills, stated plainly: run_pipeline.py (Phase 8-shaped
orchestration) has never persisted its real output to Postgres — that
wiring (Build Plan Phase 8's actual Definition of Done) doesn't exist
yet. Without it, the only rows in `reports` are Phase 7's test fixtures
(tests/test_human_governance.py), which carry placeholder text like
"test_human_governance.py fixture row" and no findings at all — nothing
a retrieval-grounded assistant could meaningfully answer questions
about.

This is NOT a substitute for that persistence wiring, and NOT invented
content: every fact below is real.
  - Work item titles/states (8: "Build Agentic Dashboard", New,
    unassigned; 9: "Analysis", To Do, unassigned; 10: "Coding", To Do,
    unassigned) were fetched live from the real `singleSlide` Azure
    DevOps project via the same PAT this project already uses
    (`GET .../_apis/wit/workitems?ids=8,9,10`), not recalled from an
    earlier run's notes.
  - The "vendor contract renewal" untracked item and its exact wording
    are copied verbatim from scripts/create_sample_status_deck.py — a
    real fixture already committed to this repo for Task 6 (Status
    Update Analysis), not written fresh for this task.
  - All three findings are classified "Needs Human Review": each real
    work item is untouched (New/To Do, no assignee) despite being
    referenced as active work in the team lead's status update — a
    real discrepancy, not an assumed classification. This matches what
    Task 6's real live agent run already found independently.

Idempotent: keyed on (program_id, week_of); safe to re-run.

Run: python scripts/seed_rag_test_data.py --target dev
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import os

from dotenv import load_dotenv

from onepulse_common.config import PostgresSettings
from onepulse_common.db import PostgresClient

load_dotenv()

TARGETS: dict[str, PostgresSettings] = {
    "dev": PostgresSettings(
        host="onepulse-pg-dev.postgres.database.azure.com",
        database="onepulse",
        role_name=os.environ.get("ONEPULSE_PG_ROLE", "app_role_local_dev"),
    ),
}

PROGRAM_NAME = "singleSlide"
WEEK_OF = dt.date(2026, 9, 1)

EXECUTIVE_SUMMARY = (
    "Program singleSlide shows three tracked work items awaiting attention: 'Build Agentic "
    "Dashboard' (item 8, state New, unassigned), 'Analysis' (item 9, state To Do, unassigned), "
    "and 'Coding' (item 10, state To Do, unassigned) — none show recorded progress in Azure "
    "DevOps despite the team lead's status update describing active work on two of them. The "
    "status update also references a vendor contract renewal blocked on external legal counsel "
    "review; this has no corresponding Azure DevOps work item and is not currently tracked."
)

# Real ADO data, fetched live 2026-09-06 via GET .../_apis/wit/workitems?ids=8,9,10 —
# not reconstructed from memory of an earlier run.
FINDINGS = [
    {
        "source_item_ref": "8",
        "title": "Build Agentic Dashboard",
        "status_label": "Needs Human Review",
        "evidence": (
            "Azure DevOps work item 8 ('Build Agentic Dashboard') is in state 'New' with no "
            "assignee — no work has started and no owner is identified."
        ),
    },
    {
        "source_item_ref": "9",
        "title": "Analysis",
        "status_label": "Needs Human Review",
        "evidence": (
            "Azure DevOps work item 9 ('Analysis') is in state 'To Do' with no assignee, though "
            "the team lead's status update claims analysis work is 'wrapping up this week, "
            "findings being written up.'"
        ),
    },
    {
        "source_item_ref": "10",
        "title": "Coding",
        "status_label": "Needs Human Review",
        "evidence": (
            "Azure DevOps work item 10 ('Coding') is in state 'To Do' with no assignee, though "
            "the team lead's status update claims implementation is 'underway, on pace for end "
            "of sprint.'"
        ),
    },
]

# Verbatim from scripts/create_sample_status_deck.py's real bullet text.
UNTRACKED_ITEM = {
    "description": "Vendor contract renewal",
    "evidence": (
        "Team Lead Status Update — Week of Sept 1: 'Vendor contract renewal: blocked on "
        "external counsel review, no ETA yet from Legal. Not currently tracked as an Azure "
        "DevOps work item.'"
    ),
    "reasoning": (
        "No Azure DevOps work item in singleSlide references a vendor contract or legal "
        "review; items 8/9/10 correspond to 'Build Agentic Dashboard', 'Analysis', and "
        "'Coding' respectively."
    ),
}


async def seed(settings: PostgresSettings) -> None:
    client = await PostgresClient.connect(settings, min_size=1, max_size=1)
    try:
        async with client.pool.acquire() as conn:
            program_id = await conn.fetchval("SELECT program_id FROM programs WHERE name = $1", PROGRAM_NAME)
            if program_id is None:
                raise RuntimeError(f"Program '{PROGRAM_NAME}' not found — run scripts/seed_dev_data.py first.")

            report_id = await conn.fetchval(
                "SELECT report_id FROM reports WHERE program_id = $1 AND week_of = $2", program_id, WEEK_OF
            )
            if report_id is not None:
                print(f"Report already exists: {report_id} ({PROGRAM_NAME}, week of {WEEK_OF}) — not re-seeding.")
                return

            async with conn.transaction():
                report_id = await conn.fetchval(
                    """
                    INSERT INTO reports (program_id, week_of, rag_status, quality_gate_outcome, executive_summary)
                    VALUES ($1, $2, 'Amber', 'approved', $3)
                    RETURNING report_id
                    """,
                    program_id,
                    WEEK_OF,
                    EXECUTIVE_SUMMARY,
                )
                print(f"Created report: {report_id} ({PROGRAM_NAME}, week of {WEEK_OF})")

                for finding in FINDINGS:
                    finding_id = await conn.fetchval(
                        """
                        INSERT INTO findings (report_id, source_item_ref, title, status_label, evidence)
                        VALUES ($1, $2, $3, $4, $5)
                        RETURNING finding_id
                        """,
                        report_id,
                        finding["source_item_ref"],
                        finding["title"],
                        finding["status_label"],
                        finding["evidence"],
                    )
                    print(f"  Created finding: {finding_id} — {finding['title']} (item {finding['source_item_ref']})")

                untracked_id = await conn.fetchval(
                    """
                    INSERT INTO untracked_items (report_id, description, evidence, reasoning)
                    VALUES ($1, $2, $3, $4)
                    RETURNING untracked_item_id
                    """,
                    report_id,
                    UNTRACKED_ITEM["description"],
                    UNTRACKED_ITEM["evidence"],
                    UNTRACKED_ITEM["reasoning"],
                )
                print(f"  Created untracked item: {untracked_id} — {UNTRACKED_ITEM['description']}")
    finally:
        await client.close()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True, choices=list(TARGETS))
    args = parser.parse_args()
    await seed(TARGETS[args.target])


if __name__ == "__main__":
    asyncio.run(main())
