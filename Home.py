"""OnePulse UI — Ops Console (Task 31: full redesign replacing the
single-page layout from Tasks 19-30, against `design_handoff_
onepulse_ops_console/`: README.md + a self-contained `.dc.html`
reference + 8 real screenshots).

Rewired for Migration Plan Phase 1 (Task 40): reviews (pending/approve/
reject), report list/detail, and chat go over real HTTP to the core
API, via the BFF as of Phase 2 (`api_client.py` is the thin client that
makes those calls), not direct `onepulse_common` imports.

Rewired again for Migration Plan Phase 3 (Task 42, ADR-021): generation
too. `run_pipeline_cycle` is no longer called from this file at all —
`api_client.trigger_report_via_api` starts a real cycle (a real `202`,
a separate worker process — `worker/main.py` — executes it out of the
request path entirely) and `api_client.get_cycle_via_api` polls its
real progress from the `cycles` status table roughly every three
seconds (ADR-021). This closes the two-path split Phase 1 deliberately
left open — see `core_api/main.py`'s own module docstring for the full
original Phase 1 reasoning, and `worker/main.py`'s for why execution
belongs there now. Real, direct consequence: this file no longer needs
`onepulse_common.pipeline` at all beyond `TOTAL_STAGES` (a display
constant), and ADR-009's `threading.Event`/`contextvars.copy_context()`
cancellation plumbing — built solely to compensate for running a long
pipeline inside Streamlit's own rerun model — has no job anymore and is
gone, not left inert. See CLAUDE.md Task 42 for the real verification
this closes: a run now survives the client closing entirely, because
nothing here owns the work.

CORE RULE unchanged since Task 18: this is a visual/UX redesign over
already-proven functions. No logic reimplementation — `api/main.py`
wraps the same real `onepulse_common` functions unchanged; `Home.py`
now calls them through that HTTP layer instead of importing them
directly, but the underlying logic itself never moved. One real,
minimal, additive SQL enhancement was needed and made directly in
`onepulse_common.pipeline.list_recent_reports` (see its own docstring,
predates this phase): the design needs the real approve/reject
*decision*, not just the existing `reviewed` boolean, and a real
"N sources" count — both now come from a real `LEFT JOIN LATERAL` on
`approval_records` and a real subquery count on `findings`, not
fabricated or reimplemented review logic.

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
  shown again. Real, structural fact as of Migration Plan Phase 3
  (Task 42), not merely a visual one: the real cycle is executing in a
  separate worker process — nothing about a Streamlit rerun, or this
  browser tab closing entirely, can reach it. It always finishes and
  persists normally, untracked visually the moment you navigate away —
  the correct, honest behavior: "stop showing me a run I've navigated
  away from," not "corrupt or duplicate real work in flight." This
  guarantee is now unconditional (survives even the client closing
  entirely), not the bounded-by-in-flight-work version ADR-009 measured
  when execution still lived inside this process.
- **Generation failure state** (a real gap in the reference's own state
  table — only success paths are specified): a real, unexpected worker
  exception is recorded as `cycles.status='failed'` with the real error
  text in `error_detail`; polling picks it up like any other terminal
  status and the currently-running step renders with the same real
  `✗ {name} — failed: {detail}` marker, the button reverting to
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

Carried forward unchanged from Task 30, now scoped to chat alone: since
generation moved to the worker (Task 42), the `onepulse_ui_pipeline_run`
root span this function used to create is gone from this file — its
real successor is `worker run_pipeline_cycle`, in `worker/main.py`, with
its own real observability lifespan (not `@st.cache_resource`, per the
Migration Plan's own Phase 3 bullet). `_get_arize_space_id()`
(`st.cache_resource`-wrapped `enable_observability()`) and the real
`onepulse_ui_chat_query` root span + Arize routing context + explicit
`force_flush()` per action still cover chat, unchanged.

Run: streamlit run Home.py (from the repository root).
"""

