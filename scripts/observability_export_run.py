"""Real export run for Task 8: send actual AgentsClient spans to the
newly-connected Application Insights resource (onepulse-observability),
so we can verify, via a real query, exactly what lands in Foundry's
Observability tab — not just what a local in-memory exporter captures.

This is the infra-tracing half only. Per explicit framing: Application
Insights/this native tracing gives infra-level signals (latency, token
counts, tool-call spans) inside the Foundry portal. It does not replace
Arize, which remains the real quality-eval tool (groundedness,
hallucination scoring) — see CLAUDE.md's Observability Scope section.

Run: python scripts/observability_export_run.py
"""

from __future__ import annotations

import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from azure.ai.agents import AgentsClient
from azure.ai.agents.telemetry import AIAgentsInstrumentor
from azure.ai.projects import AIProjectClient
from azure.core.settings import settings
from azure.core.tracing.ext.opentelemetry_span import OpenTelemetrySpan
from azure.identity import DefaultAzureCredential
from azure.monitor.opentelemetry import configure_azure_monitor
from opentelemetry import trace

from onepulse_common.agent_cleanup import maybe_delete_agent

PROJECT_ENDPOINT = "https://onepulse-resource.services.ai.azure.com/api/projects/onepulse"
DEPLOYMENT_NAME = "onePulse-gpt-5-mini"


def main() -> None:
    credential = DefaultAzureCredential()
    project_client = AIProjectClient(endpoint=PROJECT_ENDPOINT, credential=credential)
    conn_str = project_client.telemetry.get_application_insights_connection_string()
    print(f"Real Application Insights connection string resolved (App ID visible): ...{conn_str[-40:]}")

    configure_azure_monitor(connection_string=conn_str)
    settings.tracing_implementation = OpenTelemetrySpan
    AIAgentsInstrumentor().instrument(enable_content_recording=True)

    agents_client = AgentsClient(endpoint=PROJECT_ENDPOINT, credential=credential)
    with agents_client:
        agent = agents_client.create_agent(
            model=DEPLOYMENT_NAME,
            name="onepulse-observability-export-agent",
            instructions="You are a helpful assistant.",
        )
        thread = agents_client.threads.create()
        agents_client.messages.create(
            thread_id=thread.id, role="user", content="Say 'real observability export check: OK'."
        )
        run = agents_client.runs.create_and_process(thread_id=thread.id, agent_id=agent.id)
        print(f"Run status: {run.status}, run id: {run.id}, agent id: {agent.id}")
        maybe_delete_agent(agents_client, agent.id, label=agent.name)

    provider = trace.get_tracer_provider()
    if hasattr(provider, "force_flush"):
        provider.force_flush()
    print("\nFlushed. Waiting 60s for Azure Monitor ingestion before querying...")
    time.sleep(60)
    print(f"\nQuery App Insights for run id {run.id} to confirm real ingestion.")


if __name__ == "__main__":
    main()
