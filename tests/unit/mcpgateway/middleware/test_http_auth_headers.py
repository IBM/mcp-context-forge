# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/middleware/test_http_auth_headers.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge

Tests that verify HTTP auth middleware properly modifies Starlette request headers.

These tests verify the low-level header modification works correctly:
- request.scope["headers"] is updated
- Modified headers are visible to downstream dependencies (HTTPBearer)
- get_current_user() receives the transformed credentials
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi import Depends, FastAPI, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.testclient import TestClient
import pytest

# First-Party
from mcpgateway.middleware.http_auth_middleware import HttpAuthMiddleware
from mcpgateway.plugins.framework import (
    GlobalContext,
    HttpHeaderPayload,
    HttpHookType,
    PluginResult,
)


class TestRequestScopeHeaderModification:
    """Test that request.scope['headers'] is properly modified by middleware."""

    @pytest.fixture
    def simple_app_with_header_transform(self):
        """Create a simple FastAPI app that tests header transformation."""
        app = FastAPI()

        # Create mock plugin manager that transforms X-API-Key → Authorization
        mock_plugin_manager = MagicMock()

        async def mock_invoke_hook(hook_type, payload, global_context, local_contexts=None, violations_as_exceptions=False):  # noqa: ARG001
            if hook_type == HttpHookType.HTTP_PRE_REQUEST:
                # Transform X-API-Key to Authorization
                headers = dict(payload.headers.root)
                if "x-api-key" in headers and "authorization" not in headers:
                    headers["authorization"] = f"Bearer {headers['x-api-key']}"
                    return PluginResult(modified_payload=HttpHeaderPayload(headers), continue_processing=True), {}
            return PluginResult(continue_processing=True), {}

        mock_plugin_manager.invoke_hook = mock_invoke_hook

        # Add middleware
        app.add_middleware(HttpAuthMiddleware, plugin_manager=mock_plugin_manager)

        # Add bearer scheme
        bearer_scheme = HTTPBearer(auto_error=False)

        # Create endpoint that captures the credentials
        @app.get("/test-headers")
        async def test_endpoint(credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)):
            """Test endpoint that returns what credentials it received."""
            if credentials:
                return {
                    "scheme": credentials.scheme,
                    "credentials": credentials.credentials,
                    "headers_transformed": True,
                }
            return {"credentials": None, "headers_transformed": False}

        return app

    def test_x_api_key_transformed_to_authorization_bearer(self, simple_app_with_header_transform):
        """Test that X-API-Key header is transformed and visible to HTTPBearer."""
        client = TestClient(simple_app_with_header_transform)

        # Send request with only X-API-Key (no Authorization header)
        response = client.get(
            "/test-headers",
            headers={"X-API-Key": "test-secret-key-123"},
        )

        # Should succeed
        assert response.status_code == 200

        # The endpoint should have received credentials from the transformed Authorization header
        data = response.json()
        assert data["headers_transformed"] is True
        assert data["scheme"] == "Bearer"
        assert data["credentials"] == "test-secret-key-123"

    def test_original_authorization_header_not_modified(self, simple_app_with_header_transform):
        """Test that existing Authorization header is not overwritten."""
        client = TestClient(simple_app_with_header_transform)

        # Send request with Authorization header already present
        response = client.get(
            "/test-headers",
            headers={
                "Authorization": "Bearer original-token-456",
                "X-API-Key": "should-not-be-used",
            },
        )

        # Should succeed
        assert response.status_code == 200

        # Should use the original Authorization header, not the X-API-Key
        data = response.json()
        assert data["credentials"] == "original-token-456"

    def test_no_transformation_without_x_api_key(self, simple_app_with_header_transform):
        """Test that no transformation occurs when X-API-Key is not present."""
        client = TestClient(simple_app_with_header_transform)

        # Send request without X-API-Key or Authorization
        response = client.get("/test-headers")

        # Should succeed but have no credentials
        assert response.status_code == 200
        data = response.json()
        assert data["credentials"] is None


