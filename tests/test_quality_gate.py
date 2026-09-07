"""Build Plan Phase 5: written before the Self-critique agent exists.
Proves the hard stop actually fires and that nothing gets persisted when
it does — not just that the decision function returns the right label.
"""

from __future__ import annotations

import datetime as dt
import os

from onepulse_common.quality_gate import (
    code_enforced_risk_floor_check,
    decide_revision_outcome,
)
from onepulse_common.report_rendering import Finding, render_status_report

CRITICAL_FINDING = {"work_item_id": 99, "title": "Vendor Legal Review", "status": "Blocked", "evidence": "x"}
SAFE_FINDING = {"work_item_id": 1, "title": "Build Dashboard", "status": "On Track", "evidence": "x"}


# -- code_enforced_risk_floor_check: the check itself -----------------------


def test_risk_floor_passes_when_critical_finding_is_mentioned() -> None:
    narrative = "Vendor Legal Review (99) is blocked pending counsel."
    assert code_enforced_risk_floor_check([CRITICAL_FINDING], narrative, queried_item_count=1) is True


def test_risk_floor_fails_when_critical_finding_is_silently_dropped() -> None:
    narrative = "Everything is going smoothly this week."
    assert code_enforced_risk_floor_check([CRITICAL_FINDING], narrative, queried_item_count=1) is False


def test_risk_floor_ignores_non_critical_findings() -> None:
    narrative = "Everything is going smoothly this week."
    assert code_enforced_risk_floor_check([SAFE_FINDING], narrative, queried_item_count=1) is True


# -- code_enforced_risk_floor_check: real coverage extension (Task 28,
#    closing the vacuous-truth bug Task 27's stress test found — an
#    empty findings list against a NONZERO real queried count used to
#    vacuously pass, since the old check's for-loop never executed) ------


def test_risk_floor_fails_on_empty_findings_when_items_were_actually_queried() -> None:
    # The exact real Task 27 scenario: Investigation queried 465 real
    # items and returned zero findings. Must now FAIL, not vacuously pass.
    assert code_enforced_risk_floor_check([], "Nothing to report this period.", queried_item_count=465) is False


def test_risk_floor_passes_on_empty_findings_when_zero_items_were_queried() -> None:
    # A real, honest "nothing in scope" state (Task 28/Part 2: zero
    # Features tagged Committed) is NOT the same bug — there is nothing
    # that could have been dropped, so this must legitimately pass.
    assert code_enforced_risk_floor_check([], "No committed features found for this project.", queried_item_count=0) is True


def test_risk_floor_fails_on_suspiciously_incomplete_findings() -> None:
    # 465 real items were queried; only 20 came back as findings (Task
    # 27's second real run) — real, partial coverage, not just the
    # totally-empty case, must also fail.
    findings = [{"work_item_id": i, "title": f"Item {i}", "status": "On Track", "evidence": "x"} for i in range(20)]
    narrative = "Twenty items reviewed, all on track."
    assert code_enforced_risk_floor_check(findings, narrative, queried_item_count=465) is False


def test_risk_floor_passes_on_full_coverage() -> None:
    findings = [{"work_item_id": i, "title": f"Item {i}", "status": "On Track", "evidence": "x"} for i in range(5)]
    narrative = "Five items reviewed, all on track."
    assert code_enforced_risk_floor_check(findings, narrative, queried_item_count=5) is True


# -- decide_revision_outcome: the decision logic -----------------------------


def test_code_enforced_check_failing_twice_is_hard_stop() -> None:
    outcome = decide_revision_outcome(
        code_enforced_ok_before_revision=False,
        code_enforced_ok_after_revision=False,
        subjective_ok_after_revision=True,
    )
    assert outcome == "hard_stop_defect"


def test_code_enforced_recovering_after_revision_is_approved() -> None:
    outcome = decide_revision_outcome(
        code_enforced_ok_before_revision=False,
        code_enforced_ok_after_revision=True,
        subjective_ok_after_revision=True,
    )
    assert outcome == "approved"


def test_subjective_still_failing_at_cap_routes_to_human_review_not_hard_stop() -> None:
    outcome = decide_revision_outcome(
        code_enforced_ok_before_revision=False,
        code_enforced_ok_after_revision=True,
        subjective_ok_after_revision=False,
    )
    assert outcome == "route_to_human_review"


def test_code_enforced_failure_takes_priority_over_subjective_failure() -> None:
    # Both fail at the cap — HLD Section 3 treats the code-enforced
    # disagreement as the defect signal, not the subjective outcome.
    outcome = decide_revision_outcome(
        code_enforced_ok_before_revision=False,
        code_enforced_ok_after_revision=False,
        subjective_ok_after_revision=False,
    )
    assert outcome == "hard_stop_defect"


# -- Integration: force the check to fail twice, prove the hard stop
#    actually fires and nothing is written to disk -------------------------


