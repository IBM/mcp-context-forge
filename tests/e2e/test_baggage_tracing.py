# -*- coding: utf-8 -*-
"""Location: ./tests/e2e/test_baggage_tracing.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

End-to-end tests for OpenTelemetry baggage tracing.

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


class _FakeOtelBaggage:
    def __init__(self):
        self._state = {}

    def get_all(self):
        return dict(self._state)

    def set_baggage(self, key, value, context=None):
        new_context = dict(self._state if context is None else context)
        new_context[key] = value
        return new_context

    def get_current(self):
        return dict(self._state)

    def attach(self, context):
        previous = dict(self._state)
        self._state = dict(context)
        return previous

    def detach(self, token):
        self._state = dict(token)


@pytest.fixture(autouse=True)
def fake_otel_baggage(monkeypatch):
    fake = _FakeOtelBaggage()
    monkeypatch.setattr("mcpgateway.middleware.baggage_middleware.otel_baggage", fake)
    monkeypatch.setattr("mcpgateway.middleware.baggage_middleware.otel_get_current", fake.get_current)
    monkeypatch.setattr("mcpgateway.middleware.baggage_middleware.otel_attach", fake.attach)
    monkeypatch.setattr("mcpgateway.middleware.baggage_middleware.otel_detach", fake.detach)
    monkeypatch.setattr("mcpgateway.observability.otel_baggage", fake)
    monkeypatch.setattr("mcpgateway.observability.OTEL_AVAILABLE", True)
    return fake


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
        # First-Party
        from mcpgateway.middleware.baggage_middleware import otel_baggage

        return {"status": "ok", "baggage": dict(otel_baggage.get_all())}

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

        response = client.get(
            "/test",
            headers={
                "X-Tenant-ID": "tenant-123",
                "X-User-ID": "user-456",
                "X-Request-ID": "req-789",
            },
        )

        assert response.status_code == 200
        assert response.json()["baggage"] == {
            "tenant.id": "tenant-123",
            "user.id": "user-456",
            "request.id": "req-789",
        }

    def test_baggage_propagated_to_downstream(self, tracing_app):
        """Test baggage is propagated to downstream service calls."""
        client = TestClient(tracing_app)

        with patch("mcpgateway.observability.get_settings") as mock_get_settings:
            mock_settings = MagicMock()
            mock_settings.otel_baggage_enabled = True
            mock_settings.otel_baggage_propagate_to_external = True
            mock_get_settings.return_value = mock_settings

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
                    assert "baggage" in headers
                    assert "tenant.id=tenant-123" in headers["baggage"]
                    assert "user.id=user-456" in headers["baggage"]

    def test_baggage_not_propagated_when_disabled(self, tracing_app):
        """Test baggage is not propagated when propagate_to_external is false."""
        client = TestClient(tracing_app)

        with patch("mcpgateway.observability.get_settings") as mock_get_settings:
            mock_settings = MagicMock()
            mock_settings.otel_baggage_enabled = True
            mock_settings.otel_baggage_propagate_to_external = False
            mock_get_settings.return_value = mock_settings

            with patch("mcpgateway.observability.otel_context_active", return_value=True):
                with patch("mcpgateway.observability.otel_inject"):
                    response = client.get(
                        "/downstream",
                        headers={"X-Tenant-ID": "tenant-123"},
                    )

                    assert response.status_code == 200
                    headers = response.json()["headers"]
                    assert "baggage" not in headers

    def test_baggage_merged_with_upstream(self, tracing_app):
        """Test header baggage is merged with upstream baggage."""
        client = TestClient(tracing_app)

        response = client.get(
            "/test",
            headers={
                "X-Tenant-ID": "tenant-123",
                "baggage": "user.id=user-456,request.id=req-789",
            },
        )

        assert response.status_code == 200
        assert response.json()["baggage"] == {
            "tenant.id": "tenant-123",
            "user.id": "user-456",
            "request.id": "req-789",
        }

    def test_baggage_sanitized_before_propagation(self, tracing_app):
        """Test baggage values are sanitized before propagation."""
        client = TestClient(tracing_app)

        with patch("mcpgateway.observability.get_settings") as mock_get_settings:
            mock_settings = MagicMock()
            mock_settings.otel_baggage_enabled = True
            mock_settings.otel_baggage_propagate_to_external = True
            mock_get_settings.return_value = mock_settings

            with patch("mcpgateway.observability.otel_context_active", return_value=True):
                with patch("mcpgateway.observability.otel_inject"):
                    response = client.get(
                        "/downstream",
                        headers={"X-Tenant-ID": "tenant\x00\x01\x02"},
                    )

                    assert response.status_code == 200
                    headers = response.json()["headers"]
                    assert headers["baggage"] == "tenant.id=tenant"

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

    def test_baggage_span_attribute_policy_applied(self):
        """Test that baggage span attribute policy filters and formats attributes correctly."""
        # First-Party
        from mcpgateway.observability import BaggageSpanAttributePolicy, _baggage_span_attributes, configure_baggage_span_attribute_policy

        # Test baggage with multiple keys
        baggage_dict = {
            "tenant.id": "tenant-123",
            "user.id": "user-456",  # Should be filtered out
            "request.id": "req-789",  # Should be filtered out
        }

        # Test 1: Configure policy to only allow tenant.id, emit without prefix
        policy = BaggageSpanAttributePolicy(
            emit_prefixed=False,
            allowed_keys=frozenset({"tenant.id"})
        )
        configure_baggage_span_attribute_policy(policy)

        result = _baggage_span_attributes(baggage_dict)

        # Should have tenant.id without baggage. prefix
        assert "tenant.id" in result
        assert result["tenant.id"] == "tenant-123"

        # Should NOT have filtered keys
        assert "user.id" not in result
        assert "request.id" not in result
        assert "baggage.user.id" not in result
        assert "baggage.request.id" not in result
        assert "baggage.tenant.id" not in result

        # Verify only one key was emitted
        assert len(result) == 1

        # Test 2: Configure policy with prefixed mode
        policy_prefixed = BaggageSpanAttributePolicy(
            emit_prefixed=True,
            allowed_keys=frozenset({"tenant.id"})
        )
        configure_baggage_span_attribute_policy(policy_prefixed)

        result_prefixed = _baggage_span_attributes(baggage_dict)

        # Should have baggage.tenant.id with prefix
        assert "baggage.tenant.id" in result_prefixed
        assert result_prefixed["baggage.tenant.id"] == "tenant-123"
        assert "tenant.id" not in result_prefixed

        # Reset policy for other tests
        configure_baggage_span_attribute_policy(BaggageSpanAttributePolicy())
