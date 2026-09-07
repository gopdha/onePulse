import pytest

from onepulse_common.status_rollup import compute_overall_status


def test_no_items_is_unknown() -> None:
    assert compute_overall_status([]) == "Unknown"


def test_all_on_track_is_green() -> None:
    assert compute_overall_status(["On Track", "On Track"]) == "Green"


def test_any_at_risk_is_amber() -> None:
    assert compute_overall_status(["On Track", "At Risk"]) == "Amber"


def test_any_needs_human_review_is_amber() -> None:
    assert compute_overall_status(["On Track", "Needs Human Review"]) == "Amber"


def test_any_blocked_is_red() -> None:
    assert compute_overall_status(["On Track", "At Risk", "Blocked"]) == "Red"


def test_blocked_outranks_amber_conditions() -> None:
    assert compute_overall_status(["Blocked", "Needs Human Review", "At Risk"]) == "Red"


def test_unrecognized_status_raises() -> None:
    with pytest.raises(ValueError):
        compute_overall_status(["On Track", "Not A Real Status"])


def test_identical_input_always_produces_identical_output() -> None:
    statuses = ["On Track", "At Risk", "Blocked", "Needs Human Review"]
    results = {compute_overall_status(list(statuses)) for _ in range(50)}
    assert len(results) == 1
