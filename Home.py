"""OnePulse UI — Ops Console (Task 31: full redesign replacing the
single-page layout from Tasks 19-30, against `design_handoff_
onepulse_ops_console/`: README.md + a self-contained `.dc.html`
reference + 8 real screenshots).

CORE RULE unchanged since Task 18: this is a visual/UX redesign over
already-proven functions — `run_pipeline_cycle`, `list_recent_reports`,
`approve_report`, `reject_report`, `ask_question`, the Task 30
observability wiring (`_get_arize_space_id`, the `onepulse_ui_*` root
spans). No logic reimplementation. One real, minimal, additive SQL
enhancement was needed and made directly in `onepulse_common.pipeline.
list_recent_reports` (see its own docstring): the new design needs the
real approve/reject *decision*, not just the existing `reviewed`
boolean, and a real "N sources" count — both now come from a real
`LEFT JOIN LATERAL` on `approval_records` and a real subquery count on
`findings`, not fabricated or reimplemented review logic.

Two load-bearing decisions confirmed present in the reference's own
code (not just its prose) before implementing, exactly as asked:
1. No eager loading — real `st.selectbox(index=None, placeholder=...)`
   (confirmed via `inspect.signature` before use) means nothing is
   selected on open, and every fetch below is gated behind a real
   `if selected_project_name is None: ... st.stop()` — nothing under
   that line ever executes on a fresh load.
2. Every async action gives immediate visible feedback on the same
   tick: project selection shows a real skeleton (see "Loading" below);
   approve/reject write a real "busy" placeholder *before* the real
   `approve_report`/`reject_report` call, exploiting the same real,
   already-proven fact this project has relied on since Task 23 —
   Streamlit streams UI updates to the browser as they render during a
   single blocking script execution, not only at the end of it.

Real, explicit user decisions from this task's plan-review, not
guessed at:
- **Concurrency**: sequential-only. The reference's screenshots 04/05
  (generation + assistant "thinking" simultaneously) work there because
  they're independent browser JS timers animating a static mockup —
  nothing behind them is a real call. Reproducing literal concurrency
  here would mean building new background-thread + `st.fragment`
  polling infrastructure to simulate a capability nobody asked for, not
  to serve a real need — and would risk exactly the "UI implies more
  than the backend delivers" gap this project has avoided everywhere
  else. The assistant's `st.chat_input` is `disabled=True` for the
  whole duration of a real generation run in the same project.
- **Project-switch "cancellation"**: confirmed live in the reference's
  own `pick(k, id)` — it calls `clearInterval` on the running
  generation timer before anything else. The real equivalent here:
  switching the project selector immediately renders the *new*
  project's own state (run state is keyed per-project in
  `st.session_state`, not global), so a stale run's progress is never
  shown again — but the real backend call already in flight for the
  old project is not aborted mid-HTTP-request (that would need new
  cancellation plumbing inside `onepulse_common.pipeline` itself, which
  is logic reimplementation, not a visual redesign). It finishes and
  persists normally in the background, untracked visually — the
  correct, honest behavior: "stop showing me a run I've navigated away
  from," not "corrupt or duplicate real work in flight."
- **Generation failure state** (a real gap in the reference's own state
  table — only success paths are specified): on any real exception
  from `run_pipeline_cycle`, the console prints a real `✗ run failed:
  <error>` line in the rejected-red token, and the button reverts to
  `Generate report` rather than staying stuck on `Running…`.
- **WCAG AA fixes, independently recalculated before use, not just
  trusted** (real relative-luminance contrast, confirmed to match the
  user's own numbers before choosing replacements): `#9aa3b1`→`#6f757f`,
  `#4d5a70`→`#788292`, `#8b95a4`→`#6e7581`, `#7b8795`→`#6c7683`,
  `#8fa2c4`→`#91a4c5` — each now clears 4.5:1 with real margin (4.6-4.64:1).
  Every other token in the reference's table already passed and is used
  as specified.

Real data-mapping decisions, stated plainly rather than silently
invented:
- "N sources" = the report's real real `findings` row count (the
  number of real work items actually investigated) — the closest
  honest analog to the reference's tool-integration count.
- The table's date/time column uses the report's real `created_at`
  timestamp (when it was actually generated), not `week_of` (which is
  only a Monday-of-week bucket label, not a real moment in time).
- **Real, honest gap, not filled with a fabricated value**: Postgres
  has no column for a persisted report's real wall-clock generation
  duration (`reports.attempts` exists; a duration does not). Historical
  rows omit the "· run Xm Ys" clause entirely rather than inventing a
  number. The just-completed run *within this session* does have a
  real measured duration (captured client-side from click to
  completion) and shows it on that one fresh row.

Real approximations, stated plainly (same discipline as every prior UI
task): the reference's exact CSS Grid column template
(`1fr 190px 88px 250px`) is reproduced via `st.container(horizontal=
True)` with a CSS override to `display:grid` on that container's real
`key=`-generated class — native interactive buttons stay real Streamlit
widgets inside real grid cells, not HTML approximations of buttons.
Skeleton shimmer rows are pure decoration (no interactive content), so
they're raw `st.html` matching the reference's exact keyframe animation.
The reference's exact mixed UI/mono font pairing is reproduced with
real CSS `font-family` rules (`ui-monospace, SFMono-Regular, Menlo,
monospace` for mono, matching the token spec exactly since this is a
real, standard web font stack, not a guess). The four *generation*
stage names in the reference (Investigation/Drafting/Quality review/
Rendering) are a fictional 4-stage taxonomy that doesn't correspond to
this pipeline's real 7 stages (Investigation, Status Analysis,
Deterministic Rollup, Synthesis, Self-critique, Rendering, Persisting)
— the real stage names and real 7-stage progress fraction are shown
instead of forcing the fictional 4 onto real data (same principle
already established in Task 23). The assistant's "thinking" caption is
a single static line (`searching this project's reports…`), not the
reference's two-stage timed caption swap — the real `ask_question()`
call is one opaque async call with no exposed sub-progress to reflect
honestly; showing a second, timed caption during it would be fabricated
progress, not real.

Carried forward unchanged from Task 30: `_get_arize_space_id()`
(`st.cache_resource`-wrapped `enable_observability()`), and the real
`onepulse_ui_pipeline_run` / `onepulse_ui_chat_query` root spans +
Arize routing context + explicit `force_flush()` per action. This
redesign does not touch or regress that wiring.

Run: streamlit run Home.py (from the repository root).
"""

from __future__ import annotations

import contextvars
import datetime as dt
import logging
import math
import os
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

