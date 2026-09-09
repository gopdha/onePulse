"""Pure, UI-agnostic curation of real on_stage/on_detail pipeline events
into a structured per-stage progress model.

Relocated here for Migration Plan Phase 3 (ADR-021) from where it used
to live, in-process, inside `Home.py`'s own `run_generation()` (Task
32/37) — that curation logic (interpreting a raw on_stage/on_detail
message into "which stage is running, what's its one-line summary")
was always pure business logic, not presentation; it only lived in the
UI file because the UI was, until now, the only process ever calling
`run_pipeline_cycle`. Now the worker is, and it needs the identical
curation to build the `stages` JSONB it persists to the real `cycles`
status table — one real implementation, not two that could drift.
Streamlit's own rendering (`_render_stage_ui` in `Home.py` — HTML,
color, icons) stays presentation-only and now reads this exact
structure back from the database via polling instead of building it
live in-process.

Real, necessary change from the original in-process version: every
timestamp here is real wall-clock (`time.time()`), not
`time.monotonic()`. Monotonic time is only meaningful within one
process's own lifetime and cannot be serialized to JSON and read back
by a different process later — which is exactly what happens now: the
worker writes these timestamps, and Streamlit (a different process)
reads them back over HTTP.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

StageState = dict[str, Any]
Stages = dict[int, StageState]
Shared = dict[str, Any]


def new_stage_state(total: int) -> Stages:
    return {
        n: {"status": "pending", "start_ts": None, "end_ts": None, "detail": None, "live_note": None}
        for n in range(1, total + 1)
    }


def advance_stage(stages: Stages, shared: Shared, n: int, total: int, message: str, now_ts: float) -> None:
    """The real on_stage state machine (unchanged in behavior from Task
    32/37's original `on_stage` closure) — closes out whichever stage
    was previously "running", then opens stage `n` as either "running"
    or "skipped" depending on the real message text.
    """
    prev = shared.get("current_stage")
    if prev and stages[prev]["status"] == "running":
        stages[prev]["end_ts"] = now_ts
        if stages[prev]["detail"] is None:
            stages[prev]["detail"] = "done"
        stages[prev]["status"] = "done"
    if "SKIPPED" in message:
        reason = message.split("SKIPPED", 1)[1].strip(" ()-") or "skipped"
        stages[n].update(status="skipped", start_ts=now_ts, end_ts=now_ts, detail=reason)
    else:
        stages[n].update(status="running", start_ts=now_ts)
        if n == 6:
            # Real, available immediately (Task 32): the on_stage message
            # for Rendering already names the real output path — no need
            # to wait for a later on_detail to know it.
            m = re.search(r"-> (.+)$", message)
            if m:
                stages[6]["detail"] = f"saved {Path(m.group(1)).name}"
    shared["current_stage"] = n


def apply_detail(stages: Stages, shared: Shared, current_stage: int, message: str) -> None:
    """The real per-message curation (unchanged in behavior from Task
    32/37's original `_apply_detail_to_stage`) — every number here is
    parsed straight out of the same real message the full-fidelity log
    file also records verbatim; nothing is estimated or fabricated.
    """
    if current_stage == 1:
        m = re.search(r"real children of (\d+) Committed Feature", message)
        if m:
            shared["feature_count"] = int(m.group(1))
        if re.match(r"^#\d+ ", message):
            shared["pending_findings_count"] = shared.get("pending_findings_count", 0) + 1
            status = message.rsplit(" — ", 1)[-1].strip()
            if status and status != "On Track":
                shared["flagged_findings_count"] = shared.get("flagged_findings_count", 0) + 1
        if "No Features tagged 'Committed' found" in message:
            shared["zero_scope"] = True
            stages[1]["detail"] = "no committed features found"
        if not shared.get("zero_scope"):
            items = shared.get("pending_findings_count", 0)
            features = shared.get("feature_count")
            if features is not None:
                stages[1]["detail"] = f"{items} item(s) across {features} committed feature(s)"
    elif current_stage == 2:
        m = re.match(r"^(\d+) untracked initiative", message)
        if m:
            shared["untracked_count"] = int(m.group(1))
        m2 = re.match(r"^(\d+) possible connection", message)
        if m2:
            shared["connections_count"] = int(m2.group(1))
        if "untracked_count" in shared or "connections_count" in shared:
            stages[2]["detail"] = (
                f"{shared.get('untracked_count', 0)} untracked initiative(s), "
                f"{shared.get('connections_count', 0)} possible connection(s)"
            )
    elif current_stage == 3:
        m = re.match(r"^Overall status: (\w+)", message)
        if m:
            stages[3]["detail"] = f"overall status: {m.group(1)}"
    elif current_stage == 5:
        if message.startswith('Draft: "'):
            flagged = shared.get("flagged_findings_count", 0)
            stages[4]["detail"] = f"executive summary drafted, {flagged} item(s) flagged for review"
        if "Triggering the one permitted revision" in message:
            shared["revision_fired"] = True
            stages[5]["live_note"] = "revising for tone (1 of 1 permitted)"
        elif message.startswith("Revised draft:"):
            stages[5]["live_note"] = "revised — re-checking…"
        elif message.startswith("Revision-cap decision"):
            outcome = message.split(":", 1)[1].strip()
            stages[5]["live_note"] = None
            suffix = "after 1 revision" if shared.get("revision_fired") else "on first attempt"
            stages[5]["detail"] = f"{outcome} {suffix}"
    elif current_stage == 7:
        m = re.search(r"report_id=(\d+)", message)
        if message.startswith("Persisted as report_id="):
            stages[7]["detail"] = f"report_id={m.group(1)} saved"
        elif message.startswith("NOT persisted"):
            stages[7]["detail"] = "not persisted — report already exists for this week"


def finalize_stage_state(stages: Stages, shared: Shared, now_ts: float, total: int, outcome: str | None) -> None:
    """Closes out whichever stage was still "running" when the pipeline
    returned (there is no on_stage(total+1) to do this naturally — stage
    7, normally, or stage 6 on a real hard_stop_defect early return), and
    marks any still-pending stages "skipped" on a hard stop.
    """
    current_stage = shared.get("current_stage")
    if current_stage and stages[current_stage]["status"] == "running":
        stages[current_stage]["end_ts"] = now_ts
        if stages[current_stage]["detail"] is None:
            stages[current_stage]["detail"] = "done"
        stages[current_stage]["status"] = "done"
    if outcome == "hard_stop_defect":
        for n in range((current_stage or 0) + 1, total + 1):
            if stages[n]["status"] == "pending":
                stages[n].update(
                    status="skipped", start_ts=now_ts, end_ts=now_ts,
                    detail="hard stop — nothing to persist",
                )


def mark_failed(stages: Stages, shared: Shared, now_ts: float, error_text: str) -> None:
    """A real, unexpected worker-side exception — distinct from
    hard_stop_defect (a real, expected quality-gate outcome). Marks
    whichever stage was in flight as failed so the UI's existing
    "✗ {name} — failed: {detail}" rendering applies unchanged.
    """
    cur = shared.get("current_stage") or 1
    stages[cur].update(status="failed", end_ts=now_ts, detail=error_text)
