# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_observability.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for observability module.
"""

# Standard
import inspect
import logging
import os
from unittest.mock import MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway import observability
from mcpgateway.config import get_settings
from mcpgateway.observability import (
    BaggageSpanAttributePolicy,
    configure_baggage_span_attribute_policy,
    OpenTelemetryRequestMiddleware,
    create_span,
    extract_baggage_span_attribute_policy,
    inject_trace_context_headers,
    init_telemetry,
    otel_context_active,
    otel_tracing_enabled,
    trace_operation,
)
from mcpgateway.utils.trace_context import clear_trace_context, set_trace_context_from_teams, set_trace_session_id


class TestObservability:
    """Test cases for observability module."""

    def setup_method(self):
        """Reset environment before each test."""
        get_settings.cache_clear()
        configure_baggage_span_attribute_policy()
        # Clear relevant environment variables
        env_vars = [
            "OTEL_ENABLE_OBSERVABILITY",
            "OTEL_TRACES_EXPORTER",
            "OTEL_EXPORTER_OTLP_ENDPOINT",
            "OTEL_EXPORTER_OTLP_HEADERS",
            "OTEL_EXPORTER_OTLP_INSECURE",
            "OTEL_EXPORTER_OTLP_PROTOCOL",
            "OTEL_EMIT_LANGFUSE_ATTRIBUTES",
            "OTEL_CAPTURE_IDENTITY_ATTRIBUTES",
            "LANGFUSE_OTEL_ENDPOINT",
            "LANGFUSE_OTEL_AUTH",
            "LANGFUSE_PUBLIC_KEY",
            "LANGFUSE_SECRET_KEY",
            "OTEL_COPY_RESOURCE_ATTRS_TO_SPANS",
        ]
        for var in env_vars:
            os.environ.pop(var, None)

        # Reset module-level state
        observability._TRACER = None

    def _enable_observability(self):
        """Helper to enable observability for tests."""
        os.environ["OTEL_ENABLE_OBSERVABILITY"] = "true"
        get_settings.cache_clear()

    def test_observability_disabled_by_default(self):
        """Test that observability is disabled by default."""
        result = init_telemetry()
        assert result is None

    def test_observability_disabled_explicitly(self):
        """Test that observability can be explicitly disabled."""
        os.environ["OTEL_ENABLE_OBSERVABILITY"] = "false"
        get_settings.cache_clear()
        result = init_telemetry()
        assert result is None

    def test_observability_disabled_with_none_exporter(self):
        """Test that observability is disabled when exporter is 'none'."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "none"
        get_settings.cache_clear()
        result = init_telemetry()
        assert result is None

    def test_observability_disabled_without_otlp_endpoint(self):
        """Test that observability is disabled when OTLP endpoint is not configured."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "otlp"
        get_settings.cache_clear()
        result = init_telemetry()
        assert result is None

    @patch("mcpgateway.observability.OTEL_AVAILABLE", False)
    def test_observability_graceful_degradation_when_otel_not_installed(self):
        """Test graceful degradation when OpenTelemetry is not installed."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "otlp"
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://localhost:4317"
        get_settings.cache_clear()
        result = init_telemetry()
        assert result is None

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    @patch("mcpgateway.observability.TracerProvider")
    @patch("mcpgateway.observability.BatchSpanProcessor")
    def test_init_telemetry_otlp_grpc(self, mock_processor, mock_provider):
        """Test OTLP gRPC exporter initialization."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "otlp"
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://localhost:4317"
        os.environ["OTEL_EXPORTER_OTLP_PROTOCOL"] = "grpc"
        get_settings.cache_clear()

        # Mock the provider instance
        provider_instance = MagicMock()
        mock_provider.return_value = provider_instance

        # Mock OTLP_SPAN_EXPORTER
        mock_exporter = MagicMock()
        with patch("mcpgateway.observability.OTLP_SPAN_EXPORTER", mock_exporter):
            result = init_telemetry()

        # Verify exporter was created with correct endpoint
        mock_exporter.assert_called_once()
        call_kwargs = mock_exporter.call_args[1]
        assert call_kwargs["endpoint"] == "http://localhost:4317"
        assert result is not None

    def test_supports_exporter_kwarg_with_var_keyword(self):
        """Test _supports_exporter_kwarg returns True for exporters with **kwargs."""

        class ExporterWithKwargs:
            def __init__(self, endpoint=None, **kwargs):
                pass

        assert observability._supports_exporter_kwarg(ExporterWithKwargs, "insecure") is True

    def test_supports_exporter_kwarg_with_explicit_param(self):
        """Test _supports_exporter_kwarg returns True when kwarg is explicitly defined."""

        class ExporterWithInsecure:
            def __init__(self, endpoint=None, insecure=False):
                pass

        assert observability._supports_exporter_kwarg(ExporterWithInsecure, "insecure") is True

    def test_supports_exporter_kwarg_without_param(self):
        """Test _supports_exporter_kwarg returns False when kwarg is not supported."""

        class ExporterWithoutInsecure:
            def __init__(self, endpoint=None, headers=None):
                pass

        assert observability._supports_exporter_kwarg(ExporterWithoutInsecure, "insecure") is False

    def test_supports_exporter_kwarg_with_non_callable(self):
        """Test _supports_exporter_kwarg returns False for non-callable objects."""
        assert observability._supports_exporter_kwarg("not_a_callable", "insecure") is False
        assert observability._supports_exporter_kwarg(None, "insecure") is False
        assert observability._supports_exporter_kwarg(123, "insecure") is False

    def test_supports_exporter_kwarg_handles_typeerror(self):
        """Test _supports_exporter_kwarg handles TypeError from inspect.signature."""
        # Built-in types like int, str raise TypeError when inspect.signature is called
        assert observability._supports_exporter_kwarg(int, "insecure") is False
        assert observability._supports_exporter_kwarg(str, "insecure") is False
        assert observability._supports_exporter_kwarg(list, "insecure") is False

    def test_supports_exporter_kwarg_handles_valueerror(self):
        """Test _supports_exporter_kwarg handles ValueError from inspect.signature."""

        class ProblematicClass:
            """Class that causes ValueError when signature is inspected."""

            pass

        # Patch inspect.signature to raise ValueError
        with patch("inspect.signature", side_effect=ValueError("No signature available")):
            assert observability._supports_exporter_kwarg(ProblematicClass, "insecure") is False

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    @patch("mcpgateway.observability.TracerProvider")
    @patch("mcpgateway.observability.BatchSpanProcessor")
    def test_init_telemetry_otlp_grpc_with_insecure_true(self, mock_processor, mock_provider):
        """Test OTLP gRPC exporter passes insecure=True when configured."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "otlp"
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "collector.example.com:4317"
        os.environ["OTEL_EXPORTER_OTLP_PROTOCOL"] = "grpc"
        os.environ["OTEL_EXPORTER_OTLP_INSECURE"] = "true"
        get_settings.cache_clear()

        class FakeGrpcExporter:
            """Exporter with the insecure constructor kwarg used by gRPC OTLP."""

            calls = []

            def __init__(self, endpoint=None, headers=None, insecure=False, **kwargs):
                self.__class__.calls.append({"endpoint": endpoint, "headers": headers, "insecure": insecure, "kwargs": kwargs})

        provider_instance = MagicMock()
        mock_provider.return_value = provider_instance

        with patch("mcpgateway.observability.OTLP_SPAN_EXPORTER", FakeGrpcExporter):
            result = init_telemetry()

        assert result is not None
        assert FakeGrpcExporter.calls[-1]["endpoint"] == "collector.example.com:4317"
        assert FakeGrpcExporter.calls[-1]["insecure"] is True

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    @patch("mcpgateway.observability.TracerProvider")
    @patch("mcpgateway.observability.BatchSpanProcessor")
    def test_init_telemetry_otlp_grpc_without_insecure_support(self, mock_processor, mock_provider):
        """Test OTLP gRPC exporter omits insecure kwarg when not supported by exporter."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "otlp"
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "collector.example.com:4317"
        os.environ["OTEL_EXPORTER_OTLP_PROTOCOL"] = "grpc"
        os.environ["OTEL_EXPORTER_OTLP_INSECURE"] = "true"
        get_settings.cache_clear()

        class FakeGrpcExporter:
            """Exporter without insecure kwarg (older OTLP versions)."""

            calls = []

            def __init__(self, endpoint=None, headers=None):
                self.__class__.calls.append({"endpoint": endpoint, "headers": headers})

        provider_instance = MagicMock()
        mock_provider.return_value = provider_instance

        with patch("mcpgateway.observability.OTLP_SPAN_EXPORTER", FakeGrpcExporter):
            result = init_telemetry()

        assert result is not None
        assert FakeGrpcExporter.calls[-1]["endpoint"] == "collector.example.com:4317"
        assert "insecure" not in FakeGrpcExporter.calls[-1]

    def test_otlp_http_exporter_kwargs_preserve_real_exporter_certificate_defaults(self):
        """Test that HTTP OTLP exporter kwargs do not pass unsupported insecure TLS flags."""
        http_exporter_mod = pytest.importorskip("opentelemetry.exporter.otlp.proto.http.trace_exporter")
        exporter_cls = http_exporter_mod.OTLPSpanExporter

        kwargs = observability._otlp_exporter_kwargs(
            exporter_cls,
            endpoint="https://collector.example.com/v1/traces",
            headers=None,
            _protocol="http",
            insecure=True,
        )

        assert kwargs == {"endpoint": "https://collector.example.com/v1/traces", "headers": None}

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    @patch("mcpgateway.observability.TracerProvider")
    @patch("mcpgateway.observability.BatchSpanProcessor")
    def test_init_telemetry_otlp_http_keeps_certificate_file_unset_for_insecure_setting(self, mock_processor, mock_provider):
        """Test that HTTP OTLP exporters do not receive an ineffective certificate_file flag."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "otlp"
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "https://collector.example.com/v1/traces"
        os.environ["OTEL_EXPORTER_OTLP_PROTOCOL"] = "http"
        os.environ["OTEL_EXPORTER_OTLP_INSECURE"] = "true"

        class FakeHttpExporter:
            """Exporter with the certificate_file constructor kwarg used by HTTP OTLP."""

            calls = []

            def __init__(self, endpoint=None, headers=None, certificate_file="unset"):
                self.__class__.calls.append({"endpoint": endpoint, "headers": headers, "certificate_file": certificate_file})

        provider_instance = MagicMock()
        mock_provider.return_value = provider_instance

        with patch("mcpgateway.observability.OTLP_SPAN_EXPORTER", None):
            with patch("mcpgateway.observability.HTTP_EXPORTER", FakeHttpExporter):
                result = init_telemetry()

        assert result is not None
        assert FakeHttpExporter.calls[-1]["endpoint"] == "https://collector.example.com/v1/traces"
        assert FakeHttpExporter.calls[-1]["certificate_file"] == "unset"

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    @patch("mcpgateway.observability.ConsoleSpanExporter")
    @patch("mcpgateway.observability.TracerProvider")
    @patch("mcpgateway.observability.SimpleSpanProcessor")
    def test_init_telemetry_console_exporter(self, mock_processor, mock_provider, mock_exporter):
        """Test console exporter initialization."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "console"

        # Mock the provider instance
        provider_instance = MagicMock()
        mock_provider.return_value = provider_instance

        result = init_telemetry()

        # Verify console exporter was created
        mock_exporter.assert_called_once()
        # Only 1 span processor (SimpleSpanProcessor) since OTEL_COPY_RESOURCE_ATTRS_TO_SPANS is not set
        provider_instance.add_span_processor.assert_called_once()
        assert result is not None

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    @patch("mcpgateway.observability.ConsoleSpanExporter")
    @patch("mcpgateway.observability.TracerProvider")
    @patch("mcpgateway.observability.SimpleSpanProcessor")
    def test_init_telemetry_with_resource_attr_copy_enabled(self, mock_processor, mock_provider, mock_exporter):
        """Test that ResourceAttributeSpanProcessor is added when OTEL_COPY_RESOURCE_ATTRS_TO_SPANS=true."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "console"
        os.environ["OTEL_COPY_RESOURCE_ATTRS_TO_SPANS"] = "true"

        # Mock the provider instance
        provider_instance = MagicMock()
        mock_provider.return_value = provider_instance

        result = init_telemetry()

        # Verify 2 span processors: ResourceAttributeSpanProcessor + SimpleSpanProcessor
        assert provider_instance.add_span_processor.call_count == 2
        assert result is not None

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    @patch("mcpgateway.observability.ConsoleSpanExporter")
    @patch("mcpgateway.observability.TracerProvider")
    @patch("mcpgateway.observability.SimpleSpanProcessor")
    def test_init_telemetry_with_resource_attr_copy_disabled(self, mock_processor, mock_provider, mock_exporter):
        """Test that ResourceAttributeSpanProcessor is not added when OTEL_COPY_RESOURCE_ATTRS_TO_SPANS=false."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "console"
        os.environ["OTEL_COPY_RESOURCE_ATTRS_TO_SPANS"] = "false"

        # Mock the provider instance
        provider_instance = MagicMock()
        mock_provider.return_value = provider_instance

        result = init_telemetry()

        # Verify only 1 span processor (SimpleSpanProcessor)
        provider_instance.add_span_processor.assert_called_once()
        assert result is not None

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    def test_otel_tracing_enabled_when_tracer_initialized(self):
        """Test otel_tracing_enabled returns True when tracer is initialized."""
        observability._TRACER = MagicMock()
        assert otel_tracing_enabled() is True

    def test_otel_tracing_enabled_when_tracer_not_initialized(self):
        """Test otel_tracing_enabled returns False when tracer is not initialized."""
        observability._TRACER = None
        assert otel_tracing_enabled() is False

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    @patch("mcpgateway.observability.trace")
    def test_otel_context_active_with_valid_span(self, mock_trace):
        """Test otel_context_active returns True when there's a valid span."""
        mock_span = MagicMock()
        mock_span_context = MagicMock()
        mock_span_context.is_valid = True
        mock_span.get_span_context.return_value = mock_span_context
        mock_trace.get_current_span.return_value = mock_span

        assert otel_context_active() is True

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    @patch("mcpgateway.observability.trace")
    def test_otel_context_active_with_invalid_span(self, mock_trace):
        """Test otel_context_active returns False when span is invalid."""
        mock_span = MagicMock()
        mock_span_context = MagicMock()
        mock_span_context.is_valid = False
        mock_span.get_span_context.return_value = mock_span_context
        mock_trace.get_current_span.return_value = mock_span

        assert otel_context_active() is False

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    @patch("mcpgateway.observability.trace")
    def test_otel_context_active_with_no_span(self, mock_trace):
        """Test otel_context_active returns False when there's no current span."""
        mock_trace.get_current_span.return_value = None
        assert otel_context_active() is False

    @patch("mcpgateway.observability.OTEL_AVAILABLE", False)
    def test_otel_context_active_when_otel_not_available(self):
        """Test otel_context_active returns False when OpenTelemetry is not available."""
        assert otel_context_active() is False

    @patch("mcpgateway.observability.otel_context_active", return_value=True)
    @patch("mcpgateway.observability.otel_inject")
    def test_inject_trace_context_headers_with_active_context(self, mock_inject, mock_active):
        """Test inject_trace_context_headers injects context when active."""
        headers = {"existing": "header"}
        result = inject_trace_context_headers(headers)

        assert "existing" in result
        assert result["existing"] == "header"
        mock_inject.assert_called_once()

    @patch("mcpgateway.observability.otel_context_active", return_value=False)
    def test_inject_trace_context_headers_without_active_context(self, mock_active):
        """Test inject_trace_context_headers returns headers unchanged when no active context."""
        headers = {"existing": "header"}
        result = inject_trace_context_headers(headers)

        assert result == {"existing": "header"}

    def test_inject_trace_context_headers_with_none_headers(self):
        """Test inject_trace_context_headers handles None headers."""
        result = inject_trace_context_headers(None)
        assert isinstance(result, dict)

    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("/a2a/invoke", True),
            ("/a2a/invoke/", True),
            ("/a2a/example-agent/invoke", True),
            ("/a2a/example-agent/invoke/", True),
            ("/a2a/example-agent/jsonrpc", True),
            ("/a2a/example-agent/jsonrpc/", True),
            ("/a2a", False),
            ("/a2a/example-agent", False),
            ("/a2a/example-agent/card/invoke", False),
            ("/a2a/example-agent/invoke/extra", False),
            ("/unrelated/invoke", False),
        ],
    )
    def test_should_trace_only_a2a_invoke_paths(self, path, expected):
        """Trace only the two supported A2A invocation route shapes."""
        assert observability._should_trace_request_path(path) is expected

    @pytest.fixture
    def real_api_propagator(self, monkeypatch):
        """Wire the real opentelemetry-api propagator into the observability module globals.

        The API package is a transitive core dependency (via ``mcp``), so these
        tests exercise the genuine composite propagator without the SDK extra.
        """
        otel_trace_api = pytest.importorskip("opentelemetry.trace")
        # Third-Party
        from opentelemetry import baggage as otel_baggage_api
        from opentelemetry.propagate import inject as real_inject

        monkeypatch.setattr(observability, "OTEL_AVAILABLE", True)
        monkeypatch.setattr(observability, "trace", otel_trace_api)
        monkeypatch.setattr(observability, "otel_inject", real_inject)
        monkeypatch.setattr(observability, "otel_baggage", otel_baggage_api)
        return otel_trace_api

    @pytest.mark.parametrize(
        ("baggage_enabled", "propagate_external", "expect_baggage"),
        [
            (False, False, False),
            (True, False, False),
            (False, True, False),
            (True, True, True),
        ],
    )
    def test_inject_gates_context_baggage_on_propagation_policy(self, monkeypatch, real_api_propagator, baggage_enabled, propagate_external, expect_baggage):
        """Context baggage reaches outbound headers only when both baggage settings allow it."""
        # Third-Party
        from opentelemetry import baggage as otel_baggage_api
        from opentelemetry import context as otel_context_api
        from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags

        span_context = SpanContext(trace_id=0x0AF7651916CD43DD8448EB211C80319C, span_id=0x00F067AA0BA902B7, is_remote=False, trace_flags=TraceFlags(0x01))  # pragma: allowlist secret
        mock_settings = MagicMock()
        mock_settings.otel_baggage_enabled = baggage_enabled
        mock_settings.otel_baggage_propagate_to_external = propagate_external
        monkeypatch.setattr(observability, "get_settings", lambda: mock_settings)

        context_token = otel_context_api.attach(otel_baggage_api.set_baggage("review-marker", "internal"))
        try:
            with real_api_propagator.use_span(NonRecordingSpan(span_context)):
                result = inject_trace_context_headers({"Authorization": "Bearer keep"})
        finally:
            otel_context_api.detach(context_token)

        assert result["traceparent"] == "00-0af7651916cd43dd8448eb211c80319c-00f067aa0ba902b7-01"  # pragma: allowlist secret
        assert result["Authorization"] == "Bearer keep"
        assert ("baggage" in result) is expect_baggage
        if expect_baggage:
            assert "review-marker=internal" in result["baggage"]

    def test_inject_replaces_stale_propagation_headers_case_insensitively(self, monkeypatch, real_api_propagator):
        """Prepared mixed-case propagation headers are replaced by the active span context."""
        # Third-Party
        from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags

        span_context = SpanContext(trace_id=0x0AF7651916CD43DD8448EB211C80319C, span_id=0x00F067AA0BA902B7, is_remote=False, trace_flags=TraceFlags(0x01))  # pragma: allowlist secret
        mock_settings = MagicMock()
        mock_settings.otel_baggage_enabled = False
        mock_settings.otel_baggage_propagate_to_external = False
        monkeypatch.setattr(observability, "get_settings", lambda: mock_settings)

        prepared = {
            "Traceparent": "00-11111111111111111111111111111111-2222222222222222-01",  # pragma: allowlist secret
            "TraceState": "stale=yes",
            "Baggage": "stale=baggage",
            "Authorization": "Bearer keep",
        }
        with real_api_propagator.use_span(NonRecordingSpan(span_context)):
            result = inject_trace_context_headers(prepared)

        lowered = {}
        for key, value in result.items():
            assert key.lower() not in lowered, f"conflicting duplicate header casing: {key}"
            lowered[key.lower()] = value
        assert lowered["traceparent"] == "00-0af7651916cd43dd8448eb211c80319c-00f067aa0ba902b7-01"  # pragma: allowlist secret
        assert "tracestate" not in lowered
        assert "baggage" not in lowered
        assert result["Authorization"] == "Bearer keep"

    @pytest.mark.asyncio
    async def test_a2a_request_adopts_incoming_w3c_parent(self, monkeypatch):
        """The request and A2A spans remain children in the incoming W3C trace."""
        trace_sdk = pytest.importorskip("opentelemetry.sdk.trace")
        export_sdk = pytest.importorskip("opentelemetry.sdk.trace.export")
        memory_export_sdk = pytest.importorskip("opentelemetry.sdk.trace.export.in_memory_span_exporter")

        exporter = memory_export_sdk.InMemorySpanExporter()
        provider = trace_sdk.TracerProvider()
        provider.add_span_processor(export_sdk.SimpleSpanProcessor(exporter))
        monkeypatch.setattr(observability, "_TRACER", provider.get_tracer("a2a-trace-test"))

        async def app(_scope, _receive, send):
            with create_span("a2a.invoke"):
                await send({"type": "http.response.start", "status": 200, "headers": []})
                await send({"type": "http.response.body", "body": b""})

        middleware = OpenTelemetryRequestMiddleware(app)
        incoming_trace_id = "0af7651916cd43dd8448eb211c80319c"  # pragma: allowlist secret
        incoming_span_id = "b7ad6b7169203331"  # pragma: allowlist secret
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/a2a/example-agent/invoke",
            "headers": [(b"traceparent", f"00-{incoming_trace_id}-{incoming_span_id}-01".encode())],
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(_message):
            return None

        await middleware(scope, receive, send)

        spans = {span.name: span for span in exporter.get_finished_spans()}
        request_span = spans["POST /a2a/example-agent/invoke"]
        invoke_span = spans["a2a.invoke"]
        assert f"{request_span.context.trace_id:032x}" == incoming_trace_id
        assert f"{request_span.parent.span_id:016x}" == incoming_span_id
        assert invoke_span.context.trace_id == request_span.context.trace_id
        assert invoke_span.parent.span_id == request_span.context.span_id
        assert invoke_span.context.span_id != request_span.context.span_id

    @pytest.mark.asyncio
    @pytest.mark.parametrize("incoming_headers", [[], [(b"traceparent", b"malformed")]])
    async def test_a2a_request_handles_missing_or_malformed_context(self, monkeypatch, incoming_headers):
        """Missing or malformed W3C context safely creates a new root span."""
        trace_sdk = pytest.importorskip("opentelemetry.sdk.trace")
        export_sdk = pytest.importorskip("opentelemetry.sdk.trace.export")
        memory_export_sdk = pytest.importorskip("opentelemetry.sdk.trace.export.in_memory_span_exporter")

        exporter = memory_export_sdk.InMemorySpanExporter()
        provider = trace_sdk.TracerProvider()
        provider.add_span_processor(export_sdk.SimpleSpanProcessor(exporter))
        monkeypatch.setattr(observability, "_TRACER", provider.get_tracer("a2a-safe-context-test"))

        async def app(_scope, _receive, send):
            await send({"type": "http.response.start", "status": 204, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        middleware = OpenTelemetryRequestMiddleware(app)
        scope = {"type": "http", "method": "POST", "path": "/a2a/invoke", "headers": incoming_headers}

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(_message):
            return None

        await middleware(scope, receive, send)

        (request_span,) = exporter.get_finished_spans()
        assert request_span.context.is_valid
        assert request_span.parent is None

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    @patch("mcpgateway.observability.ConsoleSpanExporter")
    @patch("mcpgateway.observability.TracerProvider")
    @patch("mcpgateway.observability.SimpleSpanProcessor")
    def test_init_telemetry_instruments_httpx_clients(self, mock_processor, mock_provider, mock_exporter):
        """httpx/httpx2 client instrumentors are invoked when httpx instrumentation is enabled."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "console"
        os.environ["OTEL_HTTPX_INSTRUMENTATION_ENABLED"] = "true"
        get_settings.cache_clear()

        mock_provider.return_value = MagicMock()
        httpx_instrumentor = MagicMock()
        httpx2_instrumentor = MagicMock()

        with patch("mcpgateway.observability.HTTPX_INSTRUMENTOR", httpx_instrumentor), patch("mcpgateway.observability.HTTPX2_INSTRUMENTOR", httpx2_instrumentor):
            result = init_telemetry()

        assert result is not None
        httpx_instrumentor.return_value.instrument.assert_called_once_with()
        httpx2_instrumentor.return_value.instrument.assert_called_once_with()

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    @patch("mcpgateway.observability.ConsoleSpanExporter")
    @patch("mcpgateway.observability.TracerProvider")
    @patch("mcpgateway.observability.SimpleSpanProcessor")
    def test_init_telemetry_httpx_instrumentation_failure_is_nonfatal(self, mock_processor, mock_provider, mock_exporter, caplog):
        """A failing httpx instrumentor logs a warning and telemetry still initializes."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "console"
        os.environ["OTEL_HTTPX_INSTRUMENTATION_ENABLED"] = "true"
        get_settings.cache_clear()

        mock_provider.return_value = MagicMock()
        httpx_instrumentor = MagicMock()
        httpx_instrumentor.return_value.instrument.side_effect = RuntimeError("boom")

        with patch("mcpgateway.observability.HTTPX_INSTRUMENTOR", httpx_instrumentor), patch("mcpgateway.observability.HTTPX2_INSTRUMENTOR", None), caplog.at_level(logging.WARNING):
            result = init_telemetry()

        assert result is not None
        assert any("Failed to instrument httpx clients" in record.message for record in caplog.records)

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    @patch("mcpgateway.observability.ConsoleSpanExporter")
    @patch("mcpgateway.observability.TracerProvider")
    @patch("mcpgateway.observability.SimpleSpanProcessor")
    def test_init_telemetry_redis_instrumentation_success(self, mock_processor, mock_provider, mock_exporter):
        """Redis instrumentor is invoked when otel_redis_instrumentation_enabled is True."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "console"
        os.environ["OTEL_REDIS_INSTRUMENTATION_ENABLED"] = "true"
        get_settings.cache_clear()

        mock_provider.return_value = MagicMock()
        redis_instrumentor = MagicMock()

        with patch("mcpgateway.observability.REDIS_INSTRUMENTOR", redis_instrumentor):
            result = init_telemetry()

        assert result is not None
        redis_instrumentor.return_value.instrument.assert_called_once_with()

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    @patch("mcpgateway.observability.ConsoleSpanExporter")
    @patch("mcpgateway.observability.TracerProvider")
    @patch("mcpgateway.observability.SimpleSpanProcessor")
    def test_init_telemetry_redis_instrumentation_failure_is_nonfatal(self, mock_processor, mock_provider, mock_exporter, caplog):
        """A failing redis instrumentor logs a warning and telemetry still initializes."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "console"
        os.environ["OTEL_REDIS_INSTRUMENTATION_ENABLED"] = "true"
        get_settings.cache_clear()

        mock_provider.return_value = MagicMock()
        redis_instrumentor = MagicMock()
        redis_instrumentor.return_value.instrument.side_effect = RuntimeError("redis instrument boom")

        with patch("mcpgateway.observability.REDIS_INSTRUMENTOR", redis_instrumentor), caplog.at_level(logging.WARNING):
            result = init_telemetry()

        assert result is not None
        assert any("Failed to instrument redis clients" in record.message for record in caplog.records)

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    @patch("mcpgateway.observability.ConsoleSpanExporter")
    @patch("mcpgateway.observability.TracerProvider")
    @patch("mcpgateway.observability.SimpleSpanProcessor")
    def test_init_telemetry_redis_instrumentation_package_unavailable(self, mock_processor, mock_provider, mock_exporter, caplog):
        """When REDIS_INSTRUMENTOR is None (package absent), a warning is logged and init succeeds."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "console"
        os.environ["OTEL_REDIS_INSTRUMENTATION_ENABLED"] = "true"
        get_settings.cache_clear()

        mock_provider.return_value = MagicMock()

        with patch("mcpgateway.observability.REDIS_INSTRUMENTOR", None), caplog.at_level(logging.WARNING):
            result = init_telemetry()

        assert result is not None
        assert any("redis instrumentation enabled but package unavailable" in record.message for record in caplog.records)


class TestRequestMiddlewareTraceEnvelope:
    """Tests for trace-envelope publication in OpenTelemetryRequestMiddleware."""

    @staticmethod
    def _make_scope(headers=None):
        return {
            "type": "http",
            "path": "/mcp",
            "method": "POST",
            "headers": list(headers or []),
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 12345),
            "http_version": "1.1",
            "query_string": b"",
        }

    @staticmethod
    def _make_app(captured):
        async def app(scope, _receive, send):
            captured["headers"] = list(scope.get("headers", []))
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(_message):
            return None

        return app, receive, send

    @staticmethod
    def _fake_inject(carrier):
        carrier["traceparent"] = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        carrier["tracestate"] = "congo=t61rcWkgMzE"

    @pytest.mark.asyncio
    async def test_middleware_publishes_trace_envelope_when_no_remote_parent(self):
        """Without a valid inbound traceparent, the new root span context is added to the ASGI headers."""
        captured = {}
        app, receive, send = self._make_app(captured)
        scope = self._make_scope([(b"content-type", b"application/json")])

        mock_trace = MagicMock()
        mock_trace.get_current_span.return_value.get_span_context.return_value = MagicMock(is_valid=False, is_remote=False)

        with (
            patch("mcpgateway.observability._TRACER", MagicMock()),
            patch("mcpgateway.observability.OTEL_AVAILABLE", True),
            patch("mcpgateway.observability.trace", mock_trace),
            patch("mcpgateway.observability.otel_extract", return_value=MagicMock()),
            patch("mcpgateway.observability.otel_inject", side_effect=self._fake_inject),
        ):
            middleware = OpenTelemetryRequestMiddleware(app)
            await middleware(scope, receive, send)

        headers = captured["headers"]
        assert (b"traceparent", b"00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01") in headers
        assert (b"tracestate", b"congo=t61rcWkgMzE") in headers

    @pytest.mark.asyncio
    async def test_middleware_publishes_envelope_when_span_context_inspection_fails(self):
        """If remote-parent detection raises, the request is treated as root and the envelope is published."""
        captured = {}
        app, receive, send = self._make_app(captured)
        scope = self._make_scope()

        mock_trace = MagicMock()
        mock_trace.get_current_span.side_effect = RuntimeError("boom")

        with (
            patch("mcpgateway.observability._TRACER", MagicMock()),
            patch("mcpgateway.observability.OTEL_AVAILABLE", True),
            patch("mcpgateway.observability.trace", mock_trace),
            patch("mcpgateway.observability.otel_extract", return_value=MagicMock()),
            patch("mcpgateway.observability.otel_inject", side_effect=self._fake_inject),
        ):
            middleware = OpenTelemetryRequestMiddleware(app)
            await middleware(scope, receive, send)

        assert (b"traceparent", b"00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01") in captured["headers"]

    @pytest.mark.asyncio
    async def test_middleware_does_not_publish_envelope_with_valid_remote_parent(self):
        """A valid remote traceparent leaves the inbound headers untouched."""
        captured = {}
        app, receive, send = self._make_app(captured)
        original_headers = [(b"traceparent", b"00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01")]
        scope = self._make_scope(original_headers)

        mock_trace = MagicMock()
        mock_trace.get_current_span.return_value.get_span_context.return_value = MagicMock(is_valid=True, is_remote=True)

        with (
            patch("mcpgateway.observability._TRACER", MagicMock()),
            patch("mcpgateway.observability.OTEL_AVAILABLE", True),
            patch("mcpgateway.observability.trace", mock_trace),
            patch("mcpgateway.observability.otel_extract", return_value=MagicMock()),
            patch("mcpgateway.observability.otel_inject") as mock_inject,
        ):
            middleware = OpenTelemetryRequestMiddleware(app)
            await middleware(scope, receive, send)

        mock_inject.assert_not_called()
        assert captured["headers"] == original_headers

    @pytest.mark.asyncio
    async def test_middleware_envelope_publication_failure_is_nonfatal(self):
        """If publishing the envelope raises, the request still proceeds with headers untouched."""
        captured = {}
        app, receive, send = self._make_app(captured)
        original_headers = [(b"content-type", b"application/json")]
        scope = self._make_scope(original_headers)

        mock_trace = MagicMock()
        mock_trace.get_current_span.return_value.get_span_context.return_value = MagicMock(is_valid=False, is_remote=False)

        with (
            patch("mcpgateway.observability._TRACER", MagicMock()),
            patch("mcpgateway.observability.OTEL_AVAILABLE", True),
            patch("mcpgateway.observability.trace", mock_trace),
            patch("mcpgateway.observability.otel_extract", return_value=MagicMock()),
            patch("mcpgateway.observability.otel_inject", side_effect=RuntimeError("boom")),
        ):
            middleware = OpenTelemetryRequestMiddleware(app)
            await middleware(scope, receive, send)

        assert captured["headers"] == original_headers