def _run_gate_and_maybe_render(
    findings: list[dict],
    draft_before_revision: str,
    draft_after_revision: str,
    output_path: str,
    queried_item_count: int | None = None,
) -> str:
    """A minimal real orchestration of the HLD Section 3 gate: check the
    initial draft, revise once if needed, check again, decide, and only
    call render_status_report — the pipeline's actual persistence step —
    when the outcome permits it. Returns the outcome.

    `queried_item_count` defaults to `len(findings)` (full coverage) so
    every pre-existing caller of this helper keeps its original,
    unaffected behavior; Task 28's new coverage-shortfall test passes it
    explicitly.
    """
    if queried_item_count is None:
        queried_item_count = len(findings)
    ok_before = code_enforced_risk_floor_check(findings, draft_before_revision, queried_item_count)
    if ok_before:
        narrative = draft_before_revision
        outcome = "approved"
    else:
        ok_after = code_enforced_risk_floor_check(findings, draft_after_revision, queried_item_count)
        narrative = draft_after_revision
        outcome = decide_revision_outcome(
            code_enforced_ok_before_revision=ok_before,
            code_enforced_ok_after_revision=ok_after,
            subjective_ok_after_revision=True,
        )

    if outcome != "hard_stop_defect":
        render_status_report(
            program_name="test-program",
            as_of=dt.date(2026, 1, 1),
            overall_status="Amber",
            executive_summary=narrative,
            findings=[Finding(**f) for f in findings],
            output_path=output_path,
        )
    return outcome


def test_hard_stop_actually_fires_and_nothing_is_persisted(tmp_path) -> None:
    output_path = str(tmp_path / "should_not_exist.pptx")
    findings = [CRITICAL_FINDING]

    # The critical finding is dropped from BOTH the initial draft and the
    # revised draft — the code-enforced check fails twice, independently.
    outcome = _run_gate_and_maybe_render(
        findings,
        draft_before_revision="Everything is going smoothly this week.",
        draft_after_revision="Still all smooth, nothing to flag.",
        output_path=output_path,
    )

    assert outcome == "hard_stop_defect"
    assert not os.path.exists(output_path), "hard stop must not persist any artifact"


def test_empty_findings_against_real_queried_count_hard_stops_and_nothing_persists(tmp_path) -> None:
    """The exact real Task 27 scenario, reproduced as a regression test:
    Investigation queried 465 real items and returned zero findings;
    Synthesis wrote a vague, reassuring narrative around them anyway.
    Revision cannot manufacture findings the investigation never
    produced — `findings` is unchanged before/after revision — so this
    must hard-stop deterministically, on the first pass, every time.
    """
    output_path = str(tmp_path / "should_not_exist.pptx")

    outcome = _run_gate_and_maybe_render(
        findings=[],
        draft_before_revision="No investigated findings have been recorded this period. Monitoring continues.",
        draft_after_revision="Still nothing recorded, monitoring continues.",
        output_path=output_path,
        queried_item_count=465,
    )

    assert outcome == "hard_stop_defect"
    assert not os.path.exists(output_path), "an empty-relative-to-queried-scope report must not be persisted"


def test_suspiciously_incomplete_findings_also_hard_stops(tmp_path) -> None:
    """Task 27's second real run: 465 items queried, only 20 findings
    came back, cleanly (finish_reason=stop, not truncated) — a real,
    partial-coverage case, not the totally-empty one above.
    """
    output_path = str(tmp_path / "should_not_exist_either.pptx")
    findings = [{"work_item_id": i, "title": f"Item {i}", "status": "On Track", "evidence": "x"} for i in range(20)]

    outcome = _run_gate_and_maybe_render(
        findings=findings,
        draft_before_revision="Twenty items reviewed, all on track.",
        draft_after_revision="Twenty items reviewed, all on track, still.",
        output_path=output_path,
        queried_item_count=465,
    )

    assert outcome == "hard_stop_defect"
    assert not os.path.exists(output_path)


def test_zero_queried_items_is_a_legitimate_state_not_a_defect(tmp_path) -> None:
    """Task 28/Part 2's honest "no committed scope" state must NOT be
    treated as the same defect as the two tests above — zero items
    queried, zero findings, is not incomplete coverage of anything.
    """
    output_path = str(tmp_path / "legitimately_empty.pptx")

    outcome = _run_gate_and_maybe_render(
        findings=[],
        draft_before_revision="No committed features found for this project.",
        draft_after_revision="No committed features found for this project.",
        output_path=output_path,
        queried_item_count=0,
    )

    assert outcome == "approved"
    assert os.path.exists(output_path), "a genuine zero-scope report is real output and should still be rendered"


def test_recovery_after_one_revision_does_get_persisted(tmp_path) -> None:
    output_path = str(tmp_path / "should_exist.pptx")
    findings = [CRITICAL_FINDING]

    # The critical finding is missing initially but present after the
    # one permitted revision — this is the ordinary, expected path.
    outcome = _run_gate_and_maybe_render(
        findings,
        draft_before_revision="Everything is going smoothly this week.",
        draft_after_revision="Vendor Legal Review (99) is blocked pending counsel.",
        output_path=output_path,
    )

    assert outcome == "approved"
    assert os.path.exists(output_path), "an approved draft must actually be rendered"
