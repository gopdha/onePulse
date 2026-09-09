"""Real regression tests for the pure stage-curation logic relocated to
`onepulse_common.cycle_progress` for Migration Plan Phase 3 — this exact
logic previously lived in `Home.py`'s `run_generation()` (Task 32/37)
and was never directly unit-tested there (UI code isn't); now that it's
real, shared business logic the worker depends on to build the `cycles`
status table, it gets real, direct tests. Every message shape here is a
real message `onepulse_common.pipeline`'s own on_stage/on_detail calls
actually produce (confirmed via grep against pipeline.py before writing
these, not invented).
"""

from __future__ import annotations

from onepulse_common.cycle_progress import (
    advance_stage,
    apply_detail,
    finalize_stage_state,
    mark_failed,
    new_stage_state,
)


def test_new_stage_state_starts_every_stage_pending() -> None:
    stages = new_stage_state(7)
    assert len(stages) == 7
    assert all(s["status"] == "pending" for s in stages.values())


def test_advance_stage_opens_stage_1_running_and_records_start_ts() -> None:
    stages = new_stage_state(7)
    shared: dict = {}
    advance_stage(stages, shared, 1, 7, "Investigation — querying real Committed-tagged Features", now_ts=100.0)
    assert stages[1]["status"] == "running"
    assert stages[1]["start_ts"] == 100.0
    assert shared["current_stage"] == 1


def test_advance_stage_closes_the_previous_running_stage() -> None:
    stages = new_stage_state(7)
    shared: dict = {}
    advance_stage(stages, shared, 1, 7, "Investigation", now_ts=100.0)
    advance_stage(stages, shared, 2, 7, "Status Update Analysis — parsing 'deck.pptx'", now_ts=110.0)
    assert stages[1]["status"] == "done"
    assert stages[1]["end_ts"] == 110.0
    assert stages[1]["detail"] == "done"  # real fallback when no on_detail ever set one
    assert stages[2]["status"] == "running"


def test_advance_stage_handles_a_real_skipped_message() -> None:
    stages = new_stage_state(7)
    shared: dict = {"current_stage": 1}
    stages[1]["status"] = "running"
    advance_stage(stages, shared, 2, 7, "Status Update Analysis — SKIPPED (no committed scope)", now_ts=105.0)
    assert stages[2]["status"] == "skipped"
    assert stages[2]["detail"] == "no committed scope"


def test_advance_stage_6_parses_the_real_rendered_output_path() -> None:
    stages = new_stage_state(7)
    shared: dict = {"current_stage": 5}
    stages[5]["status"] = "running"
    advance_stage(
        stages, shared, 6, 7,
        r"Rendering final report -> output\Agentic AI Observability Platform\Agentic AI Observability Platform_2026-09-10.pptx",
        now_ts=200.0,
    )
    assert stages[6]["detail"] == "saved Agentic AI Observability Platform_2026-09-10.pptx"


def test_apply_detail_stage_1_parses_real_feature_and_finding_counts() -> None:
    stages = new_stage_state(7)
    shared: dict = {"current_stage": 1}
    apply_detail(stages, shared, 1, "Querying real children of 7 Committed Feature(s)")
    apply_detail(stages, shared, 1, "#313 Build OTEL Collector — On Track")
    apply_detail(stages, shared, 1, "#324 Improve dashboards — Needs Human Review")
    assert shared["feature_count"] == 7
    assert shared["pending_findings_count"] == 2
    assert shared["flagged_findings_count"] == 1  # only the non-"On Track" one counts
    assert stages[1]["detail"] == "2 item(s) across 7 committed feature(s)"


def test_apply_detail_stage_1_zero_scope_sets_a_real_honest_detail() -> None:
    stages = new_stage_state(7)
    shared: dict = {"current_stage": 1}
    apply_detail(stages, shared, 1, "No Features tagged 'Committed' found for this project.")
    assert shared["zero_scope"] is True
    assert stages[1]["detail"] == "no committed features found"


