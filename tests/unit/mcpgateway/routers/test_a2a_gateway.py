# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_a2a_gateway.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Tests for A2A Gateway Router.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# First-Party
from mcpgateway.config import settings
from mcpgateway.routers.a2a_gateway import get_db, router
from mcpgateway.middleware.rbac import get_current_user_with_permissions
from mcpgateway.services.a2a_gateway_service import (
    A2AGatewayAgentDisabledError,
    A2AGatewayAgentIncompatibleError,
    A2AGatewayAgentNotFoundError,
    A2AGatewayError,
)

MOCK_USER = {"sub": "testuser@example.com", "email": "testuser@example.com", "is_admin": True}

# Route prefix from settings (default: "a2a/agent")
_PREFIX = f"/{settings.a2a_gateway_route_prefix.strip('/')}"


class MockPermissionService:
    """Mock PermissionService that always allows access."""

    def __init__(self, *args, **kwargs):
        pass

    async def check_permission(self, **kwargs):
        return True

    async def require_permission(self, *args, **kwargs):
        pass

    async def has_permission(self, *args, **kwargs):
        return True


@pytest.fixture
def app():
    """Create test FastAPI app with A2A gateway router and auth bypassed."""
    test_app = FastAPI()
    test_app.include_router(router)

    test_app.dependency_overrides[get_current_user_with_permissions] = lambda: MOCK_USER
    test_app.dependency_overrides[get_db] = lambda: MagicMock()

    return test_app


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture(autouse=True)
def mock_services():
    """Mock gateway service, client service, and RBAC to isolate router logic."""
    with (
        patch("mcpgateway.routers.a2a_gateway._gateway_service") as mock_svc,
        patch("mcpgateway.routers.a2a_gateway._client_service") as mock_client,
        patch("mcpgateway.routers.a2a_gateway._run_pre_invoke_hook", new_callable=AsyncMock),
        patch("mcpgateway.routers.a2a_gateway._run_post_invoke_hook", new_callable=AsyncMock),
        patch("mcpgateway.routers.a2a_gateway.a2a_gateway_requests_counter") as mock_counter,
        patch("mcpgateway.routers.a2a_gateway.a2a_gateway_errors_counter") as mock_err_counter,
        patch("mcpgateway.routers.a2a_gateway.a2a_gateway_streams_active") as mock_streams_gauge,
        patch("mcpgateway.routers.a2a_gateway._get_rpc_filter_context", return_value=("testuser@example.com", [], False)),
        patch("mcpgateway.middleware.rbac.PermissionService", MockPermissionService),
    ):
        yield {
            "gateway_service": mock_svc,
            "client_service": mock_client,
            "counter": mock_counter,
            "err_counter": mock_err_counter,
            "streams_gauge": mock_streams_gauge,
        }


class TestAgentCard:
    """Tests for GET /{agent_id}/.well-known/agent-card.json."""

    def test_agent_card_success(self, client, mock_services):
        agent = MagicMock()
        mock_services["gateway_service"].resolve_agent.return_value = (agent, {}, None)
        mock_services["gateway_service"].generate_agent_card.return_value = {
            "name": "Echo",
            "url": f"https://gw.com{_PREFIX}/abc123",
            "version": "1.0",
        }

        response = client.get(f"{_PREFIX}/abc123/.well-known/agent-card.json")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Echo"

    def test_agent_card_not_found(self, client, mock_services):
        mock_services["gateway_service"].resolve_agent.side_effect = A2AGatewayAgentNotFoundError("not found")

        response = client.get(f"{_PREFIX}/nonexistent/.well-known/agent-card.json")
        assert response.status_code == 404

    def test_agent_card_disabled(self, client, mock_services):
        mock_services["gateway_service"].resolve_agent.side_effect = A2AGatewayAgentDisabledError("disabled")

        response = client.get(f"{_PREFIX}/disabled-agent/.well-known/agent-card.json")
        assert response.status_code == 400


