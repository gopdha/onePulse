"""Real Phase 8-shaped orchestration: Investigation -> Status Update
Analysis -> Deterministic Status Rollup -> Synthesis -> Self-critique ->
[exactly one revision if needed] -> Rendering -> Postgres persistence,
in the order High-Level Design Section 2 specifies, against real Azure
DevOps data.

This is the CLI entry point for that chain — see the tracker entries
below for its history: originally scripts/demo_report_pipeline.py
(classic azure.ai.agents.AgentsClient), renamed and cleaned up, migrated
to Microsoft Agent Framework, and — as of Task 18 — its actual pipeline
logic moved into `onepulse_common.pipeline.run_pipeline_cycle()` so the
Streamlit UI's Home page ("Trigger Pipeline") can call the exact same
real code path this script does, not a reimplementation of it. This
file is now a thin wrapper: real credential/observability setup, real
PAT loading, and printing that shared function's progress callbacks to
the console — the actual agent/persistence logic lives in
`onepulse_common/pipeline.py`.

Honest scope note: this run persists its real output to Postgres
(Phase 2's schema, `reports`/`findings`/`untracked_items` —
`onepulse_common.pipeline.persist_report()`) as its final stage.
A `route_to_human_review` outcome persists with `reviewed=FALSE`, same
as `approved` (Phase 7's own confirmed finding: FR-7 requires Program
Lead approval for every rendered report, not only ones the QA gate
routes to human review) — `scripts/review_cli.py` is the real, separate
path that acts on it from there. This script's job ends at persisting
an unreviewed report; it never marks anything approved or rejected
itself.

*** PAT-BASED AUTH — DIAGNOSTIC/DEMO USE ONLY, NEVER THE PATTERN FOR REAL
PHASE 3 CODE, REMOVE BEFORE THAT WORK BEGINS. *** Same time-boxed
exception to CLAUDE.md convention #4 as scripts/ado_investigation_spike.py
(Task 4) — see CLAUDE.md's Phase 0 tracker for why (`gopdha` is an
MSA-only ADO org; neither `--authentication azcli` nor `--authentication
interactive` ever reached its real member identity across four real
attempts). The real Entra-ID fix is still outstanding.

*** SDK MIGRATION (Phase 0/Task 10, 2026-09-05): classic
azure.ai.agents.AgentsClient -> Microsoft Agent Framework
(agent_framework + agent_framework.foundry). ***
See CLAUDE.md's Foundry Agent Integration - Path Resolution for the full
real-findings trail. Real, accepted trade-off: the client-side
`Agent(client=FoundryChatClient(...))` construction used here creates no
portal-visible resource, unlike classic AgentsClient's create_agent() —
Arize's own dashboard is the intended visibility replacement.

Observability: dual real export from one shared OpenTelemetry
TracerProvider — Application Insights (infra-level) AND Arize
(openinference-shaped). See CLAUDE.md's "Observability Scope" for why
neither replaces the other.

Config: read from a real .env file (see .env.example), not environment
variables set by hand — copy .env.example to .env once and fill in
ONEPULSE_ADO_PAT (raw token, not base64 — this script encodes it),
ONEPULSE_ARIZE_SPACE_ID, and ONEPULSE_ARIZE_API_KEY.

Run: python scripts/run_pipeline.py
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from agent_framework.foundry import FoundryChatClient
from arize.otel import set_routing_context
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv
from opentelemetry import trace

from investigation.investigate import investigate, load_ado_pat
from onepulse_common.observability import ARIZE_PROJECT_NAME, enable_observability
from onepulse_common.pipeline import TOTAL_STAGES, run_reporting_stages

load_dotenv()

PROJECT_ENDPOINT = os.environ.get(
    "ONEPULSE_FOUNDRY_PROJECT_ENDPOINT", "https://onepulse-resource.services.ai.azure.com/api/projects/onepulse"
)
DEPLOYMENT_NAME = os.environ.get("ONEPULSE_FOUNDRY_DEPLOYMENT_NAME", "onePulse-gpt-5-mini")
ADO_ORG_NAME = os.environ.get("ONEPULSE_ADO_ORG", "gopdha")
STATUS_DECK_PATH = os.environ.get("ONEPULSE_STATUS_DECK_PATH", "sample_status_deck.pptx")

OUTPUT_DIR = "output"  # real per-project path computed by onepulse_common.pipeline.build_output_path()
PPTX_MCP_SERVER_PATH = "scripts/pptx_mcp_server.py"


def parse_args() -> argparse.Namespace:
    """Real argparse guard — added because there was none: `-h`/
    `--help` and any unrecognised flag previously fell straight through
    to `asyncio.run(main())` with no inspection of `sys.argv` at all, so
    `python scripts/run_pipeline.py --help` silently launched a real
    pipeline run (confirmed: this is the exact accidental run already
    documented in CLAUDE.md's Task 30 entry). `argparse.parse_args()`
    itself exits before returning on `-h`/`--help` or an unrecognised
    flag — no special-casing of the literal string needed.
    """
    parser = argparse.ArgumentParser(description="Run the real OnePulse report pipeline once, end to end.")
    parser.add_argument(
        "--project",
        default=os.environ.get("ONEPULSE_ADO_PROJECT", "singleSlide"),
        help="Real Azure DevOps project name to investigate (default: singleSlide, or $ONEPULSE_ADO_PROJECT).",
    )
    return parser.parse_args()


def print_stage(n: int, total: int, message: str) -> None:
    print(f"\n[{n}/{total}] {message}")


def print_detail(message: str) -> None:
    print(f"      {message}")


async def main(ado_project_name: str) -> None:
    ado_pat_b64 = load_ado_pat()

    credential = DefaultAzureCredential()
    arize_space_id = enable_observability(credential, PROJECT_ENDPOINT)

    print(f"OnePulse real pipeline run — org '{ADO_ORG_NAME}', project '{ado_project_name}'")

    # Real structural fix (Task 11): one explicit root span, kept active
    # for the whole run via `with`, so every span created underneath
    # (agent.run(), MCP tool calls) nests under one shared parent rather
    # than each becoming its own root trace. See CLAUDE.md's
    # "Observability Scope" for the full real-findings trail.
    tracer = trace.get_tracer(__name__)
    try:
        # Real ordering bug fixed (Task 35, found live from a real Arize
        # screenshot showing scattered top-level siblings instead of one
        # nested tree — traced to real Application Insights
        # customDimensions data, not assumed): this used to nest
        # set_routing_context() INSIDE the root span, so the root span
        # was created before arize.space_id ever existed in the ambient
        # context — ArizeRoutingSpanProcessor.on_start() had nothing to
        # read, and on_end() then silently dropped this span entirely
        # (its own "No 'arize.space_id' attribute found" warning). The
        # span's real children still correctly carried its real span ID
        # as their own parent (confirmed directly — the OTel data itself
        # was never broken), but since Arize never received the parent
        # they pointed to, they rendered as scattered, disconnected
        # top-level siblings. This exact gap existed here too, in the
        # single-threaded CLI path — confirming it predates and is
        # unrelated to Task 32's UI threading change. Swapping the
        # nesting so the routing context is the OUTER manager means it's
        # already active by the time the root span is created, so it
        # genuinely gets arize.space_id set on itself and is no longer
        # skipped.
        with set_routing_context(space_id=arize_space_id, project_name=ARIZE_PROJECT_NAME):
            with tracer.start_as_current_span("onepulse_pipeline_run") as root_span:
                root_span.set_attribute("onepulse.ado_org", ADO_ORG_NAME)
                root_span.set_attribute("onepulse.ado_project", ado_project_name)

                # Migration Plan Phase 4: this CLI is the one real,
                # deliberate exception to "Investigation and Reporting
                # are separate processes coordinated by a queue" — a
                # standalone, un-queued, in-process composition for
                # scripted/headless local use, same shape this project
                # has kept since Task 9/18. It is the ONE place allowed
                # to import both `investigation.investigate` (Node/ADO
                # PAT-adjacent) and `onepulse_common.pipeline`
                # (Reporting-stage logic) together — see
                # `onepulse_common.pipeline.run_reporting_stages`'s own
                # docstring for why that composition can't live in the
                # shared library itself. Each function builds its own
                # real FoundryChatClient internally — two lightweight
                # instances instead of one shared one, the same real
                # shape the actual Investigation/Reporting services have
                # once split into separate processes, not a regression.
                investigation_chat_client = FoundryChatClient(
                    project_endpoint=PROJECT_ENDPOINT, model=DEPLOYMENT_NAME, credential=credential
                )

                print_stage(
                    1, TOTAL_STAGES,
                    f"Investigation — querying real Committed-tagged Features + children in '{ado_project_name}'",
                )
                findings, queried_item_count, tower_hierarchy = await investigate(
                    investigation_chat_client, ado_pat_b64, ADO_ORG_NAME, ado_project_name, print_detail
                )
                for f in findings:
                    print_detail(f"#{f['work_item_id']} {f['title']} — {f['status']}")

                result = await run_reporting_stages(
                    findings=findings,
                    queried_item_count=queried_item_count,
                    tower_hierarchy=tower_hierarchy,
                    project_endpoint=PROJECT_ENDPOINT,
                    deployment_name=DEPLOYMENT_NAME,
                    credential=credential,
                    ado_project_name=ado_project_name,
                    status_deck_path=STATUS_DECK_PATH,
                    pptx_mcp_server_path=PPTX_MCP_SERVER_PATH,
                    output_dir=OUTPUT_DIR,
                    on_stage=print_stage,
                    on_detail=print_detail,
                )

                root_span.set_attribute("onepulse.overall_status", result.overall_status)
                root_span.set_attribute("onepulse.revision_outcome", result.outcome)
                if result.report_id is not None:
                    root_span.set_attribute("onepulse.report_id", result.report_id)

                if result.rendered_path:
                    print(f"\nDone. Report saved to: {os.path.abspath(result.rendered_path)}")
    finally:
        # Real fix (Task 12): relying on azure-monitor-opentelemetry's
        # implicit shutdown_on_exit=True atexit hook was NOT reliable for
        # Arize's export specifically — see CLAUDE.md's "Observability
        # Scope" for the full real-findings trail. Flush explicitly, with
        # a generous timeout, and print the real result.
        flushed = trace.get_tracer_provider().force_flush(timeout_millis=30000)
        print(f"\nTelemetry flush before exit: {'OK' if flushed else 'TIMED OUT OR FAILED'}")


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(main(args.project))
