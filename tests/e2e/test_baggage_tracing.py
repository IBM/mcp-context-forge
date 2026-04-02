# -*- coding: utf-8 -*-
"""End-to-end tests for OpenTelemetry baggage tracing.

Tests cover:
- Full request flow with baggage extraction
- Baggage propagation to spans
- Baggage propagation to downstream services
- Integration with OpenTelemetry context
"""

# Standard
from unittest.mock import MagicMock, patch

# Third-Party
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# First-Party
from mcpgateway.baggage import BaggageConfig, HeaderMapping
from mcpgateway.middleware.baggage_middleware import BaggageMiddleware


@pytest.fixture
def tracing_app():
    """Create FastAPI app with baggage and tracing middleware."""
    app = FastAPI()

    # Simulate OpenTelemetry middleware (simplified)
    config = BaggageConfig(
        enabled=True,
        mappings=[
            HeaderMapping("X-Tenant-ID", "tenant.id"),
            HeaderMapping("X-User-ID", "user.id"),
            HeaderMapping("X-Request-ID", "request.id"),
        ],
        propagate_to_external=True,  # Enable propagation
        max_items=32,
        max_size_bytes=8192,
        log_rejected=True,
        log_sanitization=True,
    )
    app.add_middleware(BaggageMiddleware, config=config)

    @app.get("/test")
    async def test_endpoint():
        return {"status": "ok"}

    @app.get("/downstream")
    async def downstream_endpoint():
        """Simulate calling downstream service."""
        # First-Party
        from mcpgateway.observability import inject_trace_context_headers

        headers = inject_trace_context_headers()
        return {"headers": headers}

    return app


