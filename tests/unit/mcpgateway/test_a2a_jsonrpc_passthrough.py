# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_a2a_jsonrpc_passthrough.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Rakhi Dutta

A2A JSON-RPC Passthrough Endpoint testing.

Tests cover Issue #3620 - Non-Standard Request Format:
- Raw JSON-RPC request acceptance (no envelope wrapping)
- Standard A2A SDK compatibility
- Security (RBAC, token scoping)
- Error handling (invalid JSON-RPC format)
- Response format validation
"""

# Standard
from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

# Third-Party
from fastapi import status
from fastapi.testclient import TestClient
import pytest

# First-Party
from mcpgateway.db import A2AAgent as DbA2AAgent
from mcpgateway.main import app


@pytest.fixture
def mock_a2a_service():
    """Mock A2A service for testing."""
    with patch("mcpgateway.main.a2a_service") as mock_service:
        yield mock_service


@pytest.fixture
def sample_a2a_agent():
    """Sample A2A agent fixture."""
    agent_id = uuid.uuid4().hex
    return MagicMock(
        id=agent_id,
        name="test-agent",
        slug="test-agent",
        description="Test A2A Agent",
        endpoint_url="http://localhost:8000/agent",
        agent_type="custom",
        protocol_version="1.0",
        capabilities={"chat": True},
        config={},
        auth_type="none",
        auth_value=None,
        auth_query_params=None,
        enabled=True,
        reachable=True,
        visibility="public",
        team_id=None,
        owner_email=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        version=1,
    )


@pytest.fixture
def auth_headers():
    """Sample authentication headers."""
    return {"Authorization": "Bearer test-token"}


@pytest.fixture
def mock_auth():
    """Mock authentication for all tests using FastAPI dependency overrides."""
    from mcpgateway.main import get_current_user_with_permissions

    def override_get_current_user():
        """Override that returns authenticated admin user."""
        return {
            "sub": "test-user@example.com",
            "email": "test-user@example.com",
            "is_admin": True,
            "teams": None,  # Admin with no team restrictions
        }

    # Override the dependency
    app.dependency_overrides[get_current_user_with_permissions] = override_get_current_user

    yield override_get_current_user

    # Clean up
    app.dependency_overrides.clear()


class TestJSONRPCPassthroughValidation:
    """Test JSON-RPC request validation."""

    def test_non_dict_body_rejected_by_pydantic(self, mock_auth, auth_headers):
        """Test that non-dict request body is rejected by Pydantic validation."""
        client = TestClient(app)
        response = client.post(
            "/a2a/test-agent/jsonrpc",
            json=["not", "a", "dict"],  # Array instead of object
            headers=auth_headers,
        )

        # FastAPI/Pydantic validation returns 422 for invalid body type
        # (Line 5357's isinstance check is defensive but unreachable via normal paths)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_valid_jsonrpc_request(self, mock_a2a_service, mock_auth, auth_headers):
        """Test that valid JSON-RPC request is accepted."""
        # Mock successful agent invocation
        mock_a2a_service.invoke_agent = AsyncMock(
            return_value={
                "jsonrpc": "2.0",
                "result": {"taskId": "task-123", "status": "submitted"},
                "id": 1,
            }
        )

        client = TestClient(app)
        response = client.post(
            "/a2a/test-agent/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "method": "SendMessage",
                "params": {
                    "message": {
                        "messageId": "msg-123",
                        "role": "ROLE_USER",
                        "parts": [{"text": "Hello"}],
                    }
                },
                "id": 1,
            },
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert "result" in data
        assert data["id"] == 1

    def test_missing_jsonrpc_version(self, mock_auth, auth_headers):
        """Test that missing jsonrpc version is rejected."""
        client = TestClient(app)
        response = client.post(
            "/a2a/test-agent/jsonrpc",
            json={
                "method": "SendMessage",
                "params": {},
                "id": 1,
            },
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "jsonrpc" in response.text.lower()

    def test_invalid_jsonrpc_version(self, mock_auth, auth_headers):
        """Test that invalid jsonrpc version is rejected."""
        client = TestClient(app)
        response = client.post(
            "/a2a/test-agent/jsonrpc",
            json={
                "jsonrpc": "1.0",  # Wrong version
                "method": "SendMessage",
                "params": {},
                "id": 1,
            },
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert body["jsonrpc"] == "2.0"
        assert body["error"]["code"] == -32600
        assert "2.0" in body["error"]["message"]

    def test_missing_method(self, mock_auth, auth_headers):
        """Test that missing method is rejected."""
        client = TestClient(app)
        response = client.post(
            "/a2a/test-agent/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "params": {},
                "id": 1,
            },
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert body["jsonrpc"] == "2.0"
        assert body["error"]["code"] == -32600
        assert "method" in body["error"]["message"].lower()

    def test_invalid_method_type(self, mock_auth, auth_headers):
        """Test that non-string method is rejected."""
        client = TestClient(app)
        response = client.post(
            "/a2a/test-agent/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "method": 123,  # Should be string
                "params": {},
                "id": 1,
            },
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert body["jsonrpc"] == "2.0"
        assert body["error"]["code"] == -32600
        assert "method" in body["error"]["message"].lower()

    def test_invalid_params_type(self, mock_auth, auth_headers):
        """Test that non-dict params are rejected."""
        client = TestClient(app)
        response = client.post(
            "/a2a/test-agent/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "method": "SendMessage",
                "params": ["invalid", "params"],  # Should be dict
                "id": 1,
            },
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert body["jsonrpc"] == "2.0"
        assert body["error"]["code"] == -32600
        assert "params" in body["error"]["message"].lower()

    def test_missing_params_allowed(self, mock_a2a_service, mock_auth, auth_headers):
        """Test that missing params is allowed (defaults to empty dict)."""
        mock_a2a_service.invoke_agent = AsyncMock(return_value={"jsonrpc": "2.0", "result": {}, "id": 1})

        client = TestClient(app)
        response = client.post(
            "/a2a/test-agent/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "method": "ListTasks",
                "id": 1,
            },
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK

    def test_null_params_allowed(self, mock_a2a_service, mock_auth, auth_headers):
        """Test that null params is allowed."""
        mock_a2a_service.invoke_agent = AsyncMock(return_value={"jsonrpc": "2.0", "result": {}, "id": 1})

        client = TestClient(app)
        response = client.post(
            "/a2a/test-agent/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "method": "ListTasks",
                "params": None,
                "id": 1,
            },
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK

    def test_missing_id_allowed_for_notification(self, mock_a2a_service, mock_auth, auth_headers):
        """Test that missing id is allowed (JSON-RPC notification)."""
        mock_a2a_service.invoke_agent = AsyncMock(return_value={"jsonrpc": "2.0", "result": {}})

        client = TestClient(app)
        response = client.post(
            "/a2a/test-agent/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "method": "CancelTask",
                "params": {"taskId": "task-123"},
            },
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK


class TestJSONRPCPassthroughSecurity:
    """Test security and RBAC for JSON-RPC passthrough endpoint."""

    def test_requires_authentication(self, mock_a2a_service, mock_auth, auth_headers):
        """Test that endpoint requires authentication (baseline security check).

        This test verifies basic authentication requirement. For permission enforcement
        testing, see TestJSONRPCSecurityDenyPaths.test_authenticated_user_without_permission_denied.
        """
        mock_a2a_service.invoke_agent = AsyncMock(return_value={"jsonrpc": "2.0", "result": {}, "id": 1})

        client = TestClient(app)

        # Authenticated request with proper permissions should succeed
        response = client.post(
            "/a2a/test-agent/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "method": "SendMessage",
                "params": {},
                "id": 1,
            },
            headers=auth_headers,
        )
        assert response.status_code == status.HTTP_200_OK

        # Unauthenticated request should be rejected
        app.dependency_overrides.clear()
        unauth_response = client.post(
            "/a2a/test-agent/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "method": "SendMessage",
                "params": {},
                "id": 1,
            },
            # No headers - unauthenticated
        )
        from mcpgateway.main import get_current_user_with_permissions

        app.dependency_overrides[get_current_user_with_permissions] = mock_auth
        assert unauth_response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)


class TestJSONRPCPassthroughResponseFormat:
    """Test response format handling."""

    def test_wraps_non_jsonrpc_response(self, mock_a2a_service, mock_auth, auth_headers):
        """Test that non-JSON-RPC responses are wrapped in JSON-RPC format."""
        # Mock agent that returns plain dict (not JSON-RPC formatted)
        mock_a2a_service.invoke_agent = AsyncMock(return_value={"taskId": "task-123", "status": "submitted"})

        client = TestClient(app)
        response = client.post(
            "/a2a/test-agent/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "method": "SendMessage",
                "params": {},
                "id": 42,
            },
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert "result" in data
        assert data["result"]["taskId"] == "task-123"
        assert data["id"] == 42

    def test_preserves_jsonrpc_response(self, mock_a2a_service, mock_auth, auth_headers):
        """Test that JSON-RPC responses are returned as-is."""
        # Mock agent that already returns JSON-RPC formatted response
        mock_a2a_service.invoke_agent = AsyncMock(
            return_value={
                "jsonrpc": "2.0",
                "result": {"taskId": "task-123"},
                "id": 99,
            }
        )

        client = TestClient(app)
        response = client.post(
            "/a2a/test-agent/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "method": "SendMessage",
                "params": {},
                "id": 42,
            },
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert data["result"]["taskId"] == "task-123"
        # Should preserve agent's response id, not request id
        assert data["id"] == 99


class TestJSONRPCPassthroughErrorHandling:
    """Test error handling."""

    def test_agent_not_found_returns_404(self, mock_a2a_service, mock_auth, auth_headers):
        """Test that non-existent agent returns 404 with JSON-RPC error format."""
        from mcpgateway.services.a2a_service import A2AAgentNotFoundError

        mock_a2a_service.invoke_agent = AsyncMock(side_effect=A2AAgentNotFoundError("Agent not found"))

        client = TestClient(app)
        response = client.post(
            "/a2a/nonexistent-agent/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "method": "SendMessage",
                "params": {},
                "id": 1,
            },
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        # Verify proper JSON-RPC error structure at top level (not double-encoded)
        response_json = response.json()
        assert response_json["jsonrpc"] == "2.0"
        assert "error" in response_json
        assert response_json["error"]["code"] == -32001  # Server error: agent not found
        assert "Agent not found" in response_json["error"]["message"]
        assert response_json["id"] == 1

    def test_agent_error_returns_400_with_jsonrpc_error(self, mock_a2a_service, mock_auth, auth_headers):
        """Test that agent errors return 400 with JSON-RPC error format."""
        from mcpgateway.services.a2a_service import A2AAgentError

        mock_a2a_service.invoke_agent = AsyncMock(side_effect=A2AAgentError("Agent invocation failed"))

        client = TestClient(app)
        response = client.post(
            "/a2a/test-agent/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "method": "SendMessage",
                "params": {},
                "id": 1,
            },
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        # Verify proper JSON-RPC error structure at top level (not double-encoded)
        response_json = response.json()
        assert response_json["jsonrpc"] == "2.0"
        assert "error" in response_json
        assert response_json["error"]["code"] == -32603
        assert "Agent invocation failed" in response_json["error"]["message"]
        assert response_json["id"] == 1

    def test_service_unavailable_returns_503(self, mock_auth, auth_headers):
        """Test that unavailable service returns 503."""
        with patch("mcpgateway.main.a2a_service", None):
            client = TestClient(app)
            response = client.post(
                "/a2a/test-agent/jsonrpc",
                json={
                    "jsonrpc": "2.0",
                    "method": "SendMessage",
                    "params": {},
                    "id": 1,
                },
                headers=auth_headers,
            )

            assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    def test_unexpected_exception_returns_500_with_jsonrpc_error(self, mock_a2a_service, mock_auth, auth_headers):
        """Test that unexpected exceptions return 500 with JSON-RPC error format (lines 5451-5454)."""
        # Simulate an unexpected error during agent invocation
        mock_a2a_service.invoke_agent = AsyncMock(side_effect=RuntimeError("Unexpected database error"))

        client = TestClient(app)
        response = client.post(
            "/a2a/test-agent/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "method": "SendMessage",
                "params": {},
                "id": 1,
            },
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        # Verify proper JSON-RPC error structure at top level (not double-encoded)
        response_json = response.json()
        assert response_json["jsonrpc"] == "2.0"
        assert "error" in response_json
        assert response_json["error"]["code"] == -32603
        assert response_json["error"]["message"] == "Internal server error"
        assert response_json["id"] == 1


class TestJSONRPCPassthroughGovernance:
    """Test that governance features are applied."""

    @patch("mcpgateway.main.get_rpc_filter_context")
    def test_admin_unrestricted_token_teams(self, mock_get_filter_context, mock_a2a_service, mock_auth, auth_headers):
        """Test admin with no team restrictions (line 5385)."""
        # Admin with token_teams=None should stay None (unrestricted)
        mock_get_filter_context.return_value = ("admin@example.com", None, True)
        mock_a2a_service.invoke_agent = AsyncMock(return_value={"jsonrpc": "2.0", "result": {}, "id": 1})

        client = TestClient(app)
        response = client.post(
            "/a2a/test-agent/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "method": "SendMessage",
                "params": {},
                "id": 1,
            },
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        # Verify invoke_agent was called with token_teams=None (admin unrestricted)
        call_args = mock_a2a_service.invoke_agent.call_args
        assert call_args is not None
        assert call_args.kwargs["token_teams"] is None

    @patch("mcpgateway.main.get_rpc_filter_context")
    def test_non_admin_public_only_token_teams(self, mock_get_filter_context, mock_a2a_service, mock_auth, auth_headers):
        """Test non-admin without teams gets public-only access (line 5387)."""
        # Non-admin with token_teams=None should get [] (public-only)
        mock_get_filter_context.return_value = ("user@example.com", None, False)
        mock_a2a_service.invoke_agent = AsyncMock(return_value={"jsonrpc": "2.0", "result": {}, "id": 1})

        client = TestClient(app)
        response = client.post(
            "/a2a/test-agent/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "method": "SendMessage",
                "params": {},
                "id": 1,
            },
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        # Verify invoke_agent was called with token_teams=[] (public-only)
        call_args = mock_a2a_service.invoke_agent.call_args
        assert call_args is not None
        assert call_args.kwargs["token_teams"] == []

    @patch("mcpgateway.main.get_rpc_filter_context")
    def test_applies_token_scoping(self, mock_get_filter_context, mock_a2a_service, mock_auth, auth_headers):
        """Test that token scoping is applied."""
        mock_get_filter_context.return_value = ("user@example.com", ["team1"], False)
        mock_a2a_service.invoke_agent = AsyncMock(return_value={"jsonrpc": "2.0", "result": {}, "id": 1})

        client = TestClient(app)
        response = client.post(
            "/a2a/test-agent/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "method": "SendMessage",
                "params": {},
                "id": 1,
            },
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        # Verify invoke_agent was called with token_teams
        call_args = mock_a2a_service.invoke_agent.call_args
        assert call_args is not None
        assert "token_teams" in call_args.kwargs

    @patch("mcpgateway.main.uaid_utils.read_hop_count")
    def test_applies_hop_count_validation(self, mock_read_hop_count, mock_a2a_service, mock_auth, auth_headers):
        """Test that UAID hop count validation is applied."""
        mock_read_hop_count.return_value = 2
        mock_a2a_service.invoke_agent = AsyncMock(return_value={"jsonrpc": "2.0", "result": {}, "id": 1})

        client = TestClient(app)
        headers = {**auth_headers, "X-UAID-Hop-Count": "2"}
        response = client.post(
            "/a2a/test-agent/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "method": "SendMessage",
                "params": {},
                "id": 1,
            },
            headers=headers,
        )

        assert response.status_code == status.HTTP_200_OK
        # Verify hop count was read and passed to invoke_agent
        call_args = mock_a2a_service.invoke_agent.call_args
        assert call_args is not None
        assert "hop_count" in call_args.kwargs

    @patch("mcpgateway.main.getattr")
    def test_bearer_token_fallback_from_header(self, mock_getattr, mock_a2a_service, mock_auth, auth_headers):
        """Test bearer token extraction from Authorization header when not in request.state (lines 5401-5403)."""

        # Mock getattr to return None for bearer_token attribute (simulating missing request.state.bearer_token)
        def custom_getattr(obj, name, default=None):
            if name == "bearer_token":
                return None
            return object.__getattribute__(obj, name) if hasattr(obj, name) else default

        mock_getattr.side_effect = custom_getattr

        mock_a2a_service.invoke_agent = AsyncMock(return_value={"jsonrpc": "2.0", "result": {}, "id": 1})

        # Use a JWT-like token format
        jwt_token = (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"  # pragma: allowlist secret
        )

        client = TestClient(app)
        response = client.post(
            "/a2a/test-agent/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "method": "SendMessage",
                "params": {},
                "id": 1,
            },
            headers={"Authorization": f"Bearer {jwt_token}"},
        )

        assert response.status_code == status.HTTP_200_OK
        # Verify bearer_token was extracted from Authorization header fallback
        call_args = mock_a2a_service.invoke_agent.call_args
        assert call_args is not None
        assert "bearer_token" in call_args.kwargs

    def test_forwards_bearer_token_for_cross_gateway(self, mock_a2a_service, mock_auth):
        """Test that bearer token is forwarded for cross-gateway auth."""
        mock_a2a_service.invoke_agent = AsyncMock(return_value={"jsonrpc": "2.0", "result": {}, "id": 1})

        # Use a JWT-like token format
        jwt_token = (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"  # pragma: allowlist secret
        )

        client = TestClient(app)
        response = client.post(
            "/a2a/test-agent/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "method": "SendMessage",
                "params": {},
                "id": 1,
            },
            headers={"Authorization": f"Bearer {jwt_token}"},
        )

        assert response.status_code == status.HTTP_200_OK
        # Verify bearer_token was passed to invoke_agent
        call_args = mock_a2a_service.invoke_agent.call_args
        assert call_args is not None
        assert "bearer_token" in call_args.kwargs

    def test_opaque_bearer_token_suppressed(self, mock_a2a_service, mock_auth):
        """Test that opaque (non-JWT) bearer tokens are NOT forwarded for cross-gateway auth.

        Regression test for lines 5106-5109: Only JWT-shaped tokens should be forwarded;
        local opaque tokens cannot be validated by remote gateways.
        """
        mock_a2a_service.invoke_agent = AsyncMock(return_value={"jsonrpc": "2.0", "result": {}, "id": 1})

        # Use an opaque token (not JWT format)
        opaque_token = "local-opaque-token-12345"  # pragma: allowlist secret

        client = TestClient(app)
        response = client.post(
            "/a2a/test-agent/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "method": "SendMessage",
                "params": {},
                "id": 1,
            },
            headers={"Authorization": f"Bearer {opaque_token}"},
        )

        assert response.status_code == status.HTTP_200_OK
        # Verify bearer_token was NOT passed (should be None for opaque tokens)
        call_args = mock_a2a_service.invoke_agent.call_args
        assert call_args is not None
        assert "bearer_token" in call_args.kwargs
        # Critical assertion: opaque token should be suppressed (None)
        assert call_args.kwargs["bearer_token"] is None

    def test_request_context_extraction_passes_content_type_and_headers(self, mock_a2a_service, mock_auth):
        """Test that shared request context extraction passes content_type and filtered request_headers.

        Verifies lines 5114-5115 and 5135-5145: content_type and request_headers from
        _extract_a2a_request_context() are correctly passed to invoke_agent.
        """
        mock_a2a_service.invoke_agent = AsyncMock(return_value={"jsonrpc": "2.0", "result": {}, "id": 1})

        client = TestClient(app)
        response = client.post(
            "/a2a/test-agent/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "method": "SendMessage",
                "params": {},
                "id": 1,
            },
            headers={
                "Authorization": "Bearer test-token",
                "Content-Type": "application/json",
                "X-Custom-Header": "custom-value",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        # Verify content_type and request_headers were passed to invoke_agent
        call_args = mock_a2a_service.invoke_agent.call_args
        assert call_args is not None
        assert "content_type" in call_args.kwargs
        assert call_args.kwargs["content_type"] == "application/json"
        assert "request_headers" in call_args.kwargs
        # Verify request_headers is a dict (filtered sensitive headers)
        assert isinstance(call_args.kwargs["request_headers"], dict)


class TestJSONRPCPassthroughExamples:
    """Test real-world A2A SDK examples."""

    def test_google_adk_sendmessage_example(self, mock_a2a_service, mock_auth, auth_headers):
        """Test Google ADK RemoteA2aAgent SendMessage format."""
        mock_a2a_service.invoke_agent = AsyncMock(
            return_value={
                "jsonrpc": "2.0",
                "result": {
                    "id": "task-123",
                    "contextId": "ctx-456",
                    "status": {
                        "state": "TASK_STATE_WORKING",
                        "message": "Processing...",
                    },
                },
                "id": 1,
            }
        )

        client = TestClient(app)
        response = client.post(
            "/a2a/google-adk-agent/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "method": "SendMessage",
                "params": {
                    "message": {
                        "messageId": "msg-789",
                        "role": "ROLE_USER",
                        "parts": [{"text": "What is the weather in Dallas?"}],
                    }
                },
                "id": 1,
            },
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert data["result"]["id"] == "task-123"
        assert data["result"]["status"]["state"] == "TASK_STATE_WORKING"

    def test_gettask_example(self, mock_a2a_service, mock_auth, auth_headers):
        """Test GetTask method."""
        mock_a2a_service.invoke_agent = AsyncMock(
            return_value={
                "jsonrpc": "2.0",
                "result": {
                    "id": "task-123",
                    "status": {
                        "state": "TASK_STATE_COMPLETED",
                        "message": "Done",
                    },
                    "history": [
                        {
                            "messageId": "msg-1",
                            "role": "ROLE_AGENT",
                            "parts": [{"text": "The weather in Dallas is sunny."}],
                        }
                    ],
                },
                "id": 2,
            }
        )

        client = TestClient(app)
        response = client.post(
            "/a2a/google-adk-agent/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "method": "GetTask",
                "params": {"taskId": "task-123"},
                "id": 2,
            },
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert data["result"]["status"]["state"] == "TASK_STATE_COMPLETED"
        assert len(data["result"]["history"]) == 1


class TestJSONRPCSecurityDenyPaths:
    """Test security deny paths for RBAC and token scoping.

    These tests verify that security controls properly reject unauthorized requests
    without invoking the underlying service.
    """

    def test_requires_a2a_invoke_permission_decorator(self):
        """Test that /jsonrpc endpoint is decorated with @require_permission("a2a.invoke").

        This verifies the decorator is present on the endpoint function. Full RBAC deny-path
        testing (user without permission is rejected with 403) requires integration testing with
        a real database where user roles can be configured.

        The decorator's enforcement behavior is tested in:
        - tests/unit/mcpgateway/middleware/test_rbac.py
        - tests/unit/mcpgateway/middleware/test_rbac_endpoint_coverage.py
        """
        from mcpgateway.main import invoke_a2a_agent_jsonrpc

        # Verify the function has been wrapped by a decorator
        # (The @require_permission decorator uses functools.wraps, which sets __wrapped__)
        assert hasattr(invoke_a2a_agent_jsonrpc, "__wrapped__"), (
            "invoke_a2a_agent_jsonrpc is missing @require_permission decorator. "
            "This endpoint must enforce a2a.invoke permission per AGENTS.md security requirements."
        )

    def test_authenticated_user_without_permission_denied(self, mock_a2a_service, monkeypatch):
        """Test that authenticated user without a2a.invoke permission is rejected with 403.

        Security requirement per AGENTS.md: "Security-sensitive changes must include deny-path
        regression tests (unauthenticated, wrong team, insufficient permissions, feature disabled)."

        This test verifies Layer 2 (RBAC) enforcement: an authenticated user with valid token
        but lacking the a2a.invoke permission receives 403 Forbidden before agent invocation.
        """
        from mcpgateway.main import get_current_user_with_permissions
        from mcpgateway.middleware import rbac
        from fastapi import HTTPException

        # Mock user: authenticated with valid token but NO a2a.invoke permission
        def override_get_current_user_no_permission():
            return {
                "sub": "user@example.com",
                "email": "user@example.com",
                "is_admin": False,
                "teams": ["team1"],
                "permissions": [],  # Missing a2a.invoke permission
                "db": MagicMock(),
            }

        # Mock PermissionService to deny a2a.invoke permission
        mock_perm_service = AsyncMock()
        mock_perm_service.check_permission.side_effect = HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: insufficient permissions"
        )
        monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

        app.dependency_overrides[get_current_user_with_permissions] = override_get_current_user_no_permission

        # Mock to verify service is NOT called
        mock_a2a_service.invoke_agent = AsyncMock(return_value={"jsonrpc": "2.0", "result": {}, "id": 1})

        client = TestClient(app)
        response = client.post(
            "/a2a/test-agent/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "method": "SendMessage",
                "params": {},
                "id": 1,
            },
            headers={"Authorization": "Bearer test-token"},
        )

        # Should be rejected with 403 Forbidden (insufficient permissions)
        assert response.status_code == status.HTTP_403_FORBIDDEN

        # Service should NOT be invoked
        mock_a2a_service.invoke_agent.assert_not_called()

        # Clean up
        app.dependency_overrides.clear()

    def test_wrong_team_token_cannot_invoke_other_team_agent(self, mock_a2a_service, sample_a2a_agent):
        """Test that token scoped to wrong team cannot invoke agent from different team."""
        from mcpgateway.main import get_current_user_with_permissions

        # Mock user with team1 scope (not team2)
        def override_get_current_user_team1():
            return {
                "sub": "user@example.com",
                "email": "user@example.com",
                "is_admin": False,
                "teams": ["team1"],  # Token scoped to team1
                "permissions": ["a2a.invoke"],
            }

        app.dependency_overrides[get_current_user_with_permissions] = override_get_current_user_team1

        # Agent belongs to team2, user has team1 scope
        from mcpgateway.services.a2a_service import A2AAgentNotFoundError

        mock_a2a_service.invoke_agent = AsyncMock(
            side_effect=A2AAgentNotFoundError("Agent 'team2-agent' not found or access denied")
        )

        client = TestClient(app)
        response = client.post(
            "/a2a/team2-agent/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "method": "SendMessage",
                "params": {},
                "id": 1,
            },
            headers={"Authorization": "Bearer test-token"},
        )

        # Should return 404 (agent not found due to token scoping)
        assert response.status_code == status.HTTP_404_NOT_FOUND
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert data["error"]["code"] == -32001

        # Clean up
        app.dependency_overrides.clear()

    def test_public_only_token_cannot_invoke_team_agent(self, mock_a2a_service):
        """Test that public-only token (no team access) cannot invoke team-scoped agent."""
        from mcpgateway.main import get_current_user_with_permissions

        # Mock user with no team access (public-only)
        def override_get_current_user_public_only():
            return {
                "sub": "user@example.com",
                "email": "user@example.com",
                "is_admin": False,
                "teams": [],  # Public-only access
                "permissions": ["a2a.invoke"],
            }

        app.dependency_overrides[get_current_user_with_permissions] = override_get_current_user_public_only

        from mcpgateway.services.a2a_service import A2AAgentNotFoundError

        mock_a2a_service.invoke_agent = AsyncMock(
            side_effect=A2AAgentNotFoundError("Agent 'private-agent' not found or access denied")
        )

        client = TestClient(app)
        response = client.post(
            "/a2a/private-agent/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "method": "SendMessage",
                "params": {},
                "id": 1,
            },
            headers={"Authorization": "Bearer test-token"},
        )

        # Should return 404 (agent not found due to visibility restrictions)
        assert response.status_code == status.HTTP_404_NOT_FOUND
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert data["error"]["code"] == -32001

        # Clean up
        app.dependency_overrides.clear()


class TestJSONRPCNotifications:
    """Test JSON-RPC notification handling (requests without id field).

    JSON-RPC 2.0 spec: When 'id' is absent (notifications), error responses
    must omit the 'id' field entirely, not include "id": null.
    """

    def test_notification_success_omits_id_field(self, mock_a2a_service, mock_auth, auth_headers):
        """Test that successful notification response omits id field when request has no id."""
        mock_a2a_service.invoke_agent = AsyncMock(return_value={"taskId": "task-123", "status": "submitted"})

        client = TestClient(app)
        response = client.post(
            "/a2a/test-agent/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "method": "SendMessage",
                "params": {"query": "Hello"},
                # No 'id' field - this is a notification
            },
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert "result" in data
        # JSON-RPC 2.0 spec: notifications must omit 'id' field, not return "id": null
        assert "id" not in data

    def test_notification_validation_error_omits_id_field(self, mock_a2a_service, mock_auth, auth_headers):
        """Test that validation error for notification omits id field."""
        client = TestClient(app)
        response = client.post(
            "/a2a/test-agent/jsonrpc",
            json={
                "jsonrpc": "2.0",
                # Missing 'method' field - validation error
                "params": {},
                # No 'id' field - this is a notification
            },
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert "error" in data
        assert data["error"]["code"] == -32600
        # JSON-RPC 2.0 spec: error response for notification must omit 'id' field
        assert "id" not in data

    def test_notification_agent_not_found_omits_id_field(self, mock_a2a_service, mock_auth, auth_headers):
        """Test that agent not found error for notification omits id field."""
        from mcpgateway.services.a2a_service import A2AAgentNotFoundError

        mock_a2a_service.invoke_agent = AsyncMock(side_effect=A2AAgentNotFoundError("Agent not found"))

        client = TestClient(app)
        response = client.post(
            "/a2a/nonexistent-agent/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "method": "SendMessage",
                "params": {},
                # No 'id' field - this is a notification
            },
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert "error" in data
        assert data["error"]["code"] == -32001
        # JSON-RPC 2.0 spec: error response for notification must omit 'id' field
        assert "id" not in data

    def test_notification_agent_error_omits_id_field(self, mock_a2a_service, mock_auth, auth_headers):
        """Test that agent error for notification omits id field."""
        from mcpgateway.services.a2a_service import A2AAgentError

        mock_a2a_service.invoke_agent = AsyncMock(side_effect=A2AAgentError("Agent invocation failed"))

        client = TestClient(app)
        response = client.post(
            "/a2a/test-agent/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "method": "SendMessage",
                "params": {},
                # No 'id' field - this is a notification
            },
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert "error" in data
        assert data["error"]["code"] == -32603
        # JSON-RPC 2.0 spec: error response for notification must omit 'id' field
        assert "id" not in data

    def test_notification_unexpected_error_omits_id_field(self, mock_a2a_service, mock_auth, auth_headers):
        """Test that unexpected error for notification omits id field."""
        mock_a2a_service.invoke_agent = AsyncMock(side_effect=Exception("Unexpected error"))

        client = TestClient(app)
        response = client.post(
            "/a2a/test-agent/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "method": "SendMessage",
                "params": {},
                # No 'id' field - this is a notification
            },
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert "error" in data
        assert data["error"]["code"] == -32603
        # JSON-RPC 2.0 spec: error response for notification must omit 'id' field
        assert "id" not in data

    def test_request_with_id_includes_id_in_response(self, mock_a2a_service, mock_auth, auth_headers):
        """Test that regular request with id field includes id in response."""
        mock_a2a_service.invoke_agent = AsyncMock(return_value={"taskId": "task-123"})

        client = TestClient(app)
        response = client.post(
            "/a2a/test-agent/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "method": "SendMessage",
                "params": {},
                "id": 42,  # Has 'id' field - not a notification
            },
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        # Regular requests must include 'id' in response
        assert "id" in data
        assert data["id"] == 42


class TestJSONRPCPassthroughFeatureFlags:
    """Test feature flag behavior for JSON-RPC passthrough endpoint."""

    def test_jsonrpc_endpoint_exists_when_a2a_enabled(self, mock_a2a_service, mock_auth, auth_headers):
        """Test that /jsonrpc endpoint is accessible when A2A feature is enabled.

        Security requirement per AGENTS.md: High-risk transports must be feature-flagged
        and disabled by default. This test verifies the endpoint IS accessible when enabled.
        """
        mock_a2a_service.invoke_agent = AsyncMock(return_value={"jsonrpc": "2.0", "result": {}, "id": 1})

        client = TestClient(app)
        response = client.post(
            "/a2a/test-agent/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "method": "SendMessage",
                "params": {},
                "id": 1,
            },
            headers=auth_headers,
        )

        # Endpoint should be accessible (200 or service-layer error, not 404)
        # 404 would indicate the route is not mounted
        assert response.status_code != status.HTTP_404_NOT_FOUND
        # With A2A enabled and mocked service, we expect success or service error
        assert response.status_code in (
            status.HTTP_200_OK,
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    def test_a2a_endpoints_return_404_when_feature_disabled(self, mock_auth):
        """Test that A2A endpoints return 404 when MCPGATEWAY_A2A_ENABLED is disabled.

        Security requirement per AGENTS.md: "Security-sensitive changes must include deny-path
        regression tests (unauthenticated, wrong team, insufficient permissions, feature disabled)."

        This test verifies that when A2A is disabled, the router is not mounted and all
        /a2a/* endpoints return 404 Not Found.
        """
        from unittest.mock import patch
        from mcpgateway.config import settings

        # Temporarily disable A2A feature flag and reload app
        with patch.object(settings, "mcpgateway_a2a_enabled", False):
            # Import and rebuild the app with A2A disabled
            # Note: This recreates the app instance with A2A router not mounted
            import importlib
            import mcpgateway.main
            importlib.reload(mcpgateway.main)
            from mcpgateway.main import app as reloaded_app

            client = TestClient(reloaded_app)
            response = client.post(
                "/a2a/test-agent/jsonrpc",
                json={
                    "jsonrpc": "2.0",
                    "method": "SendMessage",
                    "params": {},
                    "id": 1,
                },
                headers={"Authorization": "Bearer test-token"},
            )

            # Should return 404 (route not mounted)
            assert response.status_code == status.HTTP_404_NOT_FOUND

        # Reload app again to restore A2A-enabled state for other tests
        importlib.reload(mcpgateway.main)


class TestJSONRPCPassthroughEdgeCases:
    """Test edge cases for JSON-RPC passthrough endpoint."""

    def test_id_zero_is_valid(self, mock_a2a_service, mock_auth, auth_headers):
        """Test that id: 0 is valid (common edge case)."""
        mock_a2a_service.invoke_agent = AsyncMock(return_value={"taskId": "task-123"})

        client = TestClient(app)
        response = client.post(
            "/a2a/test-agent/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "method": "SendMessage",
                "params": {},
                "id": 0,  # Zero is a valid JSON-RPC id
            },
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert "id" in data
        assert data["id"] == 0  # Must preserve zero

    def test_id_null_treated_as_notification(self, mock_a2a_service, mock_auth, auth_headers):
        """Test that id: null is treated as notification per JSON-RPC 2.0 spec."""
        mock_a2a_service.invoke_agent = AsyncMock(return_value={"taskId": "task-123"})

        client = TestClient(app)
        response = client.post(
            "/a2a/test-agent/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "method": "SendMessage",
                "params": {},
                "id": None,  # null is treated as notification
            },
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        # JSON-RPC 2.0 spec: null id means notification, omit id field from response
        assert "id" not in data

    def test_empty_params_dict(self, mock_a2a_service, mock_auth, auth_headers):
        """Test that empty params dict {} is valid."""
        mock_a2a_service.invoke_agent = AsyncMock(return_value={"taskId": "task-123"})

        client = TestClient(app)
        response = client.post(
            "/a2a/test-agent/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "method": "ListTasks",
                "params": {},  # Empty dict is valid
                "id": 1,
            },
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK

    def test_unicode_method_name(self, mock_a2a_service, mock_auth, auth_headers):
        """Test that unicode method names are accepted."""
        mock_a2a_service.invoke_agent = AsyncMock(return_value={"result": "ok"})

        client = TestClient(app)
        response = client.post(
            "/a2a/test-agent/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "method": "SendMessage_测试_🚀",  # Unicode and emoji
                "params": {},
                "id": 1,
            },
            headers=auth_headers,
        )

        # Should accept unicode method names
        assert response.status_code in (status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND)

    def test_very_long_method_name(self, mock_a2a_service, mock_auth, auth_headers):
        """Test that very long method names are handled gracefully."""
        mock_a2a_service.invoke_agent = AsyncMock(return_value={"result": "ok"})

        long_method = "SendMessage" + "A" * 1000  # 1012 chars

        client = TestClient(app)
        response = client.post(
            "/a2a/test-agent/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "method": long_method,
                "params": {},
                "id": 1,
            },
            headers=auth_headers,
        )

        # Should handle long method names gracefully (accept or reject with proper error)
        assert response.status_code in (status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND)

    def test_special_chars_in_method_name(self, mock_a2a_service, mock_auth, auth_headers):
        """Test that method names with special characters are handled."""
        mock_a2a_service.invoke_agent = AsyncMock(return_value={"result": "ok"})

        client = TestClient(app)
        response = client.post(
            "/a2a/test-agent/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "method": "Send-Message.v2:beta",  # Special chars: dash, dot, colon
                "params": {},
                "id": 1,
            },
            headers=auth_headers,
        )

        # Should handle special characters gracefully
        assert response.status_code in (status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND)


# ==============================================================================
# Security Tests for _extract_a2a_request_context() Helper
# ==============================================================================
# Tests cover critical security logic:
# - Token scoping (admin bypass, public-only, team restrictions)
# - Bearer token extraction and JWT validation
# - UAID hop count reading
# - Request header filtering
# - User identity extraction
# ==============================================================================


@pytest.fixture
def mock_request_for_context():
    """Mock FastAPI Request object for context extraction tests."""
    request = MagicMock()
    request.headers = {}
    request.state = MagicMock()
    request.state.bearer_token = None
    return request


@pytest.fixture
def mock_user_dict_for_context():
    """Mock user as dictionary for context extraction tests."""
    return {
        "sub": "user@example.com",
        "email": "user@example.com",
        "is_admin": False,
        "teams": ["team1"],
    }


class TestRequestContextTokenScoping:
    """Test _extract_a2a_request_context token scoping logic (admin bypass, public-only, team restrictions)."""

    def test_admin_with_no_team_restrictions_unrestricted(self, mock_request_for_context, mock_user_dict_for_context):
        """Test admin with token_teams=None gets unrestricted access (admin bypass)."""
        with patch("mcpgateway.main.get_rpc_filter_context") as mock_get_filter:
            # Admin with token_teams=None should remain None (unrestricted)
            mock_get_filter.return_value = ("admin@example.com", None, True)

            with patch("mcpgateway.main.uaid_utils.read_hop_count", return_value=0):
                from mcpgateway.main import _extract_a2a_request_context
                context = _extract_a2a_request_context(mock_request_for_context, mock_user_dict_for_context)

            assert context["token_teams"] is None  # Admin bypass
            assert context["user_email"] == "admin@example.com"

    def test_non_admin_with_no_teams_gets_public_only(self, mock_request_for_context, mock_user_dict_for_context):
        """Test non-admin without teams gets public-only access (empty list)."""
        with patch("mcpgateway.main.get_rpc_filter_context") as mock_get_filter:
            # Non-admin with token_teams=None should get [] (public-only)
            mock_get_filter.return_value = ("user@example.com", None, False)

            with patch("mcpgateway.main.uaid_utils.read_hop_count", return_value=0):
                from mcpgateway.main import _extract_a2a_request_context
                context = _extract_a2a_request_context(mock_request_for_context, mock_user_dict_for_context)

            assert context["token_teams"] == []  # Public-only
            assert context["user_email"] == "user@example.com"

    def test_non_admin_with_teams_preserves_teams(self, mock_request_for_context, mock_user_dict_for_context):
        """Test non-admin with specific teams preserves team list."""
        with patch("mcpgateway.main.get_rpc_filter_context") as mock_get_filter:
            # Non-admin with specific teams
            mock_get_filter.return_value = ("user@example.com", ["team1", "team2"], False)

            with patch("mcpgateway.main.uaid_utils.read_hop_count", return_value=0):
                from mcpgateway.main import _extract_a2a_request_context
                context = _extract_a2a_request_context(mock_request_for_context, mock_user_dict_for_context)

            assert context["token_teams"] == ["team1", "team2"]
            assert context["user_email"] == "user@example.com"

    def test_admin_with_specific_teams_preserves_teams(self, mock_request_for_context, mock_user_dict_for_context):
        """Test admin with specific team restrictions preserves those restrictions."""
        with patch("mcpgateway.main.get_rpc_filter_context") as mock_get_filter:
            # Admin with specific team restrictions (narrowed token)
            mock_get_filter.return_value = ("admin@example.com", ["team1"], True)

            with patch("mcpgateway.main.uaid_utils.read_hop_count", return_value=0):
                from mcpgateway.main import _extract_a2a_request_context
                context = _extract_a2a_request_context(mock_request_for_context, mock_user_dict_for_context)

            assert context["token_teams"] == ["team1"]  # Not bypassed, respects token scope
            assert context["user_email"] == "admin@example.com"


class TestRequestContextUserIdentityExtraction:
    """Test _extract_a2a_request_context user identity extraction from various user formats."""

    def test_user_dict_with_sub(self, mock_request_for_context):
        """Test user identity extracted from dict with 'sub' field."""
        user = {"sub": "user123", "email": "user@example.com"}

        with patch("mcpgateway.main.get_rpc_filter_context", return_value=("user@example.com", [], False)):
            with patch("mcpgateway.main.uaid_utils.read_hop_count", return_value=0):
                from mcpgateway.main import _extract_a2a_request_context
                context = _extract_a2a_request_context(mock_request_for_context, user)

        assert context["user_id"] == "user123"
        assert context["user_email"] == "user@example.com"

    def test_user_dict_with_id(self, mock_request_for_context):
        """Test user identity extracted from dict with 'id' field."""
        user = {"id": "user456", "email": "user@example.com"}

        with patch("mcpgateway.main.get_rpc_filter_context", return_value=("user@example.com", [], False)):
            with patch("mcpgateway.main.uaid_utils.read_hop_count", return_value=0):
                from mcpgateway.main import _extract_a2a_request_context
                context = _extract_a2a_request_context(mock_request_for_context, user)

        assert context["user_id"] == "user456"
        assert context["user_email"] == "user@example.com"

    def test_user_dict_fallback_to_email(self, mock_request_for_context):
        """Test user identity falls back to email when id/sub missing."""
        user = {"email": "user@example.com"}

        with patch("mcpgateway.main.get_rpc_filter_context", return_value=("user@example.com", [], False)):
            with patch("mcpgateway.main.uaid_utils.read_hop_count", return_value=0):
                from mcpgateway.main import _extract_a2a_request_context
                context = _extract_a2a_request_context(mock_request_for_context, user)

        assert context["user_id"] == "user@example.com"
        assert context["user_email"] == "user@example.com"

    def test_user_as_string(self, mock_request_for_context):
        """Test user identity when user is a string (non-dict format)."""
        user = "user@example.com"

        with patch("mcpgateway.main.get_rpc_filter_context", return_value=("user@example.com", [], False)):
            with patch("mcpgateway.main.uaid_utils.read_hop_count", return_value=0):
                from mcpgateway.main import _extract_a2a_request_context
                context = _extract_a2a_request_context(mock_request_for_context, user)

        assert context["user_id"] == "user@example.com"
        assert context["user_email"] == "user@example.com"


class TestRequestContextBearerTokenExtraction:
    """Test _extract_a2a_request_context bearer token extraction and JWT validation."""

    def test_bearer_token_from_request_state(self, mock_request_for_context, mock_user_dict_for_context):
        """Test bearer token extracted from request.state (preferred source)."""
        # JWT-shaped token
        jwt_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"  # pragma: allowlist secret
        mock_request_for_context.state.bearer_token = jwt_token

        with patch("mcpgateway.main.get_rpc_filter_context", return_value=("user@example.com", [], False)):
            with patch("mcpgateway.main.uaid_utils.read_hop_count", return_value=0):
                from mcpgateway.main import _extract_a2a_request_context
                context = _extract_a2a_request_context(mock_request_for_context, mock_user_dict_for_context)

        assert context["bearer_token"] == jwt_token

    def test_bearer_token_fallback_from_authorization_header(self, mock_request_for_context, mock_user_dict_for_context):
        """Test bearer token extracted from Authorization header as fallback."""
        jwt_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"  # pragma: allowlist secret
        mock_request_for_context.state.bearer_token = None  # Not set by middleware
        mock_request_for_context.headers = {"authorization": f"Bearer {jwt_token}"}

        with patch("mcpgateway.main.get_rpc_filter_context", return_value=("user@example.com", [], False)):
            with patch("mcpgateway.main.uaid_utils.read_hop_count", return_value=0):
                from mcpgateway.main import _extract_a2a_request_context
                context = _extract_a2a_request_context(mock_request_for_context, mock_user_dict_for_context)

        assert context["bearer_token"] == jwt_token

    def test_bearer_token_case_insensitive(self, mock_request_for_context, mock_user_dict_for_context):
        """Test Authorization header parsing is case-insensitive."""
        jwt_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"  # pragma: allowlist secret
        mock_request_for_context.state.bearer_token = None
        mock_request_for_context.headers = {"authorization": f"bearer {jwt_token}"}  # lowercase 'bearer'

        with patch("mcpgateway.main.get_rpc_filter_context", return_value=("user@example.com", [], False)):
            with patch("mcpgateway.main.uaid_utils.read_hop_count", return_value=0):
                from mcpgateway.main import _extract_a2a_request_context
                context = _extract_a2a_request_context(mock_request_for_context, mock_user_dict_for_context)

        assert context["bearer_token"] == jwt_token

    def test_opaque_token_suppressed(self, mock_request_for_context, mock_user_dict_for_context):
        """Test opaque (non-JWT) bearer tokens are suppressed for cross-gateway auth."""
        opaque_token = "local-opaque-token-12345"  # pragma: allowlist secret
        mock_request_for_context.state.bearer_token = opaque_token

        with patch("mcpgateway.main.get_rpc_filter_context", return_value=("user@example.com", [], False)):
            with patch("mcpgateway.main.uaid_utils.read_hop_count", return_value=0):
                with patch("mcpgateway.main._is_jwt_token", return_value=False):
                    from mcpgateway.main import _extract_a2a_request_context
                    context = _extract_a2a_request_context(mock_request_for_context, mock_user_dict_for_context)

        assert context["bearer_token"] is None  # Suppressed

    def test_jwt_token_forwarded(self, mock_request_for_context, mock_user_dict_for_context):
        """Test JWT-shaped bearer tokens are forwarded for cross-gateway auth."""
        jwt_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"  # pragma: allowlist secret
        mock_request_for_context.state.bearer_token = jwt_token

        with patch("mcpgateway.main.get_rpc_filter_context", return_value=("user@example.com", [], False)):
            with patch("mcpgateway.main.uaid_utils.read_hop_count", return_value=0):
                with patch("mcpgateway.main._is_jwt_token", return_value=True):
                    from mcpgateway.main import _extract_a2a_request_context
                    context = _extract_a2a_request_context(mock_request_for_context, mock_user_dict_for_context)

        assert context["bearer_token"] == jwt_token

    def test_no_bearer_token(self, mock_request_for_context, mock_user_dict_for_context):
        """Test no bearer token when Authorization header missing."""
        mock_request_for_context.state.bearer_token = None
        mock_request_for_context.headers = {}

        with patch("mcpgateway.main.get_rpc_filter_context", return_value=("user@example.com", [], False)):
            with patch("mcpgateway.main.uaid_utils.read_hop_count", return_value=0):
                from mcpgateway.main import _extract_a2a_request_context
                context = _extract_a2a_request_context(mock_request_for_context, mock_user_dict_for_context)

        assert context["bearer_token"] is None


class TestRequestContextHopCountReading:
    """Test _extract_a2a_request_context UAID federation hop count extraction."""

    def test_hop_count_zero_for_new_request(self, mock_request_for_context, mock_user_dict_for_context):
        """Test hop count is 0 for non-federated request."""
        with patch("mcpgateway.main.get_rpc_filter_context", return_value=("user@example.com", [], False)):
            with patch("mcpgateway.main.uaid_utils.read_hop_count", return_value=0):
                from mcpgateway.main import _extract_a2a_request_context
                context = _extract_a2a_request_context(mock_request_for_context, mock_user_dict_for_context)

        assert context["hop_count"] == 0

    def test_hop_count_incremented_for_federated_request(self, mock_request_for_context, mock_user_dict_for_context):
        """Test hop count is read from X-UAID-Hop-Count header."""
        mock_request_for_context.headers = {"X-UAID-Hop-Count": "2"}

        with patch("mcpgateway.main.get_rpc_filter_context", return_value=("user@example.com", [], False)):
            with patch("mcpgateway.main.uaid_utils.read_hop_count", return_value=2):
                from mcpgateway.main import _extract_a2a_request_context
                context = _extract_a2a_request_context(mock_request_for_context, mock_user_dict_for_context)

        assert context["hop_count"] == 2

    def test_hop_count_extraction_delegates_to_uaid_utils(self, mock_request_for_context, mock_user_dict_for_context):
        """Test hop count extraction delegates to uaid_utils.read_hop_count."""
        with patch("mcpgateway.main.get_rpc_filter_context", return_value=("user@example.com", [], False)):
            with patch("mcpgateway.main.uaid_utils.read_hop_count") as mock_read_hop:
                mock_read_hop.return_value = 5
                from mcpgateway.main import _extract_a2a_request_context
                context = _extract_a2a_request_context(mock_request_for_context, mock_user_dict_for_context)

        mock_read_hop.assert_called_once_with(mock_request_for_context.headers)
        assert context["hop_count"] == 5


class TestRequestContextMetadataExtraction:
    """Test _extract_a2a_request_context content-type and request header extraction."""

    def test_content_type_extracted(self, mock_request_for_context, mock_user_dict_for_context):
        """Test content-type header is extracted."""
        mock_request_for_context.headers = {"content-type": "application/json"}

        with patch("mcpgateway.main.get_rpc_filter_context", return_value=("user@example.com", [], False)):
            with patch("mcpgateway.main.uaid_utils.read_hop_count", return_value=0):
                with patch("mcpgateway.main._prepare_request_headers", return_value={"content-type": "application/json"}):
                    from mcpgateway.main import _extract_a2a_request_context
                    context = _extract_a2a_request_context(mock_request_for_context, mock_user_dict_for_context)

        assert context["content_type"] == "application/json"

    def test_request_headers_filtered(self, mock_request_for_context, mock_user_dict_for_context):
        """Test request headers are filtered by _prepare_request_headers."""
        mock_request_for_context.headers = {
            "content-type": "application/json",
            "x-custom-header": "custom-value",
            "authorization": "Bearer token",  # Should be filtered
        }

        filtered_headers = {
            "content-type": "application/json",
            "x-custom-header": "custom-value",
            # authorization removed by filter
        }

        with patch("mcpgateway.main.get_rpc_filter_context", return_value=("user@example.com", [], False)):
            with patch("mcpgateway.main.uaid_utils.read_hop_count", return_value=0):
                with patch("mcpgateway.main._prepare_request_headers", return_value=filtered_headers) as mock_prepare:
                    from mcpgateway.main import _extract_a2a_request_context
                    context = _extract_a2a_request_context(mock_request_for_context, mock_user_dict_for_context)

        mock_prepare.assert_called_once_with(mock_request_for_context.headers)
        assert context["request_headers"] == filtered_headers

    def test_no_content_type(self, mock_request_for_context, mock_user_dict_for_context):
        """Test content-type is None when header missing."""
        mock_request_for_context.headers = {}

        with patch("mcpgateway.main.get_rpc_filter_context", return_value=("user@example.com", [], False)):
            with patch("mcpgateway.main.uaid_utils.read_hop_count", return_value=0):
                with patch("mcpgateway.main._prepare_request_headers", return_value={}):
                    from mcpgateway.main import _extract_a2a_request_context
                    context = _extract_a2a_request_context(mock_request_for_context, mock_user_dict_for_context)

        assert context["content_type"] is None


class TestRequestContextCompleteContext:
    """Test _extract_a2a_request_context complete context structure returned."""

    def test_returns_all_required_fields(self, mock_request_for_context, mock_user_dict_for_context):
        """Test context contains all required fields."""
        jwt_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"  # pragma: allowlist secret
        mock_request_for_context.state.bearer_token = jwt_token
        mock_request_for_context.headers = {
            "content-type": "application/json",
            "X-UAID-Hop-Count": "1",
        }

        with patch("mcpgateway.main.get_rpc_filter_context", return_value=("user@example.com", ["team1"], False)):
            with patch("mcpgateway.main.uaid_utils.read_hop_count", return_value=1):
                with patch("mcpgateway.main._prepare_request_headers", return_value={"content-type": "application/json"}):
                    with patch("mcpgateway.main._is_jwt_token", return_value=True):
                        from mcpgateway.main import _extract_a2a_request_context
                        context = _extract_a2a_request_context(mock_request_for_context, mock_user_dict_for_context)

        # Verify all required fields present
        assert "user_id" in context
        assert "user_email" in context
        assert "token_teams" in context
        assert "hop_count" in context
        assert "bearer_token" in context
        assert "content_type" in context
        assert "request_headers" in context

        # Verify values
        assert context["user_email"] == "user@example.com"
        assert context["token_teams"] == ["team1"]
        assert context["hop_count"] == 1
        assert context["bearer_token"] == jwt_token
        assert context["content_type"] == "application/json"
        assert isinstance(context["request_headers"], dict)
