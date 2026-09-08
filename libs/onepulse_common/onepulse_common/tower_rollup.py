"""Executive Tower View — deterministic rollup (Task 36).

Real motivation: Investigation's FR-1 classification (On Track/At Risk/
Blocked/Needs Human Review) is a judgment about whether a Program Lead
should worry about an item — not a measure of raw delivery progress.
Computing "N of M items delivered" needs each item's real ADO workflow
state, which `pipeline._query_tower_hierarchy` fetches deterministically,
independent of the Investigation agent's own narrative judgment — same
discipline as `status_rollup.py`'s own FR-8 rule and `quality_gate.py`'s
code-enforced check: no model call here either.

Two real, explicit design decisions (not buried assumptions — see
CLAUDE.md for the full reasoning trail):
  1. Tower/feature health color: GREEN only at zero flagged items, AMBER
     for any nonzero flagged count regardless of percentage, RED if any
     item is genuinely Blocked. The real percent/count is shown
     alongside the color so severity within a tier is still visible to
     the reader — color signals category, not degree.
  2. "Needs Your Decision" one-liners are built from a fixed template
     (Feature name + a canned phrase keyed to the real status_label) —
     no new LLM call, no rephrasing. The phrasing is deliberately
     generic, not tailored to any specific project's real situation —
     that is the honest cost of staying deterministic here, not an
     oversight.

Real, deliberate choice, not an oversight: real ADO titles in this
project keep their raw sequence-number prefixes (e.g. "07 Build OTEL
Collector - AWS") — rendered as-is, not stripped, since any regex-based
cleanup would be a fragile guess at one organization's own naming
convention, not a real, general rule. The reference mockup's cleaner
titles are a layout reference, not a data contract.

Produces no `TowerRollup`s (an empty list from `build_tower_rollups`)
when a project's Committed Features have no real Epic parent above
them — singleSlide and Leave Tracker today. The caller
(`report_rendering.py`) uses the existing flat findings layout
unchanged in that case.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

TowerHealth = Literal["Green", "Amber", "Red"]

_FLAGGED_STATUSES = frozenset({"Blocked", "Needs Human Review"})
_DELIVERED_STATES = frozenset({"Closed", "Resolved", "Done"})

# Real, deterministic template phrases — see module docstring's decision 2.
# Blocked takes precedence over Needs Human Review when a feature has
# findings in both categories, matching the same severity order the
# health-color rule already uses.
_DECISION_PHRASES: dict[str, str] = {
    "Blocked": "blocked — needs a decision to unblock",
    "Needs Human Review": "needs review and an assigned owner",
}


@dataclass(frozen=True)
class FeatureRollup:
    feature_id: int
    title: str
    health: TowerHealth
    decision_line: str | None  # None if this feature is not flagged


@dataclass(frozen=True)
class TowerRollup:
    epic_id: int
    title: str
    health: TowerHealth
    delivered_count: int
    total_count: int
    percent_complete: int
    flagged_count: int
    features: list[FeatureRollup]


def _health(statuses: list[str]) -> TowerHealth:
    """Same 3-tier rule as `status_rollup.compute_overall_status`, scoped
    to one tower's or one feature's own set of real finding statuses.
    """
    if any(s == "Blocked" for s in statuses):
        return "Red"
    if any(s in _FLAGGED_STATUSES for s in statuses):
        return "Amber"
    return "Green"


def _decision_line(feature_title: str, statuses: list[str]) -> str | None:
    """Deterministic template — see module docstring's decision 2.
    Returns None when nothing under this feature is actually flagged.
    """
    if "Blocked" in statuses:
        return f"{feature_title} — {_DECISION_PHRASES['Blocked']}"
    if "Needs Human Review" in statuses:
        return f"{feature_title} — {_DECISION_PHRASES['Needs Human Review']}"
    return None


def build_tower_rollups(findings: list[dict], tower_hierarchy: dict) -> list[TowerRollup]:
    """Real, deterministic rollup — no model call, no estimation. Returns
    an empty list (not None) when `tower_hierarchy["epics"]` is empty,
    i.e. there is genuinely no real tower structure to report against —
    callers treat an empty list as "use the flat fallback layout."
    """
    epics: dict[int, dict] = tower_hierarchy.get("epics") or {}
    features: dict[int, dict] = tower_hierarchy.get("features") or {}
    children: dict[int, dict] = tower_hierarchy.get("children") or {}
    if not epics:
        return []

    findings_by_id = {f["work_item_id"]: f["status"] for f in findings}

    # Real, deterministic order: by real work item ID, matching the
    # backlog-priority ordering already implicit in this org's own real
    # title-prefix numbering, and avoiding any arbitrary dict-order
    # dependence.
    features_by_epic: dict[int, list[int]] = {}
    for feature_id, finfo in features.items():
        epic_id = finfo.get("epic_id")
        if epic_id in epics:
            features_by_epic.setdefault(epic_id, []).append(feature_id)
    for feature_list in features_by_epic.values():
        feature_list.sort()

    children_by_feature: dict[int, list[int]] = {}
    for child_id, cinfo in children.items():
        children_by_feature.setdefault(cinfo.get("feature_id"), []).append(child_id)
    for child_list in children_by_feature.values():
        child_list.sort()

    towers: list[TowerRollup] = []
    for epic_id in sorted(features_by_epic):
        epic_info = epics[epic_id]
        tower_delivered = 0
        tower_total = 0
        tower_statuses: list[str] = []
        feature_rollups: list[FeatureRollup] = []

        for feature_id in features_by_epic[epic_id]:
            finfo = features[feature_id]
            feature_item_ids = [feature_id] + children_by_feature.get(feature_id, [])
            feature_statuses: list[str] = []

            for item_id in feature_item_ids:
                item_state = finfo["state"] if item_id == feature_id else children[item_id]["state"]
                tower_total += 1
                if item_state in _DELIVERED_STATES:
                    tower_delivered += 1
                status = findings_by_id.get(item_id)
                if status is not None:
                    feature_statuses.append(status)
                    tower_statuses.append(status)

            feature_rollups.append(
                FeatureRollup(
                    feature_id=feature_id,
                    title=finfo["title"],
                    health=_health(feature_statuses),
                    decision_line=_decision_line(finfo["title"], feature_statuses),
                )
            )

        percent_complete = round(100 * tower_delivered / tower_total) if tower_total else 0
        flagged_count = sum(1 for s in tower_statuses if s in _FLAGGED_STATUSES)

        towers.append(
            TowerRollup(
                epic_id=epic_id,
                title=epic_info["title"],
                health=_health(tower_statuses),
                delivered_count=tower_delivered,
                total_count=tower_total,
                percent_complete=percent_complete,
                flagged_count=flagged_count,
                features=feature_rollups,
            )
        )

    return towers


def program_health(towers: list[TowerRollup]) -> TowerHealth:
    """The single, overall PROGRAM HEALTH badge — same 3-tier rule,
    applied across every tower's own already-computed health, not
    re-derived from raw findings (keeps this one real, single source of
    truth per level, not two independent computations that could
    disagree).
    """
    if any(t.health == "Red" for t in towers):
        return "Red"
    if any(t.health == "Amber" for t in towers):
        return "Amber"
    return "Green"