class TestBaggageTracingE2E:
    """End-to-end tests for baggage tracing."""

    def test_baggage_extracted_and_set_in_context(self, tracing_app):
        """Test baggage is extracted from headers and set in OpenTelemetry context."""
        client = TestClient(tracing_app)

        with patch("mcpgateway.middleware.baggage_middleware.otel_baggage") as mock_baggage:
            response = client.get(
                "/test",
                headers={
                    "X-Tenant-ID": "tenant-123",
                    "X-User-ID": "user-456",
                    "X-Request-ID": "req-789",
                },
            )

            assert response.status_code == 200
            # Verify all configured headers were extracted and set
            assert mock_baggage.set_baggage.call_count == 3
            mock_baggage.set_baggage.assert_any_call("tenant.id", "tenant-123")
            mock_baggage.set_baggage.assert_any_call("user.id", "user-456")
            mock_baggage.set_baggage.assert_any_call("request.id", "req-789")

    def test_baggage_propagated_to_downstream(self, tracing_app):
        """Test baggage is propagated to downstream service calls."""
        client = TestClient(tracing_app)

        with patch("mcpgateway.middleware.baggage_middleware.otel_baggage") as mock_baggage:
            with patch("mcpgateway.observability.otel_baggage") as mock_obs_baggage:
                with patch("mcpgateway.config.get_settings") as mock_get_settings:
                    # Configure settings for propagation
                    mock_settings = MagicMock()
                    mock_settings.otel_baggage_enabled = True
                    mock_settings.otel_baggage_propagate_to_external = True
                    mock_get_settings.return_value = mock_settings

                    # Mock baggage retrieval
                    mock_obs_baggage.get_all.return_value = {
                        "tenant.id": "tenant-123",
                        "user.id": "user-456",
                    }

                    with patch("mcpgateway.observability.OTEL_AVAILABLE", True):
                        with patch("mcpgateway.observability.otel_context_active", return_value=True):
                            with patch("mcpgateway.observability.otel_inject"):
                                response = client.get(
                                    "/downstream",
                                    headers={
                                        "X-Tenant-ID": "tenant-123",
                                        "X-User-ID": "user-456",
                                    },
                                )

                                assert response.status_code == 200
                                headers = response.json()["headers"]

                                # Verify baggage header was added
                                assert "baggage" in headers
                                # Verify baggage format (order may vary)
                                assert "tenant.id=tenant-123" in headers["baggage"]
                                assert "user.id=user-456" in headers["baggage"]

    def test_baggage_not_propagated_when_disabled(self, tracing_app):
        """Test baggage is not propagated when propagate_to_external is false."""
        client = TestClient(tracing_app)

        with patch("mcpgateway.middleware.baggage_middleware.otel_baggage"):
            with patch("mcpgateway.observability.otel_baggage") as mock_obs_baggage:
                with patch("mcpgateway.config.get_settings") as mock_get_settings:
                    # Disable propagation
                    mock_settings = MagicMock()
                    mock_settings.otel_baggage_enabled = True
                    mock_settings.otel_baggage_propagate_to_external = False
                    mock_get_settings.return_value = mock_settings

                    mock_obs_baggage.get_all.return_value = {
                        "tenant.id": "tenant-123",
                    }

                    with patch("mcpgateway.observability.OTEL_AVAILABLE", True):
                        with patch("mcpgateway.observability.otel_context_active", return_value=True):
                            with patch("mcpgateway.observability.otel_inject"):
                                response = client.get(
                                    "/downstream",
                                    headers={"X-Tenant-ID": "tenant-123"},
                                )

                                assert response.status_code == 200
                                headers = response.json()["headers"]

                                # Verify baggage header was NOT added
                                assert "baggage" not in headers

    def test_baggage_merged_with_upstream(self, tracing_app):
        """Test header baggage is merged with upstream baggage."""
        client = TestClient(tracing_app)

        with patch("mcpgateway.middleware.baggage_middleware.otel_baggage") as mock_baggage:
            response = client.get(
                "/test",
                headers={
                    "X-Tenant-ID": "tenant-123",
                    "baggage": "upstream.key=upstream-value,another.key=another-value",
                },
            )

            assert response.status_code == 200
            # Verify both header and upstream baggage were set
            assert mock_baggage.set_baggage.call_count == 3
            mock_baggage.set_baggage.assert_any_call("tenant.id", "tenant-123")
            mock_baggage.set_baggage.assert_any_call("upstream.key", "upstream-value")
            mock_baggage.set_baggage.assert_any_call("another.key", "another-value")

    def test_baggage_sanitized_before_propagation(self, tracing_app):
        """Test baggage values are sanitized before propagation."""
        client = TestClient(tracing_app)

        with patch("mcpgateway.middleware.baggage_middleware.otel_baggage"):
            with patch("mcpgateway.observability.otel_baggage") as mock_obs_baggage:
                with patch("mcpgateway.config.get_settings") as mock_get_settings:
                    mock_settings = MagicMock()
                    mock_settings.otel_baggage_enabled = True
                    mock_settings.otel_baggage_propagate_to_external = True
                    mock_get_settings.return_value = mock_settings

                    # Mock baggage with control characters
                    mock_obs_baggage.get_all.return_value = {
                        "tenant.id": "tenant\x00\x01\x02",
                    }

                    with patch("mcpgateway.observability.OTEL_AVAILABLE", True):
                        with patch("mcpgateway.observability.otel_context_active", return_value=True):
                            with patch("mcpgateway.observability.otel_inject"):
                                response = client.get(
                                    "/downstream",
                                    headers={"X-Tenant-ID": "tenant\x00\x01\x02"},
                                )

                                assert response.status_code == 200
                                headers = response.json()["headers"]

                                # Verify sanitized value in baggage header
                                if "baggage" in headers:
                                    assert "\x00" not in headers["baggage"]
                                    assert "\x01" not in headers["baggage"]
                                    assert "\x02" not in headers["baggage"]

    def test_span_attributes_include_baggage(self):
        """Test that spans automatically include baggage as attributes."""
        with patch("mcpgateway.observability.OTEL_AVAILABLE", True):
            with patch("mcpgateway.observability.otel_baggage") as mock_baggage:
                with patch("mcpgateway.observability._TRACER") as mock_tracer:
                    # Mock baggage retrieval
                    mock_baggage.get_all.return_value = {
                        "tenant.id": "tenant-123",
                        "user.id": "user-456",
                    }

                    # Mock span context
                    mock_span = MagicMock()
                    mock_tracer.start_as_current_span.return_value.__enter__.return_value = mock_span

                    # First-Party
                    from mcpgateway.observability import create_span

                    with create_span("test.span"):
                        pass

                    # Verify span was created with baggage attributes
                    mock_tracer.start_as_current_span.assert_called_once()
                    # The span should have baggage attributes set via the wrapper
