# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_observability_trace_policy.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for request-root OpenTelemetry export policy.
"""

# Standard
from typing import Any

# Third-Party
import pytest

try:
    from opentelemetry import baggage, context as otel_context, trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from opentelemetry.sdk.trace.sampling import ALWAYS_OFF, ALWAYS_ON
    from opentelemetry.trace import NonRecordingSpan, SpanContext, SpanKind, TraceFlags, TraceState
except ImportError:
    pytest.skip("OpenTelemetry SDK is unavailable or incomplete", allow_module_level=True)

# First-Party
from mcpgateway.observability import RequestRootFilteringSpanProcessor, RequestRootSampler


def _provider(system_traces_enabled: bool = False, delegate: Any = ALWAYS_ON) -> tuple[TracerProvider, InMemorySpanExporter]:
    """Build an in-memory provider with request-root policy."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider(sampler=RequestRootSampler(delegate, system_traces_enabled=system_traces_enabled))
    processor = RequestRootFilteringSpanProcessor(SimpleSpanProcessor(exporter), system_traces_enabled=system_traces_enabled)
    provider.add_span_processor(processor)
    return provider, exporter


def test_request_root_and_children_export():
    """Export a SERVER root and its CLIENT and INTERNAL children."""
    provider, exporter = _provider()
    tracer = provider.get_tracer(__name__)

    with tracer.start_as_current_span("POST /mcp", kind=SpanKind.SERVER):
        with tracer.start_as_current_span("httpx.send", kind=SpanKind.CLIENT):
            pass
        with tracer.start_as_current_span("tool.invoke"):
            pass

    assert [span.name for span in exporter.get_finished_spans()] == ["httpx.send", "tool.invoke", "POST /mcp"]


def test_allowed_baggage_is_attached_to_auto_instrumented_children():
    """Promote request baggage onto SERVER and CLIENT spans."""
    provider, exporter = _provider()
    tracer = provider.get_tracer(__name__)
    request_context = baggage.set_baggage("tenant.id", "tenant-a")
    token = otel_context.attach(request_context)

    try:
        with tracer.start_as_current_span("POST /mcp", kind=SpanKind.SERVER):
            with tracer.start_as_current_span("httpx.send", kind=SpanKind.CLIENT):
                pass
    finally:
        otel_context.detach(token)

    spans = {span.name: span for span in exporter.get_finished_spans()}
    root_attributes = spans["POST /mcp"].attributes
    child_attributes = spans["httpx.send"].attributes
    assert root_attributes is not None
    assert child_attributes is not None
    assert root_attributes["baggage.tenant.id"] == "tenant-a"
    assert child_attributes["baggage.tenant.id"] == "tenant-a"


def test_unfiltered_parent_context_baggage_is_not_promoted():
    """Ignore raw extracted baggage that middleware did not attach."""
    provider, exporter = _provider()
    tracer = provider.get_tracer(__name__)
    remote_parent = SpanContext(
        trace_id=3,
        span_id=4,
        is_remote=True,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
        trace_state=TraceState(),
    )
    extracted_context = baggage.set_baggage("tenant.id", "untrusted")
    extracted_context = trace.set_span_in_context(NonRecordingSpan(remote_parent), extracted_context)

    with tracer.start_as_current_span("POST /mcp", context=extracted_context, kind=SpanKind.SERVER):
        pass

    attributes = exporter.get_finished_spans()[0].attributes
    assert attributes is not None
    assert "baggage.tenant.id" not in attributes


def test_background_roots_and_children_do_not_export():
    """Drop health, Redis, and SQL roots with their descendants."""
    provider, exporter = _provider()
    tracer = provider.get_tracer(__name__)

    with tracer.start_as_current_span("gateway.health_check_batch"):
        with tracer.start_as_current_span("gateway.health_check"):
            with tracer.start_as_current_span("GET", kind=SpanKind.CLIENT):
                pass
    with tracer.start_as_current_span("redis.GET", kind=SpanKind.CLIENT):
        pass
    with tracer.start_as_current_span("SELECT", kind=SpanKind.CLIENT):
        pass

    assert exporter.get_finished_spans() == ()


def test_unsampled_remote_parent_remains_unsampled():
    """Honor an unsampled remote parent for an inbound request."""
    provider, exporter = _provider()
    tracer = provider.get_tracer(__name__)
    remote_parent = SpanContext(
        trace_id=1,
        span_id=2,
        is_remote=True,
        trace_flags=TraceFlags(0),
        trace_state=TraceState(),
    )
    parent_context = trace.set_span_in_context(NonRecordingSpan(remote_parent))

    with tracer.start_as_current_span("POST /mcp", context=parent_context, kind=SpanKind.SERVER):
        pass

    assert exporter.get_finished_spans() == ()


def test_configured_sampler_can_drop_request_root():
    """Preserve configured SDK sampling after request policy permits a root."""
    provider, exporter = _provider(delegate=ALWAYS_OFF)
    tracer = provider.get_tracer(__name__)

    with tracer.start_as_current_span("POST /mcp", kind=SpanKind.SERVER):
        pass

    assert exporter.get_finished_spans() == ()


