"""Real CLI front end for the Chat Assistant (LLD Section 2.3), same
precedent as scripts/review_cli.py: a direct, runnable front end to a
real onepulse_common function, not a stub.

Observability wiring is deliberately duplicated from
scripts/run_pipeline.py's `enable_observability()` rather than factored
into a shared module: this project already has one working,
live-verified copy of this real recipe (dual export from one shared
OpenTelemetry TracerProvider — Application Insights + Arize, plus the
real fixes for the azure-monitor-opentelemetry logging-handler bug and
the explicit-flush requirement, see CLAUDE.md's Observability Scope).
Refactoring that already-verified script to share code was not asked
for here and would mean re-verifying it; a second real, working copy is
the lower-risk choice, the same way scripts/ado_investigation_spike.py
and scripts/foundry_agent_spike.py already carry their own independent
copies of earlier real findings rather than importing from each other.

Usage:
    python scripts/chat_cli.py "was the vendor contract issue ever linked to a work item?"
    python scripts/chat_cli.py --program-id <uuid> "..."
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from agent_framework.foundry import FoundryChatClient
from agent_framework.observability import enable_instrumentation
from arize.otel import ArizeRoutingSpanProcessor, Endpoint, Transport, set_routing_context
from azure.ai.projects import AIProjectClient
from azure.core.settings import settings
from azure.core.tracing.ext.opentelemetry_span import OpenTelemetrySpan
from azure.identity import DefaultAzureCredential
from azure.monitor.opentelemetry import configure_azure_monitor
from dotenv import load_dotenv
from openinference.instrumentation.agent_framework import AgentFrameworkToOpenInferenceProcessor
from opentelemetry import trace
from opentelemetry.instrumentation.logging.handler import LoggingHandler as _OTelLoggingHandler

from onepulse_common.chat_assistant import ask_question
from onepulse_common.embeddings import build_embedding_client
from onepulse_common.search_index import build_search_client

load_dotenv()

PROJECT_ENDPOINT = os.environ.get(
    "ONEPULSE_FOUNDRY_PROJECT_ENDPOINT", "https://onepulse-resource.services.ai.azure.com/api/projects/onepulse"
)
DEPLOYMENT_NAME = os.environ.get("ONEPULSE_FOUNDRY_DEPLOYMENT_NAME", "onePulse-gpt-5-mini")
ARIZE_PROJECT_NAME = "onepulse"


def enable_observability(credential: DefaultAzureCredential) -> str:
    """Same real recipe as scripts/run_pipeline.py's enable_observability()
    — see that file's comments for the full findings trail behind each
    fix applied here.
    """
    project_client = AIProjectClient(endpoint=PROJECT_ENDPOINT, credential=credential)
    app_insights_conn_str = project_client.telemetry.get_application_insights_connection_string()

    arize_space_id = os.environ.get("ONEPULSE_ARIZE_SPACE_ID")
    arize_api_key = os.environ.get("ONEPULSE_ARIZE_API_KEY")
    if not arize_space_id or not arize_api_key:
        raise RuntimeError("ONEPULSE_ARIZE_SPACE_ID / ONEPULSE_ARIZE_API_KEY not set in .env")

    span_processors = [
        AgentFrameworkToOpenInferenceProcessor(),
        ArizeRoutingSpanProcessor(api_key=arize_api_key, endpoint=Endpoint.ARIZE, transport=Transport.GRPC),
    ]

    os.environ.setdefault("OTEL_LOGS_EXPORTER", "none")

    configure_azure_monitor(
        connection_string=app_insights_conn_str,
        disable_logging=True,
        instrumentation_options={"logging": {"enabled": False}},
        span_processors=span_processors,
    )
    settings.tracing_implementation = OpenTelemetrySpan

    logging.root.handlers = [h for h in logging.root.handlers if not isinstance(h, _OTelLoggingHandler)]

    enable_instrumentation(enable_sensitive_data=True)
    return arize_space_id


async def run(question: str, program_id: str | None) -> dict:
    credential = DefaultAzureCredential()
    arize_space_id = enable_observability(credential)

    tracer = trace.get_tracer(__name__)
    try:
        with tracer.start_as_current_span("onepulse_chat_query") as root_span:
            root_span.set_attribute("onepulse.question", question)
            if program_id:
                root_span.set_attribute("onepulse.program_id", program_id)

            with set_routing_context(space_id=arize_space_id, project_name=ARIZE_PROJECT_NAME):
                chat_client = FoundryChatClient(
                    project_endpoint=PROJECT_ENDPOINT, model=DEPLOYMENT_NAME, credential=credential
                )
                search_client = build_search_client(credential)
                embedding_client = build_embedding_client(credential)
                try:
                    result = await ask_question(
                        chat_client, search_client, embedding_client, question, program_id=program_id
                    )
                finally:
                    await search_client.close()
                    await embedding_client.close()
    finally:
        flushed = trace.get_tracer_provider().force_flush(timeout_millis=30000)
        print(f"\nTelemetry flush before exit: {'OK' if flushed else 'TIMED OUT OR FAILED'}", file=sys.stderr)

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question")
    parser.add_argument("--program-id", default=None, help="Restrict retrieval to this program's reports.")
    args = parser.parse_args()

    result = asyncio.run(run(args.question, args.program_id))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