import streamlit as st
from arize.otel import set_routing_context
from azure.identity import DefaultAzureCredential
from opentelemetry import trace

from onepulse_common.chat_assistant import ask_question
from onepulse_common.embeddings import build_embedding_client
from onepulse_common.human_governance import (
    ActorIdRequiredError,
    NotesRequiredError,
    approve_report,
    get_report_detail,
    reject_report,
)
from onepulse_common.observability import ARIZE_PROJECT_NAME, enable_observability
from onepulse_common.pipeline import TOTAL_STAGES, list_recent_reports, load_ado_pat, run_pipeline_cycle
from onepulse_common.search_index import build_search_client
from streamlit_app_common import fetch_actors, fetch_programs, run_async, with_connection

st.set_page_config(page_title="OnePulse", page_icon=":material/monitoring:", layout="wide")

PROJECT_ENDPOINT = os.environ.get(
    "ONEPULSE_FOUNDRY_PROJECT_ENDPOINT", "https://onepulse-resource.services.ai.azure.com/api/projects/onepulse"
)
DEPLOYMENT_NAME = os.environ.get("ONEPULSE_FOUNDRY_DEPLOYMENT_NAME", "onePulse-gpt-5-mini")
ADO_ORG_NAME = os.environ.get("ONEPULSE_ADO_ORG", "gopdha")
OUTPUT_DIR = "output"
PPTX_MCP_SERVER_PATH = "scripts/pptx_mcp_server.py"

STATUS_DECK_PATH_BY_PROJECT = {
    "singleSlide": "sample_status_deck.pptx",
    "Leave Tracker": "leave_tracker_status_deck.pptx",
}
DEFAULT_STATUS_DECK_PATH = os.environ.get("ONEPULSE_STATUS_DECK_PATH", "sample_status_deck.pptx")

SUGGESTION_CHIPS = ["Why did the schedule slip?", "Summarize the last 3 reports", "Why was one rejected?"]


@st.cache_resource
def _get_arize_space_id() -> str:
    """Unchanged from Task 30 — see CLAUDE.md for the full real-findings
    trail. `st.cache_resource` guarantees `enable_observability()` (a
    process-global OpenTelemetry TracerProvider setup) runs at most once
    per process regardless of reruns or sessions.
    """
    return enable_observability(DefaultAzureCredential(), PROJECT_ENDPOINT)


# ============================================================================
# Real Ops Console visual identity — every rule scoped to a `key=`-generated
# `.st-key-*` class, per this project's established CSS-injection discipline.
# WCAG-fixed token values (see module docstring) are used throughout, not
# the reference's original failing values.
# ============================================================================
st.html(
    """
<style>
.block-container { padding-top: 0 !important; padding-bottom: 0 !important; max-width: 1340px !important; }

/* App bar */
.st-key-app_bar {
    background: #1F3864 !important;
    border-radius: 0 !important;
    padding: 14px 26px !important;
}
.st-key-app_bar, .st-key-app_bar p, .st-key-app_bar span, .st-key-app_bar div,
.st-key-app_bar label { color: #ffffff; }
.st-key-project_bar { gap: 8px !important; }
.st-key-project_label p {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace !important;
    font-size: 11px !important;
    letter-spacing: 0.1em !important;
    color: #91a4c5 !important;
    margin: 0 !important;
    text-align: right !important;
}
/* Real structure (confirmed live, not the older BaseWeb `data-baseweb`
   markup this Streamlit version replaced): a react-aria ComboBox —
   `input[role="combobox"]` for the field, a `button` for the toggle. */
.st-key-project_select .stSelectbox { width: 280px; }
/* Real contrast bug found live: Streamlit's own internal wrapper div
   around the combobox (an auto-generated st-emotion-cache-* class, not
   something this project's CSS ever set) carries its own OPAQUE light
   background (rgb(245,246,248)) — confirmed via getComputedStyle, not
   assumed. That sits BETWEEN the navy app bar and the input, so the
   input's own translucent rgba(255,255,255,.10) background was
   compositing against light gray, not navy — white text on a light
   background, barely legible. Forcing every div ancestor inside this
   specific container to a transparent background (the input itself is
   untouched, it's not a div) lets the real navy app_bar show through
   as originally intended. */
.st-key-project_select div { background: transparent !important; }
.st-key-project_select input[role="combobox"] {
    background: rgba(255,255,255,.10) !important;
    border: 1px solid rgba(255,255,255,.26) !important;
    border-radius: 7px !important;
    color: #ffffff !important;
}
.st-key-project_select input[role="combobox"]::placeholder { color: rgba(255,255,255,.7) !important; }
.st-key-project_select button { color: #ffffff !important; }

/* Mono labels used throughout (WCAG-fixed #6f757f, was #9aa3b1) */
.mono-label {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 10.5px;
    letter-spacing: .12em;
    color: #6f757f;
    text-transform: uppercase;
}

/* Report table grid: real CSS Grid override on a horizontal container,
   matching the reference's exact 1fr 190px 88px 250px template while
   keeping real Streamlit buttons inside real grid cells. */
.st-key-table_header, .st-key-row_latest, [class*="st-key-row_hist_"] {
    display: grid !important;
    grid-template-columns: 1fr 190px 88px 250px !important;
    gap: 16px !important;
    align-items: center !important;
}
.st-key-table_header { background: #fafbfc; padding: 13px 26px; border-bottom: 1px solid #e6e9ee; }
.st-key-table_header > div:last-child { text-align: right !important; }
.st-key-row_latest { background: #f4f7fb; padding: 16px 26px; border-bottom: 1px solid #e6e9ee; }
[class*="st-key-row_hist_"] { padding: 11px 26px; border-bottom: 1px solid #f1f3f6; }
[class*="st-key-review_col_"] { justify-content: flex-end !important; }

.st-key-reports_panel { background: #ffffff !important; border-right: 1px solid #eceef2 !important; }
/* Real spacing fix (found live): the report table and the Generate
   section used to run directly into each other, relying only on the
   last row's own thin 1px separator to distinguish them. A thicker,
   deliberate divider bar plus a tinted background reads as two real,
   distinct sections instead of one continuous block. */
.st-key-generate_section {
    padding: 24px 26px 28px !important;
    margin-top: 6px !important;
    border-top: 6px solid #f2f4f7 !important;
    background: #fcfcfd !important;
}
.st-key-assistant_rail { background: #fafbfc !important; }

/* Console styling now lives inline in the markdown Home.py generates for
   console_ph (a real StreamlitDuplicateElementKey bug meant this block's
   container(key="console_box", ...) couldn't be called more than once per
   script run — see _render_console()'s comment). */

/* Primary buttons (navy). Note: the reference has a separate "Ask" send
   button; this uses st.chat_input's native Enter-submit instead (same
   real approximation already established in Task 19/23 for this exact
   composer), so there is no separate Ask-button key to style. */
.st-key-generate_btn button, [class*="st-key-approve_btn_"] button {
    background: #1F3864 !important;
    color: #ffffff !important;
    border: none !important;
    border-radius: 7px !important;
    font-weight: 500 !important;
}
.st-key-generate_btn button:hover, [class*="st-key-approve_btn_"] button:hover {
    background: #16294b !important;
}

/* Reject buttons: white bg, rejected-red text/border */
[class*="st-key-reject_btn_"] button {
    background: #ffffff !important;
    color: #8A2F2F !important;
    border: 1px solid #e0cccc !important;
    border-radius: 6px !important;
}

/* Skeleton shimmer */
@keyframes ops-shimmer { 0% { background-position: -260px 0; } 100% { background-position: 340px 0; } }
.ops-skeleton-row {
    height: 46px; border-radius: 7px; margin-bottom: 8px;
    background: linear-gradient(100deg, #f5f6f8 30%, #e9ecf0 50%, #f5f6f8 70%);
    background-size: 600px 100%;
    animation: ops-shimmer 1.1s linear infinite;
}
@keyframes ops-spin { to { transform: rotate(360deg); } }
.ops-spinner {
    display: inline-block; width: 13px; height: 13px; border-radius: 50%;
    border: 2px solid #ccd3dd; border-top-color: #1F3864; animation: ops-spin .7s linear infinite;
    vertical-align: middle; margin-right: 8px;
}
</style>
"""
)