class TestRequestScopeInspection:
    """Test that we can inspect request.scope to verify headers were modified."""

    @pytest.fixture
    def app_with_scope_inspection(self):
        """Create app that exposes request.scope for inspection."""
        app = FastAPI()

        # Mock plugin manager
        mock_plugin_manager = MagicMock()

        async def mock_invoke_hook(hook_type, payload, global_context, local_contexts=None, violations_as_exceptions=False):  # noqa: ARG001
            if hook_type == HttpHookType.HTTP_PRE_REQUEST:
                headers = dict(payload.headers.root)
                if "x-test-header" in headers:
                    headers["x-transformed-header"] = f"transformed-{headers['x-test-header']}"
                    return PluginResult(modified_payload=HttpHeaderPayload(headers), continue_processing=True), {}
            return PluginResult(continue_processing=True), {}

        mock_plugin_manager.invoke_hook = mock_invoke_hook
        app.add_middleware(HttpAuthMiddleware, plugin_manager=mock_plugin_manager)

        @app.get("/inspect-scope")
        async def inspect_scope(request: Request):
            """Return the raw request.scope['headers'] for inspection."""
            # Convert bytes headers back to dict for JSON response
            headers_dict = {}
            for name, value in request.scope["headers"]:
                headers_dict[name.decode()] = value.decode()
            return {"scope_headers": headers_dict, "request_headers": dict(request.headers)}

        return app

    def test_scope_headers_contain_transformed_header(self, app_with_scope_inspection):
        """Test that request.scope['headers'] contains the transformed header."""
        client = TestClient(app_with_scope_inspection)

        response = client.get(
            "/inspect-scope",
            headers={"X-Test-Header": "original-value"},
        )

        assert response.status_code == 200
        data = response.json()

        # Check that both original and transformed headers are in scope
        scope_headers = data["scope_headers"]
        assert "x-test-header" in scope_headers
        assert scope_headers["x-test-header"] == "original-value"
        assert "x-transformed-header" in scope_headers
        assert scope_headers["x-transformed-header"] == "transformed-original-value"

    def test_request_headers_reflect_scope_modifications(self, app_with_scope_inspection):
        """Test that request.headers reflects the scope modifications."""
        client = TestClient(app_with_scope_inspection)

        response = client.get(
            "/inspect-scope",
            headers={"X-Test-Header": "test-123"},
        )

        assert response.status_code == 200
        data = response.json()

        # request.headers should match scope headers
        request_headers = data["request_headers"]
        assert "x-transformed-header" in request_headers
        assert request_headers["x-transformed-header"] == "transformed-test-123"


class TestRequestStateRequestId:
    """Test that request_id is stored in request.state and used consistently."""

    @pytest.fixture
    def app_with_request_id_tracking(self):
        """Create app that tracks request_id."""
        app = FastAPI()

        # Mock plugin manager that records request IDs
        request_ids_seen = []

        mock_plugin_manager = MagicMock()

        async def mock_invoke_hook(hook_type, payload, global_context, local_contexts=None, violations_as_exceptions=False):  # noqa: ARG001
            # Record the request_id from global_context
            request_ids_seen.append(global_context.request_id)
            return PluginResult(continue_processing=True), {}

        mock_plugin_manager.invoke_hook = mock_invoke_hook
        app.add_middleware(HttpAuthMiddleware, plugin_manager=mock_plugin_manager)

        @app.get("/test-request-id")
        async def test_endpoint(request: Request):
            """Return the request_id from request.state."""
            request_id = getattr(request.state, "request_id", None)
            return {
                "request_id_from_state": request_id,
                "request_ids_seen_by_hooks": request_ids_seen.copy(),
            }

        # Store request_ids_seen so we can access it
        app.state.request_ids_seen = request_ids_seen

        return app

    def test_request_id_consistent_across_hooks(self, app_with_request_id_tracking):
        """Test that same request_id is used in all hooks for a single request."""
        client = TestClient(app_with_request_id_tracking)

        # Clear any previous request IDs
        app_with_request_id_tracking.state.request_ids_seen.clear()

        response = client.get("/test-request-id")

        assert response.status_code == 200
        data = response.json()

        # Should have a request_id in state
        assert data["request_id_from_state"] is not None

        # All hooks should have seen the same request_id
        request_ids = data["request_ids_seen_by_hooks"]
        if len(request_ids) > 0:
            assert len(set(request_ids)) == 1, "All hooks should see the same request_id"
            assert request_ids[0] == data["request_id_from_state"], "Hooks should see same request_id as in state"

    def test_different_requests_get_different_ids(self, app_with_request_id_tracking):
        """Test that different requests get different request_ids."""
        client = TestClient(app_with_request_id_tracking)

        # Make first request
        response1 = client.get("/test-request-id")
        data1 = response1.json()
        request_id1 = data1["request_id_from_state"]

        # Clear tracking
        app_with_request_id_tracking.state.request_ids_seen.clear()

        # Make second request
        response2 = client.get("/test-request-id")
        data2 = response2.json()
        request_id2 = data2["request_id_from_state"]

        # Should have different request IDs
        assert request_id1 != request_id2


