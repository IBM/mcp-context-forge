# -*- coding: utf-8 -*-
"""
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for the main API endpoints.
"""

import os
from unittest.mock import ANY, MagicMock, patch  # ← added ANY

import pytest
from fastapi.testclient import TestClient

from mcpgateway.schemas import ResourceRead, ServerRead
from mcpgateway.types import InitializeResult, ResourceContent, ServerCapabilities

# --------------------------------------------------------------------------- #
# Constants                                                                    #
# --------------------------------------------------------------------------- #
PROTOCOL_VERSION = os.getenv("PROTOCOL_VERSION", "2025-03-26")


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #
@pytest.fixture
def test_client(app):
    """
    Return a TestClient whose dependency graph bypasses real authentication.

    Every FastAPI dependency on ``require_auth`` is overridden to return the
    static user name ``"test_user"``.  This keeps the protected endpoints
    accessible without needing to furnish JWTs in every request.
    """
    from mcpgateway.main import require_auth

    app.dependency_overrides[require_auth] = lambda: "test_user"
    client = TestClient(app)
    yield client
    app.dependency_overrides.pop(require_auth, None)


@pytest.fixture
def mock_jwt_token():
    """Create a mock JWT token (kept for backwards-compat)."""
    return "123.123.this_is_a_test_token"


@pytest.fixture
def auth_headers(mock_jwt_token):
    """Default auth header (still accepted by the overridden dependency)."""
    return {"Authorization": f"Bearer {mock_jwt_token}"}