def test_apply_detail_stage_2_parses_real_untracked_and_connection_counts() -> None:
    stages = new_stage_state(7)
    shared: dict = {"current_stage": 2}
    apply_detail(stages, shared, 2, "1 untracked initiative(s) found")
    apply_detail(stages, shared, 2, "6 possible connection(s) found")
    assert stages[2]["detail"] == "1 untracked initiative(s), 6 possible connection(s)"


def test_apply_detail_stage_3_parses_the_real_computed_overall_status() -> None:
    stages = new_stage_state(7)
    shared: dict = {"current_stage": 3}
    apply_detail(stages, shared, 3, "Overall status: AMBER")
    assert stages[3]["detail"] == "overall status: AMBER"


def test_apply_detail_stage_5_records_the_real_revision_cap_decision_after_a_revision() -> None:
    stages = new_stage_state(7)
    shared: dict = {"current_stage": 5, "flagged_findings_count": 3}
    apply_detail(stages, shared, 5, 'Draft: "Here is the executive summary..."')
    apply_detail(stages, shared, 5, "Triggering the one permitted revision (HLD Section 3)")
    apply_detail(stages, shared, 5, "Revised draft: ...")
    apply_detail(stages, shared, 5, "Revision-cap decision (HLD Section 3, no model call): approved")
    assert stages[4]["detail"] == "executive summary drafted, 3 item(s) flagged for review"
    assert stages[5]["detail"] == "approved after 1 revision"
    assert stages[5]["live_note"] is None


def test_apply_detail_stage_5_records_first_attempt_when_no_revision_fired() -> None:
    stages = new_stage_state(7)
    shared: dict = {"current_stage": 5}
    apply_detail(stages, shared, 5, "Revision-cap decision (HLD Section 3, no model call): hard_stop_defect")
    assert stages[5]["detail"] == "hard_stop_defect on first attempt"


def test_apply_detail_stage_7_persisted_and_not_persisted() -> None:
    stages = new_stage_state(7)
    shared: dict = {"current_stage": 7}
    apply_detail(stages, shared, 7, "Persisted as report_id=612 (reviewed=FALSE...)")
    assert stages[7]["detail"] == "report_id=612 saved"

    stages2 = new_stage_state(7)
    shared2: dict = {"current_stage": 7}
    apply_detail(stages2, shared2, 7, "NOT persisted: a report for 'X', week of 2026-09-08, already exists...")
    assert stages2[7]["detail"] == "not persisted — report already exists for this week"


def test_finalize_stage_state_closes_the_trailing_running_stage() -> None:
    stages = new_stage_state(7)
    shared: dict = {"current_stage": 7}
    stages[7]["status"] = "running"
    stages[7]["start_ts"] = 100.0
    finalize_stage_state(stages, shared, now_ts=150.0, total=7, outcome="approved")
    assert stages[7]["status"] == "done"
    assert stages[7]["end_ts"] == 150.0


def test_finalize_stage_state_marks_remaining_pending_stages_skipped_on_hard_stop() -> None:
    stages = new_stage_state(7)
    shared: dict = {"current_stage": 5}
    stages[5]["status"] = "running"
    finalize_stage_state(stages, shared, now_ts=200.0, total=7, outcome="hard_stop_defect")
    assert stages[5]["status"] == "done"
    assert stages[6]["status"] == "skipped"
    assert stages[7]["status"] == "skipped"
    assert stages[6]["detail"] == "hard stop — nothing to persist"


def test_mark_failed_marks_the_in_flight_stage_failed_with_real_error_text() -> None:
    stages = new_stage_state(7)
    shared: dict = {"current_stage": 1}
    stages[1]["status"] = "running"
    mark_failed(stages, shared, now_ts=300.0, error_text="ConnectionError: MCP server unreachable")
    assert stages[1]["status"] == "failed"
    assert stages[1]["detail"] == "ConnectionError: MCP server unreachable"