def test_system_tracing_exports_background_roots():
    """Export platform roots only when system tracing is enabled."""
    provider, exporter = _provider(system_traces_enabled=True)
    tracer = provider.get_tracer(__name__)

    with tracer.start_as_current_span("gateway.health_check_batch"):
        with tracer.start_as_current_span("gateway.health_check"):
            pass
    with tracer.start_as_current_span("redis.GET", kind=SpanKind.CLIENT):
        pass

    assert [span.name for span in exporter.get_finished_spans()] == ["gateway.health_check", "gateway.health_check_batch", "redis.GET"]


def test_empty_filter_does_not_call_exporter():
    """Avoid exporter calls when every candidate trace is filtered."""

    class CountingExporter(InMemorySpanExporter):
        """Count exporter invocations."""

        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        def export(self, spans: Any) -> Any:
            """Count and export a span batch."""
            self.calls += 1
            return super().export(spans)

    exporter = CountingExporter()
    provider = TracerProvider(sampler=ALWAYS_ON)
    provider.add_span_processor(RequestRootFilteringSpanProcessor(SimpleSpanProcessor(exporter)))
    tracer = provider.get_tracer(__name__)

    with tracer.start_as_current_span("gateway.health_check_batch"):
        pass

    assert exporter.calls == 0


@pytest.mark.parametrize("prefixed", [False, True])
@pytest.mark.parametrize("allowlisted", [False, True])
def test_sensitive_baggage_is_redacted_before_export(monkeypatch, prefixed, allowlisted):
    """Redact original baggage keys for manual and automatic spans."""
    from mcpgateway import observability
    from mcpgateway.utils import trace_redaction

    monkeypatch.setattr(trace_redaction, "_CONFIG_LOADED", True)
    monkeypatch.setattr(trace_redaction, "_REDACT_FIELDS", {"password", "apikey", "authorization"})
    values = {"password": "private-value-a", "api_key": "private-value-b", "authorization": "private-value-c", "tenant.id": "tenant-a", "excluded": "omit-me"}  # pragma: allowlist secret
    allowed = frozenset(values.keys() - {"excluded"}) if allowlisted else None
    monkeypatch.setattr(observability, "_BAGGAGE_SPAN_ATTRIBUTE_POLICY", observability.BaggageSpanAttributePolicy(prefixed, allowed))
    provider, exporter = _provider()
    tracer = provider.get_tracer(__name__)
    monkeypatch.setattr(observability, "_TRACER", tracer)
    request_context = otel_context.Context()
    for key, value in values.items():
        request_context = baggage.set_baggage(key, value, context=request_context)
    token = otel_context.attach(request_context)
    try:
        with tracer.start_as_current_span("request", kind=SpanKind.SERVER):
            with tracer.start_as_current_span("httpx", kind=SpanKind.CLIENT):
                pass
            with observability.create_span("manual"):
                pass
    finally:
        otel_context.detach(token)
        provider.shutdown()
    spans = exporter.get_finished_spans()
    assert len(spans) == 3
    prefix = "baggage." if prefixed else ""
    for span in spans:
        assert span.attributes is not None
        assert span.attributes[prefix + "tenant.id"] == "tenant-a"
        for key in ("password", "api_key", "authorization"):
            assert span.attributes[prefix + key] == "***"
        if allowlisted:
            assert prefix + "excluded" not in span.attributes


def test_baggage_retains_final_attribute_policy(monkeypatch):
    """Suppress denied identity attributes after baggage promotion."""
    from mcpgateway import observability

    monkeypatch.setattr(observability, "_BAGGAGE_SPAN_ATTRIBUTE_POLICY", observability.BaggageSpanAttributePolicy(False))
    monkeypatch.setattr(observability, "_should_capture_identity_attributes", lambda: False)
    provider, exporter = _provider()
    token = otel_context.attach(baggage.set_baggage("user.email", "private@example.com"))
    try:
        with provider.get_tracer(__name__).start_as_current_span("request", kind=SpanKind.SERVER):
            pass
    finally:
        otel_context.detach(token)
    attributes = exporter.get_finished_spans()[0].attributes
    assert attributes is not None
    assert "user.email" not in attributes
    provider.shutdown()


def test_processor_depends_on_sampler_for_descendants():
    """Filter roots independently while retaining sampled children and request roots."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider(sampler=ALWAYS_ON)
    provider.add_span_processor(RequestRootFilteringSpanProcessor(SimpleSpanProcessor(exporter)))
    tracer = provider.get_tracer(__name__)
    with tracer.start_as_current_span("background"):
        with tracer.start_as_current_span("background-child"):
            pass
    with tracer.start_as_current_span("request", kind=SpanKind.SERVER):
        pass
    assert [span.name for span in exporter.get_finished_spans()] == ["background-child", "request"]
    provider.shutdown()
