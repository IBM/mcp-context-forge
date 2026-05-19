# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_observability.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for observability module.
"""

# Standard
import importlib
import inspect
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
            protocol="http",
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
