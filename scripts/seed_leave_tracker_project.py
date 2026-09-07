"""One-off administrative seeding script for a second, richer real Azure
DevOps project ("Leave Tracker") — better demo/test data than
singleSlide's original three items, deliberately covering every FR-1
status tier (On Track/At Risk/Blocked/Needs Human Review... mapped here
to this Scrum process template's real states) plus Done/Closed work,
which nothing in this project has exercised live before.

Deliberately separate from Investigation/Status Update Analysis's own
scoped, read-only MCP tool access (Physical Architecture's least-
privilege design, NFR-3) — this script uses `az boards`/`az devops`
directly (the operator's own authenticated `az login` session, not the
PAT those agents use) plus one direct REST call for a doc-library
comment `az boards` has no CLI surface for. Real infrastructure, not a
mock: every ID printed below is a real Azure DevOps work item created
in the real `gopdha` org.

Real field-value mapping note: this org's existing projects (singleSlide)
use the Scrum process template, whose real states are "To Do / In
Progress / Done / Removed" (Task) and "New / In Progress / Done /
Removed" (Feature) — confirmed live via
`az devops invoke --resource workitemtypes` before writing this, not
assumed from a generic Agile/CMMI template. There is no "Active" or
"Closed" state in this real template, so those informal labels map to
"In Progress" and "Done" respectively below.

Real, honest limitation: Azure DevOps sets `System.ChangedDate` from the
actual wall-clock time of the last real field change — it cannot be
backdated through any real API. The "stale/blocked" work item below is
therefore not literally old the moment this script runs; its real
signal for the Investigation agent is the state + a real, specific
comment describing an actual blocker, not a fabricated old timestamp.

Run once: python scripts/seed_leave_tracker_project.py
"""

from __future__ import annotations

import json
import shutil
import subprocess

ORG_URL = "https://dev.azure.com/gopdha"
PROJECT_NAME = "Leave Tracker"
REAL_ASSIGNEE = "gopdha@gmail.com"  # the only real user in this org, confirmed via `az devops user list`

# On Windows, the real az CLI installs as az.cmd; subprocess.run's default
# (non-shell) CreateProcess call can't resolve that the way a shell does,
# so resolve the real executable path explicitly rather than assume "az"
# alone works cross-platform.
AZ_EXECUTABLE = shutil.which("az.cmd") or shutil.which("az") or "az"