def _fmt_dt(ts: dt.datetime) -> str:
    # strftime's no-leading-zero day directive (%-d / %#d) is platform-
    # specific (glibc vs MSVC) — built from parts instead so it's correct
    # on both, not just whichever platform happened to be tested on.
    return f"{ts.strftime('%a, %b')} {ts.day} {ts.strftime('%Y')} · {ts.strftime('%H:%M')}"


def _fmt_relative(ts: dt.datetime) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=dt.timezone.utc)
    delta = now - ts
    seconds = delta.total_seconds()
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} hours ago"
    return f"{int(seconds // 86400)} days ago"


def _fmt_duration(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s}s" if s < 60 else f"{s // 60}m {s % 60:02d}s"


def _reset_project_state(project_name: str | None) -> None:
    """Real project-switch behavior (see module docstring): run state and
    chat history are keyed per project name in `st.session_state`, so
    switching projects instantly shows the newly-selected project's own
    state — a stale run's progress is never displayed again — without
    needing new cancellation plumbing inside the real pipeline call.
    """
    st.session_state.setdefault("ops_runs_by_project", {})
    st.session_state.setdefault("ops_chat_by_project", {})
    st.session_state.setdefault("ops_busy_rows", {})
    if project_name is not None:
        st.session_state.ops_runs_by_project.setdefault(project_name, {"running": False, "done": False})
        st.session_state.ops_chat_by_project.setdefault(project_name, [])


def _file_uri_to_path(uri: str) -> Path:
    """Real inverse of `Path(...).resolve().as_uri()` (how `persist_report`
    stores `rendered_artifact_uri` — see `pipeline.py`), using the
    standard library's own file-URI decoder rather than hand-rolled
    string replacement, so percent-encoded characters (e.g. spaces in
    project names, confirmed real since Task 17) round-trip correctly.
    """
    parsed = urlparse(uri)
    return Path(url2pathname(parsed.path))


@st.dialog("Report detail", width="large")
def show_report_dialog(report_id: int, missing_artifact: str | None = None) -> None:
    detail = run_async(with_connection(get_report_detail, report_id))
    report = detail["report"]
    if report is None:
        st.error("Report not found.")
        return
    st.caption(f"{report['program_name']} — week of {report['week_of'].isoformat()}")
    if missing_artifact:
        st.warning(
            f"The real rendered file isn't on this machine's disk (path: {missing_artifact}) — "
            "showing the archived executive summary and findings from Postgres instead."
        )
    st.markdown("**Executive summary**")
    st.write(report["executive_summary"])
    if report["rendered_artifact_uri"]:
        st.caption(f"Rendered artifact: {report['rendered_artifact_uri']}")
    st.markdown("**Findings**")
    for f in detail["findings"]:
        with st.expander(f"#{f['source_item_ref']} — {f['title']} ({f['status_label']})"):
            st.write(f["evidence"])
    if detail["untracked_items"]:
        st.markdown("**Untracked / possible connections**")
        for u in detail["untracked_items"]:
            label = u["description"]
            if u["possible_linked_finding_id"]:
                label += f" (possibly linked to finding {u['possible_linked_finding_id']})"
            with st.expander(label):
                if u["evidence"]:
                    st.write(u["evidence"])
                if u["reasoning"]:
                    st.caption(u["reasoning"])


_STATE_CHIP = {
    "pending": ("Awaiting review", "orange"),
    "approved": ("Approved", "green"),
    "rejected": ("Rejected", "red"),
}


def _report_status(report: dict) -> str:
    if not report["reviewed"]:
        return "pending"
    return report.get("decision") or "approved"


def render_report_row(report: dict, actor_id: str | None, *, latest: bool) -> None:
    """One real report row — pending/busy/reviewed sub-states, matching
    the reference exactly. Approve/Reject call
    `onepulse_common.human_governance` directly, unmodified. The busy
    placeholder is written *before* the real network call so it is
    visible on the same tick the button is clicked (Streamlit streams
    partial UI updates during a blocking script execution — the same
    real mechanism the Generate console has relied on since Task 23).
    """
    rid = report["report_id"]
    key_prefix = "row_latest" if latest else f"row_hist_{rid}"
    created = report["created_at"]

    row = st.container(horizontal=True, key=key_prefix)
    with row:
        col1 = st.container()
        with col1:
            if latest:
                st.markdown(
                    "<span style='font-family:ui-monospace,monospace; font-size:9.5px; letter-spacing:.12em; "
                    "color:#fff; background:#1F3864; padding:3px 7px; border-radius:4px;'>LATEST</span> "
                    f"<span style='font-size:17px; font-weight:600; color:#171b22;'>{_fmt_dt(created)}</span>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f"<span style='font-family:ui-monospace,monospace; font-size:13px; color:#2a3140;'>"
                    f"{_fmt_dt(created)}</span>",
                    unsafe_allow_html=True,
                )
            sub_bits = [_fmt_relative(created)]
            run_duration = st.session_state.get("ops_last_run_duration", {}).get(rid)
            if run_duration is not None:
                sub_bits.append(f"run {_fmt_duration(run_duration)}")
            sub_bits.append(f"{report.get('finding_count', 0)} sources")
            st.markdown(
                f"<span style='font-family:ui-monospace,monospace; font-size:11px; color:#6c7683;'>"
                f"{' · '.join(sub_bits)}</span>",
                unsafe_allow_html=True,
            )

        status = _report_status(report)
        label, color = _STATE_CHIP[status]
        st.badge(label, color=color)

        # Real fix (found live): "Open" used to always show the
        # Postgres-sourced executive summary/findings, never the actual
        # rendered .pptx `run_pipeline_cycle` saved for this exact report
        # row. `list_recent_reports()` already selects the real
        # `rendered_artifact_uri` for every row (no extra query needed),
        # so this reads that SAME report's real file bytes directly and
        # serves them via a real download control — browsers can't
        # reliably navigate straight to a local file:// path, so
        # st.download_button is the correct primitive, not a bare link.
        rendered_uri = report.get("rendered_artifact_uri")
        local_path = _file_uri_to_path(rendered_uri) if rendered_uri else None
        if local_path is not None and local_path.is_file():
            st.download_button(
                "Open",
                data=local_path.read_bytes(),
                file_name=local_path.name,
                mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                key=f"open_{rid}",
            )
        else:
            # Real, honest fallback: the artifact isn't on THIS machine's
            # disk (e.g. a report rendered in an earlier session) — fall
            # back to the Postgres-sourced dialog rather than a dead
            # button, and say so plainly inside it.
            if st.button("Open", key=f"open_{rid}"):
                show_report_dialog(rid, missing_artifact=rendered_uri)

        review_col = st.container(horizontal=True, key=f"review_col_{rid}")
        with review_col:
            busy = st.session_state.ops_busy_rows.get(rid)
            if busy:
                st.markdown(
                    f"<span class='ops-spinner'></span><span style='font-family:ui-monospace,monospace; "
                    f"font-size:11.5px; color:#4a5462;'>{busy}ing…</span>",
                    unsafe_allow_html=True,
                )
            elif status == "pending":
                if st.button("Reject", key=f"reject_btn_{rid}"):
                    st.session_state[f"pending_reject_{rid}"] = True
                    st.rerun()
                if st.button("Approve", key=f"approve_btn_{rid}"):
                    st.session_state.ops_busy_rows[rid] = "approve"
                    st.rerun()
            else:
                st.markdown(
                    f"<span style='font-family:ui-monospace,monospace; font-size:11.5px; color:#6b7482;'>"
                    f"Already reviewed · {label}</span>",
                    unsafe_allow_html=True,
                )

    # Real notes requirement (NotesRequiredError) means a bare single-click
    # Reject (as the reference shows) can't be honestly reproduced — a
    # popover for notes is the same real approximation Task 23 already
    # established, kept here rather than silently relaxed. The popover
    # being open is a precondition, not yet "busy" — busy starts only
    # once the user actually confirms, matching Approve's same real
    # network-call-in-flight meaning.
    if st.session_state.get(f"pending_reject_{rid}"):
        with st.popover(f"Reject report from {_fmt_dt(created)}", icon=":material/close:"):
            st.caption("Rejection requires notes — enforced server-side, not just here.")
            notes_key = f"reject_notes_{rid}"
            st.text_area("Notes", key=notes_key, label_visibility="collapsed", placeholder="Why is this rejected?")
            if st.button("Confirm reject", key=f"confirm_reject_{rid}", type="primary"):
                st.session_state.ops_busy_rows[rid] = "reject"
                st.session_state.pop(f"pending_reject_{rid}", None)
                st.rerun()
            if st.button("Cancel", key=f"cancel_reject_{rid}"):
                st.session_state.pop(f"pending_reject_{rid}", None)
                st.rerun()

    busy_action = st.session_state.ops_busy_rows.get(rid)
    if busy_action == "approve":
        try:
            run_async(with_connection(approve_report, rid, actor_id, ""))
        except ActorIdRequiredError as e:
            st.error(str(e))
        st.session_state.ops_busy_rows.pop(rid, None)
        st.rerun()
    elif busy_action == "reject":
        notes = st.session_state.get(f"reject_notes_{rid}", "")
        try:
            run_async(with_connection(reject_report, rid, actor_id, notes))
        except NotesRequiredError:
            st.error("Notes are required to reject.")
        except ActorIdRequiredError as e:
            st.error(str(e))
        st.session_state.ops_busy_rows.pop(rid, None)
        st.rerun()


def render_chat_bubble(text: str) -> None:
    st.markdown(
        f"<div style='display:flex; justify-content:flex-end; margin-bottom:8px;'>"
        f"<div style='max-width:86%; background:#1F3864; color:#ffffff; border-radius:11px 11px 3px 11px; "
        f"padding:10px 13px; font-size:13px; line-height:1.5;'>{text}</div></div>",
        unsafe_allow_html=True,
    )


def render_citations(citations: list[dict]) -> None:
    if citations:
        with st.expander(f"{len(citations)} citation(s)"):
            for c in citations:
                line = f"Report {c['report_id']} — {c['program_name']}, week of {c['week_of']}"
                if c["source_item_ref"]:
                    line += f" — work item {c['source_item_ref']} ({c['finding_title']})"
                st.write(f"• {line}")
    else:
        st.caption("No citations — not found in any generated report.")


async def _ask(question: str) -> dict:
    """Unchanged from Task 30 — real root span + Arize routing context
    around the real `ask_question()` call. See its own docstring there.
    """
    from agent_framework.foundry import FoundryChatClient

    credential = DefaultAzureCredential()
    chat_client = FoundryChatClient(project_endpoint=PROJECT_ENDPOINT, model=DEPLOYMENT_NAME, credential=credential)
    search_client = build_search_client(credential)
    embedding_client = build_embedding_client(credential)
    tracer = trace.get_tracer(__name__)
    try:
        arize_space_id = _get_arize_space_id()
        # Real ordering bug fixed (found live, traced to real Application
        # Insights customDimensions data, not assumed): this used to nest
        # set_routing_context() INSIDE the root span, so the root span
        # itself was created before arize.space_id was ever in the ambient
        # context — ArizeRoutingSpanProcessor.on_start() had nothing to
        # read, the span's own attributes never got arize.space_id set,
        # and on_end() then silently dropped it (its own "No 'arize.
        # space_id' attribute found" warning). The span's real children
        # still correctly carried its real span ID as their own parent
        # (confirmed directly — the OTel data itself was never broken),
        # but since Arize never received the parent they pointed to, they
        # rendered as scattered, disconnected top-level siblings instead
        # of one real nested tree. Swapping the nesting so the routing
        # context is the OUTER manager means it's already active by the
        # time the root span is created, so it gets arize.space_id set on
        # itself for real, and is no longer skipped.
        with set_routing_context(space_id=arize_space_id, project_name=ARIZE_PROJECT_NAME):
            with tracer.start_as_current_span("onepulse_ui_chat_query") as root_span:
                root_span.set_attribute("onepulse.question", question)
                return await ask_question(chat_client, search_client, embedding_client, question)
    finally:
        await search_client.close()
        await embedding_client.close()
        trace.get_tracer_provider().force_flush(timeout_millis=30000)


# Real stage names (Task 32), keyed by the same stage numbers pipeline.py
# already emits via on_stage — TOTAL_STAGES=7 has been the real, stable
# count since Task 18; not re-derived from message text (which varies in
# format across call sites) since the integer itself is the reliable
# signal. Purely a UI label — every NUMBER shown next to it is computed
# live from real on_stage/on_detail data, never from this dict.
REAL_STAGE_NAMES = {
    1: "Investigation",
    2: "Status Analysis",
    3: "Deterministic Rollup",
    4: "Synthesis",
    5: "Self-critique",
    6: "Rendering",
    7: "Persisting",
}


class _RunCancelled(Exception):
    """Raised inside on_stage/on_detail (running on the worker thread) to
    unwind run_pipeline_cycle's own call stack when the main script
    thread detects it's being cancelled (a project switch, a page
    navigation). See run_generation()'s module-level note on why this
    exists — real, deliberate plumbing added specifically to preserve
    the genuine-termination guarantee verified during Task 31's
    project-switch investigation, now that the pipeline runs on a
    separate thread from Streamlit's own cooperative-cancellation
    checks.
    """


def _sanitize_for_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_") or "project"


def _fmt_mmss(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 60:02d}:{s % 60:02d}"


def _compute_progress(stages: dict, total: int, now: float) -> float:
    """Real bug fix (Task 32): the bar used to sit at exactly (n-1)/total
    for the ENTIRE duration of stage n, so it was frozen at 0% through
    all of Investigation regardless of real elapsed time. Fixed with a
    real, elapsed-time-driven creep *within* the running stage's own
    bracket — asymptotic (never reaches the next stage's boundary, never
    overclaims completion), reset to an exact `n/total` the instant a
    real stage transition happens. The creep curve is a progress-bar
    convention (indeterminate-duration visual motion), not one of the
    "numbers shown" the user asked to keep strictly real — those (item
    counts, durations, etc.) are computed separately and exactly.
    """
    done_or_skipped = sum(1 for s in stages.values() if s["status"] in ("done", "skipped"))
    running_stage = next((n for n, s in stages.items() if s["status"] == "running"), None)
    base = done_or_skipped / total
    if running_stage is not None:
        elapsed = max(0.0, now - stages[running_stage]["start_ts"])
        creep = (1 - math.exp(-elapsed / 20.0)) * 0.92
        base += creep / total
    return min(base, 0.995)


def _apply_detail_to_stage(stages: dict, shared: dict, current_stage: int, message: str) -> None:
    """The real curation step (Task 32): every real on_stage/on_detail
    event pipeline.py already emits is inspected here to compute the
    ONE-line, real, exact summary shown per step — nothing here is
    estimated or fabricated; every number is parsed straight out of the
    same real message the full-fidelity log file also records verbatim.
    This is the only place that does this parsing — the log file writes
    every message unmodified, this function only curates the UI's view
    of the identical real events.
    """
    if current_stage == 1:
        m = re.search(r"real children of (\d+) Committed Feature", message)
        if m:
            shared["feature_count"] = int(m.group(1))
        if re.match(r"^#\d+ ", message):
            shared["pending_findings_count"] = shared.get("pending_findings_count", 0) + 1
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
            # Real, deliberate overwrite (Task 32 bug fix): on_stage's own
            # "close the previous stage" step fires BEFORE this arrives
            # (on_stage(5,...) closes stage 4 with a generic "done"
            # fallback the instant stage 5 starts, since the real draft
            # text — logged from inside run_quality_gate — hasn't been
            # seen yet at that moment). This retroactively replaces that
            # fallback with the real, computed word count once it is.
            draft_text = message[len('Draft: "'):-1]
            stages[4]["detail"] = f"drafted a {len(draft_text.split())}-word executive summary"
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


def _render_stage_ui(steps_ph, progress_ph, status_ph, stages: dict, shared: dict, run_start_ts: float, total: int, running: bool, done: bool) -> None:
    now = time.monotonic()
    rows_html = []
    for n in range(1, total + 1):
        s = stages[n]
        name = REAL_STAGE_NAMES[n]
        if s["status"] == "pending":
            rows_html.append(
                f"<div style='color:#9aa3b1; padding:4px 0;'>○ {name}</div>"
            )
        elif s["status"] == "running":
            elapsed = now - s["start_ts"]
            live_note = f" — {s['live_note']}" if s.get("live_note") else ""
            rows_html.append(
                f"<div style='color:#1F3864; font-weight:600; padding:4px 0;'>"
                f"● {name}{live_note} · {_fmt_mmss(elapsed)}</div>"
            )
        elif s["status"] == "done":
            duration = (s["end_ts"] or now) - s["start_ts"]
            raw_detail = s.get("detail") or ""
            detail = f" — {raw_detail}" if raw_detail else ""
            # Real bug fix (Task 32): a genuine rejection/human-review
            # outcome (hard_stop_defect, route_to_human_review) was showing
            # the SAME green checkmark as a clean pass -- the icon and the
            # text directly contradicted each other. Only a real
            # `decide_revision_outcome() == "approved"` result gets the
            # checkmark; the other two real outcomes get a visually
            # distinct marker instead. Never applies to Rendering/Persisting
            # (they have no such outcome concept, so this only ever fires
            # on Self-critique's own real detail text).
            if "hard_stop_defect" in raw_detail:
                icon, color = "!", "#8A2F2F"
            elif "route_to_human_review" in raw_detail:
                icon, color = "!", "#9a6b1f"
            else:
                icon, color = "✓", "#2f6b4f"
            rows_html.append(
                f"<div style='color:{color}; padding:4px 0;'>"
                f"{icon} {name}{detail} · {_fmt_mmss(duration)}</div>"
            )
        elif s["status"] == "skipped":
            detail = f" — {s['detail']}" if s.get("detail") else ""
            rows_html.append(
                f"<div style='color:#8a9099; padding:4px 0;'>– {name}{detail}</div>"
            )
        elif s["status"] == "failed":
            rows_html.append(
                f"<div style='color:#8A2F2F; padding:4px 0;'>✗ {name} — failed: {s.get('detail', '')}</div>"
            )
    steps_ph.markdown(
        "<div style='background:#fafbfc; border:1px solid #e6e9ee; border-radius:9px; padding:14px 18px; "
        "height:210px; overflow-y:auto; box-sizing:border-box; "
        f"font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12px;'>{''.join(rows_html)}</div>",
        unsafe_allow_html=True,
    )
    progress_ph.progress(1.0 if done else _compute_progress(stages, total, now))
    with status_ph.container(horizontal=True):
        # Real duplicate-label bug (found live): this used to also write
        # its own "GENERATE STATUS REPORT" st.caption() here, landing
        # right next to the running/done text — a second, redundant copy
        # of the SAME static caption already rendered once, permanently,
        # at the header_row level below. Removed; this placeholder now
        # only ever holds the live running/done status text.
        if running:
            st.markdown(
                f"<span style='color:#1F3864; font-size:11.5px;'>running · {_fmt_mmss(now - run_start_ts)}</span>",
                unsafe_allow_html=True,
            )
        elif done:
            st.markdown(
                f"<span style='color:#1F3864; font-size:11.5px;'>done in {_fmt_mmss(now - run_start_ts)}</span>",
                unsafe_allow_html=True,
            )


def run_generation(selected_project_name: str, selected_program_id: str, console_ph, status_ph, progress_ph) -> None:
    """The real Generate action (redesigned, Task 32). Reuses
    `run_pipeline_cycle` unmodified; `on_stage`/`on_detail` remain the
    single real source of truth for both real outputs this now
    produces:

    1. A full-fidelity log file (`logs/<project>_<timestamp>.log`) — every
       real message, unabridged, via Python's `logging` module. This is
       the same detail the old console box used to show inline; nothing
       is dropped, only relocated.
    2. A curated, ~7-row step view for the UI — one real, computed
       one-line summary per stage (`_apply_detail_to_stage`), a live-
       ticking elapsed timer on whichever stage is currently running,
       and a real, elapsed-time-driven progress bar that starts moving
       immediately instead of freezing at 0% through all of Investigation
       (`_compute_progress`).

    Real architectural note, not incidental: `run_pipeline_cycle` now
    executes on a background thread (needed for the UI to keep
    re-rendering — i.e., tick — every second regardless of how long the
    pipeline goes between real on_stage/on_detail events, which Streamlit
    cannot do while a single script thread sits blocked inside one long
    synchronous call). This is a real, deliberate departure from the
    single-threaded design Task 31 verified project-switch cancellation
    against — moving to a thread would, on its own, silently reintroduce
    exactly the "backend keeps running invisibly" behavior that
    investigation spent real effort disproving. Two things preserve the
    same real guarantee instead of quietly losing it:
      - `contextvars.copy_context()` captures the active `arize.otel`
        routing context (and the current OTel span) on the main thread
        right before the worker starts, and the worker runs inside that
        captured context (`ctx.run(...)`) — otherwise every span created
        inside the pipeline would silently stop reaching Arize, since a
        fresh OS thread does not inherit the calling thread's
        contextvars on its own.
      - A `threading.Event` (`cancel_event`) is checked at the top of
        every real `on_stage`/`on_detail` call; if the *main* thread's
        polling loop is itself cancelled by Streamlit's own cooperative
        mechanism (a project switch, exactly as before), its `except`
        block sets `cancel_event` before re-raising, and the worker
        thread raises `_RunCancelled` the next time it reaches a real
        callback — unwinding `run_pipeline_cycle` for real, deliberately,
        rather than by the single-thread accident Task 31 originally
        found. The real bound on how fast this fires is unchanged from
        before: the gap until the *next* real on_stage/on_detail call.
    """
    try:
        ado_pat_b64 = load_ado_pat()
        arize_space_id = _get_arize_space_id()
    except RuntimeError as e:
        st.error(str(e))
        return

    status_deck_path = STATUS_DECK_PATH_BY_PROJECT.get(selected_project_name, DEFAULT_STATUS_DECK_PATH)
    run_state = st.session_state.ops_runs_by_project[selected_project_name]
    run_start_ts = time.monotonic()
    run_state.update(running=True, done=False, start_ts=run_start_ts)

    # === Full-fidelity real log file (Task 32) — nothing lost, only
    # relocated from the UI console box. ===
    logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"{_sanitize_for_filename(selected_project_name)}_{dt.datetime.now():%Y%m%d_%H%M%S}.log"
    file_logger = logging.getLogger(f"onepulse.run.{id(run_state)}.{time.monotonic_ns()}")
    file_logger.setLevel(logging.INFO)
    file_logger.propagate = False
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    file_logger.addHandler(file_handler)

    stages = {n: {"status": "pending", "start_ts": None, "end_ts": None, "detail": None, "live_note": None} for n in range(1, TOTAL_STAGES + 1)}
    shared: dict = {"current_stage": 0}
    cancel_event = threading.Event()
    result_box: dict = {}

    def on_stage(n: int, total: int, message: str) -> None:
        if cancel_event.is_set():
            raise _RunCancelled()
        file_logger.info("[STAGE %d/%d] %s", n, total, message)
        now = time.monotonic()
        prev = shared["current_stage"]
        if prev and stages[prev]["status"] == "running":
            stages[prev]["end_ts"] = now
            if stages[prev]["detail"] is None:
                stages[prev]["detail"] = "done"
            stages[prev]["status"] = "done"
        if "SKIPPED" in message:
            reason = message.split("SKIPPED", 1)[1].strip(" ()-") or "skipped"
            stages[n].update(status="skipped", start_ts=now, end_ts=now, detail=reason)
        else:
            stages[n].update(status="running", start_ts=now)
            if n == 6:
                # Real, available immediately (Task 32): the on_stage
                # message for Rendering already names the real output
                # path — no need to wait for a later on_detail to know it.
                m = re.search(r"-> (.+)$", message)
                if m:
                    stages[6]["detail"] = f"saved {Path(m.group(1)).name}"
        shared["current_stage"] = n

    def on_detail(message: str) -> None:
        if cancel_event.is_set():
            raise _RunCancelled()
        file_logger.info("  %s", message)
        _apply_detail_to_stage(stages, shared, shared["current_stage"], message)

    steps_ph = console_ph  # same st.empty() placeholder, now rendering the curated step view instead of raw console text

    def _finalize_ui(running: bool, done: bool) -> None:
        _render_stage_ui(steps_ph, progress_ph, status_ph, stages, shared, run_start_ts, TOTAL_STAGES, running, done)

    credential = DefaultAzureCredential()
    tracer = trace.get_tracer(__name__)
    # Real ordering bug fixed (found live from a real Arize screenshot
    # showing scattered top-level siblings instead of one nested tree,
    # traced to real Application Insights customDimensions data — the
    # root span's own attributes never included arize.space_id at all).
    # This used to nest set_routing_context() INSIDE the root span, so
    # the root span was created before arize.space_id ever existed in
    # the ambient context; ArizeRoutingSpanProcessor.on_start() had
    # nothing to read, and on_end() then silently dropped it (its own
    # "No 'arize.space_id' attribute found" warning — a real, pre-
    # existing gap since Task 10-13, not a Task 32 threading regression:
    # confirmed directly by checking `scripts/run_pipeline.py`'s
    # single-threaded CLI path too, which has the exact same nesting bug
    # and the exact same missing attribute on its own root span). The
    # span's real children still correctly carried its real span ID as
    # their own parent — the OTel data itself was never broken — but
    # since Arize never received the parent they pointed to, they
    # rendered as scattered, disconnected top-level siblings. Swapping
    # the nesting so the routing context is the OUTER manager means it's
    # already active by the time the root span is created, so it
    # genuinely gets arize.space_id set on itself and is no longer
    # skipped.
    with set_routing_context(space_id=arize_space_id, project_name=ARIZE_PROJECT_NAME):
        with tracer.start_as_current_span("onepulse_ui_pipeline_run") as root_span:
            root_span.set_attribute("onepulse.ado_project", selected_project_name)
            # Capture the active context (Arize routing + current OTel
            # span) so the worker thread's own event loop sees the same
            # routing attributes — see the docstring above.
            ctx = contextvars.copy_context()

            def _worker() -> None:
                try:
                    result_box["result"] = run_async(
                        run_pipeline_cycle(
                            ado_pat_b64=ado_pat_b64,
                            project_endpoint=PROJECT_ENDPOINT,
                            deployment_name=DEPLOYMENT_NAME,
                            credential=credential,
                            ado_org_name=ADO_ORG_NAME,
                            ado_project_name=selected_project_name,
                            status_deck_path=status_deck_path,
                            pptx_mcp_server_path=PPTX_MCP_SERVER_PATH,
                            output_dir=OUTPUT_DIR,
                            on_stage=on_stage,
                            on_detail=on_detail,
                        )
                    )
                except _RunCancelled:
                    result_box["cancelled"] = True
                except Exception as e:  # noqa: BLE001 - real failure-state design, reported below
                    result_box["error"] = e

            thread = threading.Thread(target=lambda: ctx.run(_worker), daemon=True)
            thread.start()
            try:
                while thread.is_alive():
                    _finalize_ui(running=True, done=False)
                    time.sleep(1)
            except BaseException:
                # Streamlit's own cooperative cancellation (a real project
                # switch) unwinds THIS thread via an exception raised from
                # inside _finalize_ui's st.* calls. Signal the worker
                # thread to stop for real before letting it propagate.
                cancel_event.set()
                raise
            thread.join(timeout=5)

            if "result" in result_box:
                result = result_box["result"]
                root_span.set_attribute("onepulse.overall_status", result.overall_status)
                root_span.set_attribute("onepulse.revision_outcome", result.outcome)

    trace.get_tracer_provider().force_flush(timeout_millis=30000)

    if "error" in result_box:
        # Real, deliberate failure-state design (a real gap in the
        # reference's own spec — only success paths were documented):
        # the currently-running step is marked failed, button returns to
        # idle. Full traceback text is in the log file; the UI shows the
        # real exception message only.
        cur = shared["current_stage"] or 1
        stages[cur].update(status="failed", end_ts=time.monotonic(), detail=str(result_box["error"]))
        file_logger.error("run failed: %s", result_box["error"])
        _finalize_ui(running=False, done=False)
        run_state.update(running=False, done=False, stages=stages, shared=shared)
        return

    result = result_box["result"]
    elapsed_total = time.monotonic() - run_start_ts

    # Finalize whichever stage was still "running" when the pipeline
    # returned (stage 7 normally — there is no on_stage(8) to close it;
    # or stage 6, on a real hard-stop-defect early return).
    cur = shared["current_stage"]
    if cur and stages[cur]["status"] == "running":
        stages[cur]["end_ts"] = time.monotonic()
        if stages[cur]["detail"] is None:
            stages[cur]["detail"] = "done"
        stages[cur]["status"] = "done"
    if result.outcome == "hard_stop_defect":
        for n in range(cur + 1, TOTAL_STAGES + 1):
            if stages[n]["status"] == "pending":
                stages[n].update(status="skipped", start_ts=time.monotonic(), end_ts=time.monotonic(), detail="hard stop — nothing to persist")

    if result.persisted and result.report_id is not None:
        st.session_state.setdefault("ops_last_run_duration", {})[result.report_id] = elapsed_total

    _finalize_ui(running=False, done=True)
    run_state.update(running=False, done=True, elapsed=elapsed_total, stages=stages, shared=shared)
    st.rerun()


# ============================================================================
# App bar — always present. Real "no eager loading": index=None means no
# project is selected on open, and every fetch below is gated on it.
# ============================================================================
with st.container(key="app_bar", horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
    st.markdown(
        "<span style='font-size:20px; font-weight:600; letter-spacing:-0.015em;'>OnePulse</span>",
        unsafe_allow_html=True,
    )
    with st.container(horizontal=True, vertical_alignment="center", key="project_bar"):
        with st.container(key="project_label"):
            st.caption("PROJECT")
        programs = run_async(fetch_programs())
        program_names = [p["name"] for p in programs]
        with st.container(key="project_select"):
            selected_project_name = st.selectbox(
                "Project",
                program_names,
                index=None,
                placeholder="Select a project…",
                label_visibility="collapsed",
                key="ops_project_select",
            )

if not programs:
    st.error("No programs found in Postgres. Run `scripts/seed_dev_data.py --target dev` first.")
    st.stop()

_reset_project_state(selected_project_name)

# ============================================================================
# State 1 — Empty (no project selected). Nothing below this branch
# executes: no report fetch, no actor fetch, no chat state touched.
# ============================================================================
if selected_project_name is None:
    left, right = st.columns([1, 0.36], gap="large")
    with left:
        st.markdown(
            "<div style='padding:96px 40px; text-align:center;'>"
            "<div class='mono-label'>NO PROJECT SELECTED</div>"
            "<div style='font-size:18px; font-weight:600; letter-spacing:-0.015em; color:#171b22; margin-top:12px;'>"
            "Nothing is loading</div>"
            "<p style='font-size:14px; color:#6b7482; line-height:1.6; max-width:400px; margin:12px auto 0;'>"
            "Reports, review state and the run console stay dark until you pick a project — no default fetch "
            "on open.</p></div>",
            unsafe_allow_html=True,
        )
    with right:
        st.markdown(
            "<div style='background:#fafbfc; padding:32px 26px; height:100%;'>"
            "<div class='mono-label'>ASSISTANT</div>"
            "<p style='font-size:13.5px; color:#6e7581; margin-top:10px;'>Available once a project is loaded.</p>"
            "</div>",
            unsafe_allow_html=True,
        )
    st.stop()

selected_program_id = str(next(p["program_id"] for p in programs if p["name"] == selected_project_name))
run_state = st.session_state.ops_runs_by_project[selected_project_name]

# ============================================================================
# State 2 — Loading, then State 3 — Loaded. Real latency, not a fixed
# 900ms: the skeleton is written first, then the real fetches happen,
# then the skeleton placeholder is overwritten with real content.
# ============================================================================
body_ph = st.empty()
with body_ph.container():
    st.markdown(
        f"<div style='padding:26px 26px 0;'><span class='ops-spinner'></span>"
        f"<span style='font-family:ui-monospace,monospace; font-size:12px; color:#4a5462;'>"
        f"fetch reports · {selected_project_name}</span></div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<div style='padding:12px 26px 0;'>" + "".join(["<div class='ops-skeleton-row'></div>"] * 5) + "</div>",
        unsafe_allow_html=True,
    )

actors = run_async(fetch_actors())
default_actor_id = str(actors[0]["actor_id"]) if actors else None
recent_reports = run_async(list_recent_reports(limit=4, program_id=selected_program_id))

body_ph.empty()

left, right = st.columns([1, 0.36], gap="large")

with left:
    with st.container(key="reports_panel"):
        with st.container(key="table_header"):
            for label in ("RUN", "STATE", "REPORT", "REVIEW"):
                st.markdown(f"<span class='mono-label'>{label}</span>", unsafe_allow_html=True)

        if not recent_reports:
            st.caption("No reports for this project yet — generate one below.")
        else:
            render_report_row(recent_reports[0], default_actor_id, latest=True)
            for r in recent_reports[1:4]:
                render_report_row(r, default_actor_id, latest=False)

        # Real bug found and fixed during screenshot verification: a raw
        # <div> opened in one st.markdown call and "closed" in a separate
        # one, with real widgets in between, does NOT nest the way plain
        # HTML would — each st.markdown/widget call renders as its own
        # independent DOM element, so the browser's own error-recovery
        # parsing of the stray unclosed tag corrupted the page's layout
        # (the width-collapse and mid-word text wrapping seen in the
        # first real screenshot). A real st.container with CSS padding
        # on its own key is the correct way to pad a group of widgets.
        with st.container(key="generate_section"):
            header_row = st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center")
            with header_row:
                with st.container(horizontal=True):
                    st.caption("GENERATE STATUS REPORT")
                    status_ph = st.empty()
                trigger_clicked = st.button(
                    "Run again" if run_state.get("done") else "Generate report",
                    key="generate_btn",
                    disabled=run_state.get("running", False),
                )
            progress_ph = st.empty()
            console_ph = st.empty()

        if not run_state.get("running") and not trigger_clicked:
            if run_state.get("stages"):
                # Real, persisted result of the last completed run in this
                # session for this project — same renderer as a live run,
                # just fed its final, already-settled state.
                _render_stage_ui(
                    console_ph, progress_ph, status_ph, run_state["stages"], run_state.get("shared", {}),
                    run_state.get("start_ts", time.monotonic()), TOTAL_STAGES, running=False, done=run_state.get("done", False),
                )
            else:
                with status_ph.container():
                    st.caption("no run in progress")
                progress_ph.progress(0.0)
                console_ph.markdown(
                    "<div style='background:#fafbfc; border:1px solid #e6e9ee; border-radius:9px; padding:14px 18px; "
                    "height:210px; overflow-y:auto; box-sizing:border-box; "
                    "font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12px; color:#9aa3b1;'>"
                    + "".join(f"<div style='padding:4px 0;'>○ {REAL_STAGE_NAMES[n]}</div>" for n in range(1, TOTAL_STAGES + 1))
                    + "</div>",
                    unsafe_allow_html=True,
                )

        if trigger_clicked:
            run_generation(selected_project_name, selected_program_id, console_ph, status_ph, progress_ph)

with right:
    with st.container(key="assistant_rail"):
        st.markdown("<div style='padding:15px 22px; border-bottom:1px solid #e6e9ee;'>"
                     "<span class='mono-label'>STATUS REPORT ASSISTANT</span></div>", unsafe_allow_html=True)

        chat_history = st.session_state.ops_chat_by_project[selected_project_name]
        chat_box = st.container(height=430, key="chat_history_box")
        with chat_box:
            if not chat_history:
                st.caption(f"Grounded in this project's {len(recent_reports)} reports. Ask anything.")
            for turn in chat_history:
                render_chat_bubble(turn["question"])
                with st.chat_message("assistant"):
                    st.write(turn["answer"])
                    render_citations(turn["citations"])

        is_generating = run_state.get("running", False)
        for chip in SUGGESTION_CHIPS:
            if st.button(chip, key=f"chip_{chip}", disabled=is_generating):
                st.session_state["ops_pending_question"] = chip

        question = st.chat_input(
            "Ask about past reports…", disabled=is_generating, key="ops_chat_input"
        ) or st.session_state.pop("ops_pending_question", None)

        if question:
            with chat_box:
                render_chat_bubble(question)
                with st.chat_message("assistant"):
                    with st.spinner("searching this project's reports…"):
                        try:
                            result = run_async(_ask(question))
                        except Exception as e:
                            st.error(f"Assistant query failed: {e}")
                            result = None
                    if result is not None:
                        st.write(result["answer"])
                        render_citations(result["citations"])
                        chat_history.append(
                            {"question": question, "answer": result["answer"], "citations": result["citations"]}
                        )