class TestHeaderMergingBehavior:
    """Test that middleware correctly merges plugin-modified headers with original headers."""

    @pytest.fixture
    def app_with_header_merging(self):
        """Create app that tests header merging behavior in middleware."""
        app = FastAPI()

        # Mock plugin manager that modifies and adds headers
        mock_plugin_manager = MagicMock()

        async def mock_invoke_hook(hook_type, payload, global_context, local_contexts=None, violations_as_exceptions=False):  # noqa: ARG001
            if hook_type == HttpHookType.HTTP_PRE_REQUEST:
                headers = dict(payload.headers.root)
                # Modify existing header and add new header
                headers["x-test"] = "modified-by-plugin"  # Override existing
                headers["x-added-by-plugin"] = "new-value"  # Add new
                return PluginResult(modified_payload=HttpHeaderPayload(headers), continue_processing=True), {}
            return PluginResult(continue_processing=True), {}

        mock_plugin_manager.invoke_hook = mock_invoke_hook
        app.add_middleware(HttpAuthMiddleware, plugin_manager=mock_plugin_manager)

        @app.get("/test-merge")
        async def test_endpoint(request: Request):
            """Return the headers seen by the endpoint."""
            return {"headers": dict(request.headers)}

        return app

    def test_modified_headers_take_precedence(self, app_with_header_merging):
        """Test that plugin-modified headers override original headers in middleware."""
        client = TestClient(app_with_header_merging)

        response = client.get(
            "/test-merge",
            headers={
                "X-Test": "original-value",
                "X-Other": "preserved-value",
            },
        )

        assert response.status_code == 200
        headers = response.json()["headers"]

        # Plugin should override x-test
        assert headers["x-test"] == "modified-by-plugin"
        # Original x-other should be preserved
        assert headers["x-other"] == "preserved-value"

    def test_plugin_adds_new_headers(self, app_with_header_merging):
        """Test that plugins can add new headers alongside existing ones."""
        client = TestClient(app_with_header_merging)

        response = client.get(
            "/test-merge",
            headers={"X-Original": "original-value"},
        )

        assert response.status_code == 200
        headers = response.json()["headers"]

        # Original header should be present
        assert headers["x-original"] == "original-value"
        # Plugin-added header should be present
        assert headers["x-added-by-plugin"] == "new-value"

    def test_headers_converted_to_asgi_format_in_scope(self, app_with_header_merging):
        """Test that middleware properly converts headers to ASGI format (lowercase bytes) in request.scope."""
        app = FastAPI()

        mock_plugin_manager = MagicMock()

        async def mock_invoke_hook(hook_type, payload, global_context, local_contexts=None, violations_as_exceptions=False):  # noqa: ARG001
            if hook_type == HttpHookType.HTTP_PRE_REQUEST:
                headers = dict(payload.headers.root)
                headers["Authorization"] = "Bearer token123"
                headers["X-Custom-Header"] = "CustomValue"
                return PluginResult(modified_payload=HttpHeaderPayload(headers), continue_processing=True), {}
            return PluginResult(continue_processing=True), {}

        mock_plugin_manager.invoke_hook = mock_invoke_hook
        app.add_middleware(HttpAuthMiddleware, plugin_manager=mock_plugin_manager)

        @app.get("/test-asgi-format")
        async def test_endpoint(request: Request):
            """Check ASGI scope headers format."""
            # Check that headers in scope are lowercase bytes tuples
            scope_headers = request.scope["headers"]
            headers_dict = {name.decode(): value.decode() for name, value in scope_headers}
            return {"scope_headers_lowercase": all(name == name.lower() for name, _ in scope_headers), "headers": headers_dict}

        client = TestClient(app)
        response = client.get("/test-asgi-format")

        assert response.status_code == 200
        data = response.json()

        # All header names in scope should be lowercase
        assert data["scope_headers_lowercase"] is True

        # Headers should be accessible and properly formatted
        assert "authorization" in data["headers"]
        assert data["headers"]["authorization"] == "Bearer token123"
        assert "x-custom-header" in data["headers"]
        assert data["headers"]["x-custom-header"] == "CustomValue"
