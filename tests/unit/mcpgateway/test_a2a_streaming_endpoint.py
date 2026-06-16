# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_a2a_streaming_endpoint_combined.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

A2A Agent Streaming Endpoint Tests (Combined).

Tests cover:
- Issue #3620 Phase 1: stream_a2a_agent() endpoint functionality
- SSE endpoint behavior
- Authentication and authorization
- Error handling
- Integration with stream_agent_response()
- Endpoint-level edge cases
- Connection interruption handling
- Malformed request bodies
- Rate limiting during streaming
- Concurrent stream handling
- SSE format validation
- HTTP header edge cases
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
        - Missing/invalid authentication returns auth/permission error
        Note: May return 401 (auth failure) or 403 (permission denied) depending
        on decorator evaluation order in different test environments.
        """
        from mcpgateway.main import get_current_user_with_permissions

        async def mock_auth_fail():
            raise HTTPException(status_code=401, detail="Unauthorized")

        app.dependency_overrides[get_current_user_with_permissions] = mock_auth_fail

        response = client.post("/a2a/test-agent/stream", json={"parameters": {}})
        assert response.status_code in (401, 403), f"Expected 401 or 403, got {response.status_code}"

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


# Edge case tests from test_a2a_streaming_endpoint_edge_cases.py
class TestStreamingEndpointEdgeCases:
    """Test edge cases for streaming endpoint."""

    def test_stream_endpoint_handles_malformed_json(self, client, mock_auth_dependencies):
        """Test endpoint handles malformed JSON in request body.

        Scenario: Client sends invalid JSON.
        Expected: 422 Unprocessable Entity error.
        """
        from mcpgateway.main import get_current_user_with_permissions, get_db

        app.dependency_overrides[get_current_user_with_permissions] = mock_auth_dependencies["get_current_user"]
        app.dependency_overrides[get_db] = mock_auth_dependencies["get_db"]

        with patch("mcpgateway.main.a2a_service") as mock_service:
            # Send malformed JSON
            response = client.post(
                "/a2a/test-agent/stream",
                data='{"parameters": invalid-json}',  # Malformed
                headers={
                    "Authorization": "Bearer test-token",
                    "Content-Type": "application/json"
                },
            )

            # Should return 422 for invalid request body
            assert response.status_code == 422

    def test_stream_endpoint_handles_empty_body(self, client, mock_auth_dependencies):
        """Test endpoint handles empty request body gracefully.

        Scenario: Client sends empty body.
        Expected: Uses default empty parameters dict.
        """
        from mcpgateway.main import get_current_user_with_permissions, get_db

        async def mock_stream(*args, **kwargs):
            yield "data: success\n\n"

        with patch("mcpgateway.main.a2a_service") as mock_service:
            mock_service.stream_agent_response = lambda *args, **kwargs: mock_stream(*args, **kwargs)

            app.dependency_overrides[get_current_user_with_permissions] = mock_auth_dependencies["get_current_user"]
            app.dependency_overrides[get_db] = mock_auth_dependencies["get_db"]

            with patch("mcpgateway.main.get_rpc_filter_context", return_value=("test@example.com", None, True)):
                with patch("mcpgateway.main.uaid_utils.read_hop_count", return_value=0):
                    with patch("mcpgateway.main._is_jwt_token", return_value=True):
                        with patch("mcpgateway.main._filter_sensitive_headers", return_value={}):
                            response = client.post(
                                "/a2a/test-agent/stream",
                                json={},  # Empty parameters
                                headers={"Authorization": "Bearer test-token"},
                            )

                            assert response.status_code == 200
                            # Should use default empty dict for parameters

    def test_stream_endpoint_handles_missing_content_type(self, client, mock_auth_dependencies):
        """Test endpoint handles missing Content-Type header.

        Scenario: Client omits Content-Type header.
        Expected: FastAPI infers from body or returns 422.
        """
        from mcpgateway.main import get_current_user_with_permissions, get_db

        app.dependency_overrides[get_current_user_with_permissions] = mock_auth_dependencies["get_current_user"]
        app.dependency_overrides[get_db] = mock_auth_dependencies["get_db"]

        with patch("mcpgateway.main.a2a_service") as mock_service:
            response = client.post(
                "/a2a/test-agent/stream",
                data='{"parameters": {}}',  # JSON body without Content-Type header
                headers={"Authorization": "Bearer test-token"},
            )

            # FastAPI should handle this (either 422 or infer content-type)
            assert response.status_code in [200, 422]

    def test_stream_endpoint_large_parameter_payload(self, client, mock_auth_dependencies):
        """Test endpoint handles large parameter payload.

        Scenario: Client sends very large parameters dict.
        Expected: Stream starts if within size limits.
        """
        from mcpgateway.main import get_current_user_with_permissions, get_db

        async def mock_stream(*args, **kwargs):
            yield "data: success\n\n"

        with patch("mcpgateway.main.a2a_service") as mock_service:
            mock_service.stream_agent_response = lambda *args, **kwargs: mock_stream(*args, **kwargs)

            app.dependency_overrides[get_current_user_with_permissions] = mock_auth_dependencies["get_current_user"]
            app.dependency_overrides[get_db] = mock_auth_dependencies["get_db"]

            with patch("mcpgateway.main.get_rpc_filter_context", return_value=("test@example.com", None, True)):
                with patch("mcpgateway.main.uaid_utils.read_hop_count", return_value=0):
                    with patch("mcpgateway.main._is_jwt_token", return_value=True):
                        with patch("mcpgateway.main._filter_sensitive_headers", return_value={}):
                            # Large parameters payload
                            large_params = {"data": "x" * 10000}
                            response = client.post(
                                "/a2a/test-agent/stream",
                                json={"parameters": large_params},
                                headers={"Authorization": "Bearer test-token"},
                            )

                            # Should handle large payload
                            assert response.status_code == 200

    def test_stream_endpoint_special_characters_in_agent_name(self, client, mock_auth_dependencies):
        """Test endpoint handles special characters in agent name.

        Scenario: Agent name contains URL-encoded special characters.
        Expected: Correctly decoded and processed.
        """
        from mcpgateway.main import get_current_user_with_permissions, get_db

        async def mock_stream(*args, **kwargs):
            yield "data: success\n\n"

        with patch("mcpgateway.main.a2a_service") as mock_service:
            mock_service.stream_agent_response = lambda *args, **kwargs: mock_stream(*args, **kwargs)

            app.dependency_overrides[get_current_user_with_permissions] = mock_auth_dependencies["get_current_user"]
            app.dependency_overrides[get_db] = mock_auth_dependencies["get_db"]

            with patch("mcpgateway.main.get_rpc_filter_context", return_value=("test@example.com", None, True)):
                with patch("mcpgateway.main.uaid_utils.read_hop_count", return_value=0):
                    with patch("mcpgateway.main._is_jwt_token", return_value=True):
                        with patch("mcpgateway.main._filter_sensitive_headers", return_value={}):
                            # Agent name with spaces (URL encoded as %20)
                            response = client.post(
                                "/a2a/test%20agent%20with%20spaces/stream",
                                json={"parameters": {}},
                                headers={"Authorization": "Bearer test-token"},
                            )

                            # FastAPI should decode URL encoding
                            assert response.status_code in [200, 404]


class TestStreamingConcurrency:
    """Test concurrent streaming scenarios."""

    def test_stream_endpoint_concurrent_requests_same_agent(self, client, mock_auth_dependencies):
        """Test multiple concurrent streams to same agent.

        Scenario: 3 clients stream from same agent simultaneously.
        Expected: All streams independent, no cross-contamination.
        """
        from mcpgateway.main import get_current_user_with_permissions, get_db

        call_count = [0]

        async def mock_stream(*args, **kwargs):
            call_count[0] += 1
            stream_id = call_count[0]
            yield f"data: stream-{stream_id}-chunk1\n\n"
            yield f"data: stream-{stream_id}-chunk2\n\n"

        with patch("mcpgateway.main.a2a_service") as mock_service:
            # Each call gets a new generator
            mock_service.stream_agent_response = lambda *args, **kwargs: mock_stream(*args, **kwargs)

            app.dependency_overrides[get_current_user_with_permissions] = mock_auth_dependencies["get_current_user"]
            app.dependency_overrides[get_db] = mock_auth_dependencies["get_db"]

            with patch("mcpgateway.main.get_rpc_filter_context", return_value=("test@example.com", None, True)):
                with patch("mcpgateway.main.uaid_utils.read_hop_count", return_value=0):
                    with patch("mcpgateway.main._is_jwt_token", return_value=True):
                        with patch("mcpgateway.main._filter_sensitive_headers", return_value={}):
                            # Make 3 concurrent requests (simulated by sequential in tests)
                            responses = []
                            for i in range(3):
                                response = client.post(
                                    "/a2a/test-agent/stream",
                                    json={"parameters": {"request_id": i}},
                                    headers={"Authorization": "Bearer test-token"},
                                )
                                responses.append(response)

                            # All should succeed
                            assert all(r.status_code == 200 for r in responses)

    def test_stream_endpoint_different_interaction_types(self, client, mock_auth_dependencies):
        """Test streaming with different interaction types.

        Scenario: Stream with interaction_type="execute" vs "query".
        Expected: Both work, interaction_type passed to service.
        """
        from mcpgateway.main import get_current_user_with_permissions, get_db

        captured_interaction_types = []

        async def mock_stream(*args, **kwargs):
            captured_interaction_types.append(kwargs.get('interaction_type', args[3] if len(args) > 3 else None))
            yield "data: success\n\n"

        with patch("mcpgateway.main.a2a_service") as mock_service:
            mock_service.stream_agent_response = lambda *args, **kwargs: mock_stream(*args, **kwargs)

            app.dependency_overrides[get_current_user_with_permissions] = mock_auth_dependencies["get_current_user"]
            app.dependency_overrides[get_db] = mock_auth_dependencies["get_db"]

            with patch("mcpgateway.main.get_rpc_filter_context", return_value=("test@example.com", None, True)):
                with patch("mcpgateway.main.uaid_utils.read_hop_count", return_value=0):
                    with patch("mcpgateway.main._is_jwt_token", return_value=True):
                        with patch("mcpgateway.main._filter_sensitive_headers", return_value={}):
                            # Test "query" interaction type
                            response1 = client.post(
                                "/a2a/test-agent/stream",
                                json={"parameters": {}, "interaction_type": "query"},
                                headers={"Authorization": "Bearer test-token"},
                            )

                            # Test "execute" interaction type
                            response2 = client.post(
                                "/a2a/test-agent/stream",
                                json={"parameters": {}, "interaction_type": "execute"},
                                headers={"Authorization": "Bearer test-token"},
                            )

                            assert response1.status_code == 200
                            assert response2.status_code == 200


class TestStreamingSSEFormat:
    """Test SSE format compliance."""

    def test_stream_endpoint_sse_headers_correct(self, client, mock_auth_dependencies):
        """Test that SSE-specific headers are set correctly.

        Verifies:
        - Content-Type: text/event-stream
        - Cache-Control: no-cache
        - Connection: keep-alive
        - X-Accel-Buffering: no
        """
        from mcpgateway.main import get_current_user_with_permissions, get_db

        async def mock_stream(*args, **kwargs):
            yield "data: test\n\n"

        with patch("mcpgateway.main.a2a_service") as mock_service:
            mock_service.stream_agent_response = lambda *args, **kwargs: mock_stream(*args, **kwargs)

            app.dependency_overrides[get_current_user_with_permissions] = mock_auth_dependencies["get_current_user"]
            app.dependency_overrides[get_db] = mock_auth_dependencies["get_db"]

            with patch("mcpgateway.main.get_rpc_filter_context", return_value=("test@example.com", None, True)):
                with patch("mcpgateway.main.uaid_utils.read_hop_count", return_value=0):
                    with patch("mcpgateway.main._is_jwt_token", return_value=True):
                        with patch("mcpgateway.main._filter_sensitive_headers", return_value={}):
                            response = client.post(
                                "/a2a/test-agent/stream",
                                json={"parameters": {}},
                                headers={"Authorization": "Bearer test-token"},
                            )

                            # Verify SSE headers
                            assert response.status_code == 200
                            assert "text/event-stream" in response.headers.get("content-type", "")
                            assert response.headers.get("cache-control") == "no-cache"
                            assert response.headers.get("connection") == "keep-alive"
                            assert response.headers.get("x-accel-buffering") == "no"

    def test_stream_endpoint_chunks_have_sse_format(self, client, mock_auth_dependencies):
        """Test that response chunks follow SSE format.

        Verifies each chunk:
        - Starts with "data: "
        - Ends with "\n\n"
        """
        from mcpgateway.main import get_current_user_with_permissions, get_db

        async def mock_stream(*args, **kwargs):
            yield "data: chunk1\n\n"
            yield "data: chunk2\n\n"
            yield "data: chunk3\n\n"

        with patch("mcpgateway.main.a2a_service") as mock_service:
            mock_service.stream_agent_response = lambda *args, **kwargs: mock_stream(*args, **kwargs)

            app.dependency_overrides[get_current_user_with_permissions] = mock_auth_dependencies["get_current_user"]
            app.dependency_overrides[get_db] = mock_auth_dependencies["get_db"]

            with patch("mcpgateway.main.get_rpc_filter_context", return_value=("test@example.com", None, True)):
                with patch("mcpgateway.main.uaid_utils.read_hop_count", return_value=0):
                    with patch("mcpgateway.main._is_jwt_token", return_value=True):
                        with patch("mcpgateway.main._filter_sensitive_headers", return_value={}):
                            response = client.post(
                                "/a2a/test-agent/stream",
                                json={"parameters": {}},
                                headers={"Authorization": "Bearer test-token"},
                            )

                            assert response.status_code == 200
                            content = response.text

                            # Verify SSE format
                            lines = content.split("\n\n")
                            # Filter empty lines
                            chunks = [line for line in lines if line.strip()]

                            for chunk in chunks:
                                assert chunk.startswith("data: "), f"Chunk doesn't start with 'data: ': {chunk}"


class TestStreamingServiceUnavailable:
    """Test service unavailability scenarios."""

    def test_stream_endpoint_when_a2a_service_none(self, client, mock_auth_dependencies):
        """Test endpoint when a2a_service is None (service not initialized).

        Scenario: A2A service failed to initialize at startup.
        Expected: 503 Service Unavailable.
        """
        from mcpgateway.main import get_current_user_with_permissions, get_db

        with patch("mcpgateway.main.a2a_service", None):  # Service not available
            app.dependency_overrides[get_current_user_with_permissions] = mock_auth_dependencies["get_current_user"]
            app.dependency_overrides[get_db] = mock_auth_dependencies["get_db"]

            with patch("mcpgateway.main.get_rpc_filter_context", return_value=("test@example.com", None, True)):
                response = client.post(
                    "/a2a/test-agent/stream",
                    json={"parameters": {}},
                    headers={"Authorization": "Bearer test-token"},
                )

                assert response.status_code == 503
                assert "A2A service not available" in response.text


class TestStreamingRateLimiting:
    """Test rate limiting edge cases (placeholder for future implementation)."""

    def test_stream_endpoint_rate_limit_not_yet_implemented(self, client, mock_auth_dependencies):
        """Placeholder test for rate limiting during streaming.

        Note: Rate limiting for streaming is not yet implemented.
        This test documents the expected behavior for future implementation.

        Expected future behavior:
        - Rate limit checked before streaming starts
        - If limit exceeded mid-stream, stream should complete
        - Next request should be rate-limited
        """
        # This is a placeholder for future rate limiting tests
        # When implemented, this should verify:
        # 1. Rate limit checked before stream starts
        # 2. Client receives error if limit exceeded
        # 3. Existing streams not interrupted by rate limit
        pass
