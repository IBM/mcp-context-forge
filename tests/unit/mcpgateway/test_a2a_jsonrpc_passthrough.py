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
        assert "2.0" in response.text

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
        assert "method" in response.text.lower()

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
        assert "method" in response.text.lower()

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
        assert "params" in response.text.lower()

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

    def test_requires_authentication(self):
        """Test that endpoint requires authentication."""
        client = TestClient(app)
        response = client.post(
            "/a2a/test-agent/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "method": "SendMessage",
                "params": {},
                "id": 1,
            },
        )

        # Should return 401 or 403 depending on auth configuration
        assert response.status_code in [
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        ]

    def test_requires_a2a_invoke_permission(self, mock_a2a_service, mock_auth, auth_headers):
        """Test that endpoint requires a2a.invoke permission.

        This test verifies that the @require_permission('a2a.invoke') decorator
        is applied to the route. The decorator is applied at import time, so we
        verify it indirectly by ensuring authenticated requests succeed (implying
        RBAC checks passed) while unauthenticated requests are rejected.
        """
        mock_a2a_service.invoke_agent = AsyncMock(return_value={"jsonrpc": "2.0", "result": {}, "id": 1})

        client = TestClient(app)

        # Authenticated request should succeed (RBAC allows it)
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

        # Verify the decorator is present by checking the route's endpoint
        from mcpgateway.main import invoke_a2a_agent_jsonrpc

        # The @require_permission decorator adds metadata to the function
        assert hasattr(invoke_a2a_agent_jsonrpc, "__wrapped__") or "a2a.invoke" in str(invoke_a2a_agent_jsonrpc)


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
