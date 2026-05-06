# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_observability.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for observability module.
"""

# Standard
import importlib
import os
from unittest.mock import MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway import observability
from mcpgateway.config import get_settings
from mcpgateway.observability import OpenTelemetryRequestMiddleware, create_span, inject_trace_context_headers, init_telemetry, otel_context_active, otel_tracing_enabled, trace_operation
from mcpgateway.utils.trace_context import clear_trace_context, set_trace_context_from_teams, set_trace_session_id


class TestObservability:
    """Test cases for observability module."""

    def setup_method(self):
        """Reset environment before each test."""
        get_settings.cache_clear()
        # Clear relevant environment variables
        env_vars = [
            "OTEL_ENABLE_OBSERVABILITY",
            "OTEL_TRACES_EXPORTER",
            "OTEL_EXPORTER_OTLP_ENDPOINT",
            "OTEL_EXPORTER_OTLP_HEADERS",
            "OTEL_EMIT_LANGFUSE_ATTRIBUTES",
            "OTEL_CAPTURE_IDENTITY_ATTRIBUTES",
            "OTEL_CAPTURE_INPUT_SPANS",
            "OTEL_CAPTURE_OUTPUT_SPANS",
            "OTEL_SERVICE_NAME",
            "OTEL_RESOURCE_ATTRIBUTES",
            "OTEL_COPY_RESOURCE_ATTRS_TO_SPANS",
            "OTEL_EXPORTER_JAEGER_USER",
            "OTEL_EXPORTER_JAEGER_PASSWORD",
            "DEPLOYMENT_ENV",
            "ENVIRONMENT",
            "LANGFUSE_OTEL_ENDPOINT",
            "LANGFUSE_PUBLIC_KEY",
            "LANGFUSE_SECRET_KEY",
            "LANGFUSE_OTEL_AUTH",
        ]
        for var in env_vars:
            os.environ.pop(var, None)
        clear_trace_context()

    @staticmethod
    def _enable_observability() -> None:
        """Enable OpenTelemetry for tests that exercise initialization paths."""
        os.environ["OTEL_ENABLE_OBSERVABILITY"] = "true"

    @staticmethod
    def _enable_langfuse_span_attrs() -> None:
        """Enable Langfuse-specific and identity span attributes for tests."""
        os.environ["OTEL_EMIT_LANGFUSE_ATTRIBUTES"] = "true"
        os.environ["OTEL_CAPTURE_IDENTITY_ATTRIBUTES"] = "true"

    def teardown_method(self):
        """Clean up after each test."""
        get_settings.cache_clear()
        # Reset global tracer
        # First-Party
        import mcpgateway.observability

        # pylint: disable=protected-access
        mcpgateway.observability._TRACER = None
        clear_trace_context()

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

        with patch("mcpgateway.observability.HTTP_EXPORTER") as mock_exporter:
            with patch("mcpgateway.observability.TracerProvider"):
                with patch("mcpgateway.observability.BatchSpanProcessor"):
                    init_telemetry()

                    # Verify headers were parsed correctly
                    call_kwargs = mock_exporter.call_args[1]
                    assert call_kwargs["headers"]["api-key"] == "secret"
                    assert call_kwargs["headers"]["x-auth"] == "token123"

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    def test_init_telemetry_langfuse_endpoint_without_auth_raises(self):
        """Langfuse OTLP must fail closed when no auth material is configured."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "otlp"
        os.environ["LANGFUSE_OTEL_ENDPOINT"] = "https://cloud.langfuse.com/api/public/otel/v1/traces"

        with pytest.raises(RuntimeError, match="valid Basic Authorization"):
            init_telemetry()

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    def test_init_telemetry_langfuse_keys_derive_auth_header(self):
        """Langfuse project keys should derive the OTLP basic auth header automatically."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "otlp"
        os.environ["LANGFUSE_OTEL_ENDPOINT"] = "https://cloud.langfuse.com/api/public/otel/v1/traces"
        os.environ["LANGFUSE_PUBLIC_KEY"] = "pk-lf-test-public"
        os.environ["LANGFUSE_SECRET_KEY"] = "sk-lf-test-secret"

        with patch("mcpgateway.observability.HTTP_EXPORTER") as mock_exporter:
            with patch("mcpgateway.observability.TracerProvider"):
                with patch("mcpgateway.observability.BatchSpanProcessor"):
                    init_telemetry()

        call_kwargs = mock_exporter.call_args[1]
        assert call_kwargs["headers"]["Authorization"] == "Basic cGstbGYtdGVzdC1wdWJsaWM6c2stbGYtdGVzdC1zZWNyZXQ="

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    def test_init_telemetry_langfuse_merges_explicit_headers_with_derived_auth(self):
        """Langfuse auth should be merged into explicit OTLP headers when missing."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "otlp"
        os.environ["LANGFUSE_OTEL_ENDPOINT"] = "https://cloud.langfuse.com/api/public/otel/v1/traces"
        os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = "x-trace=abc"
        os.environ["LANGFUSE_PUBLIC_KEY"] = "pk-lf-test-public"
        os.environ["LANGFUSE_SECRET_KEY"] = "sk-lf-test-secret"

        with patch("mcpgateway.observability.HTTP_EXPORTER") as mock_exporter:
            with patch("mcpgateway.observability.TracerProvider"):
                with patch("mcpgateway.observability.BatchSpanProcessor"):
                    init_telemetry()

        call_kwargs = mock_exporter.call_args[1]
        assert call_kwargs["headers"]["x-trace"] == "abc"
        assert call_kwargs["headers"]["Authorization"] == "Basic cGstbGYtdGVzdC1wdWJsaWM6c2stbGYtdGVzdC1zZWNyZXQ="

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    def test_init_telemetry_langfuse_non_auth_headers_still_raise(self):
        """Langfuse OTLP should reject explicit headers that omit Authorization."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "otlp"
        os.environ["LANGFUSE_OTEL_ENDPOINT"] = "https://cloud.langfuse.com/api/public/otel/v1/traces"
        os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = "x-trace=abc"

        with pytest.raises(RuntimeError, match="valid Basic Authorization"):
            init_telemetry()

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    def test_init_telemetry_langfuse_non_basic_auth_still_raises(self):
        """Langfuse OTLP should reject Authorization headers that are not Basic auth."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "otlp"
        os.environ["LANGFUSE_OTEL_ENDPOINT"] = "https://cloud.langfuse.com/api/public/otel/v1/traces"
        os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = "Authorization=Bearer abc"

        with pytest.raises(RuntimeError, match="valid Basic Authorization"):
            init_telemetry()

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    def test_init_telemetry_langfuse_invalid_basic_auth_still_raises(self):
        """Langfuse OTLP should reject malformed Basic auth headers."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "otlp"
        os.environ["LANGFUSE_OTEL_ENDPOINT"] = "https://cloud.langfuse.com/api/public/otel/v1/traces"
        os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = "Authorization=Basic not-base64"

        with pytest.raises(RuntimeError, match="valid Basic Authorization"):
            init_telemetry()

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    def test_init_telemetry_langfuse_endpoint_forces_http_protocol(self):
        """Langfuse endpoints should use the HTTP OTLP exporter path."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "otlp"
        os.environ["OTEL_EXPORTER_OTLP_PROTOCOL"] = "grpc"
        os.environ["LANGFUSE_OTEL_ENDPOINT"] = "https://cloud.langfuse.com/api/public/otel/v1/traces"
        os.environ["LANGFUSE_PUBLIC_KEY"] = "pk-lf-test-public"
        os.environ["LANGFUSE_SECRET_KEY"] = "sk-lf-test-secret"

        with patch("mcpgateway.observability.OTLP_SPAN_EXPORTER") as mock_grpc_exporter:
            with patch("mcpgateway.observability.HTTP_EXPORTER") as mock_http_exporter:
                with patch("mcpgateway.observability.TracerProvider"):
                    with patch("mcpgateway.observability.BatchSpanProcessor"):
                        init_telemetry()

        mock_grpc_exporter.assert_not_called()
        mock_http_exporter.assert_called_once()

    def test_observability_helper_branches(self, monkeypatch):
        """Exercise helper branches used by OTEL and Langfuse configuration."""
        assert observability._sanitize_span_exception_message(None) == ""

        monkeypatch.setattr(observability, "sanitize_trace_text", lambda _value: "   ")
        monkeypatch.setattr(observability, "sanitize_for_log", lambda value: value)
        assert observability._sanitize_span_exception_message(ValueError("secret")) == "ValueError"

        monkeypatch.setattr(observability, "urlparse", MagicMock(side_effect=ValueError("boom")))
        assert observability._is_langfuse_otlp_endpoint("https://langfuse.example.com/api/public/otel/v1/traces") is True

        os.environ["LANGFUSE_OTEL_AUTH"] = "explicit-auth"
        get_settings.cache_clear()
        assert observability._resolve_langfuse_basic_auth() == "explicit-auth"

        parsed = observability._parse_otlp_headers("Authorization=Basic abc, invalid-header, x-test =  value ")
        assert parsed == {"Authorization": "Basic abc", "x-test": "value"}
        assert observability._get_header_case_insensitive(parsed, "authorization") == "Basic abc"
        assert observability._get_header_case_insensitive(parsed, "missing") is None

        observability._set_header_case_insensitive(parsed, "AUTHORIZATION", "Basic def")
        assert parsed["Authorization"] == "Basic def"
        observability._set_header_case_insensitive(parsed, "x-new", "123")
        assert parsed["x-new"] == "123"

    def test_span_attribute_policy_and_exception_fallback_branches(self):
        """Cover attribute-gating and sanitized exception-event fallback paths."""
        clear_trace_context()
        span = MagicMock()

        assert observability._should_emit_span_attribute("user.email") is False
        observability.set_span_attribute(span, "user.email", "user@example.com")
        span.set_attribute.assert_not_called()

        observability.set_span_attribute(None, "tool.name", "demo")
        observability._set_pre_sanitized_span_attribute(None, "tool.name", "demo")
        observability._record_sanitized_exception_event(None, ValueError, "boom")

        class BrokenException(Exception):
            def __init__(self, _message):
                raise RuntimeError("cannot instantiate")

        fallback_span = MagicMock()
        del fallback_span.add_event
        observability._record_sanitized_exception_event(fallback_span, BrokenException, "boom")
        fallback_span.record_exception.assert_called_once()
        recorded_exc = fallback_span.record_exception.call_args.args[0]
        assert isinstance(recorded_exc, Exception)
        assert str(recorded_exc) == "boom"

    def test_derive_langfuse_trace_name_variants(self):
        """Derive Langfuse-friendly names for the major traced operation families."""
        assert observability._derive_langfuse_trace_name("tool.invoke", {"tool.name": "clock"}) == "Tool: clock"
        assert observability._derive_langfuse_trace_name("tool.list", {}) == "Tools"
        assert observability._derive_langfuse_trace_name("prompt.list", {}) == "Prompts"
        assert observability._derive_langfuse_trace_name("resource.read", {"resource.uri": "time://formats"}) == "Resource: time://formats"
        assert observability._derive_langfuse_trace_name("resource.list", {}) == "Resources"
        assert observability._derive_langfuse_trace_name("resource_template.list", {}) == "Resource Templates"
        assert observability._derive_langfuse_trace_name("root.list", {}) == "Roots"
        assert observability._derive_langfuse_trace_name("llm.proxy", {"gen_ai.request.model": "gpt-5"}) == "LLM Proxy: gpt-5"
        assert observability._derive_langfuse_trace_name("llm.chat", {"gen_ai.request.model": "gpt-5-mini"}) == "LLM Chat: gpt-5-mini"
        assert observability._derive_langfuse_trace_name("a2a.invoke", {"a2a.agent.name": "echo-agent"}) == "A2A: echo-agent"

    @patch("mcpgateway.observability._TRACER")
    def test_create_span_swallow_trace_context_injection_errors(self, mock_tracer, monkeypatch):
        """create_span should tolerate trace-context auto-injection failures."""
        self._enable_langfuse_span_attrs()
        mock_span = MagicMock()
        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_span)
        mock_context.__exit__ = MagicMock(return_value=None)
        mock_tracer.start_as_current_span.return_value = mock_context

        monkeypatch.setattr(observability, "_derive_langfuse_trace_name", MagicMock(side_effect=RuntimeError("inject-failed")))

        with patch.object(observability.logger, "debug") as mock_debug:
            with create_span("test.operation", {"tool.name": "clock"}) as span:
                assert span is mock_span

        mock_debug.assert_called()

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

    @patch("mcpgateway.observability._TRACER")
    def test_create_span_auto_injects_trace_context(self, mock_tracer):
        """create_span should inject trace/user/session metadata into spans."""
        os.environ["DEPLOYMENT_ENV"] = "staging"
        self._enable_langfuse_span_attrs()
        set_trace_context_from_teams(["team-a", "team-b"], user_email="user@example.com", is_admin=True, auth_method="jwt", team_name="Team A")
        set_trace_session_id("session-123")

        mock_span = MagicMock()
        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_span)
        mock_context.__exit__ = MagicMock(return_value=None)
        mock_tracer.start_as_current_span.return_value = mock_context

        with patch("mcpgateway.observability.get_correlation_id", return_value="corr-1"):
            with create_span("test.operation") as span:
                assert span is mock_span

        mock_span.set_attribute.assert_any_call("correlation_id", "corr-1")
        mock_span.set_attribute.assert_any_call("request_id", "corr-1")
        mock_span.set_attribute.assert_any_call("user.email", "user@example.com")
        mock_span.set_attribute.assert_any_call("langfuse.user.id", "user@example.com")
        mock_span.set_attribute.assert_any_call("user.is_admin", True)
        mock_span.set_attribute.assert_any_call("team.scope", "team-a,team-b")
        mock_span.set_attribute.assert_any_call("team.name", "Team A")
        mock_span.set_attribute.assert_any_call("auth.method", "jwt")
        mock_span.set_attribute.assert_any_call("langfuse.session.id", "session-123")
        mock_span.set_attribute.assert_any_call("langfuse.environment", "staging")
        mock_span.set_attribute.assert_any_call("langfuse.trace.tags", ["team:team-a", "auth:jwt", "env:staging"])
        mock_span.set_attribute.assert_any_call("langfuse.trace.name", "test.operation")
        mock_span.set_attribute.assert_any_call("langfuse.observation.level", "DEFAULT")

    @patch("mcpgateway.observability._TRACER")
    def test_create_span_sanitizes_url_like_prompt_ids_in_trace_name(self, mock_tracer):
        """Prompt-derived Langfuse trace names should not leak URL query secrets."""
        self._enable_langfuse_span_attrs()

        mock_span = MagicMock()
        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_span)
        mock_context.__exit__ = MagicMock(return_value=None)
        mock_tracer.start_as_current_span.return_value = mock_context

        with create_span("prompt.render", {"prompt.id": "https://prompt.example.com/item?api_key=secret123"}) as span:
            assert span is mock_span

        mock_span.set_attribute.assert_any_call("langfuse.trace.name", "Prompt: https://prompt.example.com/item?api_key=REDACTED")

    @patch("mcpgateway.observability._TRACER")
    def test_create_span_omits_langfuse_and_identity_metadata_by_default(self, mock_tracer):
        """Non-Langfuse spans should not emit Langfuse or identity metadata by default."""
        set_trace_context_from_teams(["team-a"], user_email="user@example.com", is_admin=True, auth_method="jwt", team_name="Team A")
        set_trace_session_id("session-123")

        mock_span = MagicMock()
        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_span)
        mock_context.__exit__ = MagicMock(return_value=None)
        mock_tracer.start_as_current_span.return_value = mock_context

        with create_span("test.operation") as span:
            assert span is mock_span

        mock_span.set_attribute.assert_any_call("auth.method", "jwt")
        for disallowed_key in (
            "user.email",
            "langfuse.user.id",
            "team.scope",
            "team.name",
            "langfuse.session.id",
            "langfuse.environment",
            "langfuse.trace.tags",
            "langfuse.trace.name",
            "langfuse.observation.level",
        ):
            assert all(call.args[0] != disallowed_key for call in mock_span.set_attribute.call_args_list)

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
        mock_span.add_event.assert_called_once()
        assert mock_span.record_exception.call_count == 0

    @pytest.mark.asyncio
    @patch("mcpgateway.observability._TRACER")
    async def test_trace_operation_decorator_sanitizes_exception_message(self, mock_tracer):
        """trace_operation should sanitize exception text before storing it."""
        mock_span = MagicMock()
        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_span)
        mock_context.__exit__ = MagicMock(return_value=None)
        mock_tracer.start_as_current_span.return_value = mock_context

        @trace_operation("test.operation")
        async def test_func():
            raise ValueError("boom https://api.example.com?api_key=secret123\nCRITICAL")

        with pytest.raises(ValueError):
            await test_func()

        error_message = next(call.args[1] for call in mock_span.set_attribute.call_args_list if call.args[0] == "error.message")
        assert "secret123" not in error_message
        assert "REDACTED" in error_message
        assert "\n" not in error_message

    @pytest.mark.asyncio
    @patch("mcpgateway.observability._TRACER")
    async def test_trace_operation_decorator_redacts_free_text_secret_assignments(self, mock_tracer):
        """trace_operation should redact free-text key/value secrets before storing them."""
        mock_span = MagicMock()
        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_span)
        mock_context.__exit__ = MagicMock(return_value=None)
        mock_tracer.start_as_current_span.return_value = mock_context

        @trace_operation("test.operation")
        async def test_func():
            raise ValueError('boom token=supersecret authorization:"Bearer abc123"')

        with pytest.raises(ValueError):
            await test_func()

        error_message = next(call.args[1] for call in mock_span.set_attribute.call_args_list if call.args[0] == "error.message")
        assert "supersecret" not in error_message
        assert "abc123" not in error_message
        assert "token=***" in error_message

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

    def test_create_span_returns_wrapped_context_when_auto_attributes_exist(self):
        """create_span wraps the context when auto-injected attributes are present."""
        # First-Party
        import mcpgateway.observability

        self._enable_langfuse_span_attrs()

        mock_span = MagicMock()
        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_span)
        mock_context.__exit__ = MagicMock(return_value=None)
        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value = mock_context
        # pylint: disable=protected-access
        mcpgateway.observability._TRACER = mock_tracer

        with patch("mcpgateway.observability.get_correlation_id", return_value=None):
            with create_span("test.operation") as span:
                assert span is mock_span

        mock_tracer.start_as_current_span.assert_called_once_with("test.operation")
        mock_span.set_attribute.assert_any_call("langfuse.environment", "development")

    def test_span_with_attributes_records_exception_and_status(self):
        """Test SpanWithAttributes records errors and sets status."""
        # First-Party
        import mcpgateway.observability

        self._enable_langfuse_span_attrs()

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

        mock_span.add_event.assert_called_once()
        assert mock_span.record_exception.call_count == 0
        mock_span.set_attribute.assert_any_call("error", True)
        mock_span.set_attribute.assert_any_call("error.type", "ValueError")
        mock_span.set_attribute.assert_any_call("error.message", "boom")
        mock_span.set_attribute.assert_any_call("langfuse.observation.level", "ERROR")
        mock_span.set_attribute.assert_any_call("langfuse.observation.status_message", "boom")
        status_arg = mock_span.set_status.call_args[0][0]
        assert isinstance(status_arg, DummyStatus)
        assert status_arg.code == DummyStatusCode.ERROR

    def test_span_with_attributes_sanitizes_and_truncates_exception_message(self):
        """SpanWithAttributes should sanitize and bound exception messages."""
        # First-Party
        import mcpgateway.observability

        self._enable_langfuse_span_attrs()

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

        message = "boom https://api.example.com?api_key=secret123\n" + ("x" * 80)
        with patch("mcpgateway.observability.OTEL_AVAILABLE", True):
            with patch("mcpgateway.observability.Status", DummyStatus):
                with patch("mcpgateway.observability.StatusCode", DummyStatusCode):
                    with patch("mcpgateway.observability._MAX_SPAN_EXCEPTION_MESSAGE_LENGTH", 48):
                        with pytest.raises(ValueError):
                            with create_span("test.operation", {"key": "value"}):
                                raise ValueError(message)

        error_message = next(call.args[1] for call in mock_span.set_attribute.call_args_list if call.args[0] == "error.message")
        status_message = next(call.args[1] for call in mock_span.set_attribute.call_args_list if call.args[0] == "langfuse.observation.status_message")
        assert error_message == status_message
        assert "secret123" not in error_message
        assert "\n" not in error_message
        assert len(error_message) <= 48
        if len(error_message) == 48:
            assert error_message.endswith("...")
        status_arg = mock_span.set_status.call_args[0][0]
        assert status_arg.description == error_message

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

    def test_otel_tracing_enabled_reflects_global_tracer(self):
        """Test OTEL middleware enablement tracks tracer availability."""
        # First-Party
        import mcpgateway.observability

        # pylint: disable=protected-access
        mcpgateway.observability._TRACER = None
        assert otel_tracing_enabled() is False

        # pylint: disable=protected-access
        mcpgateway.observability._TRACER = MagicMock()
        assert otel_tracing_enabled() is True

    @patch("mcpgateway.observability.trace")
    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    def test_otel_context_active_checks_current_span_validity(self, mock_trace):
        """Test OTEL context detection follows the active current span."""
        valid_context = MagicMock(is_valid=True)
        invalid_context = MagicMock(is_valid=False)

        mock_trace.get_current_span.return_value = MagicMock(get_span_context=MagicMock(return_value=valid_context))
        assert otel_context_active() is True

        mock_trace.get_current_span.return_value = MagicMock(get_span_context=MagicMock(return_value=invalid_context))
        assert otel_context_active() is False

    @patch("mcpgateway.observability.trace")
    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    def test_otel_context_active_returns_false_when_span_missing_or_lookup_fails(self, mock_trace):
        """Test OTEL context detection fails closed for missing or broken spans."""
        mock_trace.get_current_span.return_value = None
        assert otel_context_active() is False

        mock_trace.get_current_span.side_effect = RuntimeError("boom")
        assert otel_context_active() is False

    @patch("mcpgateway.observability.otel_inject")
    def test_inject_trace_context_headers_injects_into_copy(self, mock_inject):
        """Test W3C trace context injection returns a copied carrier."""
        original = {"authorization": "Bearer abc"}

        def _fake_inject(carrier):
            carrier["traceparent"] = "00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01"
            carrier["tracestate"] = "vendor=value"

        mock_inject.side_effect = _fake_inject

        with patch("mcpgateway.observability.otel_context_active", return_value=True):
            carrier = inject_trace_context_headers(original)

        assert carrier["authorization"] == "Bearer abc"
        assert carrier["traceparent"].startswith("00-")
        assert carrier["tracestate"] == "vendor=value"
        assert "traceparent" not in original

    def test_inject_trace_context_headers_returns_copy_when_inactive(self):
        """Test inactive OTEL contexts do not mutate outbound headers."""
        original = {"authorization": "Bearer abc"}

        with patch("mcpgateway.observability.otel_context_active", return_value=False):
            carrier = inject_trace_context_headers(original)

        assert carrier == original
        assert carrier is not original

    @patch("mcpgateway.observability.otel_inject", side_effect=RuntimeError("boom"))
    def test_inject_trace_context_headers_logs_and_returns_headers_when_inject_fails(self, _mock_inject):
        """Test outbound headers survive OTEL propagation injection failures."""
        original = {"authorization": "Bearer abc"}

        with (
            patch("mcpgateway.observability.otel_context_active", return_value=True),
            patch("mcpgateway.observability.logger") as mock_logger,
        ):
            carrier = inject_trace_context_headers(original)

        assert carrier == original
        mock_logger.debug.assert_called_once()

    def test_scope_headers_to_carrier_skips_malformed_headers(self):
        """Test malformed ASGI header tuples are ignored during carrier conversion."""
        # First-Party
        import mcpgateway.observability

        carrier = mcpgateway.observability._scope_headers_to_carrier(
            [
                (b"user-agent", b"pytest"),
                ("bad-key", b"value"),
                (b"x-test", object()),
            ]
        )

        assert carrier == {"user-agent": "pytest"}

    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("/servers/demo/mcp", True),
            ("/servers/demo/message/", True),
            ("/_internal/mcp/plugin", True),
            ("/mcp/sse", True),
            ("/mcp/message", True),
            ("/mcp/sse/", True),
            ("/mcp/message/", True),
            ("/health", False),
            ("/mcp/unknown", False),
        ],
    )
    def test_should_trace_request_path_handles_transport_variants(self, path, expected):
        """Test transport-specific request paths are selected for tracing."""
        # First-Party
        import mcpgateway.observability

        assert mcpgateway.observability._should_trace_request_path(path) is expected

    def test_open_telemetry_request_middleware_proxies_app_attributes(self):
        """Test middleware proxies attribute access to the wrapped app."""

        class AppWithRouteMarker:
            routes = ["route-a"]

        middleware = OpenTelemetryRequestMiddleware(AppWithRouteMarker())
        assert middleware.routes == ["route-a"]

    @pytest.mark.asyncio
    async def test_open_telemetry_request_middleware_skips_untraced_http_paths(self):
        """Test OTEL request middleware ignores non-transport HTTP paths."""
        sent_messages = []

        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 204, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        middleware = OpenTelemetryRequestMiddleware(app)
        tracer = MagicMock()

        # First-Party
        import mcpgateway.observability

        # pylint: disable=protected-access
        mcpgateway.observability._TRACER = tracer

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/admin",
            "headers": [],
            "query_string": b"",
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent_messages.append(message)

        await middleware(scope, receive, send)

        tracer.start_as_current_span.assert_not_called()
        assert sent_messages[0]["status"] == 204

    @pytest.mark.asyncio
    async def test_open_telemetry_request_middleware_supports_custom_path_filter(self):
        """Test OTEL request middleware can be reused with runtime-specific path filters."""
        sent_messages = []
        span = MagicMock()
        span_context = MagicMock()
        span_context.__enter__ = MagicMock(return_value=span)
        span_context.__exit__ = MagicMock(return_value=None)
        tracer = MagicMock()
        tracer.start_as_current_span.return_value = span_context

        # First-Party
        import mcpgateway.observability

        # pylint: disable=protected-access
        mcpgateway.observability._TRACER = tracer

        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        middleware = OpenTelemetryRequestMiddleware(app, should_trace_request_path=lambda path: path == "/custom")
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/custom",
            "headers": [],
            "query_string": b"",
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent_messages.append(message)

        await middleware(scope, receive, send)

        tracer.start_as_current_span.assert_called_once()
        assert sent_messages[0]["status"] == 200

    @pytest.mark.asyncio
    @patch("mcpgateway.observability.otel_extract", return_value="parent-context")
    async def test_open_telemetry_request_middleware_creates_server_span(self, mock_extract):
        """Test OTEL request middleware creates a root server span for /rpc."""
        sent_messages = []
        span = MagicMock()
        span_context = MagicMock()
        span_context.__enter__ = MagicMock(return_value=span)
        span_context.__exit__ = MagicMock(return_value=None)
        tracer = MagicMock()
        tracer.start_as_current_span.return_value = span_context

        # First-Party
        import mcpgateway.observability

        # pylint: disable=protected-access
        mcpgateway.observability._TRACER = tracer

        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}"})

        middleware = OpenTelemetryRequestMiddleware(app)
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/rpc",
            "headers": [
                (b"user-agent", b"pytest"),
                (b"x-correlation-id", b"corr-123"),
                (b"traceparent", b"00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"),
            ],
            "query_string": b"server_id=abc",
            "http_version": "1.1",
            "server": ("localhost", 4444),
            "client": ("127.0.0.1", 51234),
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent_messages.append(message)

        await middleware(scope, receive, send)

        tracer.start_as_current_span.assert_called_once_with(
            "POST /rpc",
            context="parent-context",
            kind=mcpgateway.observability.SpanKind.SERVER,
        )
        mock_extract.assert_called_once()
        span.set_attribute.assert_any_call("http.request.method", "POST")
        span.set_attribute.assert_any_call("http.route", "/rpc")
        # Query string is now sanitized - non-sensitive params remain visible
        span.set_attribute.assert_any_call("url.query", "server_id=abc")
        span.set_attribute.assert_any_call("user_agent.original", "pytest")
        span.set_attribute.assert_any_call("correlation_id", "corr-123")
        span.set_attribute.assert_any_call("http.response.status_code", 200)
        assert sent_messages[0]["status"] == 200

    @pytest.mark.asyncio
    async def test_open_telemetry_request_middleware_records_exceptions(self):
        """Test OTEL request middleware records exceptions on the root span."""
        span = MagicMock()
        span_context = MagicMock()
        span_context.__enter__ = MagicMock(return_value=span)
        span_context.__exit__ = MagicMock(return_value=None)
        tracer = MagicMock()
        tracer.start_as_current_span.return_value = span_context

        # First-Party
        import mcpgateway.observability

        class DummyStatusCode:
            ERROR = "error"

        class DummyStatus:
            def __init__(self, code, description=None):
                self.code = code
                self.description = description

        # pylint: disable=protected-access
        mcpgateway.observability._TRACER = tracer

        async def app(scope, receive, send):
            raise RuntimeError("boom")

        middleware = OpenTelemetryRequestMiddleware(app)
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/rpc",
            "headers": [],
            "query_string": b"",
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            return None

        with patch("mcpgateway.observability.OTEL_AVAILABLE", True):
            with patch("mcpgateway.observability.Status", DummyStatus):
                with patch("mcpgateway.observability.StatusCode", DummyStatusCode):
                    with pytest.raises(RuntimeError, match="boom"):
                        await middleware(scope, receive, send)

        span.add_event.assert_called_once()
        span.set_attribute.assert_any_call("error", True)
        span.set_attribute.assert_any_call("error.type", "RuntimeError")
        span.set_attribute.assert_any_call("error.message", "boom")
        status_arg = span.set_status.call_args[0][0]
        assert isinstance(status_arg, DummyStatus)
        assert status_arg.code == DummyStatusCode.ERROR

    @pytest.mark.asyncio
    async def test_open_telemetry_request_middleware_tolerates_extract_failures_and_non_bytes_query(self):
        """Test middleware continues tracing when parent extraction fails."""
        sent_messages = []
        span = MagicMock()
        span_context = MagicMock()
        span_context.__enter__ = MagicMock(return_value=span)
        span_context.__exit__ = MagicMock(return_value=None)
        tracer = MagicMock()
        tracer.start_as_current_span.return_value = span_context

        # First-Party
        import mcpgateway.observability

        # pylint: disable=protected-access
        mcpgateway.observability._TRACER = tracer

        class DummyStatusCode:
            OK = "ok"

        class DummyStatus:
            def __init__(self, code, description=None):
                self.code = code
                self.description = description

        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 204, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        middleware = OpenTelemetryRequestMiddleware(app)
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/servers/plugin-a/mcp",
            "headers": [(b"user-agent", b"pytest"), ("broken", b"value")],
            "query_string": "trace=1",
            "http_version": "1.1",
            "server": ("localhost", 4444),
            "client": ("127.0.0.1", 51234),
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent_messages.append(message)

        with (
            patch("mcpgateway.observability.otel_extract", side_effect=RuntimeError("bad parent")),
            patch("mcpgateway.observability.OTEL_AVAILABLE", True),
            patch("mcpgateway.observability.Status", DummyStatus),
            patch("mcpgateway.observability.StatusCode", DummyStatusCode),
        ):
            await middleware(scope, receive, send)

        tracer.start_as_current_span.assert_called_once()
        span.set_attribute.assert_any_call("http.request.method", "GET")
        span.set_attribute.assert_any_call("url.query", "trace=1")
        span.set_status.assert_called_once()
        assert sent_messages[0]["status"] == 204

    @pytest.mark.asyncio
    async def test_open_telemetry_request_middleware_redacts_session_id_in_query_string(self):
        """Test middleware redacts session_id from query strings to prevent leaking live sessions."""
        sent_messages = []
        span = MagicMock()
        span_context = MagicMock()
        span_context.__enter__ = MagicMock(return_value=span)
        span_context.__exit__ = MagicMock(return_value=None)
        tracer = MagicMock()
        tracer.start_as_current_span.return_value = span_context

        # First-Party
        import mcpgateway.observability

        # pylint: disable=protected-access
        mcpgateway.observability._TRACER = tracer

        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}"})

        middleware = OpenTelemetryRequestMiddleware(app)

        # Simulate SSE callback URL with session_id in query string
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/message",
            "headers": [(b"user-agent", b"pytest")],
            "query_string": b"session_id=live-session-abc123&other=value",
            "http_version": "1.1",
            "server": ("localhost", 4444),
            "client": ("127.0.0.1", 51234),
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent_messages.append(message)

        await middleware(scope, receive, send)

        # Verify session_id was redacted in the span attribute
        span.set_attribute.assert_any_call("http.request.method", "POST")
        span.set_attribute.assert_any_call("http.route", "/message")

        # Check that session_id is redacted but other params remain
        query_calls = [call for call in span.set_attribute.call_args_list if call[0][0] == "url.query"]
        assert len(query_calls) == 1
        query_value = query_calls[0][0][1]

        # session_id should be redacted
        assert "live-session-abc123" not in query_value
        assert "session_id=***" in query_value or "sessionid=***" in query_value.lower()

        # Non-sensitive params should remain visible
        assert "other=value" in query_value

        assert sent_messages[0]["status"] == 200

    @pytest.mark.asyncio
    async def test_open_telemetry_request_middleware_tolerates_extract_failures_continued(self):
        """Test middleware continues after extraction failures."""
        sent_messages = []
        span = MagicMock()
        span_context = MagicMock()
        span_context.__enter__ = MagicMock(return_value=span)
        span_context.__exit__ = MagicMock(return_value=None)
        tracer = MagicMock()
        tracer.start_as_current_span.return_value = span_context

        # First-Party
        import mcpgateway.observability

        # pylint: disable=protected-access
        mcpgateway.observability._TRACER = tracer

        class DummyStatusCode:
            OK = "ok"

        class DummyStatus:
            def __init__(self, code, description=None):
                self.code = code
                self.description = description

        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 204, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        middleware = OpenTelemetryRequestMiddleware(app)
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/servers/plugin-a/mcp",
            "headers": [(b"user-agent", b"pytest")],
            "query_string": "trace=1",
            "http_version": "1.1",
            "server": ("localhost", 4444),
            "client": ("127.0.0.1", 51234),
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent_messages.append(message)

        with (
            patch("mcpgateway.observability.otel_extract", side_effect=RuntimeError("bad parent")),
            patch("mcpgateway.observability.OTEL_AVAILABLE", True),
            patch("mcpgateway.observability.Status", DummyStatus),
            patch("mcpgateway.observability.StatusCode", DummyStatusCode),
            patch("mcpgateway.observability.logger") as mock_logger,
        ):
            await middleware(scope, receive, send)

        tracer.start_as_current_span.assert_called_once()
        span.set_attribute.assert_any_call("http.response.status_code", 204)
        status_arg = span.set_status.call_args[0][0]
        assert isinstance(status_arg, DummyStatus)
        assert status_arg.code == DummyStatusCode.OK
        assert sent_messages[0]["status"] == 204
        mock_logger.debug.assert_called_once()

    def test_observability_module_imports_otel_symbols_when_dependency_present(self):
        """Test module import path binds OTEL symbols when OpenTelemetry imports succeed."""
        # First-Party
        import mcpgateway.observability as observability

        fake_trace = object()
        fake_extract = object()
        fake_inject = object()
        fake_resource = object()
        fake_tracer_provider = object()
        fake_batch = object()
        fake_console = object()
        fake_simple = object()
        fake_span_kind = object()
        fake_status = object()
        fake_status_code = object()

        original_import = importlib.import_module

        def _fake_import(name, package=None):
            if name == "opentelemetry.exporter.otlp.proto.http.trace_exporter":
                return type("FakeOTLPModule", (), {"OTLPSpanExporter": object()})()
            return original_import(name, package)

        with (
            patch.object(observability, "_im", side_effect=_fake_import),
            patch.dict(
                "sys.modules",
                {
                    "opentelemetry": type("FakeOtel", (), {"trace": fake_trace})(),
                    "opentelemetry.propagate": type("FakePropagate", (), {"extract": fake_extract, "inject": fake_inject})(),
                    "opentelemetry.sdk.resources": type("FakeResources", (), {"Resource": fake_resource})(),
                    "opentelemetry.sdk.trace": type("FakeSDKTrace", (), {"TracerProvider": fake_tracer_provider})(),
                    "opentelemetry.sdk.trace.export": type(
                        "FakeSDKTraceExport",
                        (),
                        {
                            "BatchSpanProcessor": fake_batch,
                            "ConsoleSpanExporter": fake_console,
                            "SimpleSpanProcessor": fake_simple,
                        },
                    )(),
                    "opentelemetry.trace": type(
                        "FakeTraceModule",
                        (),
                        {
                            "SpanKind": fake_span_kind,
                            "Status": fake_status,
                            "StatusCode": fake_status_code,
                        },
                    )(),
                },
                clear=False,
            ),
        ):
            reloaded = importlib.reload(observability)

        try:
            assert reloaded.OTEL_AVAILABLE is True
            assert reloaded.trace is fake_trace
            assert reloaded.otel_extract is fake_extract
            assert reloaded.otel_inject is fake_inject
            assert reloaded.SpanKind is fake_span_kind
        finally:
            importlib.reload(reloaded)