def run_az(args: list[str]) -> dict:
    # Real, live-hit issue: az.cmd on Windows relays subprocess output
    # through a console codepage that isn't UTF-8, so a real em dash in
    # a --discussion/--title argument crashed the reader thread with a
    # UnicodeDecodeError under strict utf-8 decoding. errors="replace"
    # keeps this robust regardless of what any future argument contains;
    # kept plain ASCII in this script's own text either way.
    result = subprocess.run(
        [AZ_EXECUTABLE, *args, "--organization", ORG_URL, "--output", "json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"az {' '.join(args)} failed:\n{result.stderr}")
    return json.loads(result.stdout) if result.stdout.strip() else {}


def create_project() -> None:
    existing = run_az(["devops", "project", "list"])
    names = [p["name"] for p in existing.get("value", [])]
    if PROJECT_NAME in names:
        print(f"Project '{PROJECT_NAME}' already exists — not recreating.")
        return
    print(f"Creating real Azure DevOps project '{PROJECT_NAME}'...")
    run_az(
        [
            "devops",
            "project",
            "create",
            "--name",
            PROJECT_NAME,
            "--process",
            "Scrum",
            "--source-control",
            "git",
            "--visibility",
            "private",
        ]
    )
    print(f"Created '{PROJECT_NAME}'.")


def create_work_item(
    *,
    work_item_type: str,
    title: str,
    state: str,
    assigned_to: str | None = None,
    discussion: str | None = None,
) -> int:
    """Real, checked two-step flow — NOT the obvious single-call one.
    `az boards work-item create --fields "System.State=..."` genuinely
    fails live ("not in the list of supported values") even for a
    confirmed-valid state name; isolated and confirmed the real, working
    mechanism is `create` (title/type/assignment only) followed by a
    separate `update --state ... --discussion ...` call, which has its
    own dedicated `--state` flag `create` lacks.
    """
    create_args = [
        "boards",
        "work-item",
        "create",
        "--project",
        PROJECT_NAME,
        "--type",
        work_item_type,
        "--title",
        title,
    ]
    if assigned_to:
        create_args += ["--assigned-to", assigned_to]
    work_item_id = run_az(create_args)["id"]

    update_args = ["boards", "work-item", "update", "--id", str(work_item_id), "--state", state]
    if discussion:
        update_args += ["--discussion", discussion]
    run_az(update_args)

    print(f"  #{work_item_id} [{work_item_type}, {state}] {title}")
    return work_item_id


def seed_work_items() -> dict[str, int]:
    print("\nSeeding real work items...")
    ids: dict[str, int] = {}

    # GREEN candidates: In Progress, assigned, real recent progress comments.
    ids["submission_form"] = create_work_item(
        work_item_type="Task",
        title="Implement leave request submission form",
        state="In Progress",
        assigned_to=REAL_ASSIGNEE,
        discussion=(
            "Frontend form is functional - built with React Hook Form, client-side validation for "
            "date ranges and leave type selection working. Wiring up the submit handler to the "
            "approval API next."
        ),
    )
    ids["approval_workflow"] = create_work_item(
        work_item_type="Task",
        title="Build manager approval workflow",
        state="In Progress",
        assigned_to=REAL_ASSIGNEE,
        discussion=(
            "Approval API endpoints (POST /approvals, PATCH /approvals/{id}) are implemented and "
            "passing integration tests. Working on the manager notification trigger next."
        ),
    )

    # AMBER candidates: unassigned, no comments, matching singleSlide's real proven pattern.
    ids["balance_logic"] = create_work_item(
        work_item_type="Feature",
        title="Design leave balance calculation logic",
        state="New",
    )
    ids["email_service"] = create_work_item(
        work_item_type="Task",
        title="Set up email notification service",
        state="To Do",
    )

    # RED candidate: a real, specific blocker comment — a tier never yet exercised live.
    ids["payroll_integration"] = create_work_item(
        work_item_type="Task",
        title="Integrate with HR payroll system",
        state="In Progress",
        discussion=(
            "Blocked: vendor has not yet provided the sandbox API credentials for the payroll "
            "integration. Followed up with their support team on 2026-09-02, still waiting on a "
            "response. No further progress possible until credentials are received."
        ),
    )

    # Done/Closed: real closing comments — tests Synthesis doesn't over-flag finished work.
    ids["ci_cd"] = create_work_item(
        work_item_type="Task",
        title="Set up project repository and CI/CD pipeline",
        state="Done",
        discussion=(
            "Repository created, branch protection rules configured, and the CI/CD pipeline "
            "(build + test + lint on every PR) is live and passing. Closing this out."
        ),
    )
    ids["db_schema"] = create_work_item(
        work_item_type="Task",
        title="Create database schema for leave types",
        state="Done",
        discussion=(
            "Schema finalized and migrated: leave_types table with accrual rules, carryover "
            "limits, and eligibility rules per type. Reviewed with the team, no further changes "
            "needed."
        ),
    )

    return ids


def write_status_deck(ids: dict[str, int]) -> None:
    from pptx import Presentation
    from pptx.util import Inches, Pt

    output_path = "leave_tracker_status_deck.pptx"

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])

    title_box = slide.shapes.add_textbox(Inches(0.5), Inches(0.4), Inches(9), Inches(0.6))
    title_box.text_frame.paragraphs[0].text = "Team Lead Status Update — Leave Tracker — Week of Sept 6"
    title_box.text_frame.paragraphs[0].font.size = Pt(24)
    title_box.text_frame.paragraphs[0].font.bold = True

    body_box = slide.shapes.add_textbox(Inches(0.5), Inches(1.3), Inches(9), Inches(5))
    tf = body_box.text_frame
    tf.word_wrap = True

    bullets = [
        f"Leave request submission form (#{ids['submission_form']}): frontend nearly done, "
        "on track for this sprint.",
        f"Manager approval workflow (#{ids['approval_workflow']}): backend API work progressing well.",
        f"Payroll system integration (#{ids['payroll_integration']}): stuck waiting on the vendor "
        "for API credentials — no ETA yet.",
        f"Database schema for leave types (#{ids['db_schema']}) and the CI/CD pipeline setup "
        f"(#{ids['ci_cd']}) are both wrapped up.",
        "Mobile app support for leave requests: design discussions are in progress with the "
        "mobile team. Not yet tracked as an Azure DevOps work item.",
    ]
    for i, bullet in enumerate(bullets):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = f"• {bullet}"
        p.font.size = Pt(15)

    prs.save(output_path)
    print(f"\nWrote {output_path}")


def main() -> None:
    create_project()
    ids = seed_work_items()
    write_status_deck(ids)
    print("\nReal work item IDs:", json.dumps(ids, indent=2))


if __name__ == "__main__":
    main()
