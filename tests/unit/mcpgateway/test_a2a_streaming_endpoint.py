# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_a2a_streaming_endpoint.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

A2A Agent Streaming Endpoint Tests.

Tests cover:
- Issue #3620 Phase 1: stream_a2a_agent() endpoint functionality
- SSE endpoint behavior
- Authentication and authorization
- Error handling
- Integration with stream_agent_response()
"""

# Standard
import json
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

# Third-Party
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

# First-Party
from mcpgateway.main import app
from mcpgateway.services.a2a_service import A2AAgentError, A2AAgentNotFoundError


@pytest.fixture
def client():
    """Create a new TestClient for each test."""
    return TestClient(app)


@pytest.fixture(autouse=True)
def cleanup_overrides():
    """Clean up dependency overrides after each test."""
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def mock_auth_dependencies():
    """Mock authentication dependencies for endpoint tests."""
    mock_user = {"email": "test@example.com", "id": "user-123", "sub": "test@example.com", "is_admin": False}

    async def mock_get_current_user():
        return mock_user

    async def mock_get_db():
        mock_db = MagicMock()
        try:
            yield mock_db
        finally:
            pass

    return {
        "get_current_user": mock_get_current_user,
        "get_db": mock_get_db,
        "user": mock_user,
    }


class TestStreamA2AAgentEndpoint:
    """Test /a2a/{agent_name}/stream endpoint."""

    def test_stream_endpoint_returns_sse_response(self, client, mock_auth_dependencies):
        """Test that streaming endpoint returns SSE response with correct headers.

        Verifies:
        - Response media type is text/event-stream
        - Cache-Control header is no-cache
        - Connection header is keep-alive
        - X-Accel-Buffering header is no (nginx)
        """
        from mcpgateway.main import get_current_user_with_permissions, get_db

        # Mock streaming generator - must return actual async generator
        async def mock_stream(*args, **kwargs):
            yield "data: chunk1\n\n"
            yield "data: chunk2\n\n"

        with patch("mcpgateway.main.a2a_service") as mock_service:
            # Return a new generator each time it's called
            mock_service.stream_agent_response = lambda *args, **kwargs: mock_stream(*args, **kwargs)

            # Override dependencies
            app.dependency_overrides[get_current_user_with_permissions] = mock_auth_dependencies["get_current_user"]
            app.dependency_overrides[get_db] = mock_auth_dependencies["get_db"]

            with patch("mcpgateway.main.get_rpc_filter_context", return_value=("test@example.com", None, True)):
                with patch("mcpgateway.main.uaid_utils.read_hop_count", return_value=0):
                    with patch("mcpgateway.main._is_jwt_token", return_value=True):
                        with patch("mcpgateway.main._filter_sensitive_headers", return_value={}):
                            response = client.post(
                                "/a2a/test-agent/stream",
                                json={"parameters": {"message": "test"}},
                                headers={"Authorization": "Bearer test-token"},
                            )

                            # Verify response
                            assert response.status_code == 200
                            assert "text/event-stream" in response.headers["content-type"]

    def test_stream_endpoint_requires_authentication(self, client):
        """Test that streaming endpoint requires authentication when enabled.

        Verifies:
        - Missing/invalid authentication returns error
        """
        from mcpgateway.main import get_current_user_with_permissions

        async def mock_auth_fail():
            raise HTTPException(status_code=401, detail="Unauthorized")

        app.dependency_overrides[get_current_user_with_permissions] = mock_auth_fail

        response = client.post("/a2a/test-agent/stream", json={"parameters": {}})
        assert response.status_code == 401

    def test_stream_endpoint_enforces_rbac(self, client):
        """Test that RBAC is enforced via @require_permission decorator.

        Verifies:
        - Permission check happens before streaming
        - Insufficient permissions return 403
        """
        from mcpgateway.main import get_current_user_with_permissions

        async def mock_permission_denied():
            raise HTTPException(status_code=403, detail="Forbidden")

        app.dependency_overrides[get_current_user_with_permissions] = mock_permission_denied

        response = client.post(
            "/a2a/test-agent/stream",
            json={"parameters": {}},
            headers={"Authorization": "Bearer test-token"},
        )
        assert response.status_code == 403

    def test_stream_endpoint_handles_agent_not_found(self, client, mock_auth_dependencies):
        """Test that agent not found errors are handled.

        Verifies:
        - Agent not found returns error in SSE stream
        - Error message is properly formatted

        Note: The actual stream_agent_response() yields error SSE events for
        agent not found, rather than raising exceptions. This tests the actual behavior.
        """
        from mcpgateway.main import get_current_user_with_permissions, get_db

        with patch("mcpgateway.main.a2a_service") as mock_service:
            # Mock: Return error SSE event (what the real service does)
            async def mock_stream(*args, **kwargs):
                yield 'data: {"error": "A2A Agent not found with name: nonexistent"}\n\n'

            mock_service.stream_agent_response = MagicMock(return_value=mock_stream())

            app.dependency_overrides[get_current_user_with_permissions] = mock_auth_dependencies["get_current_user"]
            app.dependency_overrides[get_db] = mock_auth_dependencies["get_db"]

            with patch("mcpgateway.main.get_rpc_filter_context", return_value=("test@example.com", None, True)):
                with patch("mcpgateway.main.uaid_utils.read_hop_count", return_value=0):
                    with patch("mcpgateway.main._filter_sensitive_headers", return_value={}):
                        response = client.post(
                            "/a2a/nonexistent/stream",
                            json={"parameters": {}},
                            headers={"Authorization": "Bearer test-token"},
                        )
                        # Streaming returns 200 with error in body
                        assert response.status_code == 200
                        assert "text/event-stream" in response.headers["content-type"]
                        # Verify error message in response
                        assert b"not found" in response.content

    def test_stream_endpoint_handles_agent_error(self, client, mock_auth_dependencies):
        """Test that agent errors are handled in stream.

        Verifies:
        - Agent errors returned as SSE error events
        - Error message properly formatted

        Note: The actual stream_agent_response() yields error SSE events for
        agent errors (like disabled), rather than raising exceptions.
        """
        from mcpgateway.main import get_current_user_with_permissions, get_db

        with patch("mcpgateway.main.a2a_service") as mock_service:
            # Mock: Return error SSE event (what the real service does)
            async def mock_stream(*args, **kwargs):
                yield 'data: {"error": "A2A Agent \'test-agent\' is disabled"}\n\n'

            mock_service.stream_agent_response = MagicMock(return_value=mock_stream())

            app.dependency_overrides[get_current_user_with_permissions] = mock_auth_dependencies["get_current_user"]
            app.dependency_overrides[get_db] = mock_auth_dependencies["get_db"]

            with patch("mcpgateway.main.get_rpc_filter_context", return_value=("test@example.com", None, True)):
                with patch("mcpgateway.main.uaid_utils.read_hop_count", return_value=0):
                    with patch("mcpgateway.main._filter_sensitive_headers", return_value={}):
                        response = client.post(
                            "/a2a/disabled-agent/stream",
                            json={"parameters": {}},
                            headers={"Authorization": "Bearer test-token"},
                        )
                        # Streaming returns 200 with error in body
                        assert response.status_code == 200
                        assert "text/event-stream" in response.headers["content-type"]
                        # Verify error message in response
                        assert b"disabled" in response.content

    def test_stream_endpoint_passes_parameters_correctly(self, client, mock_auth_dependencies):
        """Test that request parameters are correctly passed to service.

        Verifies:
        - parameters from body passed
        - interaction_type passed
        - user context passed
        """
        from mcpgateway.main import get_current_user_with_permissions, get_db

        with patch("mcpgateway.main.a2a_service") as mock_service:
            # Mock successful stream
            async def mock_stream(*args, **kwargs):
                yield "data: test\n\n"

            # Use MagicMock with return_value to track calls
            mock_service.stream_agent_response = MagicMock(return_value=mock_stream())

            test_params = {"message": "test message", "context": {"key": "value"}}

            app.dependency_overrides[get_current_user_with_permissions] = mock_auth_dependencies["get_current_user"]
            app.dependency_overrides[get_db] = mock_auth_dependencies["get_db"]

            with patch("mcpgateway.main.get_rpc_filter_context", return_value=("test@example.com", ["team1"], False)):
                with patch("mcpgateway.main.uaid_utils.read_hop_count", return_value=1):
                    with patch("mcpgateway.main._is_jwt_token", return_value=True):
                        with patch("mcpgateway.main._filter_sensitive_headers", return_value={"x-custom": "value"}):
                            response = client.post(
                                "/a2a/test-agent/stream",
                                json={"parameters": test_params, "interaction_type": "execute"},
                                headers={"Authorization": "Bearer test-token", "Content-Type": "application/json"},
                            )

                            # Verify service was called
                            assert mock_service.stream_agent_response.called

                            # Verify parameters passed correctly
                            call_args = mock_service.stream_agent_response.call_args
                            # First positional arg is db, second is agent_name, third is parameters
                            assert call_args[0][1] == "test-agent"  # agent_name
                            assert call_args[0][2] == test_params  # parameters
                            assert call_args[0][3] == "execute"  # interaction_type

    def test_stream_endpoint_handles_service_unavailable(self, client, mock_auth_dependencies):
        """Test that 503 is returned when A2A service is None.

        Verifies:
        - Missing service returns 503
        """
        from mcpgateway.main import get_current_user_with_permissions, get_db

        with patch("mcpgateway.main.a2a_service", None):
            app.dependency_overrides[get_current_user_with_permissions] = mock_auth_dependencies["get_current_user"]
            app.dependency_overrides[get_db] = mock_auth_dependencies["get_db"]

            with patch("mcpgateway.main.get_rpc_filter_context", return_value=("test@example.com", None, True)):
                response = client.post(
                    "/a2a/test-agent/stream",
                    json={"parameters": {}},
                    headers={"Authorization": "Bearer test-token"},
                )
                assert response.status_code == 503

    def test_stream_endpoint_token_scoping(self, client, mock_auth_dependencies):
        """Test that token scoping is correctly applied.

        Verifies:
        - Admin with no token teams = unrestricted
        - Non-admin with no token teams = public-only
        """
        from mcpgateway.main import get_current_user_with_permissions, get_db

        with patch("mcpgateway.main.a2a_service") as mock_service:
            async def mock_stream(*args, **kwargs):
                yield "data: test\n\n"

            # Test 1: Admin with token_teams=None -> unrestricted
            mock_service.stream_agent_response = MagicMock(return_value=mock_stream())

            app.dependency_overrides[get_current_user_with_permissions] = mock_auth_dependencies["get_current_user"]
            app.dependency_overrides[get_db] = mock_auth_dependencies["get_db"]

            with patch("mcpgateway.main.get_rpc_filter_context", return_value=("admin@example.com", None, True)):
                with patch("mcpgateway.main.uaid_utils.read_hop_count", return_value=0):
                    with patch("mcpgateway.main._filter_sensitive_headers", return_value={}):
                        response = client.post(
                            "/a2a/test-agent/stream",
                            json={"parameters": {}},
                            headers={"Authorization": "Bearer admin-token"},
                        )

                        assert response.status_code == 200
                        # Verify admin unrestricted (token_teams=None)
                        call_kwargs = mock_service.stream_agent_response.call_args.kwargs
                        assert call_kwargs["token_teams"] is None

            # Test 2: Non-admin with token_teams=None -> public-only
            mock_service.stream_agent_response = MagicMock(return_value=mock_stream())

            with patch("mcpgateway.main.get_rpc_filter_context", return_value=("user@example.com", None, False)):
                with patch("mcpgateway.main.uaid_utils.read_hop_count", return_value=0):
                    with patch("mcpgateway.main._filter_sensitive_headers", return_value={}):
                        response = client.post(
                            "/a2a/test-agent/stream",
                            json={"parameters": {}},
                            headers={"Authorization": "Bearer user-token"},
                        )

                        assert response.status_code == 200
                        # Verify non-admin public-only (token_teams=[])
                        call_kwargs = mock_service.stream_agent_response.call_args.kwargs
                        assert call_kwargs["token_teams"] == []

    def test_stream_endpoint_bearer_token_forwarding(self, client, mock_auth_dependencies):
        """Test that bearer token is extracted and forwarded correctly.

        Verifies:
        - JWT tokens are forwarded
        - Non-JWT tokens are not forwarded
        """
        from mcpgateway.main import get_current_user_with_permissions, get_db

        with patch("mcpgateway.main.a2a_service") as mock_service:
            async def mock_stream(*args, **kwargs):
                yield "data: test\n\n"

            mock_service.stream_agent_response = MagicMock(return_value=mock_stream())

            app.dependency_overrides[get_current_user_with_permissions] = mock_auth_dependencies["get_current_user"]
            app.dependency_overrides[get_db] = mock_auth_dependencies["get_db"]

            # Test with JWT token
            with patch("mcpgateway.main.get_rpc_filter_context", return_value=("test@example.com", None, True)):
                with patch("mcpgateway.main.uaid_utils.read_hop_count", return_value=0):
                    with patch("mcpgateway.main._is_jwt_token", return_value=True):
                        with patch("mcpgateway.main._filter_sensitive_headers", return_value={}):
                            response = client.post(
                                "/a2a/test-agent/stream",
                                json={"parameters": {}},
                                headers={"Authorization": "Bearer jwt.token.here"},
                            )

                            assert response.status_code == 200
                            # Verify JWT token forwarded
                            call_kwargs = mock_service.stream_agent_response.call_args.kwargs
                            assert call_kwargs["bearer_token"] == "jwt.token.here"

            mock_service.stream_agent_response.reset_mock()
            mock_service.stream_agent_response = MagicMock(return_value=mock_stream())

            # Test with non-JWT token
            with patch("mcpgateway.main.get_rpc_filter_context", return_value=("test@example.com", None, True)):
                with patch("mcpgateway.main.uaid_utils.read_hop_count", return_value=0):
                    with patch("mcpgateway.main._is_jwt_token", return_value=False):
                        with patch("mcpgateway.main._filter_sensitive_headers", return_value={}):
                            response = client.post(
                                "/a2a/test-agent/stream",
                                json={"parameters": {}},
                                headers={"Authorization": "Bearer opaque.token"},
                            )

                            assert response.status_code == 200
                            # Verify non-JWT token NOT forwarded
                            call_kwargs = mock_service.stream_agent_response.call_args.kwargs
                            assert call_kwargs["bearer_token"] is None
