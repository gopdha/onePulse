"""Deterministic Status Rollup (HLD Section 2, Step 5; closes FR-8).

FR-8: "The platform-wide headline status indicator (Red, Amber, Green, or
Unknown) shall be computed by a fixed, auditable rule and shall never be
determined by model inference." This module is that fixed rule — a pure
function, no model call, always reproducible from the same inputs.

Per-item statuses are FR-1's four-level taxonomy: On Track, At Risk,
Blocked, or Needs Human Review. The design docs specify that a fixed rule
must exist but do not spell out its exact thresholds, so the mapping
below is this project's first concrete definition of that rule — not
pulled from a doc, and open to revision, but auditable and worth
recording precisely because nothing upstream fixed it yet:

  - No items at all                        -> Unknown
  - Any item Blocked                       -> Red
  - Any item At Risk or Needs Human Review -> Amber
  - Every item On Track                    -> Green
"""

from __future__ import annotations

from typing import Literal

ItemStatus = Literal["On Track", "At Risk", "Blocked", "Needs Human Review"]
OverallStatus = Literal["Red", "Amber", "Green", "Unknown"]

_VALID_ITEM_STATUSES: frozenset[str] = frozenset(
    {"On Track", "At Risk", "Blocked", "Needs Human Review"}
)


def compute_overall_status(item_statuses: list[str]) -> OverallStatus:
    """Compute the platform-wide headline status from individual item
    statuses. Pure function: same input always yields the same output.
    """
    invalid = [s for s in item_statuses if s not in _VALID_ITEM_STATUSES]
    if invalid:
        raise ValueError(f"Unrecognized item status(es): {invalid!r}")

    if not item_statuses:
        return "Unknown"
    if any(s == "Blocked" for s in item_statuses):
        return "Red"
    if any(s in ("At Risk", "Needs Human Review") for s in item_statuses):
        return "Amber"
    return "Green"
