"""Real dual observability export — Application Insights (infra-level:
latency, token counts, tool-call spans) AND Arize (openinference-shaped,
the real quality-eval tool) — from one shared OpenTelemetry
TracerProvider. See CLAUDE.md's "Observability Scope" for why neither
replaces the other; this module is the one real implementation of the
wiring, not a description of it duplicated per call site.

Moved here from `scripts/run_pipeline.py` (Task 30), where it was
originally built and proven (Tasks 8-13) — Home.py needs the identical,
already-working function, not a second copy of this real, non-trivial
setup (the CORE RULE that already moved the pipeline's own orchestration
logic into this package in Task 18). `scripts/run_pipeline.py` now
imports `enable_observability`/`ARIZE_PROJECT_NAME` from here instead of
defining them locally.

Real, deliberate scope note (Task 18, reversed by Task 30): the UI layer
originally did NOT wire this at all, to avoid re-initializing a global
TracerProvider on every Streamlit rerun. Task 29's own real stress test
demonstrated a concrete cost of that gap — diagnosing a UI-triggered
failure required a fresh CLI reproduction, since the UI run itself left
no trace anywhere. `st.cache_resource` (see Home.py) is Streamlit's own
documented mechanism for exactly this situation — an expensive,
process-global, stateful resource that must be created once and reused
across every rerun and every session, not recreated per call — so the
original concern is real but has a standard, correct fix, not a reason
to leave the UI unobserved indefinitely.
"""

from __future__ import annotations

import logging
import os

from agent_framework.observability import enable_instrumentation
from arize.otel import ArizeRoutingSpanProcessor, Endpoint, Transport
from azure.ai.projects import AIProjectClient
from azure.core.settings import settings
from azure.core.tracing.ext.opentelemetry_span import OpenTelemetrySpan
from azure.identity import DefaultAzureCredential
from azure.monitor.opentelemetry import configure_azure_monitor
from openinference.instrumentation.agent_framework import AgentFrameworkToOpenInferenceProcessor
from opentelemetry.instrumentation.logging.handler import LoggingHandler as _OTelLoggingHandler

ARIZE_PROJECT_NAME = "onepulse"


def enable_observability(credential: DefaultAzureCredential, project_endpoint: str) -> str:
    """Dual real export from one shared TracerProvider: Application
    Insights (infra-level) AND Arize (openinference-shaped). Returns the
    Arize space ID for use with `arize.otel.set_routing_context()`
    around each real agent-invoking action.

    Real, load-bearing constraint, unchanged since Task 8-13: this
    configures GLOBAL OpenTelemetry state (`configure_azure_monitor`
    calls `trace.set_tracer_provider(...)` once) — calling it more than
    once per process is exactly the re-init risk Task 18 originally
    deferred the whole UI wiring to avoid. Every real caller (this
    module's own callers) must ensure this runs at most once per
    process — `scripts/run_pipeline.py` does so by construction (one
    process per CLI run); `Home.py` does so via `st.cache_resource`.
    """
    project_client = AIProjectClient(endpoint=project_endpoint, credential=credential)
    app_insights_conn_str = project_client.telemetry.get_application_insights_connection_string()

    arize_space_id = os.environ.get("ONEPULSE_ARIZE_SPACE_ID")
    arize_api_key = os.environ.get("ONEPULSE_ARIZE_API_KEY")
    if not arize_space_id or not arize_api_key:
        raise RuntimeError("ONEPULSE_ARIZE_SPACE_ID / ONEPULSE_ARIZE_API_KEY not set in .env")

    # AgentFrameworkToOpenInferenceProcessor additively merges openinference.*
    # attributes onto each span's existing gen_ai.* ones (confirmed by reading
    # its real on_end() source: `span._attributes = {**span.attributes,
    # **openinference_attributes}`) — Application Insights keeps everything it
    # already had; it just also sees the extra attributes Arize needs.
    span_processors = [
        AgentFrameworkToOpenInferenceProcessor(),
        ArizeRoutingSpanProcessor(api_key=arize_api_key, endpoint=Endpoint.ARIZE, transport=Transport.GRPC),
    ]

    # Real, confirmed bug in the installed azure-monitor-opentelemetry==1.8.9:
    # its _default_disable_logging() unconditionally overwrites
    # configurations["disable_logging"] = False after **kwargs is merged in,
    # unless OTEL_LOGS_EXPORTER == "none" — so passing disable_logging=True
    # directly is silently discarded. This env var is the only path that
    # function actually honors.
    os.environ.setdefault("OTEL_LOGS_EXPORTER", "none")

    configure_azure_monitor(
        connection_string=app_insights_conn_str,
        disable_logging=True,
        instrumentation_options={"logging": {"enabled": False}},
        span_processors=span_processors,
    )
    settings.tracing_implementation = OpenTelemetrySpan

    # Real, confirmed finding (Task 9): azure-monitor-opentelemetry attaches
    # an OTel LoggingHandler to the root logger unconditionally, and it
    # crashes at interpreter shutdown. Same fix as before.
    logging.root.handlers = [h for h in logging.root.handlers if not isinstance(h, _OTelLoggingHandler)]

    enable_instrumentation(enable_sensitive_data=True)
    return arize_space_id
