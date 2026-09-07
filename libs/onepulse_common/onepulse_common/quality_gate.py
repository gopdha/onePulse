"""Quality Assurance & Revision cap decision (HLD Section 3; closes FR-4).

Build Plan Phase 5: "a code-enforced check failing twice independently is
a hard stop with nothing persisted, not a silent pass... write the
regression test that forces a code-enforced check to fail twice and
proves the hard stop actually fires" — before any other Phase 5 work.
This module is that fixed decision logic; the regression test lives in
tests/test_quality_gate.py.

HLD Section 3's distinction, exactly:
  - A code-enforced check (deterministic, no model call — e.g. the risk
    floor below) is re-verified independently at two points: before the
    one permitted revision, and after it. If it fails both times, the
    two independent evaluations disagree with reality in the same way
    twice, which HLD treats as a software defect, not a content
    judgment call — hard stop, nothing persisted.
  - A subjective, skill-defined check (tone, conciseness — judged by the
    Self-critique agent) still failing at the cap is a legitimate content
    outcome, not a defect: it routes to human review rather than halting.

`decide_revision_outcome` is pure and deterministic — no model call, and
it never itself judges content; it only interprets verdicts computed
elsewhere. This is what FR-4's "revise up to a bounded number of times"
gate compiles down to.

`code_enforced_risk_floor_check` is this project's first concrete
definition of the "risk floor" HLD Section 3 names as its own example
(such as the risk floor — no critical item may be silently dropped) but
does not spell out with exact thresholds. Concretely: every finding
whose FR-1 status is Blocked or Needs Human Review — the two statuses
that most need a human's attention — must be referenced in the draft
narrative. Open to revision, but auditable and worth recording precisely
because nothing upstream fixed it yet.

Real, serious gap found and fixed (Task 28), from a real stress test at
scale (Task 27): the check above only ever loops over `findings` itself
— against a genuinely EMPTY findings list, that loop never executes and
the function vacuously returns True. A real run against a 465-item
project let Investigation return zero findings; Synthesis then wrote a
vague, falsely-reassuring narrative around them; and this check waved it
through as "approved" with zero errors anywhere. `queried_item_count`
closes this: it is how many real items were actually in scope to
investigate, computed deterministically by the caller (not the model),
so the check can tell "zero findings because zero real items existed to
investigate" (a legitimate, honest state) apart from "zero, or
suspiciously few, findings when N>0 items were actually queried" (a real
defect). The bar chosen is exact coverage (`len(findings) >=
queried_item_count`), not a fuzzy percentage — defensible specifically
because Task 28/Part 2 bounds real Investigation scope tightly (Committed
Features + their real children only, not an entire project), making full
coverage a real, achievable, auditable bar rather than an arbitrary
tolerance. Because `findings` itself does not change between the
pre-revision and post-revision check (only the narrative text does — see
`pipeline.run_quality_gate`), a genuine coverage shortfall is now
structurally guaranteed to fail both checks and correctly reach
`hard_stop_defect` below — revision cannot manufacture findings the
underlying investigation never produced.
"""

from __future__ import annotations

from typing import Literal

RevisionOutcome = Literal["approved", "hard_stop_defect", "route_to_human_review"]

_CRITICAL_STATUSES = frozenset({"Blocked", "Needs Human Review"})


def code_enforced_risk_floor_check(findings: list[dict], narrative: str, queried_item_count: int) -> bool:
    """True iff (1) findings cover every real item that was actually
    queried, and (2) no critical (Blocked / Needs Human Review) finding
    is silently dropped from the narrative. Pure, deterministic — no
    model call; a finding is "referenced" if its id or title literally
    appears in the narrative text.

    `queried_item_count` is required, not optional, so no caller can
    silently fall back to the old vacuous-on-empty behavior without
    deciding what "how many items were actually in scope" means for its
    own call site. Pass 0 for a genuine, honest zero-scope run (e.g.
    Task 28/Part 2's "no Features tagged Committed" case) — that
    trivially passes, since there is nothing to have dropped.
    """
    if queried_item_count > 0 and len(findings) < queried_item_count:
        return False
    for finding in findings:
        if finding["status"] not in _CRITICAL_STATUSES:
            continue
        if str(finding["work_item_id"]) not in narrative and finding["title"] not in narrative:
            return False
    return True


def decide_revision_outcome(
    *,
    code_enforced_ok_before_revision: bool,
    code_enforced_ok_after_revision: bool,
    subjective_ok_after_revision: bool,
) -> RevisionOutcome:
    """HLD Section 3's revision-cap decision. Only meaningful when a
    revision was actually triggered (code_enforced_ok_before_revision is
    False) — if the initial draft passed everything there is no
    revision and this function is not consulted.
    """
    if not code_enforced_ok_before_revision and not code_enforced_ok_after_revision:
        return "hard_stop_defect"
    if not subjective_ok_after_revision:
        return "route_to_human_review"
    return "approved"