class TestJsonrpcEndpoint:
    """Tests for POST /{agent_id} (JSON-RPC dispatcher)."""

    def test_invalid_json(self, client):
        response = client.post(
            f"{_PREFIX}/abc123",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["error"]["code"] == -32700

    def test_invalid_jsonrpc_structure(self, client, mock_services):
        mock_services["gateway_service"].validate_jsonrpc_request.return_value = {
            "jsonrpc": "2.0",
            "error": {"code": -32600, "message": "Missing method"},
            "id": None,
        }

        response = client.post(f"{_PREFIX}/abc123", json={"missing": "method"})
        assert response.status_code == 200
        assert response.json()["error"]["code"] == -32600

    def test_message_send_success(self, client, mock_services):
        mock_services["gateway_service"].validate_jsonrpc_request.return_value = None
        mock_services["gateway_service"].is_streaming_method.return_value = False

        agent = MagicMock(endpoint_url="https://downstream.com/a2a")
        agent._gateway_endpoint_url = "https://downstream.com/a2a"
        mock_services["gateway_service"].resolve_agent.return_value = (agent, {"Authorization": "Bearer tok"}, None)

        mock_services["client_service"].send_jsonrpc = AsyncMock(
            return_value={"jsonrpc": "2.0", "result": {"id": "task-1", "status": {"state": "completed"}}, "id": 1}
        )

        response = client.post(
            f"{_PREFIX}/abc123",
            json={"jsonrpc": "2.0", "method": "message/send", "params": {}, "id": 1},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["result"]["id"] == "task-1"

    def test_agent_not_found_returns_jsonrpc_error(self, client, mock_services):
        mock_services["gateway_service"].validate_jsonrpc_request.return_value = None
        mock_services["gateway_service"].resolve_agent.side_effect = A2AGatewayAgentNotFoundError("not found")

        response = client.post(
            f"{_PREFIX}/nonexistent",
            json={"jsonrpc": "2.0", "method": "message/send", "params": {}, "id": 1},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["error"]["code"] == -32603
        assert "not found" in data["error"]["message"].lower()

    def test_agent_disabled_returns_jsonrpc_error(self, client, mock_services):
        mock_services["gateway_service"].validate_jsonrpc_request.return_value = None
        mock_services["gateway_service"].resolve_agent.side_effect = A2AGatewayAgentDisabledError("disabled")

        response = client.post(
            f"{_PREFIX}/disabled-id",
            json={"jsonrpc": "2.0", "method": "tasks/get", "params": {}, "id": 2},
        )

        assert response.status_code == 200
        data = response.json()
        assert "disabled" in data["error"]["message"].lower()

    def test_downstream_error_tracked_in_metrics(self, client, mock_services):
        mock_services["gateway_service"].validate_jsonrpc_request.return_value = None
        mock_services["gateway_service"].is_streaming_method.return_value = False

        agent = MagicMock(endpoint_url="https://downstream.com/a2a")
        agent._gateway_endpoint_url = "https://downstream.com/a2a"
        mock_services["gateway_service"].resolve_agent.return_value = (agent, {}, None)

        mock_services["client_service"].send_jsonrpc = AsyncMock(
            return_value={"jsonrpc": "2.0", "error": {"code": -32603, "message": "Internal error"}, "id": 1}
        )

        response = client.post(
            f"{_PREFIX}/abc123",
            json={"jsonrpc": "2.0", "method": "message/send", "params": {}, "id": 1},
        )

        assert response.status_code == 200
        assert "error" in response.json()


class TestGetAuthenticatedCard:
    """Tests for agent/getAuthenticatedExtendedCard method."""

    def test_authenticated_card_success(self, client, mock_services):
        mock_services["gateway_service"].validate_jsonrpc_request.return_value = None

        agent = MagicMock()
        mock_services["gateway_service"].resolve_agent.return_value = (agent, {}, None)
        mock_services["gateway_service"].generate_agent_card.return_value = {"name": "Echo", "url": f"https://gw.com{_PREFIX}/abc123"}

        response = client.post(
            f"{_PREFIX}/abc123",
            json={"jsonrpc": "2.0", "method": "agent/getAuthenticatedExtendedCard", "params": {}, "id": 1},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["result"]["name"] == "Echo"

    def test_authenticated_card_agent_not_found(self, client, mock_services):
        mock_services["gateway_service"].validate_jsonrpc_request.return_value = None
        mock_services["gateway_service"].resolve_agent.side_effect = A2AGatewayAgentNotFoundError("not found")

        response = client.post(
            f"{_PREFIX}/nonexistent",
            json={"jsonrpc": "2.0", "method": "agent/getAuthenticatedExtendedCard", "params": {}, "id": 1},
        )

        assert response.status_code == 200
        assert "error" in response.json()


class TestDenyPaths:
    """Deny-path regression tests for access control.

    Per CLAUDE.md: security-sensitive changes must include deny-path regression tests
    for wrong team, insufficient permissions, feature disabled, etc.
    """

    def test_access_denied_returns_404_not_403_agent_card(self, client, mock_services):
        """Access denied for agent card should return 404 to avoid leaking existence."""
        mock_services["gateway_service"].resolve_agent.side_effect = A2AGatewayAgentNotFoundError("not found")

        response = client.get(f"{_PREFIX}/private-agent-id/.well-known/agent-card.json")
        assert response.status_code == 404
        # Must NOT be 403 — would reveal agent exists
        assert response.status_code != 403

    def test_access_denied_returns_jsonrpc_error_not_403_jsonrpc(self, client, mock_services):
        """Access denied for JSON-RPC should return JSON-RPC error with HTTP 200, not 403."""
        mock_services["gateway_service"].validate_jsonrpc_request.return_value = None
        mock_services["gateway_service"].resolve_agent.side_effect = A2AGatewayAgentNotFoundError("not found")

        response = client.post(
            f"{_PREFIX}/private-agent-id",
            json={"jsonrpc": "2.0", "method": "message/send", "params": {}, "id": 1},
        )
        # JSON-RPC: errors are returned as HTTP 200 with error in body
        assert response.status_code == 200
        data = response.json()
        assert "error" in data
        assert "not found" in data["error"]["message"].lower()

    def test_gateway_error_returns_jsonrpc_internal_error(self, client, mock_services):
        """Generic A2AGatewayError should return JSON-RPC internal error."""
        mock_services["gateway_service"].validate_jsonrpc_request.return_value = None
        mock_services["gateway_service"].resolve_agent.side_effect = A2AGatewayError("auth decryption failed")

        response = client.post(
            f"{_PREFIX}/abc123",
            json={"jsonrpc": "2.0", "method": "message/send", "params": {}, "id": 1},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["error"]["code"] == -32603

    def test_wrong_team_token_denied_via_resolve(self, client, mock_services):
        """Wrong team token should result in agent not found (not 403)."""
        # Simulate _get_rpc_filter_context returning wrong team
        with patch(
            "mcpgateway.routers.a2a_gateway._get_rpc_filter_context",
            return_value=("user@wrong-team.com", ["wrong-team"], False),
        ):
            mock_services["gateway_service"].validate_jsonrpc_request.return_value = None
            # resolve_agent raises NotFound when team doesn't match (returns 404, not 403)
            mock_services["gateway_service"].resolve_agent.side_effect = A2AGatewayAgentNotFoundError("not found")

            response = client.post(
                f"{_PREFIX}/team-agent-id",
                json={"jsonrpc": "2.0", "method": "message/send", "params": {}, "id": 1},
            )

            assert response.status_code == 200
            assert "not found" in response.json()["error"]["message"].lower()

    def test_public_only_token_denied_for_private_agent(self, client, mock_services):
        """Public-only token (empty teams) should not access private agents."""
        with patch(
            "mcpgateway.routers.a2a_gateway._get_rpc_filter_context",
            return_value=("user@example.com", [], False),
        ):
            mock_services["gateway_service"].validate_jsonrpc_request.return_value = None
            mock_services["gateway_service"].resolve_agent.side_effect = A2AGatewayAgentNotFoundError("not found")

            response = client.post(
                f"{_PREFIX}/private-agent-id",
                json={"jsonrpc": "2.0", "method": "tasks/get", "params": {}, "id": 1},
            )

            assert response.status_code == 200
            assert "error" in response.json()

    def test_disabled_agent_card_returns_400(self, client, mock_services):
        """Disabled agent via agent card endpoint returns 400 (not 404 or 500)."""
        mock_services["gateway_service"].resolve_agent.side_effect = A2AGatewayAgentDisabledError("agent disabled")

        response = client.get(f"{_PREFIX}/disabled-agent-id/.well-known/agent-card.json")
        assert response.status_code == 400

    def test_disabled_agent_jsonrpc_returns_error(self, client, mock_services):
        """Disabled agent via JSON-RPC returns JSON-RPC error (not HTTP error)."""
        mock_services["gateway_service"].validate_jsonrpc_request.return_value = None
        mock_services["gateway_service"].resolve_agent.side_effect = A2AGatewayAgentDisabledError("agent disabled")

        response = client.post(
            f"{_PREFIX}/disabled-agent-id",
            json={"jsonrpc": "2.0", "method": "message/send", "params": {}, "id": 1},
        )

        assert response.status_code == 200
        data = response.json()
        assert "error" in data
        assert "disabled" in data["error"]["message"].lower()


class TestAgentTypeCompatibility:
    """Tests for agent type validation — A2A gateway only works with JSON-RPC agents."""

    def test_incompatible_agent_card_returns_400(self, client, mock_services):
        """Agent card for non-JSON-RPC agent type returns 400."""
        mock_services["gateway_service"].resolve_agent.side_effect = A2AGatewayAgentIncompatibleError(
            "Agent 'OpenAI Bot' (type: openai) is not compatible with the A2A protocol gateway."
        )

        response = client.get(f"{_PREFIX}/openai-agent/.well-known/agent-card.json")
        assert response.status_code == 400
        assert "not compatible" in response.json()["detail"].lower()

    def test_incompatible_agent_jsonrpc_returns_error(self, client, mock_services):
        """JSON-RPC to non-JSON-RPC agent returns JSON-RPC error with clear message."""
        mock_services["gateway_service"].validate_jsonrpc_request.return_value = None
        mock_services["gateway_service"].resolve_agent.side_effect = A2AGatewayAgentIncompatibleError(
            "Agent 'Anthropic Bot' (type: anthropic) is not compatible with the A2A protocol gateway. "
            "Only 'generic' or 'jsonrpc' agent types support JSON-RPC 2.0. "
            "Use MCP tool wrapping to interact with this agent."
        )

        response = client.post(
            f"{_PREFIX}/anthropic-agent",
            json={"jsonrpc": "2.0", "method": "message/send", "params": {}, "id": 1},
        )

        assert response.status_code == 200
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == -32603
        assert "not compatible" in data["error"]["message"].lower()
        assert "mcp tool wrapping" in data["error"]["message"].lower()

    def test_incompatible_custom_agent_returns_error(self, client, mock_services):
        """Custom agent type returns incompatible error."""
        mock_services["gateway_service"].validate_jsonrpc_request.return_value = None
        mock_services["gateway_service"].resolve_agent.side_effect = A2AGatewayAgentIncompatibleError(
            "Agent 'Custom API' (type: custom) is not compatible"
        )

        response = client.post(
            f"{_PREFIX}/custom-agent",
            json={"jsonrpc": "2.0", "method": "tasks/get", "params": {}, "id": 2},
        )

        assert response.status_code == 200
        assert "error" in response.json()
        assert "not compatible" in response.json()["error"]["message"].lower()