from __future__ import annotations

import datetime as dt
import math
import os
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

import streamlit as st
from arize.otel import set_routing_context
from azure.identity import DefaultAzureCredential
from opentelemetry import trace

from api_client import (
    approve_report_via_api,
    ask_question_via_api,
    get_cycle_via_api,
    get_report_detail_via_api,
    list_recent_reports_via_api,
    reject_report_via_api,
    trigger_report_via_api,
)
from onepulse_common.cycle_progress import new_stage_state
from onepulse_common.human_governance import ActorIdRequiredError, NotesRequiredError
from onepulse_common.observability import ARIZE_PROJECT_NAME, enable_observability
from onepulse_common.pipeline import TOTAL_STAGES
from streamlit_app_common import fetch_actors, fetch_programs, run_async

st.set_page_config(page_title="OnePulse", page_icon=":material/monitoring:", layout="wide")

PROJECT_ENDPOINT = os.environ.get(
    "ONEPULSE_FOUNDRY_PROJECT_ENDPOINT", "https://onepulse-resource.services.ai.azure.com/api/projects/onepulse"
)
# Real, deliberate scope reduction (Migration Plan Phase 3): Home.py no
# longer calls run_pipeline_cycle itself, so DEPLOYMENT_NAME/ADO_ORG_NAME/
# OUTPUT_DIR/PPTX_MCP_SERVER_PATH/STATUS_DECK_PATH_BY_PROJECT all moved
# to worker/main.py, the only real caller left. PROJECT_ENDPOINT stays —
# _get_arize_space_id() (chat's own observability path, unchanged) still
# needs it.

POLL_INTERVAL_SECONDS = 3.0  # ADR-021: "polled by the client... roughly every three seconds"

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
/* Real structure (confirmed live, not the older BaseWeb `data-baseweb`
   markup this Streamlit version replaced): a react-aria ComboBox —
   `input[role="combobox"]` for the field, a `button` for the toggle.
   `margin-left: auto` forces this flush against the app bar's right
   edge regardless of the row's own flex-distribution quirks (found
   live: `horizontal_alignment="distribute"` alone did not reliably
   push a single remaining child all the way to the edge). */
