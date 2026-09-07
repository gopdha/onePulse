"""Guards against silent drift from Low-Level Design Section 3. If one
of these fails, the code changed without the design doc changing first —
exactly the ordering convention #5 (design checkpoint before
implementation) exists to prevent.
"""

from onepulse_common import constants


def test_revision_cap_matches_lld() -> None:
    assert constants.MAX_REVISIONS == 1


def test_turn_budget_matches_lld() -> None:
    assert constants.MAX_TURNS == 6


def test_agent_call_isolation_flags_match_lld() -> None:
    assert constants.AGENT_CALL_ISOLATION == {
        "setting_sources": [],
        "skills": [],
        "strict_mcp_config": True,
    }


def test_on_demand_rate_limit_matches_lld() -> None:
    assert constants.ON_DEMAND_RATE_LIMIT_PER_LEAD_PER_DAY == 2


def test_min_replicas_matches_lld() -> None:
    assert constants.MIN_SERVICE_REPLICAS == 3


def test_content_safety_check_is_mandatory_and_not_configurable() -> None:
    assert constants.CONTENT_SAFETY_CHECK_MANDATORY is True
