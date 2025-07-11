# -*- coding: utf-8 -*-
"""
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Comprehensive tests for the main API endpoints with full coverage.
"""

# Standard
from copy import deepcopy
import json
import os
from unittest.mock import ANY, MagicMock, patch

# Third-Party
from fastapi.testclient import TestClient
import pytest

# First-Party
from mcpgateway.config import settings
from mcpgateway.models import InitializeResult, ResourceContent, ServerCapabilities
from mcpgateway.schemas import (
    PromptRead,
    ResourceRead,
    ServerRead,
)

# --------------------------------------------------------------------------- #
# Constants                                                                   #
# --------------------------------------------------------------------------- #
PROTOCOL_VERSION = os.getenv("PROTOCOL_VERSION", "2025-03-26")

# Mock data templates with complete field structures
MOCK_METRICS = {
    "total_executions": 10,
    "successful_executions": 8,
    "failed_executions": 2,
    "failure_rate": 0.2,
    "min_response_time": 0.1,
    "max_response_time": 2.5,
    "avg_response_time": 1.2,
    "last_execution_time": "2023-01-01T00:00:00+00:00",
}

MOCK_SERVER_READ = {
    "id": "1",
    "name": "test_server",
    "description": "A test server",
    "icon": "server-icon",
    "created_at": "2023-01-01T00:00:00+00:00",
    "updated_at": "2023-01-01T00:00:00+00:00",
    "is_active": True,
    "associated_tools": ["101"],
    "associated_resources": [201],
    "associated_prompts": [301],
    "metrics": MOCK_METRICS,
}

MOCK_TOOL_READ = {
    "id": "1",
    "name": "test_tool",
    "originalName": "test_tool",
    "url": "http://example.com/tools/test",
    "description": "A test tool",
    "requestType": "POST",
    "integrationType": "MCP",
    "headers": {"Content-Type": "application/json"},
    "inputSchema": {"type": "object", "properties": {"param": {"type": "string"}}},
    "annotations": {},
    "jsonpathFilter": None,
    "auth": {"auth_type": "none"},
    "createdAt": "2023-01-01T00:00:00+00:00",
    "updatedAt": "2023-01-01T00:00:00+00:00",
    "enabled": True,
    "reachable": True,
    "gatewayId": "gateway-1",
    "executionCount": 5,
    "metrics": MOCK_METRICS,
    "gatewaySlug": "gateway-1",
    "originalNameSlug": "test-tool",
}

# camelCase → snake_case key map for the fields that differ
_TOOL_KEY_MAP = {
    "originalName": "original_name",
    "requestType": "request_type",
    "integrationType": "integration_type",
    "inputSchema": "input_schema",
    "jsonpathFilter": "jsonpath_filter",
    "createdAt": "created_at",
    "updatedAt": "updated_at",
    "gatewayId": "gateway_id",
    "gatewaySlug": "gateway_slug",
    "originalNameSlug": "original_name_slug",
}


def camel_to_snake_tool(d: dict) -> dict:
    out = deepcopy(d)
    # id must be str
    out["id"] = str(out["id"])
    for camel, snake in _TOOL_KEY_MAP.items():
        if camel in out:
            out[snake] = out.pop(camel)
    return out


MOCK_TOOL_READ_SNAKE = camel_to_snake_tool(MOCK_TOOL_READ)


MOCK_RESOURCE_READ = {
    "id": 1,
    "uri": "test/resource",
    "name": "Test Resource",
    "description": "A test resource",
    "mime_type": "text/plain",
    "size": 12,
    "created_at": "2023-01-01T00:00:00+00:00",
    "updated_at": "2023-01-01T00:00:00+00:00",
    "is_active": True,
    "metrics": MOCK_METRICS,
}

MOCK_PROMPT_READ = {
    "id": 1,
    "name": "test_prompt",
    "description": "A test prompt",
    "template": "Hello {name}",
    "arguments": [],
    "created_at": "2023-01-01T00:00:00+00:00",
    "updated_at": "2023-01-01T00:00:00+00:00",
    "is_active": True,
    "metrics": MOCK_METRICS,
}

MOCK_GATEWAY_READ = {
    "id": "1",
    "name": "test_gateway",
    "url": "http://example.com",
    "description": "A test gateway",
    "transport": "SSE",
    "auth_type": "none",
    "created_at": "2023-01-01T00:00:00+00:00",
    "updated_at": "2023-01-01T00:00:00+00:00",
    "enabled": True,
    "reachable": True,
}

MOCK_ROOT = {
    "uri": "/test",
    "name": "Test Root",
}


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #
@pytest.fixture
def test_client(app):
    """
    Return a TestClient whose dependency graph bypasses real authentication.

    Every FastAPI dependency on ``require_auth`` is overridden to return the
    static user name ``"test_user"``.  This keeps the protected endpoints
    accessible without needing to furnish JWTs in every request.
    """
    # First-Party
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


