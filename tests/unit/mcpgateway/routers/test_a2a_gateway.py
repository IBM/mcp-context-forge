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
        mock_services["gateway_service"].resolve_agent.return_value = (agent, {})
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
        mock_services["gateway_service"].resolve_agent.return_value = (agent, {"Authorization": "Bearer tok"})

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
        mock_services["gateway_service"].resolve_agent.return_value = (agent, {})

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
        mock_services["gateway_service"].resolve_agent.return_value = (agent, {})
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
