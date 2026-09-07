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

import datetime as dt
import os
import time

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
.st-key-project_label p {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace !important;
    font-size: 11px !important;
    letter-spacing: 0.1em !important;
    color: #91a4c5 !important;
    margin: 0 !important;
}
/* Real structure (confirmed live, not the older BaseWeb `data-baseweb`
   markup this Streamlit version replaced): a react-aria ComboBox —
   `input[role="combobox"]` for the field, a `button` for the toggle. */
.st-key-project_select .stSelectbox { width: 280px; }
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
.st-key-row_latest { background: #f4f7fb; padding: 22px 26px; border-bottom: 1px solid #e6e9ee; }
[class*="st-key-row_hist_"] { padding: 15px 26px; border-bottom: 1px solid #f1f3f6; }
[class*="st-key-review_col_"] { justify-content: flex-end !important; }

.st-key-reports_panel { background: #ffffff !important; border-right: 1px solid #eceef2 !important; }
.st-key-generate_section { padding: 24px 26px 28px !important; }
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


@st.dialog("Report detail", width="large")
def show_report_dialog(report_id: int) -> None:
    detail = run_async(with_connection(get_report_detail, report_id))
    report = detail["report"]
    if report is None:
        st.error("Report not found.")
        return
    st.caption(f"{report['program_name']} — week of {report['week_of'].isoformat()}")
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

        if st.button("Open", key=f"open_{rid}"):
            show_report_dialog(rid)

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
        with tracer.start_as_current_span("onepulse_ui_chat_query") as root_span:
            root_span.set_attribute("onepulse.question", question)
            with set_routing_context(space_id=arize_space_id, project_name=ARIZE_PROJECT_NAME):
                return await ask_question(chat_client, search_client, embedding_client, question)
    finally:
        await search_client.close()
        await embedding_client.close()
        trace.get_tracer_provider().force_flush(timeout_millis=30000)


def run_generation(selected_project_name: str, selected_program_id: str, console_ph, status_ph, progress_ph) -> None:
    """The real Generate action. Reuses `run_pipeline_cycle` unmodified;
    only the presentation of its `on_stage`/`on_detail` callbacks is new.
    Real stage names and the real 7-stage fraction are shown — not the
    reference's fictional 4-stage taxonomy (see module docstring).
    """
    try:
        ado_pat_b64 = load_ado_pat()
        arize_space_id = _get_arize_space_id()
    except RuntimeError as e:
        st.error(str(e))
        return

    status_deck_path = STATUS_DECK_PATH_BY_PROJECT.get(selected_project_name, DEFAULT_STATUS_DECK_PATH)
    run_state = st.session_state.ops_runs_by_project[selected_project_name]
    run_state.update(running=True, done=False, log=[], start_ts=time.monotonic())
    log_lines: list[str] = ["$ awaiting run — investigation · status analysis · synthesis · render"]

    def _render_console() -> None:
        # A real bug found live: st.container(key="console_box", ...) raised
        # StreamlitDuplicateElementKey the moment a real run produced more
        # than one on_stage/on_detail callback in a single script execution
        # (an explicit key must be globally unique per script run, even when
        # writing into the same st.empty() placeholder each time — unlike
        # auto-generated element IDs, which this version of Streamlit does
        # let a placeholder reuse). Fixed by dropping the explicit key and
        # building one self-contained st.markdown() call per update instead,
        # with the console's styling moved inline (previously carried by the
        # now-removed `.st-key-console_box` CSS rule).
        lines_html = "".join(
            f"<div style='color:#c3ccda; white-space:pre-wrap;'>{line}</div>" for line in log_lines
        )
        console_ph.markdown(
            "<div style='background:#111722; border-radius:9px; padding:16px 18px; height:186px; "
            "overflow-y:auto; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:11.5px; "
            f"line-height:1.6;'>{lines_html}</div>",
            unsafe_allow_html=True,
        )

    def on_stage(n: int, total: int, message: str) -> None:
        elapsed = time.monotonic() - run_state["start_ts"]
        ts = f"{int(elapsed // 60):02d}:{int(elapsed % 60):02d}"
        log_lines.append(f"<span style='color:#788292;'>{ts}</span>  <span style='color:#8fb0e8;'>— {message.upper()}</span>")
        progress_ph.progress((n - 1) / total)
        with status_ph.container(horizontal=True):
            st.caption("GENERATE STATUS REPORT")
            st.markdown(f"<span style='color:#1F3864; font-size:11.5px;'>{message.lower()} · stage {n} of {total}</span>", unsafe_allow_html=True)
        _render_console()

    def on_detail(message: str) -> None:
        elapsed = time.monotonic() - run_state["start_ts"]
        ts = f"{int(elapsed // 60):02d}:{int(elapsed % 60):02d}"
        log_lines.append(f"<span style='color:#788292;'>{ts}</span>  <span style='color:#c3ccda;'>{message}</span>")
        _render_console()

    credential = DefaultAzureCredential()
    tracer = trace.get_tracer(__name__)
    try:
        with tracer.start_as_current_span("onepulse_ui_pipeline_run") as root_span:
            root_span.set_attribute("onepulse.ado_project", selected_project_name)
            with set_routing_context(space_id=arize_space_id, project_name=ARIZE_PROJECT_NAME):
                result = run_async(
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
            root_span.set_attribute("onepulse.overall_status", result.overall_status)
            root_span.set_attribute("onepulse.revision_outcome", result.outcome)
    except Exception as e:
        # Real, deliberate failure-state design (a real gap in the
        # reference's own spec — only success paths were documented):
        # a real error line in the console, button returns to idle.
        log_lines.append(f"<span style='color:#8A2F2F;'>✗ run failed: {e}</span>")
        _render_console()
        run_state.update(running=False, done=False)
        return
    finally:
        trace.get_tracer_provider().force_flush(timeout_millis=30000)

    elapsed_total = time.monotonic() - run_state["start_ts"]
    if result.outcome == "hard_stop_defect":
        log_lines.append("<span style='color:#8A2F2F;'>✗ hard-stop defect — nothing rendered or persisted</span>")
    elif result.persisted:
        log_lines.append("<span style='color:#7fc9a2;'>✓ report ready · awaiting review</span>")
        if result.report_id is not None:
            st.session_state.setdefault("ops_last_run_duration", {})[result.report_id] = elapsed_total
    else:
        # Real, honest case (Task 20/21's weekly-dedup constraint): the
        # run genuinely completed, but a report for this project/week
        # already exists — reports.findings are INSERT-only, so this
        # run's fresh output can't be reconciled into it. Not the same
        # as "report ready," and not a failure either.
        log_lines.append(
            f"<span style='color:#8fb0e8;'>· run complete — report_id={result.report_id} already exists "
            "for this week, not persisted</span>"
        )
    _render_console()
    progress_ph.progress(1.0)
    run_state.update(running=False, done=True, elapsed=elapsed_total)
    st.rerun()


# ============================================================================
# App bar — always present. Real "no eager loading": index=None means no
# project is selected on open, and every fetch below is gated on it.
# ============================================================================
with st.container(key="app_bar", horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
    st.markdown(
        "<span style='font-size:20px; font-weight:600; letter-spacing:-0.015em;'>OnePulse</span>"
        "&nbsp;&nbsp;<span style='font-size:13.5px; color:#a9b8d4;'>AI status reports · review queue · "
        "one project at a time</span>",
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
            with status_ph.container():
                st.caption("no run in progress" if not run_state.get("done") else f"done in {_fmt_duration(run_state.get('elapsed', 0))}")
            progress_ph.progress(1.0 if run_state.get("done") else 0.0)
            if run_state.get("log"):
                idle_lines_html = "".join(f"<div>{line}</div>" for line in run_state["log"])
            else:
                idle_lines_html = (
                    "<div style='color:#5a6577;'>$ awaiting run — investigation · status analysis · "
                    "synthesis · render</div>"
                )
            console_ph.markdown(
                "<div style='background:#111722; border-radius:9px; padding:16px 18px; height:186px; "
                "overflow-y:auto; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:11.5px; "
                f"line-height:1.6;'>{idle_lines_html}</div>",
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
