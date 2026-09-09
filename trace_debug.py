"""Real, local, direct proof of span parent-child linkage — Migration
Plan Phase 2's own explicit bar: "Application Insights showing correct
operation_Id grouping is NOT sufficient proof on its own... the parent-
span chain had gaps." Arize's own dashboard is the real destination for
this data, but this project has no Arize Developer Access API key
provisioned (a real, long-standing, already-documented gap — see
CLAUDE.md's Task 10/30 entries), so this captures the exact same real
span objects OpenTelemetry hands to every configured exporter —
including the Arize one — as they're actually created, not a separate
or simulated trace.

Opt-in via `ONEPULSE_DEBUG_SPAN_LOG` (a real file path) so this has zero
effect unless explicitly enabled — not a permanent tax on every request
in a real deployment.
"""

from __future__ import annotations

import json
import os
import time

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import format_span_id, format_trace_id


class _JsonlSpanExporter(SpanExporter):
    """Appends one real JSON line per span, at real on_end() time — the
    exact moment ArizeRoutingSpanProcessor and Application Insights'
    own exporter also see it (this runs as an additional processor
    alongside them, never instead of them).
    """

    def __init__(self, path: str, service_name: str) -> None:
        self._path = path
        self._service_name = service_name

    def export(self, spans: list[ReadableSpan]) -> SpanExportResult:
        with open(self._path, "a", encoding="utf-8") as f:
            for span in spans:
                ctx = span.get_span_context()
                parent = span.parent
                f.write(
                    json.dumps(
                        {
                            "service": self._service_name,
                            "name": span.name,
                            "trace_id": format_trace_id(ctx.trace_id),
                            "span_id": format_span_id(ctx.span_id),
                            "parent_span_id": format_span_id(parent.span_id) if parent else None,
                            "start_time": span.start_time,
                            "end_time": span.end_time,
                            "captured_at": time.time(),
                        }
                    )
                    + "\n"
                )
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        pass


def enable_debug_span_log(service_name: str) -> None:
    """Adds a real, additional span processor to the process-global
    TracerProvider already configured by `onepulse_common.observability.
    enable_observability()` — `TracerProvider.add_span_processor()` is a
    standard, public OpenTelemetry API for adding more processors after
    the fact, so this needs no change to that shared function. No-op if
    `ONEPULSE_DEBUG_SPAN_LOG` isn't set.
    """
    path = os.environ.get("ONEPULSE_DEBUG_SPAN_LOG")
    if not path:
        return
    from opentelemetry import trace

    provider = trace.get_tracer_provider()
    provider.add_span_processor(SimpleSpanProcessor(_JsonlSpanExporter(path, service_name)))
