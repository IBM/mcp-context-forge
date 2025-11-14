# -*- coding: utf-8 -*-
"""Tests for correlation ID middleware."""

import pytest
from unittest.mock import Mock, patch
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from mcpgateway.middleware.correlation_id import CorrelationIDMiddleware
from mcpgateway.utils.correlation_id import get_correlation_id


@pytest.fixture
def app():
    """Create a test FastAPI app with correlation ID middleware."""
    test_app = FastAPI()

    # Add the correlation ID middleware
    test_app.add_middleware(CorrelationIDMiddleware)

    @test_app.get("/test")
    async def test_endpoint(request: Request):
        # Get correlation ID from context
        correlation_id = get_correlation_id()
        return {"correlation_id": correlation_id}

    return test_app


@pytest.fixture
def client(app):
    """Create a test client."""
    return TestClient(app)


def test_middleware_generates_correlation_id_when_not_provided(client):
    """Test that middleware generates a correlation ID when not provided by client."""
    response = client.get("/test")

    assert response.status_code == 200
    data = response.json()

    # Should have a correlation ID in response body
    assert "correlation_id" in data
    assert data["correlation_id"] is not None
    assert len(data["correlation_id"]) == 32  # UUID hex format

    # Should have correlation ID in response headers
    assert "X-Correlation-ID" in response.headers
    assert response.headers["X-Correlation-ID"] == data["correlation_id"]


def test_middleware_preserves_client_correlation_id(client):
    """Test that middleware preserves correlation ID from client."""
    client_id = "client-provided-id-123"

    response = client.get("/test", headers={"X-Correlation-ID": client_id})

    assert response.status_code == 200
    data = response.json()

    # Should use the client-provided ID
    assert data["correlation_id"] == client_id

    # Should echo it back in response headers
    assert response.headers["X-Correlation-ID"] == client_id


def test_middleware_case_insensitive_header(client):
    """Test that middleware handles case-insensitive headers."""
    client_id = "lowercase-header-id"

    response = client.get("/test", headers={"x-correlation-id": client_id})

    assert response.status_code == 200
    data = response.json()

    # Should use the client-provided ID regardless of case
    assert data["correlation_id"] == client_id


def test_middleware_strips_whitespace_from_header(client):
    """Test that middleware strips whitespace from correlation ID header."""
    client_id = "  whitespace-id  "

    response = client.get("/test", headers={"X-Correlation-ID": client_id})

    assert response.status_code == 200
    data = response.json()

    # Should strip whitespace
    assert data["correlation_id"] == "whitespace-id"


def test_middleware_clears_correlation_id_after_request(app):
    """Test that middleware clears correlation ID after request completes."""
    client = TestClient(app)

    # Make a request
    response = client.get("/test")
    assert response.status_code == 200

    # After request completes, correlation ID should be cleared
    # (Note: This happens in a different context, so we can't directly test it here,
    # but we verify that multiple requests get different IDs)
    response2 = client.get("/test")
    assert response2.status_code == 200

    # Two requests without client-provided IDs should have different correlation IDs
    assert response.json()["correlation_id"] != response2.json()["correlation_id"]


def test_middleware_handles_empty_header(client):
    """Test that middleware generates new ID when header is empty."""
    response = client.get("/test", headers={"X-Correlation-ID": ""})

    assert response.status_code == 200
    data = response.json()

    # Should generate a new ID when header is empty
    assert data["correlation_id"] is not None
    assert len(data["correlation_id"]) == 32


def test_middleware_with_custom_settings(monkeypatch):
    """Test middleware with custom configuration settings."""
    # Create a mock settings object
    mock_settings = Mock()
    mock_settings.correlation_id_header = "X-Request-ID"
    mock_settings.correlation_id_preserve = False
    mock_settings.correlation_id_response_header = False

    # Create app with custom settings
    app = FastAPI()

    # Patch settings at module level
    with patch("mcpgateway.middleware.correlation_id.settings", mock_settings):
        app.add_middleware(CorrelationIDMiddleware)

        @app.get("/test")
        async def test_endpoint():
            return {"correlation_id": get_correlation_id()}

        client = TestClient(app)

        # Test with custom header name
        response = client.get("/test", headers={"X-Request-ID": "custom-id"})

        assert response.status_code == 200

        # When preserve=False, should always generate new ID (not use client's)
        # When response_header=False, should not include in response headers
        assert "X-Request-ID" not in response.headers


def test_middleware_integration_with_multiple_requests(client):
    """Test middleware properly isolates correlation IDs across multiple requests."""
    ids = []

    for i in range(5):
        response = client.get("/test", headers={"X-Correlation-ID": f"request-{i}"})
        assert response.status_code == 200
        ids.append(response.json()["correlation_id"])

    # Each request should have its unique correlation ID
    assert len(ids) == 5
    assert len(set(ids)) == 5  # All unique
    for i, correlation_id in enumerate(ids):
        assert correlation_id == f"request-{i}"


def test_middleware_context_isolation():
    """Test that correlation ID is properly isolated per request context."""
    app = FastAPI()
    app.add_middleware(CorrelationIDMiddleware)

    correlation_ids_seen = []

    @app.get("/capture")
    async def capture_endpoint():
        # Capture the correlation ID during request handling
        correlation_id = get_correlation_id()
        correlation_ids_seen.append(correlation_id)
        return {"captured": correlation_id}

    client = TestClient(app)

    # Make multiple concurrent-like requests
    for i in range(3):
        response = client.get("/capture", headers={"X-Correlation-ID": f"id-{i}"})
        assert response.status_code == 200

    # Each request should have captured its own unique ID
    assert len(correlation_ids_seen) == 3
    assert correlation_ids_seen[0] == "id-0"
    assert correlation_ids_seen[1] == "id-1"
    assert correlation_ids_seen[2] == "id-2"


def test_middleware_preserves_correlation_id_through_request_lifecycle():
    """Test that correlation ID remains consistent throughout entire request."""
    captured_ids = []

    app = FastAPI()

    @app.middleware("http")
    async def capture_middleware(request: Request, call_next):
        # Capture ID at middleware level (after CorrelationIDMiddleware sets it)
        captured_ids.append(("middleware", get_correlation_id()))
        response = await call_next(request)
        return response

    # Add CorrelationIDMiddleware last so it executes first (LIFO)
    app.add_middleware(CorrelationIDMiddleware)

    @app.get("/test")
    async def test_endpoint():
        # Capture ID at endpoint level
        captured_ids.append(("endpoint", get_correlation_id()))
        return {"ok": True}

    client = TestClient(app)
    response = client.get("/test", headers={"X-Correlation-ID": "consistent-id"})

    assert response.status_code == 200

    # Both captures should have the same correlation ID
    assert len(captured_ids) == 2
    assert captured_ids[0][1] == "consistent-id"  # Middleware capture
    assert captured_ids[1][1] == "consistent-id"  # Endpoint capture