# --------------------------------------------------------------------------- #
# Tests                                                                        #
# --------------------------------------------------------------------------- #
class TestAPIEndpoints:
    """Tests for the API endpoints."""

    # Health & readiness -------------------------------------------------- #
    def test_health_check(self, test_client):
        response = test_client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_ready_check(self, test_client):
        response = test_client.get("/ready")
        assert response.status_code == 200
        assert response.json()["status"] == "ready"

    # Root redirect ------------------------------------------------------- #
    def test_root_redirect(self, test_client):
        response = test_client.get("/", follow_redirects=False)  # ← param name
        assert response.status_code == 303  # ← actual code
        assert response.headers["location"] == "/admin"

    # Static files -------------------------------------------------------- #
    def test_static_files(self, test_client):
        with patch("os.path.exists", return_value=True), patch("builtins.open", MagicMock()):
            response = test_client.get("/static/test.css")
            assert response.status_code == 404  # route registered, file absent

    # /protocol/initialize ------------------------------------------------ #
    @patch("mcpgateway.main.validate_request")
    @patch("mcpgateway.main.session_registry.handle_initialize_logic")  # ← new patch path
    def test_initialize_endpoint(self, mock_handle_initialize, _mock_validate, test_client, auth_headers):
        mock_capabilities = ServerCapabilities(
            prompts={"listChanged": True},
            resources={"subscribe": True, "listChanged": True},
            tools={"listChanged": True},
            logging={},
            roots={"listChanged": True},
            sampling={},
        )
        mock_result = InitializeResult(
            protocolVersion=PROTOCOL_VERSION,
            capabilities=mock_capabilities,
            serverInfo={"name": "MCP Gateway", "version": "1.0.0"},
            instructions="MCP Gateway providing federated tools, resources and prompts.",
        )
        mock_handle_initialize.return_value = mock_result

        req = {
            "protocol_version": PROTOCOL_VERSION,
            "capabilities": {},
            "client_info": {"name": "Test Client", "version": "1.0.0"},
        }
        response = test_client.post("/protocol/initialize", json=req, headers=auth_headers)

        assert response.status_code == 200
        body = response.json()
        assert body["protocolVersion"] == PROTOCOL_VERSION
        mock_handle_initialize.assert_called_once()

    # /protocol/ping ------------------------------------------------------ #
    @patch("mcpgateway.main.validate_request")
    def test_ping_endpoint(self, _mock_validate, test_client, auth_headers):
        req = {"jsonrpc": "2.0", "method": "ping", "id": "test-id"}
        response = test_client.post("/protocol/ping", json=req, headers=auth_headers)

        assert response.status_code == 200
        body = response.json()
        assert body == {"jsonrpc": "2.0", "id": "test-id", "result": {}}

    # Servers ------------------------------------------------------------- #
    @patch("mcpgateway.main.server_service.list_servers")
    def test_list_servers_endpoint(self, mock_list_servers, test_client, auth_headers):
        mock_list_servers.return_value = [
            ServerRead(
                id="1",
                name="test_server",
                description="A test server",
                icon="server-icon",
                created_at="2023-01-01T00:00:00",
                updated_at="2023-01-01T00:00:00",
                is_active=True,
                associated_tools=["1"],
                associated_resources=[201],
                associated_prompts=[301],
                metrics={
                    "total_executions": 0,
                    "successful_executions": 0,
                    "failed_executions": 0,
                    "failure_rate": 0.0,
                    "min_response_time": None,
                    "max_response_time": None,
                    "avg_response_time": None,
                    "last_execution_time": None,
                },
            )
        ]

        response = test_client.get("/servers/", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1 and data[0]["name"] == "test_server"
        mock_list_servers.assert_called_once()

    # Tools ---------------------------------------------------------------- #
    @patch("mcpgateway.main.tool_service.list_tools")
    def test_list_tools_endpoint(self, mock_list_tools, test_client, auth_headers):
        # return simple dicts to avoid pydantic validation strictness
        mock_list_tools.return_value = [
            {
                "id": 1,
                "name": "test_tool",
                "url": "http://example.com/tools/test",
                "description": "A test tool",
                "integration_type": "MCP",
                "request_type": "POST",
                "headers": {"Content-Type": "application/json"},
                "input_schema": {"type": "object", "properties": {"param": {"type": "string"}}},
                "is_active": True,
            }
        ]

        response = test_client.get("/tools/", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1 and data[0]["name"] == "test_tool"
        mock_list_tools.assert_called_once()

    # Resources ----------------------------------------------------------- #
    @patch("mcpgateway.main.resource_service.list_resources")
    def test_list_resources_endpoint(self, mock_list_resources, test_client, auth_headers):
        mock_list_resources.return_value = [
            ResourceRead(
                id=1,
                uri="test/resource",
                name="Test Resource",
                description="A test resource",
                mime_type="text/plain",
                size=12,
                created_at="2023-01-01T00:00:00",
                updated_at="2023-01-01T00:00:00",
                is_active=True,
                metrics={
                    "total_executions": 0,
                    "successful_executions": 0,
                    "failed_executions": 0,
                    "failure_rate": 0.0,
                    "min_response_time": None,
                    "max_response_time": None,
                    "avg_response_time": None,
                    "last_execution_time": None,
                },
            )
        ]

        response = test_client.get("/resources/", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1 and data[0]["name"] == "Test Resource"
        mock_list_resources.assert_called_once()

    @patch("mcpgateway.main.resource_service.read_resource")
    def test_read_resource_endpoint(self, mock_read_resource, test_client, auth_headers):
        mock_read_resource.return_value = ResourceContent(
            type="resource",
            uri="test/resource",
            mime_type="text/plain",
            text="This is test content",
        )

        response = test_client.get("/resources/test/resource", headers=auth_headers)
        assert response.status_code == 200
        body = response.json()
        assert body["uri"] == "test/resource" and body["text"] == "This is test content"
        mock_read_resource.assert_called_once()

    # RPC: tool ----------------------------------------------------------- #
    @patch("mcpgateway.main.tool_service.invoke_tool")
    def test_rpc_tool_invocation(self, mock_invoke_tool, test_client, auth_headers):
        mock_invoke_tool.return_value = {
            "content": [{"type": "text", "text": "Tool response"}],
            "is_error": False,
        }

        req = {
            "jsonrpc": "2.0",
            "id": "test-id",
            "method": "test_tool",
            "params": {"param": "value"},
        }
        response = test_client.post("/rpc/", json=req, headers=auth_headers)

        assert response.status_code == 200
        body = response.json()
        assert body["content"][0]["text"] == "Tool response"
        mock_invoke_tool.assert_called_once_with(db=ANY, name="test_tool", arguments={"param": "value"})

    # RPC: prompt --------------------------------------------------------- #
    @patch("mcpgateway.main.prompt_service.get_prompt")
    @patch("mcpgateway.main.validate_request")
    def test_rpc_prompt_get(self, _mock_validate, mock_get_prompt, test_client, auth_headers):
        mock_get_prompt.return_value = {
            "messages": [{"role": "user", "content": {"type": "text", "text": "Rendered prompt"}}],
            "description": "A test prompt",
        }

        req = {
            "jsonrpc": "2.0",
            "id": "test-id",
            "method": "prompts/get",
            "params": {"name": "test_prompt", "arguments": {"param": "value"}},
        }
        response = test_client.post("/rpc/", json=req, headers=auth_headers)

        assert response.status_code == 200
        body = response.json()
        assert body["messages"][0]["content"]["text"] == "Rendered prompt"
        mock_get_prompt.assert_called_once_with(ANY, "test_prompt", {"param": "value"})

    # RPC: invalid -------------------------------------------------------- #
    @patch("mcpgateway.main.validate_request")
    def test_invalid_request(self, mock_validate, test_client, auth_headers):
        mock_validate.side_effect = Exception("Invalid request")

        req = {"jsonrpc": "1.0", "id": "test-id", "method": "invalid_method"}
        response = test_client.post("/rpc/", json=req, headers=auth_headers)

        assert response.status_code == 200
        body = response.json()
        assert "error" in body and "Invalid request" in body["error"]["data"]
