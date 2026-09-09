"""BFF-only observability setup — deliberately NOT
`onepulse_common.observability.enable_observability`, because that
function's own real implementation calls `AIProjectClient(...).
telemetry.get_application_insights_connection_string()`, a real call
against the Foundry project. The BFF's own boundary (ADR-017) is "no
Postgres connection, no Azure AI Search, no Foundry — none, not even
for one convenient query" — reading a connection string is exactly the
kind of "just this one query" the boundary exists to prevent, so this
reads the identical real connection string from a plain environment
variable (`ONEPULSE_APPINSIGHTS_CONNECTION_STRING`, fetched once via
`az monitor app-insights component show` — see CLAUDE.md Task 41)
instead. Everything downstream of that (the dual Arize + Application
Insights export itself) is the same real, already-proven mechanism
`enable_observability` uses — duplicated here rather than shared,
specifically so this file's own import graph never has to touch
`onepulse_common.observability`'s Foundry import at all.
"""

from __future__ import annotations

import logging
import os

from arize.otel import ArizeRoutingSpanProcessor, Endpoint, Transport
from azure.core.settings import settings
from azure.core.tracing.ext.opentelemetry_span import OpenTelemetrySpan
from azure.monitor.opentelemetry import configure_azure_monitor
from openinference.instrumentation.agent_framework import AgentFrameworkToOpenInferenceProcessor
from opentelemetry.instrumentation.logging.handler import LoggingHandler as _OTelLoggingHandler

ARIZE_PROJECT_NAME = "onepulse"


def enable_bff_observability() -> str:
    """Same real dual export as `onepulse_common.observability.
    enable_observability`, minus the Foundry round-trip to fetch the
    connection string — see module docstring for why. Returns the real
    Arize space ID, same as the original.
    """
    app_insights_conn_str = os.environ.get("ONEPULSE_APPINSIGHTS_CONNECTION_STRING")
    if not app_insights_conn_str:
        raise RuntimeError("ONEPULSE_APPINSIGHTS_CONNECTION_STRING not set in .env")

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

    return arize_space_id
