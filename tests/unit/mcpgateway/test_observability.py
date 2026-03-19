# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_observability.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for observability module.
"""

# Standard
import os
from unittest.mock import MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.observability import create_span, init_telemetry, trace_operation


class TestObservability:
    """Test cases for observability module."""

    def setup_method(self):
        """Reset environment before each test."""
        # Clear relevant environment variables
        env_vars = [
            "OTEL_ENABLE_OBSERVABILITY",
            "OTEL_TRACES_EXPORTER",
            "OTEL_EXPORTER_OTLP_ENDPOINT",
            "OTEL_SERVICE_NAME",
            "OTEL_RESOURCE_ATTRIBUTES",
            "OTEL_COPY_RESOURCE_ATTRS_TO_SPANS",
        ]
        for var in env_vars:
            os.environ.pop(var, None)

    @staticmethod
    def _enable_observability() -> None:
        """Enable OpenTelemetry for tests that exercise initialization paths."""
        os.environ["OTEL_ENABLE_OBSERVABILITY"] = "true"

    def teardown_method(self):
        """Clean up after each test."""
        # Reset global tracer
        # First-Party
        import mcpgateway.observability

        # pylint: disable=protected-access
        mcpgateway.observability._TRACER = None

    def test_init_telemetry_disabled_via_env(self):
        """Test that telemetry can be disabled via environment variable."""
        os.environ["OTEL_ENABLE_OBSERVABILITY"] = "false"

        result = init_telemetry()
        assert result is None

    @patch("mcpgateway.observability.OTEL_AVAILABLE", False)
    def test_init_telemetry_otel_not_installed(self):
        """Test graceful degradation when OpenTelemetry is not installed."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "otlp"
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://localhost:4317"

        with patch("mcpgateway.observability.logger") as mock_logger:
            result = init_telemetry()

            # Should log warning and return None
            mock_logger.warning.assert_called()
            mock_logger.info.assert_called()
            assert result is None

    def test_init_telemetry_none_exporter(self):
        """Test that 'none' exporter disables telemetry."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "none"

        result = init_telemetry()
        assert result is None

    def test_init_telemetry_no_endpoint(self):
        """Test that missing OTLP endpoint skips initialization."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "otlp"
        # Don't set OTEL_EXPORTER_OTLP_ENDPOINT

        result = init_telemetry()
        assert result is None

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    @patch("mcpgateway.observability.OTLP_SPAN_EXPORTER")
    @patch("mcpgateway.observability.TracerProvider")
    @patch("mcpgateway.observability.BatchSpanProcessor")
    def test_init_telemetry_otlp_success(self, mock_processor, mock_provider, mock_exporter):
        """Test successful OTLP initialization."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "otlp"
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://localhost:4317"
        os.environ["OTEL_SERVICE_NAME"] = "test-service"

        # Mock the provider instance
        provider_instance = MagicMock()
        mock_provider.return_value = provider_instance

        result = init_telemetry()

        # Verify provider was created and configured
        mock_provider.assert_called_once()
        # Only 1 span processor (BatchSpanProcessor) since OTEL_COPY_RESOURCE_ATTRS_TO_SPANS is not set
        provider_instance.add_span_processor.assert_called_once()
        assert result is not None

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
    def test_init_telemetry_custom_resource_attributes(self):
        """Test parsing of custom resource attributes."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "console"
        os.environ["OTEL_RESOURCE_ATTRIBUTES"] = "env=prod,team=platform,version=1.0"

        with patch("mcpgateway.observability.Resource.create") as mock_resource:
            with patch("mcpgateway.observability.TracerProvider"):
                with patch("mcpgateway.observability.ConsoleSpanExporter"):
                    init_telemetry()

                    # Verify resource attributes were parsed correctly
                    call_args = mock_resource.call_args[0][0]
                    assert call_args["env"] == "prod"
                    assert call_args["team"] == "platform"
                    assert call_args["version"] == "1.0"

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    def test_init_telemetry_otlp_headers_parsing(self):
        """Test parsing of OTLP headers."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "otlp"
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://localhost:4317"
        os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = "api-key=secret,x-auth=token123"

        with patch("mcpgateway.observability.OTLP_SPAN_EXPORTER") as mock_exporter:
            with patch("mcpgateway.observability.TracerProvider"):
                with patch("mcpgateway.observability.BatchSpanProcessor"):
                    init_telemetry()

                    # Verify headers were parsed correctly
                    call_kwargs = mock_exporter.call_args[1]
                    assert call_kwargs["headers"]["api-key"] == "secret"
                    assert call_kwargs["headers"]["x-auth"] == "token123"

    def test_create_span_no_tracer(self):
        """Test create_span when tracer is not initialized."""
        # First-Party
        import mcpgateway.observability

        # pylint: disable=protected-access
        mcpgateway.observability._TRACER = None

        # Should return a no-op context manager
        with create_span("test.operation") as span:
            assert span is None

    @patch("mcpgateway.observability._TRACER")
    def test_create_span_with_attributes(self, mock_tracer):
        """Test create_span with attributes."""
        # Setup mock
        mock_span = MagicMock()
        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_span)
        mock_context.__exit__ = MagicMock(return_value=None)
        mock_tracer.start_as_current_span.return_value = mock_context

        # Test with attributes
        attrs = {"key1": "value1", "key2": 42}
        with create_span("test.operation", attrs) as span:
            assert span is not None
            # Verify attributes were set
            span.set_attribute.assert_any_call("key1", "value1")
            span.set_attribute.assert_any_call("key2", 42)

    @pytest.mark.skip(reason="Mock doesn't properly simulate SpanWithAttributes wrapper behavior")
    def test_create_span_with_exception(self):
        """Test create_span exception handling."""
        # Note: This test is skipped because mocking the complex interaction
        # between the SpanWithAttributes wrapper and the underlying span
        # doesn't accurately represent the real behavior.
        # Manual testing confirms the exception handling works correctly.
        pass

    @pytest.mark.asyncio
    async def test_trace_operation_decorator_no_tracer(self):
        """Test trace_operation decorator when tracer is not initialized."""
        # First-Party
        import mcpgateway.observability

        # pylint: disable=protected-access
        mcpgateway.observability._TRACER = None

        @trace_operation("test.operation")
        async def test_func():
            return "result"

        result = await test_func()
        assert result == "result"

    @pytest.mark.asyncio
    @patch("mcpgateway.observability._TRACER")
    async def test_trace_operation_decorator_with_tracer(self, mock_tracer):
        """Test trace_operation decorator with tracer."""
        # Setup mock
        mock_span = MagicMock()
        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_span)
        mock_context.__exit__ = MagicMock(return_value=None)
        mock_tracer.start_as_current_span.return_value = mock_context

        @trace_operation("test.operation", {"attr1": "value1"})
        async def test_func():
            return "result"

        result = await test_func()

        assert result == "result"
        mock_tracer.start_as_current_span.assert_called_once_with("test.operation")
        mock_span.set_attribute.assert_any_call("attr1", "value1")
        mock_span.set_attribute.assert_any_call("status", "success")

    @pytest.mark.asyncio
    @patch("mcpgateway.observability._TRACER")
    async def test_trace_operation_decorator_with_exception(self, mock_tracer):
        """Test trace_operation decorator exception handling."""
        # Setup mock
        mock_span = MagicMock()
        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_span)
        mock_context.__exit__ = MagicMock(return_value=None)
        mock_tracer.start_as_current_span.return_value = mock_context

        @trace_operation("test.operation")
        async def test_func():
            raise ValueError("Test error")

        with pytest.raises(ValueError):
            await test_func()

        mock_span.set_attribute.assert_any_call("status", "error")
        mock_span.set_attribute.assert_any_call("error.message", "Test error")
        mock_span.record_exception.assert_called_once()

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    @patch("mcpgateway.observability.JAEGER_EXPORTER", None)
    def test_init_telemetry_jaeger_import_error(self):
        """Test Jaeger exporter when not installed."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "jaeger"

        # Mock ImportError for Jaeger
        with patch("mcpgateway.observability.logger") as mock_logger:
            result = init_telemetry()

            # Should log error and return None
            mock_logger.error.assert_called()
            assert result is None

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    @patch("mcpgateway.observability.ZIPKIN_EXPORTER", None)
    def test_init_telemetry_zipkin_import_error(self):
        """Test Zipkin exporter when not installed."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "zipkin"

        # Mock ImportError for Zipkin
        with patch("mcpgateway.observability.logger") as mock_logger:
            result = init_telemetry()

            # Should log error and return None
            mock_logger.error.assert_called()
            assert result is None

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    def test_init_telemetry_unknown_exporter(self):
        """Test unknown exporter type falls back to console."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "unknown_exporter"

        with patch("mcpgateway.observability.ConsoleSpanExporter") as mock_console:
            with patch("mcpgateway.observability.TracerProvider"):
                with patch("mcpgateway.observability.logger") as mock_logger:
                    init_telemetry()

                    # Should warn and use console exporter
                    mock_logger.warning.assert_called()
                    mock_console.assert_called()

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    def test_init_telemetry_exception_handling(self):
        """Test exception handling during initialization."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "otlp"
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://localhost:4317"

        with patch("mcpgateway.observability.TracerProvider", side_effect=Exception("Test error")):
            with patch("mcpgateway.observability.logger") as mock_logger:
                result = init_telemetry()

                # Should log error and return None
                mock_logger.error.assert_called()
                assert result is None

    def test_create_span_none_attributes_filtered(self):
        """Test that None values in attributes are filtered out."""
        # First-Party
        import mcpgateway.observability

        # Setup mock tracer
        mock_span = MagicMock()
        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_span)
        mock_context.__exit__ = MagicMock(return_value=None)

        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value = mock_context
        # pylint: disable=protected-access
        mcpgateway.observability._TRACER = mock_tracer

        # Test with None values
        attrs = {"key1": "value1", "key2": None, "key3": 42}
        with create_span("test.operation", attrs) as span:
            # Verify only non-None attributes were set
            span.set_attribute.assert_any_call("key1", "value1")
            span.set_attribute.assert_any_call("key3", 42)
            # key2 should not be set
            for call in span.set_attribute.call_args_list:
                assert call[0][0] != "key2" or call[0][0] == "error"

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    def test_init_telemetry_otlp_http_fallback(self):
        """Test OTLP HTTP exporter fallback when gRPC exporter is unavailable."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "otlp"
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://localhost:4317"
        os.environ["OTEL_EXPORTER_OTLP_PROTOCOL"] = "http"

        provider_instance = MagicMock()
        with patch("mcpgateway.observability.OTLP_SPAN_EXPORTER", None):
            with patch("mcpgateway.observability.HTTP_EXPORTER") as mock_http_exporter:
                with patch("mcpgateway.observability.TracerProvider", return_value=provider_instance):
                    with patch("mcpgateway.observability.BatchSpanProcessor"):
                        with patch("mcpgateway.observability.trace") as mock_trace:
                            mock_trace.get_tracer.return_value = MagicMock()
                            init_telemetry()

        call_kwargs = mock_http_exporter.call_args[1]
        assert call_kwargs["endpoint"] == "http://localhost:4318/v1/traces"

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    def test_init_telemetry_otlp_no_exporter(self):
        """Test OTLP init returns None when no exporter is available."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "otlp"
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://localhost:4317"

        with patch("mcpgateway.observability.OTLP_SPAN_EXPORTER", None):
            with patch("mcpgateway.observability.HTTP_EXPORTER", None):
                with patch("mcpgateway.observability.logger") as mock_logger:
                    result = init_telemetry()
                    mock_logger.error.assert_called()
                    assert result is None

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    def test_init_telemetry_jaeger_success(self):
        """Test Jaeger exporter initialization path."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "jaeger"
        os.environ["OTEL_EXPORTER_JAEGER_ENDPOINT"] = "http://jaeger:14268/api/traces"
        os.environ["OTEL_EXPORTER_JAEGER_USER"] = "jaeger-user"
        os.environ["OTEL_EXPORTER_JAEGER_PASSWORD"] = "jaeger-pass"

        provider_instance = MagicMock()
        with patch("mcpgateway.observability.JAEGER_EXPORTER") as mock_exporter:
            with patch("mcpgateway.observability.TracerProvider", return_value=provider_instance):
                with patch("mcpgateway.observability.BatchSpanProcessor"):
                    init_telemetry()

        mock_exporter.assert_called_once_with(
            collector_endpoint="http://jaeger:14268/api/traces",
            username="jaeger-user",
            password="jaeger-pass",
        )

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    def test_init_telemetry_zipkin_success(self):
        """Test Zipkin exporter initialization path."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "zipkin"
        os.environ["OTEL_EXPORTER_ZIPKIN_ENDPOINT"] = "http://zipkin:9411/api/v2/spans"

        provider_instance = MagicMock()
        with patch("mcpgateway.observability.ZIPKIN_EXPORTER") as mock_exporter:
            with patch("mcpgateway.observability.TracerProvider", return_value=provider_instance):
                with patch("mcpgateway.observability.BatchSpanProcessor"):
                    init_telemetry()

        mock_exporter.assert_called_once_with(endpoint="http://zipkin:9411/api/v2/spans")

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    def test_init_telemetry_resource_none_uses_default_provider(self):
        """Test default TracerProvider path when Resource.create is unavailable."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "console"

        provider_instance = MagicMock()
        with patch("mcpgateway.observability.Resource", object()):
            with patch("mcpgateway.observability.TracerProvider", return_value=provider_instance) as mock_provider:
                with patch("mcpgateway.observability.ConsoleSpanExporter"):
                    with patch("mcpgateway.observability.SimpleSpanProcessor"):
                        init_telemetry()

        mock_provider.assert_called_once_with()

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    def test_init_telemetry_sets_tracer_provider_and_noop_tracer(self):
        """Test set_tracer_provider call and NoopTracer when get_tracer is missing."""
        # Standard
        from types import SimpleNamespace

        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "console"

        trace_stub = SimpleNamespace(set_tracer_provider=MagicMock())
        provider_instance = MagicMock()
        with patch("mcpgateway.observability.trace", trace_stub):
            with patch("mcpgateway.observability.TracerProvider", return_value=provider_instance):
                with patch("mcpgateway.observability.ConsoleSpanExporter"):
                    with patch("mcpgateway.observability.SimpleSpanProcessor"):
                        tracer = init_telemetry()

        trace_stub.set_tracer_provider.assert_called_once_with(provider_instance)
        with tracer.start_as_current_span("noop-span") as span:
            assert span is None

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    @patch("mcpgateway.observability.ConsoleSpanExporter")
    @patch("mcpgateway.observability.TracerProvider")
    @patch("mcpgateway.observability.SimpleSpanProcessor")
    def test_resource_attribute_span_processor_copies_attrs(self, mock_processor, mock_provider, mock_exporter):
        """Test ResourceAttributeSpanProcessor copies configured attributes."""
        # Standard
        from types import SimpleNamespace

        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "console"
        os.environ["OTEL_COPY_RESOURCE_ATTRS_TO_SPANS"] = "true"

        provider_instance = MagicMock()
        mock_provider.return_value = provider_instance
        init_telemetry()

        processor = provider_instance.add_span_processor.call_args_list[0][0][0]
        span = MagicMock()
        span.resource = SimpleNamespace(attributes={"arize.project.name": "proj", "model_id": "model-1"})
        processor.on_start(span)

        span.set_attribute.assert_any_call("arize.project.name", "proj")
        span.set_attribute.assert_any_call("model_id", "model-1")

        span_no_resource = MagicMock()
        span_no_resource.resource = None
        processor.on_start(span_no_resource)

    @patch("mcpgateway.observability.get_correlation_id", return_value="corr-123")
    def test_create_span_injects_correlation_id(self, mock_get_correlation_id):
        """Test correlation_id injection when missing from attributes."""
        # First-Party
        import mcpgateway.observability

        mock_span = MagicMock()
        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_span)
        mock_context.__exit__ = MagicMock(return_value=None)

        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value = mock_context
        # pylint: disable=protected-access
        mcpgateway.observability._TRACER = mock_tracer

        with create_span("test.operation") as span:
            assert span is not None

        span.set_attribute.assert_any_call("correlation_id", "corr-123")
        span.set_attribute.assert_any_call("request_id", "corr-123")

    def test_create_span_correlation_id_error_logs(self):
        """Test correlation ID failures are logged and ignored."""
        # First-Party
        import mcpgateway.observability

        mock_span = MagicMock()
        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_span)
        mock_context.__exit__ = MagicMock(return_value=None)

        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value = mock_context
        # pylint: disable=protected-access
        mcpgateway.observability._TRACER = mock_tracer

        with patch("mcpgateway.observability.get_correlation_id", side_effect=RuntimeError("boom")):
            with patch("mcpgateway.observability.logger") as mock_logger:
                with create_span("test.operation", {"key": "value"}):
                    pass

        mock_logger.debug.assert_called()

    def test_create_span_returns_span_context_when_no_attributes(self):
        """Test create_span returns the raw span context when no attributes exist."""
        # First-Party
        import mcpgateway.observability

        mock_context = MagicMock()
        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value = mock_context
        # pylint: disable=protected-access
        mcpgateway.observability._TRACER = mock_tracer

        with patch("mcpgateway.observability.get_correlation_id", return_value=None):
            context = create_span("test.operation")

        assert context is mock_context

    def test_span_with_attributes_records_exception_and_status(self):
        """Test SpanWithAttributes records errors and sets status."""
        # First-Party
        import mcpgateway.observability

        class DummyStatusCode:
            OK = "ok"
            ERROR = "error"

        class DummyStatus:
            def __init__(self, code, description=None):
                self.code = code
                self.description = description

        mock_span = MagicMock()
        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_span)
        mock_context.__exit__ = MagicMock(return_value=None)

        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value = mock_context
        # pylint: disable=protected-access
        mcpgateway.observability._TRACER = mock_tracer

        with patch("mcpgateway.observability.OTEL_AVAILABLE", True):
            with patch("mcpgateway.observability.Status", DummyStatus):
                with patch("mcpgateway.observability.StatusCode", DummyStatusCode):
                    with pytest.raises(ValueError):
                        with create_span("test.operation", {"key": "value"}):
                            raise ValueError("boom")

        mock_span.record_exception.assert_called()
        mock_span.set_attribute.assert_any_call("error", True)
        mock_span.set_attribute.assert_any_call("error.type", "ValueError")
        mock_span.set_attribute.assert_any_call("error.message", "boom")
        status_arg = mock_span.set_status.call_args[0][0]
        assert isinstance(status_arg, DummyStatus)
        assert status_arg.code == DummyStatusCode.ERROR

    def test_span_with_attributes_sets_ok_status(self):
        """Test SpanWithAttributes sets OK status on success."""
        # First-Party
        import mcpgateway.observability

        class DummyStatusCode:
            OK = "ok"

        class DummyStatus:
            def __init__(self, code, description=None):
                self.code = code
                self.description = description

        mock_span = MagicMock()
        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_span)
        mock_context.__exit__ = MagicMock(return_value=None)

        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value = mock_context
        # pylint: disable=protected-access
        mcpgateway.observability._TRACER = mock_tracer

        with patch("mcpgateway.observability.OTEL_AVAILABLE", True):
            with patch("mcpgateway.observability.Status", DummyStatus):
                with patch("mcpgateway.observability.StatusCode", DummyStatusCode):
                    with create_span("test.operation", {"key": "value"}):
                        pass

        status_arg = mock_span.set_status.call_args[0][0]
        assert isinstance(status_arg, DummyStatus)
        assert status_arg.code == DummyStatusCode.OK