# ========================================================================== #
#                                  TEST CLASSES                              #
# ========================================================================== #


# ----------------------------------------------------- #
# Health & Infrastructure Tests                         #
# ----------------------------------------------------- #
class TestHealthAndInfrastructure:
    """Tests for health checks, readiness, and basic infrastructure endpoints."""

    def test_health_check(self, test_client):
        """Test the basic health check endpoint."""
        response = test_client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_ready_check(self, test_client):
        """Test the readiness check endpoint."""
        response = test_client.get("/ready")
        assert response.status_code == 200
        assert response.json()["status"] == "ready"

    def test_root_redirect(self, test_client):
        """Test that root path behavior depends on UI configuration."""
        response = test_client.get("/", follow_redirects=False)

        # Check if UI is enabled
        if settings.mcpgateway_ui_enabled:
            # When UI is enabled, should redirect to admin
            assert response.status_code == 303
            assert response.headers["location"] == "/admin"
        else:
            # When UI is disabled, should return API info
            assert response.status_code == 200
            data = response.json()
            assert data["name"] == "MCP_Gateway"
            assert data["ui_enabled"] is False

    def test_static_files(self, test_client):
        """Test static file serving (when files don't exist)."""
        with patch("os.path.exists", return_value=True), patch("builtins.open", MagicMock()):
            response = test_client.get("/static/test.css")
            assert response.status_code == 404  # route registered, file absent


# ----------------------------------------------------- #
# Protocol & MCP Core Tests                             #
# ----------------------------------------------------- #
class TestProtocolEndpoints:
    """Tests for MCP protocol operations: initialize, ping, notifications, etc."""

    @patch("mcpgateway.main.validate_request")
    @patch("mcpgateway.main.session_registry.handle_initialize_logic")
    def test_initialize_endpoint(self, mock_handle_initialize, _mock_validate, test_client, auth_headers):
        """Test MCP protocol initialization."""
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

    @patch("mcpgateway.main.validate_request")
    def test_ping_endpoint(self, _mock_validate, test_client, auth_headers):
        """Test MCP ping endpoint."""
        req = {"jsonrpc": "2.0", "method": "ping", "id": "test-id"}
        response = test_client.post("/protocol/ping", json=req, headers=auth_headers)

        assert response.status_code == 200
        body = response.json()
        assert body == {"jsonrpc": "2.0", "id": "test-id", "result": {}}

    def test_ping_invalid_method(self, test_client, auth_headers):
        """Test ping endpoint with invalid method."""
        req = {"jsonrpc": "2.0", "method": "invalid", "id": "test-id"}
        response = test_client.post("/protocol/ping", json=req, headers=auth_headers)
        # Implementation raises 5xx for unsupported method
        assert response.status_code == 500

    @patch("mcpgateway.main.logging_service.notify")
    def test_handle_notification_initialized(self, mock_notify, test_client, auth_headers):
        """Test handling client initialized notification."""
        req = {"method": "notifications/initialized"}
        response = test_client.post("/protocol/notifications", json=req, headers=auth_headers)
        assert response.status_code == 200
        mock_notify.assert_called_once()

    @patch("mcpgateway.main.logging_service.notify")
    def test_handle_notification_cancelled(self, mock_notify, test_client, auth_headers):
        """Test handling request cancelled notification."""
        req = {"method": "notifications/cancelled", "params": {"requestId": "123"}}
        response = test_client.post("/protocol/notifications", json=req, headers=auth_headers)
        assert response.status_code == 200
        mock_notify.assert_called_once()

    @patch("mcpgateway.main.logging_service.notify")
    def test_handle_notification_message(self, mock_notify, test_client, auth_headers):
        """Test handling log message notification."""
        req = {
            "method": "notifications/message",
            "params": {"data": "Test message", "level": "info", "logger": "test"},
        }
        response = test_client.post("/protocol/notifications", json=req, headers=auth_headers)
        assert response.status_code == 200
        mock_notify.assert_called_once()

    @patch("mcpgateway.main.completion_service.handle_completion")
    def test_handle_completion_endpoint(self, mock_completion, test_client, auth_headers):
        """Test completion handling endpoint."""
        mock_completion.return_value = {"result": "completion_result"}
        req = {"ref": {"type": "ref/prompt", "name": "test"}}
        response = test_client.post("/protocol/completion/complete", json=req, headers=auth_headers)
        assert response.status_code == 200
        mock_completion.assert_called_once()

    @patch("mcpgateway.main.sampling_handler.create_message")
    def test_handle_sampling_endpoint(self, mock_sampling, test_client, auth_headers):
        """Test sampling message creation endpoint."""
        mock_sampling.return_value = {"messageId": "123"}
        req = {"messages": [{"role": "user", "content": {"type": "text", "text": "Hello"}}]}
        response = test_client.post("/protocol/sampling/createMessage", json=req, headers=auth_headers)
        assert response.status_code == 200
        mock_sampling.assert_called_once()