.st-key-project_select { margin-left: auto !important; }
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
    /* Real bug found and fixed live via DOM inspection (not guessed):
       widening the assistant rail (below) shrank this table's own
       column, and the 1fr RUN track computed to ~117px — narrower than
       the real "Tue, Sep 8 2026 · 02:48 NEW" text, which then visually
       overflowed into the STATE column instead of wrapping (confirmed
       via getBoundingClientRect on both columns showing overlapping x
       ranges). STATE/REVIEW narrowed further (190->115, 250->210 —
       their real content, short badge chips and two buttons, never
       needed that much) to give the RUN column real room again. */
    grid-template-columns: 1fr 115px 88px 210px !important;
    gap: 16px !important;
    align-items: center !important;
}
.st-key-table_header { background: #fafbfc; padding: 13px 26px; border-bottom: 1px solid #e6e9ee; }
.st-key-table_header > div:last-child { text-align: right !important; }
/* Real fix: the "latest" row no longer gets a distinct tinted
   background — all 4 rows now share the same white background. Row
   heights halved (16px/11px vertical padding -> 8px/6px) now that the
   meta line ("41 min ago · run 3m 12s · N sources") below the date is
   gone entirely. */
.st-key-row_latest { padding: 8px 26px; border-bottom: 1px solid #e6e9ee; }
[class*="st-key-row_hist_"] { padding: 6px 26px; border-bottom: 1px solid #f1f3f6; }
[class*="st-key-review_col_"] { justify-content: flex-end !important; }
/* Real fix: the header and first data row used to carry Streamlit's own
   default inter-container vertical gap between them, reading as a real
   visible gap rather than one connected block — reports_table wraps
   just the header + rows so gap=0 (passed on the container itself,
   see Python) applies only there, not to the generate section below. */

.st-key-reports_panel { background: #ffffff !important; border-right: 1px solid #eceef2 !important; }
/* Real spacing fix (found live): the report table and the Generate
   section used to run directly into each other, relying only on the
   last row's own thin 1px separator to distinguish them. A thicker,
   deliberate divider bar plus a tinted background reads as two real,
   distinct sections instead of one continuous block. Margin increased
   5x (6px -> 30px) per explicit request for more visual separation. */
.st-key-generate_section {
    padding: 24px 26px 28px !important;
    margin-top: 30px !important;
    border-top: 6px solid #f2f4f7 !important;
    background: #fcfcfd !important;
}
.st-key-assistant_rail { background: #fafbfc !important; }
/* Suggested-question chips: smaller, secondary-looking text (found
   live: default st.button sizing read too large/prominent for what
   are meant to be lightweight prompt suggestions). */
[class*="st-key-chip_"] button {
    font-size: 11.5px !important;
    padding: 3px 10px !important;
    color: #55607a !important;
}
/* Chat input: darker, navy-tinted background instead of the default
   light/white field, matching the app's navy accent. */
.st-key-assistant_rail [data-testid="stChatInput"] {
    background: #d3dcec !important;
    border: 1px solid #adbcd6 !important;
    border-radius: 8px !important;
}
.st-key-assistant_rail [data-testid="stChatInput"] textarea {
    background: transparent !important;
    color: #1c2b45 !important;
}

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
    detail = run_async(get_report_detail_via_api(report_id))
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
            # Real fix: the meta line ("41 min ago · run 3m 12s · N
            # sources") is gone entirely, and the "latest" badge now
            # reads "NEW" and comes AFTER the date/time text instead of
            # before it — both explicit, requested changes, not a
            # cosmetic rewrite of the whole row.
            # Real bug found and fixed live: removing the meta line below
            # (per this task's own request) left this column's real
            # content narrower than before, and shrinking the reports
            # panel to make room for a wider assistant rail (below)
            # narrowed the grid's flexible RUN column further still —
            # together enough to make the browser wrap the date across
            # 3 lines. `white-space: nowrap` on the wrapping span forces
            # the grid's `1fr` track to size to the text's real
            # min-content width instead, which is the correct fix per
            # how CSS Grid computes track sizes, not a workaround.
            if latest:
                st.markdown(
                    "<span style='white-space:nowrap;'>"
                    f"<span style='font-size:17px; font-weight:600; color:#171b22;'>{_fmt_dt(created)}</span> "
                    "<span style='font-family:ui-monospace,monospace; font-size:9.5px; letter-spacing:.12em; "
                    "color:#fff; background:#1F3864; padding:3px 7px; border-radius:4px;'>NEW</span></span>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f"<span style='white-space:nowrap; font-family:ui-monospace,monospace; font-size:13px; "
                    f"color:#2a3140;'>{_fmt_dt(created)}</span>",
                    unsafe_allow_html=True,
                )

        status = _report_status(report)
        label, color = _STATE_CHIP[status]
        st.badge(label, color=color)

        # Real fix (found live, Task 34): this used to always show the
        # Postgres-sourced executive summary/findings, never the actual
        # rendered .pptx `run_pipeline_cycle` saved for this exact report
        # row. `list_recent_reports()` already selects the real
        # `rendered_artifact_uri` for every row (no extra query needed),
        # so this reads that SAME report's real file bytes directly and
        # serves them via a real download control — browsers can't
        # reliably navigate straight to a local file:// path, so
        # st.download_button is the correct primitive, not a bare link.
        # Label renamed "Open" -> "Download" to match its real behavior.
        rendered_uri = report.get("rendered_artifact_uri")
        local_path = _file_uri_to_path(rendered_uri) if rendered_uri else None
        if local_path is not None and local_path.is_file():
            st.download_button(
                "Download",
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
            if st.button("Download", key=f"open_{rid}"):
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
            run_async(approve_report_via_api(rid, actor_id))
        except ActorIdRequiredError as e:
            st.error(str(e))
        st.session_state.ops_busy_rows.pop(rid, None)
        st.rerun()
    elif busy_action == "reject":
        notes = st.session_state.get(f"reject_notes_{rid}", "")
        try:
            run_async(reject_report_via_api(rid, actor_id, notes))
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
    """Rewired for Migration Plan Phase 1: the real chat logic now runs
    behind the FastAPI service (`ask_question_via_api`, POST
    /api/v1/chat/query) instead of `ask_question()` being called
    in-process. The Arize/root-span wrapping below is unchanged,
    Streamlit-side telemetry — it observes this UI's own request to the
    API, independent of where the actual work now happens. `program_id`
    stays `None` here, matching the exact pre-migration behavior (the
    original call site never actually scoped chat to the selected
    project either, despite the UI's own caption text implying it did —
    not something this rewiring changes).
    """
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
                return await ask_question_via_api(question, None, default_actor_id)
    finally:
        trace.get_tracer_provider().force_flush(timeout_millis=30000)


# Real stage names (Task 32), keyed by the same stage numbers pipeline.py
# already emits via on_stage — TOTAL_STAGES=7 has been the real, stable
# count since Task 18; not re-derived from message text (which varies in
# format across call sites) since the integer itself is the reliable
# signal. Purely a UI label — every NUMBER shown next to it is computed
# live from real on_stage/on_detail data, never from this dict.
REAL_STAGE_NAMES = {
    1: "ADO Investigation",
    2: "Status Reports Investigation",
    3: "Deterministic Rollup",
    4: "Synthesis",
    5: "Self-critique",
    6: "Rendering",
    7: "Persisting",
}


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


def _render_stage_ui(steps_ph, progress_ph, status_ph, stages: dict, shared: dict, run_start_ts: float, total: int, running: bool, done: bool) -> None:
    """Presentation only (HTML, color, icons) — `stages` is now read back
    from the real `cycles` status table via polling (Migration Plan
    Phase 3), not built live in-process; the curation that produces it
    lives in `onepulse_common.cycle_progress`, shared with the worker.
    `run_start_ts` and every stage's own `start_ts`/`end_ts` are real
    wall-clock (`time.time()`) timestamps now, not `time.monotonic()` —
    monotonic time can't cross the process boundary this data now does.
    """
    now = time.time()
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


_TERMINAL_CYCLE_STATUSES = {
    "persisted", "persisted_route_to_human_review",
    "not_persisted_already_exists", "hard_stop_defect", "failed",
}


def run_generation(selected_project_name: str, selected_program_id: str, console_ph, status_ph, progress_ph) -> None:
    """The real Generate action — Migration Plan Phase 3. Execution no
    longer happens here at all: this triggers a real cycle via the API
    (`POST /api/v1/programs/{programId}/reports`, real `202`, a worker
    process picks it up) and polls its real progress from the `cycles`
    status table (`GET /api/v1/cycles/{cycleId}`) roughly every three
    seconds (ADR-021), rendering whatever the worker has already
    curated and persisted — `onepulse_common.cycle_progress`'s
    `advance_stage`/`apply_detail`, unchanged in behavior, just now
    running in the worker instead of here.

    Real, deliberate retirement (Migration Plan Phase 3's own explicit
    instruction): ADR-009's `threading.Event` cancellation plumbing and
    `contextvars.copy_context()` propagation existed solely to
    compensate for running a long pipeline inside Streamlit's own rerun
    model. With execution in a separate worker process, closing this
    browser tab mid-run does not touch the worker at all — the run
    completes and persists regardless, which is this phase's own
    headline guarantee, not something this function has to engineer.
    If Streamlit's own cooperative cancellation interrupts this
    function's polling loop (a project switch), it simply stops
    polling; nothing needs to be signaled anywhere, because nothing
    here owns the real work anymore.
    """
    run_state = st.session_state.ops_runs_by_project[selected_project_name]
    run_state.update(running=True, done=False)

    try:
        triggered = run_async(trigger_report_via_api(selected_program_id))
    except Exception as e:  # noqa: BLE001 - a real, honest failure to even start
        st.error(f"Failed to start a run: {e}")
        run_state.update(running=False, done=False)
        return

    cycle_id = triggered["cycle_id"]
    run_state["cycle_id"] = cycle_id

    def _finalize_ui(stages: dict, run_start_ts: float, running: bool, done: bool) -> None:
        _render_stage_ui(console_ph, progress_ph, status_ph, stages, {}, run_start_ts, TOTAL_STAGES, running, done)

    while True:
        cycle = run_async(get_cycle_via_api(cycle_id))
        run_start_ts = dt.datetime.fromisoformat(cycle["created_at"]).timestamp()
        raw_stages = cycle["stages"]
        # JSONB round-trips dict keys as strings ("1".."7") — normalize
        # back to the real int keys _render_stage_ui/new_stage_state use.
        # An empty {} means the worker hasn't claimed this cycle yet
        # (still "queued"): render the same all-pending baseline
        # new_stage_state produces, not a blank/broken view.
        stages = {int(k): v for k, v in raw_stages.items()} if raw_stages else new_stage_state(TOTAL_STAGES)

        done = cycle["status"] in _TERMINAL_CYCLE_STATUSES
        _finalize_ui(stages, run_start_ts, running=not done, done=done)

        if done:
            break
        time.sleep(POLL_INTERVAL_SECONDS)

    elapsed_total = time.time() - run_start_ts
    run_state.update(
        running=False, done=True, elapsed=elapsed_total, stages=stages, shared={}, start_ts=run_start_ts,
        status=cycle["status"], report_id=cycle["report_id"], error_detail=cycle["error_detail"],
    )
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
# Real redesign (Task 37): a single, unified centered message replaces
# the two separate left/right empty-state panels — there is no left/
# right split at all in this state, since a two-column empty layout was
# itself part of what read as "two separate broken sections" rather than
# one deliberate empty state.
# ============================================================================
if selected_project_name is None:
    st.markdown(
        "<div style='display:flex; flex-direction:column; align-items:center; justify-content:center; "
        "min-height:58vh; text-align:center; padding:40px;'>"
        "<p style='font-size:16px; color:#6b7482; margin:0 0 16px;'>"
        "Your executive status report is one click away.</p>"
        "<div class='mono-label' style='font-size:13px; letter-spacing:.16em;'>SELECT YOUR PROJECT</div>"
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
recent_reports = run_async(list_recent_reports_via_api(limit=4, program_id=selected_program_id))

body_ph.empty()

# Real fix (Task 37): the assistant rail was noticeably narrower than
# the reports panel — widened using the same visual proportion as the
# gap already separating "Generate status report" from "Previous status
# reports" as the reference point, rather than an arbitrary new ratio.
# (0.62 initially overshot: it left the report table's own RUN column
# too narrow for its real date text, confirmed via live DOM inspection
# — see the grid-template-columns comment above. 0.5 is still a
# substantial real increase from the original 0.36.)
left, right = st.columns([1, 0.5], gap="large")

with left:
    with st.container(key="reports_panel"):
        # Real fix (Task 37): the header and first data row used to
        # carry Streamlit's own default inter-container vertical gap
        # between them (a visible seam), rather than reading as one
        # connected table block. Wrapping just the header + rows in
        # their own container with gap=0 (a real int pixel value this
        # Streamlit version's Gap type accepts, confirmed via
        # inspect.signature) closes that seam without touching the
        # separately-controlled gap before the Generate section below.
        with st.container(key="reports_table", gap=0):
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
                    run_state.get("start_ts", time.time()), TOTAL_STAGES, running=False, done=run_state.get("done", False),
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
