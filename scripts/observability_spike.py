"""Phase 0 observability go/no-go: what does Foundry-native GenAI
tracing actually capture for our real AgentsClient (thread/run) path?

Real finding from reading the installed SDK source before writing any
code here (not assumed):

  AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING gates
  `azure.ai.projects.telemetry.AIProjectInstrumentor`, whose `_agents_apis()`
  list (azure_ai_projects/telemetry/_ai_project_instrumentor.py) only
  wraps `AgentsOperations.create_version` — the newer "Agent resource"
  model this project deliberately deferred (see CLAUDE.md Path
  Resolution) — plus `get_openai_client()`. The lines that would wrap the
  classic `azure.ai.agents` thread/run surface are commented out in this
  installed version (azure-ai-projects==2.6.0). So setting that env var
  alone traces NOTHING for the AgentsClient path this project actually
  uses.

  The instrumentor that actually covers our real path is a SEPARATE
  class: `azure.ai.agents.telemetry.AIAgentsInstrumentor`
  (azure_ai_agents/telemetry/_ai_agents_instrumentor.py). Its
  `_agents_apis()` list wraps ThreadsOperations.create,
  MessagesOperations.create, RunsOperations.create/get/create_and_process,
  RunsOperations.submit_tool_outputs, MessagesOperations.list — i.e.
  exactly our real usage. It is NOT gated by
  AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING at all; it just needs
  azure-core-tracing-opentelemetry installed and an OpenTelemetry span
  implementation registered with azure-core's settings.

  Quality-eval signals (groundedness, hallucination, rubric scoring) live
  in a completely separate, unrelated subsystem —
  `azure.ai.projects.operations.EvaluationRulesOperations` / rubric
  evaluator models (`EvaluatorDefinitionType.RUBRIC`, `Dimension`,
  `pass_threshold`) — not the tracing/span mechanism at all. Grepping the
  actual span/attribute code in both instrumentors turns up only
  infra-level signals: thread/run/message/agent IDs, token usage counts,
  tool call names and arguments, latency (span duration), errors. No
  groundedness or hallucination attribute exists anywhere in either
  instrumentor.

  Real, live blocker hit while trying to export to the actual Foundry
  Observability tab: the `onepulse` Foundry project has NO Application
  Insights resource connected —
  `AIProjectClient(...).telemetry.get_application_insights_connection_string()`
  raises `ResourceNotFoundError: No Application Insights connection
  found.` That's a real portal-side action (Foundry portal -> Tracing ->
  Connect Application Insights), not something to script around. This
  spike instead proves what AIAgentsInstrumentor actually captures using
  a local in-memory span exporter against a real live agent run — no App
  Insights needed for that proof, but nothing here reaches the actual
  Foundry Observability tab until that resource is connected for real.

Run: python scripts/observability_spike.py
"""

from __future__ import annotations

import json
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from azure.ai.agents import AgentsClient
from azure.ai.agents.telemetry import AIAgentsInstrumentor
from azure.core.settings import settings
from azure.core.tracing.ext.opentelemetry_span import OpenTelemetrySpan
from azure.identity import DefaultAzureCredential
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from onepulse_common.agent_cleanup import maybe_delete_agent

PROJECT_ENDPOINT = "https://onepulse-resource.services.ai.azure.com/api/projects/onepulse"
DEPLOYMENT_NAME = "onePulse-gpt-5-mini"


def main() -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    settings.tracing_implementation = OpenTelemetrySpan

    AIAgentsInstrumentor().instrument(enable_content_recording=True)

    credential = DefaultAzureCredential()
    agents_client = AgentsClient(endpoint=PROJECT_ENDPOINT, credential=credential)

    with agents_client:
        agent = agents_client.create_agent(
            model=DEPLOYMENT_NAME,
            name="onepulse-observability-spike-agent",
            instructions="You are a helpful assistant.",
        )
        thread = agents_client.threads.create()
        agents_client.messages.create(thread_id=thread.id, role="user", content="Say 'observability check: OK'.")
        agents_client.runs.create_and_process(thread_id=thread.id, agent_id=agent.id)
        maybe_delete_agent(agents_client, agent.id, label=agent.name)

    spans = exporter.get_finished_spans()
    print(f"\n--- Real spans captured: {len(spans)} ---")
    for span in spans:
        print(f"\nSpan: {span.name}")
        print(f"  Duration: {(span.end_time - span.start_time) / 1e6:.2f} ms")
        for key, value in span.attributes.items():
            value_str = str(value)
            print(f"  {key} = {value_str[:200]}")
        for event in span.events:
            print(f"  Event: {event.name}")
            for key, value in event.attributes.items():
                print(f"    {key} = {str(value)[:300]}")


if __name__ == "__main__":
    main()