# ----------------------------------------------------- #
# Server Management Tests                               #
# ----------------------------------------------------- #
class TestServerEndpoints:
    """Tests for virtual server management: CRUD operations, status toggles, etc."""

    @patch("mcpgateway.main.server_service.list_servers")
    def test_list_servers_endpoint(self, mock_list_servers, test_client, auth_headers):
        """Test listing all servers."""
        mock_list_servers.return_value = [ServerRead(**MOCK_SERVER_READ)]

        response = test_client.get("/servers/", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1 and data[0]["name"] == "test_server"
        mock_list_servers.assert_called_once()

    @patch("mcpgateway.main.server_service.get_server")
    def test_get_server_endpoint(self, mock_get, test_client, auth_headers):
        """Test retrieving a specific server."""
        mock_get.return_value = ServerRead(**MOCK_SERVER_READ)
        response = test_client.get("/servers/1", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["name"] == "test_server"
        mock_get.assert_called_once()

    @patch("mcpgateway.main.server_service.register_server")
    def test_create_server_endpoint(self, mock_create, test_client, auth_headers):
        """Test creating a new server."""
        mock_create.return_value = ServerRead(**MOCK_SERVER_READ)
        req = {"name": "test_server", "description": "A test server"}
        response = test_client.post("/servers/", json=req, headers=auth_headers)
        assert response.status_code == 201
        mock_create.assert_called_once()

    @patch("mcpgateway.main.server_service.update_server")
    def test_update_server_endpoint(self, mock_update, test_client, auth_headers):
        """Test updating an existing server."""
        mock_update.return_value = ServerRead(**MOCK_SERVER_READ)
        req = {"description": "Updated description"}
        response = test_client.put("/servers/1", json=req, headers=auth_headers)
        assert response.status_code == 200
        mock_update.assert_called_once()

    @patch("mcpgateway.main.server_service.toggle_server_status")
    def test_toggle_server_status(self, mock_toggle, test_client, auth_headers):
        """Test toggling server active/inactive status."""
        updated_server = MOCK_SERVER_READ.copy()
        updated_server["is_active"] = False
        mock_toggle.return_value = ServerRead(**updated_server)
        response = test_client.post("/servers/1/toggle?activate=false", headers=auth_headers)
        assert response.status_code == 200
        mock_toggle.assert_called_once()

    @patch("mcpgateway.main.server_service.delete_server")
    def test_delete_server_endpoint(self, mock_delete, test_client, auth_headers):
        """Test permanently deleting a server."""
        mock_delete.return_value = None
        response = test_client.delete("/servers/1", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["status"] == "success"

    @patch("mcpgateway.main.tool_service.list_server_tools")
    def test_server_get_tools(self, mock_list_tools, test_client, auth_headers):
        """Test listing tools associated with a server."""
        mock_tool = MagicMock()
        mock_tool.model_dump.return_value = MOCK_TOOL_READ
        mock_list_tools.return_value = [mock_tool]

        response = test_client.get("/servers/1/tools", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        mock_list_tools.assert_called_once()

    @patch("mcpgateway.main.resource_service.list_server_resources")
    def test_server_get_resources(self, mock_list_resources, test_client, auth_headers):
        """Test listing resources associated with a server."""
        mock_resource = MagicMock()
        mock_resource.model_dump.return_value = MOCK_RESOURCE_READ
        mock_list_resources.return_value = [mock_resource]

        response = test_client.get("/servers/1/resources", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        mock_list_resources.assert_called_once()

    @patch("mcpgateway.main.prompt_service.list_server_prompts")
    def test_server_get_prompts(self, mock_list_prompts, test_client, auth_headers):
        """Test listing prompts associated with a server."""
        # First-Party
        from mcpgateway.schemas import PromptRead

        mock_list_prompts.return_value = [PromptRead(**MOCK_PROMPT_READ)]

        response = test_client.get("/servers/1/prompts", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        mock_list_prompts.assert_called_once()


# ----------------------------------------------------- #
# Tool Management Tests                                 #
# ----------------------------------------------------- #
class TestToolEndpoints:
    """Tests for tool management: registration, invocation, updates, etc."""

    @patch("mcpgateway.main.tool_service.list_tools")
    def test_list_tools_endpoint(self, mock_list_tools, test_client, auth_headers):
        """Test listing all registered tools."""
        mock_list_tools.return_value = [MOCK_TOOL_READ]

        response = test_client.get("/tools/", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1 and data[0]["name"] == "test_tool"
        mock_list_tools.assert_called_once()

    @patch("mcpgateway.main.tool_service.register_tool")
    def test_create_tool_endpoint(self, mock_create, test_client, auth_headers):
        mock_create.return_value = MOCK_TOOL_READ_SNAKE
        req = {"name": "test_tool", "url": "http://example.com", "description": "A test tool"}
        response = test_client.post("/tools/", json=req, headers=auth_headers)
        assert response.status_code == 200
        mock_create.assert_called_once()

    @patch("mcpgateway.main.tool_service.get_tool")
    def test_get_tool_endpoint(self, mock_get, test_client, auth_headers):
        mock_get.return_value = MOCK_TOOL_READ_SNAKE
        response = test_client.get("/tools/1", headers=auth_headers)
        assert response.status_code == 200
        mock_get.assert_called_once()

    @patch("mcpgateway.main.tool_service.update_tool")
    def test_update_tool_endpoint(self, mock_update, test_client, auth_headers):
        updated = {**MOCK_TOOL_READ_SNAKE, "description": "Updated description"}
        mock_update.return_value = updated
        req = {"description": "Updated description"}
        response = test_client.put("/tools/1", json=req, headers=auth_headers)
        assert response.status_code == 200
        mock_update.assert_called_once()

    @patch("mcpgateway.main.tool_service.toggle_tool_status")
    def test_toggle_tool_status(self, mock_toggle, test_client, auth_headers):
        """Test toggling tool active/inactive status."""
        mock_tool = MagicMock()
        mock_tool.model_dump.return_value = {"id": 1, "name": "test", "is_active": False}
        mock_toggle.return_value = mock_tool
        response = test_client.post("/tools/1/toggle?activate=false", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["status"] == "success"

    @patch("mcpgateway.main.tool_service.delete_tool")
    def test_delete_tool_endpoint(self, mock_delete, test_client, auth_headers):
        """Test permanently deleting a tool."""
        mock_delete.return_value = None
        response = test_client.delete("/tools/1", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["status"] == "success"


# ----------------------------------------------------- #
# Resource Management Tests                             #
# ----------------------------------------------------- #
class TestResourceEndpoints:
    """Tests for resource management: reading, creation, caching, etc."""

    @patch("mcpgateway.main.resource_service.list_resources")
    def test_list_resources_endpoint(self, mock_list_resources, test_client, auth_headers):
        """Test listing all available resources."""
        mock_list_resources.return_value = [ResourceRead(**MOCK_RESOURCE_READ)]

        response = test_client.get("/resources/", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1 and data[0]["name"] == "Test Resource"
        mock_list_resources.assert_called_once()

    @patch("mcpgateway.main.resource_service.register_resource")
    def test_create_resource_endpoint(self, mock_create, test_client, auth_headers):
        """Test registering a new resource."""
        mock_create.return_value = ResourceRead(**MOCK_RESOURCE_READ)

        req = {"uri": "test/resource", "name": "Test Resource", "description": "A test resource", "content": "Hello world"}  # ← required field
        response = test_client.post("/resources/", json=req, headers=auth_headers)

        assert response.status_code == 200  # route returns 200 on success
        mock_create.assert_called_once()

    @patch("mcpgateway.main.resource_service.read_resource")
    def test_read_resource_endpoint(self, mock_read_resource, test_client, auth_headers):
        """Test reading resource content."""
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

    @patch("mcpgateway.main.resource_service.update_resource")
    def test_update_resource_endpoint(self, mock_update, test_client, auth_headers):
        """Test updating an existing resource."""
        mock_update.return_value = ResourceRead(**MOCK_RESOURCE_READ)
        req = {"description": "Updated description"}
        response = test_client.put("/resources/test/resource", json=req, headers=auth_headers)
        assert response.status_code == 200
        mock_update.assert_called_once()

    @patch("mcpgateway.main.resource_service.delete_resource")
    def test_delete_resource_endpoint(self, mock_delete, test_client, auth_headers):
        """Test deleting a resource."""
        mock_delete.return_value = None
        response = test_client.delete("/resources/test/resource", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["status"] == "success"

    @patch("mcpgateway.main.resource_service.list_resource_templates")
    def test_list_resource_templates(self, mock_list, test_client, auth_headers):
        """Test listing available resource templates."""
        mock_list.return_value = []
        response = test_client.get("/resources/templates/list", headers=auth_headers)
        assert response.status_code == 200
        mock_list.assert_called_once()

    @patch("mcpgateway.main.resource_service.toggle_resource_status")
    def test_toggle_resource_status(self, mock_toggle, test_client, auth_headers):
        """Test toggling resource active/inactive status."""
        mock_resource = MagicMock()
        mock_resource.model_dump.return_value = {"id": 1, "is_active": False}
        mock_toggle.return_value = mock_resource
        response = test_client.post("/resources/1/toggle?activate=false", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["status"] == "success"

    @patch("mcpgateway.main.resource_service.subscribe_events")
    def test_subscribe_resource_events(self, mock_subscribe, test_client, auth_headers):
        """Test subscribing to resource change events via SSE."""
        mock_subscribe.return_value = iter(["data: test\n\n"])
        response = test_client.post("/resources/subscribe/test/resource", headers=auth_headers)
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"


# ----------------------------------------------------- #
# Prompt Management Tests                               #
# ----------------------------------------------------- #
class TestPromptEndpoints:
    """Tests for prompt template management: creation, rendering, arguments, etc."""

    @patch("mcpgateway.main.prompt_service.list_prompts")
    def test_list_prompts_endpoint(self, mock_list_prompts, test_client, auth_headers):
        """Test listing all available prompts."""
        mock_list_prompts.return_value = [MOCK_PROMPT_READ]
        response = test_client.get("/prompts/", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        mock_list_prompts.assert_called_once()

    @patch("mcpgateway.main.prompt_service.register_prompt")
    def test_create_prompt_endpoint(self, mock_create, test_client, auth_headers):
        """Test creating a new prompt template."""
        # Return an actual model instance
        mock_create.return_value = PromptRead(**MOCK_PROMPT_READ)

        req = {"name": "test_prompt", "template": "Hello {name}", "description": "A test prompt"}
        response = test_client.post("/prompts/", json=req, headers=auth_headers)

        assert response.status_code == 200
        mock_create.assert_called_once()

    @patch("mcpgateway.main.prompt_service.get_prompt")
    def test_get_prompt_with_args(self, mock_get, test_client, auth_headers):
        """Test getting a prompt with template arguments."""
        mock_get.return_value = {
            "messages": [{"role": "user", "content": {"type": "text", "text": "Rendered prompt"}}],
            "description": "A test prompt",
        }
        req = {"name": "value"}
        response = test_client.post("/prompts/test_prompt", json=req, headers=auth_headers)
        assert response.status_code == 200
        body = response.json()
        assert body["messages"][0]["content"]["text"] == "Rendered prompt"
        mock_get.assert_called_once()

    @patch("mcpgateway.main.prompt_service.get_prompt")
    def test_get_prompt_no_args(self, mock_get, test_client, auth_headers):
        """Test getting a prompt without arguments."""
        mock_get.return_value = {"name": "test", "template": "Hello"}
        response = test_client.get("/prompts/test", headers=auth_headers)
        assert response.status_code == 200
        mock_get.assert_called_once_with(ANY, "test", {})

    @patch("mcpgateway.main.prompt_service.update_prompt")
    def test_update_prompt_endpoint(self, mock_update, test_client, auth_headers):
        """Test updating an existing prompt."""
        updated = {**MOCK_PROMPT_READ, "description": "Updated description"}
        mock_update.return_value = PromptRead(**updated)  # <- real model

        req = {"description": "Updated description"}
        response = test_client.put("/prompts/test_prompt", json=req, headers=auth_headers)

        assert response.status_code == 200
        mock_update.assert_called_once()

    @patch("mcpgateway.main.prompt_service.delete_prompt")
    def test_delete_prompt_endpoint(self, mock_delete, test_client, auth_headers):
        """Test deleting a prompt."""
        mock_delete.return_value = None
        response = test_client.delete("/prompts/test_prompt", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["status"] == "success"

    @patch("mcpgateway.main.prompt_service.toggle_prompt_status")
    def test_toggle_prompt_status(self, mock_toggle, test_client, auth_headers):
        """Test toggling prompt active/inactive status."""
        mock_prompt = MagicMock()
        mock_prompt.model_dump.return_value = {"id": 1, "is_active": False}
        mock_toggle.return_value = mock_prompt
        response = test_client.post("/prompts/1/toggle?activate=false", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["status"] == "success"


# ----------------------------------------------------- #
# Gateway Federation Tests                              #
# ----------------------------------------------------- #
class TestGatewayEndpoints:
    """Tests for gateway federation: registration, discovery, forwarding, etc."""

    @patch("mcpgateway.main.gateway_service.list_gateways")
    def test_list_gateways_endpoint(self, mock_list, test_client, auth_headers):
        """Test listing all registered gateways."""
        mock_list.return_value = [MOCK_GATEWAY_READ]
        response = test_client.get("/gateways/", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        mock_list.assert_called_once()

    @patch("mcpgateway.main.gateway_service.register_gateway")
    def test_create_gateway_endpoint(self, mock_create, test_client, auth_headers):
        """Test registering a new gateway."""
        mock_create.return_value = MOCK_GATEWAY_READ
        req = {"name": "test_gateway", "url": "http://example.com"}
        response = test_client.post("/gateways/", json=req, headers=auth_headers)
        assert response.status_code == 200
        mock_create.assert_called_once()

    @patch("mcpgateway.main.gateway_service.get_gateway")
    def test_get_gateway_endpoint(self, mock_get, test_client, auth_headers):
        """Test retrieving a specific gateway."""
        mock_get.return_value = MOCK_GATEWAY_READ
        response = test_client.get("/gateways/1", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["name"] == "test_gateway"
        mock_get.assert_called_once()

    @patch("mcpgateway.main.gateway_service.update_gateway")
    def test_update_gateway_endpoint(self, mock_update, test_client, auth_headers):
        """Test updating an existing gateway."""
        mock_update.return_value = MOCK_GATEWAY_READ
        req = {"description": "Updated description"}
        response = test_client.put("/gateways/1", json=req, headers=auth_headers)
        assert response.status_code == 200
        mock_update.assert_called_once()

    @patch("mcpgateway.main.gateway_service.delete_gateway")
    def test_delete_gateway_endpoint(self, mock_delete, test_client, auth_headers):
        """Test deleting a gateway."""
        mock_delete.return_value = None
        response = test_client.delete("/gateways/1", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["status"] == "success"

    @patch("mcpgateway.main.gateway_service.toggle_gateway_status")
    def test_toggle_gateway_status(self, mock_toggle, test_client, auth_headers):
        """Test toggling gateway active/inactive status."""
        mock_gateway = MagicMock()
        mock_gateway.model_dump.return_value = {"id": "1", "is_active": False}
        mock_toggle.return_value = mock_gateway
        response = test_client.post("/gateways/1/toggle?activate=false", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["status"] == "success"


# ----------------------------------------------------- #
# Root Management Tests                                 #
# ----------------------------------------------------- #
class TestRootEndpoints:
    """Tests for root directory management: registration, listing, changes, etc."""

    @patch("mcpgateway.main.root_service.list_roots")
    def test_list_roots_endpoint(self, mock_list, test_client, auth_headers):
        """Test listing all registered roots."""
        # First-Party
        from mcpgateway.models import Root

        mock_list.return_value = [Root(uri="file:///test", name="Test Root")]  # valid URI
        response = test_client.get("/roots/", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        mock_list.assert_called_once()

    @patch("mcpgateway.main.root_service.add_root")
    def test_add_root_endpoint(self, mock_add, test_client, auth_headers):
        """Test adding a new root directory."""
        # First-Party
        from mcpgateway.models import Root

        mock_add.return_value = Root(uri="file:///test", name="Test Root")  # valid URI

        req = {"uri": "file:///test", "name": "Test Root"}  # valid body
        response = test_client.post("/roots/", json=req, headers=auth_headers)

        assert response.status_code == 200
        mock_add.assert_called_once()

    @patch("mcpgateway.main.root_service.remove_root")
    def test_remove_root_endpoint(self, mock_remove, test_client, auth_headers):
        """Test removing a root directory."""
        mock_remove.return_value = None
        response = test_client.delete("/roots/%2Ftest", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["status"] == "success"

    @patch("mcpgateway.main.root_service.subscribe_changes")
    def test_subscribe_root_changes(self, mock_subscribe, test_client, auth_headers):
        """Test subscribing to root directory changes via SSE."""
        mock_subscribe.return_value = iter(["data: test\n\n"])
        response = test_client.get("/roots/changes", headers=auth_headers)
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"


# ----------------------------------------------------- #
# JSON-RPC & Utility Tests                             #
# ----------------------------------------------------- #
class TestRPCEndpoints:
    """Tests for JSON-RPC functionality and utility endpoints."""

    @patch("mcpgateway.main.tool_service.invoke_tool")
    def test_rpc_tool_invocation(self, mock_invoke_tool, test_client, auth_headers):
        """Test tool invocation via JSON-RPC."""
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

    @patch("mcpgateway.main.prompt_service.get_prompt")
    @patch("mcpgateway.main.validate_request")
    def test_rpc_prompt_get(self, _mock_validate, mock_get_prompt, test_client, auth_headers):
        """Test prompt retrieval via JSON-RPC."""
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

    @patch("mcpgateway.main.tool_service.list_tools")
    @patch("mcpgateway.main.validate_request")
    def test_rpc_list_tools(self, _mock_validate, mock_list_tools, test_client, auth_headers):
        """Test listing tools via JSON-RPC."""
        mock_tool = MagicMock()
        mock_tool.model_dump.return_value = MOCK_TOOL_READ
        mock_list_tools.return_value = [mock_tool]

        req = {
            "jsonrpc": "2.0",
            "id": "test-id",
            "method": "tools/list",
            "params": {},
        }
        response = test_client.post("/rpc/", json=req, headers=auth_headers)

        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, list)
        mock_list_tools.assert_called_once()

    @patch("mcpgateway.main.validate_request")
    def test_rpc_invalid_request(self, mock_validate, test_client, auth_headers):
        """Test RPC error handling for invalid requests."""
        mock_validate.side_effect = Exception("Invalid request")

        req = {"jsonrpc": "1.0", "id": "test-id", "method": "invalid_method"}
        response = test_client.post("/rpc/", json=req, headers=auth_headers)

        assert response.status_code == 200
        body = response.json()
        assert "error" in body and "Invalid request" in body["error"]["data"]

    def test_rpc_invalid_json(self, test_client, auth_headers):
        """Test RPC error handling for malformed JSON."""
        headers = auth_headers
        headers["content-type"] = "application/json"
        response = test_client.post("/rpc/", content="invalid json", headers=headers)
        assert response.status_code == 200  # Returns error response, not HTTP error
        body = response.json()
        assert "error" in body

    @patch("mcpgateway.main.logging_service.set_level")
    def test_set_log_level_endpoint(self, mock_set_level, test_client, auth_headers):
        """Test setting the application log level."""
        req = {"level": "debug"}  # lowercase to match enum
        response = test_client.post("/logging/setLevel", json=req, headers=auth_headers)
        assert response.status_code == 200
        mock_set_level.assert_called_once()


# ----------------------------------------------------- #
# WebSocket & SSE Tests                                 #
# ----------------------------------------------------- #
class TestRealtimeEndpoints:
    """Tests for real-time communication: WebSocket, SSE, message handling, etc."""

    @patch("mcpgateway.main.httpx.AsyncClient")  # stub network calls
    def test_websocket_endpoint(self, mock_client, test_client):
        # Standard
        from types import SimpleNamespace

        """Test WebSocket connection and message handling."""
        # ----- set up async context-manager dummy -----
        mock_instance = mock_client.return_value
        mock_instance.__aenter__.return_value = mock_instance
        mock_instance.__aexit__.return_value = False

        async def dummy_post(*_args, **_kwargs):
            # minimal object that looks like an httpx.Response
            return SimpleNamespace(text='{"jsonrpc":"2.0","id":1,"result":{}}')

        mock_instance.post = dummy_post
        # ---------------------------------------------

        with test_client.websocket_connect("/ws") as websocket:
            websocket.send_text('{"jsonrpc":"2.0","method":"ping","id":1}')
            data = websocket.receive_text()
            response = json.loads(data)
            assert response == {"jsonrpc": "2.0", "id": 1, "result": {}}

    @patch("mcpgateway.main.session_registry.add_session")
    @patch("mcpgateway.main.session_registry.respond")
    @patch("mcpgateway.main.SSETransport")
    def test_sse_endpoint(self, mock_transport_class, mock_respond, mock_add_session, test_client, auth_headers):
        """Test SSE connection establishment."""
        mock_transport = MagicMock()
        mock_transport.session_id = "test-session"
        mock_transport.create_sse_response.return_value = MagicMock()
        mock_transport_class.return_value = mock_transport

        response = test_client.get("/sse", headers=auth_headers)

        # Note: This test may need adjustment based on actual SSE implementation
        # The exact assertion will depend on how SSE responses are structured
        mock_transport_class.assert_called_once()

    @patch("mcpgateway.main.session_registry.broadcast")
    def test_message_endpoint(self, mock_broadcast, test_client, auth_headers):
        """Test message broadcasting to SSE sessions."""
        message = {"type": "test", "data": "hello"}
        response = test_client.post("/message?session_id=test-session", json=message, headers=auth_headers)
        assert response.status_code == 202
        mock_broadcast.assert_called_once()


# ----------------------------------------------------- #
# Metrics & Monitoring Tests                            #
# ----------------------------------------------------- #
class TestMetricsEndpoints:
    """Tests for metrics collection, aggregation, and reset functionality."""

    @patch("mcpgateway.main.tool_service.aggregate_metrics")
    @patch("mcpgateway.main.resource_service.aggregate_metrics")
    @patch("mcpgateway.main.server_service.aggregate_metrics")
    @patch("mcpgateway.main.prompt_service.aggregate_metrics")
    def test_get_metrics(self, mock_prompt, mock_server, mock_resource, mock_tool, test_client, auth_headers):
        """Test retrieving aggregated metrics for all entity types."""
        mock_tool.return_value = {"total": 5}
        mock_resource.return_value = {"total": 3}
        mock_server.return_value = {"total": 2}
        mock_prompt.return_value = {"total": 1}

        response = test_client.get("/metrics", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "tools" in data and "resources" in data
        assert "servers" in data and "prompts" in data

    @patch("mcpgateway.main.tool_service.reset_metrics")
    @patch("mcpgateway.main.resource_service.reset_metrics")
    @patch("mcpgateway.main.server_service.reset_metrics")
    @patch("mcpgateway.main.prompt_service.reset_metrics")
    def test_reset_all_metrics(self, mock_prompt_reset, mock_server_reset, mock_resource_reset, mock_tool_reset, test_client, auth_headers):
        """Test resetting metrics for all entity types."""
        response = test_client.post("/metrics/reset", headers=auth_headers)
        assert response.status_code == 200

        # Verify all services had their metrics reset
        mock_tool_reset.assert_called_once()
        mock_resource_reset.assert_called_once()
        mock_server_reset.assert_called_once()
        mock_prompt_reset.assert_called_once()

    @patch("mcpgateway.main.tool_service.reset_metrics")
    def test_reset_specific_entity_metrics(self, mock_tool_reset, test_client, auth_headers):
        """Test resetting metrics for a specific entity type."""
        response = test_client.post("/metrics/reset?entity=tool&entity_id=1", headers=auth_headers)
        assert response.status_code == 200
        mock_tool_reset.assert_called_once_with(ANY, 1)

    def test_reset_invalid_entity_metrics(self, test_client, auth_headers):
        """Test error handling for invalid entity type in metrics reset."""
        response = test_client.post("/metrics/reset?entity=invalid", headers=auth_headers)
        assert response.status_code == 400


# ----------------------------------------------------- #
# Middleware & Security Tests                           #
# ----------------------------------------------------- #
class TestMiddlewareAndSecurity:
    """Tests for middleware functionality, authentication, CORS, path rewriting, etc."""

    def test_docs_auth_middleware_protected_path(self, test_client):
        """Test that documentation paths require authentication."""
        response = test_client.get("/docs", follow_redirects=False)
        assert response.status_code == 401

    def test_docs_auth_middleware_unprotected_path(self, test_client):
        """Test that non-documentation paths bypass docs auth middleware."""
        response = test_client.get("/health")
        assert response.status_code == 200

    def test_openapi_protected(self, test_client):
        """Test that OpenAPI spec endpoint requires authentication."""
        response = test_client.get("/openapi.json")
        assert response.status_code == 401

    def test_redoc_protected(self, test_client):
        """Test that ReDoc endpoint requires authentication."""
        response = test_client.get("/redoc")
        assert response.status_code == 401

    def test_cors_headers(self, test_client, auth_headers):
        """Test that CORS headers are properly set."""
        response = test_client.options("/tools/", headers=auth_headers)
        # CORS is handled by FastAPI middleware, exact behavior depends on configuration
        assert response.status_code in [200, 405]  # Either handled or method not allowed


# ----------------------------------------------------- #
# Error Handling & Edge Cases                           #
# ----------------------------------------------------- #
class TestErrorHandling:
    """Tests for error scenarios, validation failures, and edge cases."""

    def test_invalid_json_body(self, test_client, auth_headers):
        """Test handling of malformed JSON in request bodies."""
        headers = auth_headers
        headers["content-type"] = "application/json"
        response = test_client.post("/protocol/initialize", content="invalid json", headers=headers)
        assert response.status_code == 400  # body cannot be parsed, so 400

    @patch("mcpgateway.main.server_service.get_server")
    def test_server_not_found(self, mock_get, test_client, auth_headers):
        """Test proper error response when server is not found."""
        # First-Party
        from mcpgateway.services.server_service import ServerNotFoundError

        mock_get.side_effect = ServerNotFoundError("Server not found")

        response = test_client.get("/servers/999", headers=auth_headers)
        assert response.status_code == 404

    @patch("mcpgateway.main.resource_service.read_resource")
    def test_resource_not_found(self, mock_read, test_client, auth_headers):
        """Test proper error response when resource is not found."""
        # First-Party
        from mcpgateway.services.resource_service import ResourceNotFoundError

        mock_read.side_effect = ResourceNotFoundError("Resource not found")

        response = test_client.get("/resources/nonexistent", headers=auth_headers)
        assert response.status_code == 404

    @patch("mcpgateway.main.tool_service.register_tool")
    def test_tool_name_conflict(self, mock_register, test_client, auth_headers):
        """Test handling of tool name conflicts during registration."""
        # First-Party
        from mcpgateway.services.tool_service import ToolNameConflictError

        mock_register.side_effect = ToolNameConflictError("Tool name already exists")

        req = {"name": "existing_tool", "url": "http://example.com"}
        response = test_client.post("/tools/", json=req, headers=auth_headers)
        assert response.status_code == 409

    def test_missing_required_fields(self, test_client, auth_headers):
        """Test validation errors for missing required fields."""
        req = {"description": "Missing required name field"}
        response = test_client.post("/tools/", json=req, headers=auth_headers)
        assert response.status_code == 422  # Validation error
