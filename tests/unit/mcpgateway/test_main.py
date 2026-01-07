# -*- coding: utf-8 -*-

# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_main.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Comprehensive tests for the main API endpoints with full coverage.
"""

# Standard
from copy import deepcopy
import datetime
import json
import os
from unittest.mock import ANY, MagicMock, patch

# Third-Party
from fastapi import HTTPException
from fastapi.testclient import TestClient
import jwt
import pytest

# First-Party
from mcpgateway.config import settings
from mcpgateway.common.models import InitializeResult, ResourceContent, ServerCapabilities
from mcpgateway.schemas import (
    GatewayRead,
    PromptRead,
    ResourceRead,
    ServerRead,
    ToolRead,
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
    "enabled": True,
    "associated_tools": ["101"],
    "associated_resources": ["201"],
    "associated_prompts": ["301"],
    "metrics": MOCK_METRICS,
}

MOCK_TOOL_READ = {
    "id": "1",
    "name": "test_tool",
    "originalName": "test_tool",
    "customName": "test_tool",
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
    "customNameSlug": "test-tool",
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
    "customNameSlug": "custom_name_slug",
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
    "id": "39334ce0ed2644d79ede8913a66930c9",
    "uri": "test/resource",
    "name": "Test Resource",
    "description": "A test resource",
    "mime_type": "text/plain",
    "size": 12,
    "created_at": "2023-01-01T00:00:00+00:00",
    "updated_at": "2023-01-01T00:00:00+00:00",
    "enabled": True,
    "metrics": MOCK_METRICS,
}

MOCK_PROMPT_READ = {
    "id": "ca627760127d409080fdefc309147e08",
    "name": "test_prompt",
    "original_name": "test_prompt",
    "custom_name": "test_prompt",
    "custom_name_slug": "test-prompt",
    "display_name": "Test Prompt",
    "description": "A test prompt",
    "template": "Hello {name}",
    "arguments": [],
    "created_at": "2023-01-01T00:00:00+00:00",
    "updated_at": "2023-01-01T00:00:00+00:00",
    "enabled": True,
    "metrics": MOCK_METRICS,
}

MOCK_GATEWAY_READ = {
    "id": "1",
    "name": "test_gateway",
    "url": "http://example.com",
    "description": "A test gateway",
    "transport": "SSE",
    "created_at": "2023-01-01T00:00:00+00:00",
    "updated_at": "2023-01-01T00:00:00+00:00",
    "enabled": True,
    "reachable": True,
    "auth_type": None,
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

    Also overrides RBAC dependencies to bypass permission checks for tests.
    """
    # First-Party
    # Mock user object for RBAC system
    from mcpgateway.db import EmailUser
    from mcpgateway.main import require_auth
    from mcpgateway.middleware.rbac import get_current_user_with_permissions

    mock_user = EmailUser(
        email="test_user@example.com",
        full_name="Test User",
        is_admin=True,  # Give admin privileges for tests
        is_active=True,
        auth_provider="test",
    )

    # Override old auth system
    app.dependency_overrides[require_auth] = lambda: "test_user"

    # Patch the auth function used by DocsAuthMiddleware
    # Standard
    from unittest.mock import MagicMock, patch

    # Third-Party
    from fastapi import HTTPException, status

    # First-Party

    # Mock security_logger to prevent database access
    mock_sec_logger = MagicMock()
    mock_sec_logger.log_authentication_attempt = MagicMock(return_value=None)
    mock_sec_logger.log_security_event = MagicMock(return_value=None)
    sec_patcher = patch("mcpgateway.middleware.auth_middleware.security_logger", mock_sec_logger)
    sec_patcher.start()

    # Create a mock that validates JWT tokens properly
    async def mock_require_auth_override(auth_header=None, jwt_token=None):
        # Third-Party
        import jwt as jwt_lib

        # First-Party
        from mcpgateway.config import settings

        # Try to get token from auth_header or jwt_token
        token = jwt_token
        if not token and auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]  # Remove "Bearer " prefix

        if not token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization required")

        try:
            # Always coerce key to str in case SecretStr leaks through
            key = settings.jwt_secret_key
            # Only call get_secret_value if it exists and is callable (not a string)
            if hasattr(key, "get_secret_value") and callable(getattr(key, "get_secret_value", None)):
                key = key.get_secret_value()
            payload = jwt_lib.decode(token, key, algorithms=[settings.jwt_algorithm], options={"verify_aud": False})
            username = payload.get("sub")
            if username:
                return username
            else:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        except jwt_lib.ExpiredSignatureError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
        except jwt_lib.InvalidTokenError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    patcher = patch("mcpgateway.main.require_docs_auth_override", mock_require_auth_override)
    patcher.start()

    # Override the core auth function used by RBAC system
    # First-Party
    from mcpgateway.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda credentials=None, db=None: mock_user

    # Override get_current_user_with_permissions for RBAC system
    def mock_get_current_user_with_permissions(request=None, credentials=None, jwt_token=None, db=None):
        return {"email": "test_user@example.com", "full_name": "Test User", "is_admin": True, "ip_address": "127.0.0.1", "user_agent": "test", "db": db}

    app.dependency_overrides[get_current_user_with_permissions] = mock_get_current_user_with_permissions

    # Mock the permission service to always return True for tests
    # First-Party
    from mcpgateway.services.permission_service import PermissionService

    # Store original method
    if not hasattr(PermissionService, "_original_check_permission"):
        PermissionService._original_check_permission = PermissionService.check_permission

    # Mock with correct async signature matching the real method
    async def mock_check_permission(self, user_email: str, permission: str, resource_type=None, resource_id=None, team_id=None, ip_address=None, user_agent=None) -> bool:
        return True

    PermissionService.check_permission = mock_check_permission

    client = TestClient(app)
    yield client

    # Clean up overrides and restore original methods
    app.dependency_overrides.pop(require_auth, None)
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_current_user_with_permissions, None)
    patcher.stop()  # Stop the require_auth_override patch
    sec_patcher.stop()  # Stop the security_logger patch
    if hasattr(PermissionService, "_original_check_permission"):
        PermissionService.check_permission = PermissionService._original_check_permission


@pytest.fixture
def mock_jwt_token():
    """Create a valid JWT token for testing."""
    payload = {"sub": "test_user@example.com", "email": "test_user@example.com", "iss": "mcpgateway", "aud": "mcpgateway-api"}
    secret = settings.jwt_secret_key
    if hasattr(secret, "get_secret_value") and callable(getattr(secret, "get_secret_value", None)):
        secret = secret.get_secret_value()
    algorithm = settings.jwt_algorithm
    return jwt.encode(payload, secret, algorithm=algorithm)


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
            # When UI is enabled, should redirect to admin with trailing slash
            assert response.status_code == 303
            assert response.headers["location"] == f"{settings.app_root_path}/admin/"
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

    # @patch("mcpgateway.main.validate_request")
    @patch("mcpgateway.main.session_registry.handle_initialize_logic")
    def test_initialize_endpoint(self, mock_handle_initialize, test_client, auth_headers):
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

    # @patch("mcpgateway.main.validate_request")
    def test_ping_endpoint(self, test_client, auth_headers):
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
    @patch("mcpgateway.main.server_service.update_server")
    def test_update_server_not_found(self, mock_update, test_client, auth_headers):
        """Test update_server returns 404 if server not found."""
        # First-Party
        from mcpgateway.services.server_service import ServerNotFoundError

        mock_update.side_effect = ServerNotFoundError("Server not found")
        req = {"description": "Updated description"}
        response = test_client.put("/servers/999", json=req, headers=auth_headers)
        assert response.status_code == 404

    @patch("mcpgateway.main.server_service.register_server")
    def test_create_server_validation_error(self, mock_create, test_client, auth_headers):
        """Test create_server returns 422 for missing required fields."""
        mock_create.side_effect = None  # Let validation error happen
        req = {"description": "Missing name"}
        response = test_client.post("/servers/", json=req, headers=auth_headers)
        assert response.status_code == 422

    """Tests for virtual server management: CRUD operations, status toggles, etc."""

    @patch("mcpgateway.main.server_service.list_servers")
    def test_list_servers_endpoint(self, mock_list_servers, test_client, auth_headers):
        """Test listing all servers."""
        mock_list_servers.return_value = ([ServerRead(**MOCK_SERVER_READ)], None)

        response = test_client.get("/servers/", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        # Default response is a plain list (include_pagination=False by default)
        assert isinstance(data, list)
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
        req = {"server": {"name": "test_server", "description": "A test server"}, "team_id": None, "visibility": "private"}
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
        updated_server["enabled"] = False
        mock_toggle.return_value = ServerRead(**updated_server)
        response = test_client.post("/servers/1/toggle?activate=false", headers=auth_headers)
        assert response.status_code == 200
        mock_toggle.assert_called_once()

    @patch("mcpgateway.main.server_service.delete_server")
    @patch("mcpgateway.main.server_service.get_server")
    def test_delete_server_endpoint(self, mock_get, mock_delete, test_client, auth_headers):
        """Test permanently deleting a server."""
        mock_get.return_value = ServerRead(**MOCK_SERVER_READ)
        mock_delete.return_value = None
        response = test_client.delete("/servers/1", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["status"] == "success"

    @patch("mcpgateway.main.server_service.get_server")
    def test_delete_server_not_found(self, mock_get, test_client, auth_headers):
        """Test deleting a non-existent server returns 404."""
        from mcpgateway.services.server_service import ServerNotFoundError

        mock_get.side_effect = ServerNotFoundError("Server not found: nonexistent-id")
        response = test_client.delete("/servers/nonexistent-id", headers=auth_headers)
        assert response.status_code == 404
        assert "Server not found" in response.json()["detail"]

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
    @patch("mcpgateway.main.tool_service.update_tool")
    def test_update_tool_not_found(self, mock_update, test_client, auth_headers):
        """Test update_tool returns 404 if tool not found."""
        # First-Party
        from mcpgateway.services.tool_service import ToolNotFoundError

        mock_update.side_effect = ToolNotFoundError("Tool not found")
        req = {"description": "Updated description"}
        response = test_client.put("/tools/999", json=req, headers=auth_headers)
        assert response.status_code == 404

    @patch("mcpgateway.main.create_tool")
    def test_create_tool_validation_error(self, mock_create, test_client, auth_headers):
        """Test create_tool returns 422 for missing required fields."""
        mock_create.side_effect = None  # Let validation error happen
        req = {"description": "Missing name and url"}
        response = test_client.post("/tools/", json=req, headers=auth_headers)
        assert response.status_code == 422

    """Tests for tool management: registration, invocation, updates, etc."""

    @patch("mcpgateway.main.tool_service.list_tools")
    def test_list_tools_endpoint(self, mock_list_tools, test_client, auth_headers):
        """Test listing all registered tools."""
        tool_read = ToolRead(**MOCK_TOOL_READ_SNAKE)
        mock_list_tools.return_value = ([tool_read], None)

        response = test_client.get("/tools/", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        # Default response is a plain list (include_pagination=False by default)
        assert isinstance(data, list)
        assert len(data) == 1 and data[0]["name"] == "test_tool"
        mock_list_tools.assert_called_once()

    @patch("mcpgateway.main.tool_service.register_tool")
    def test_create_tool_endpoint(self, mock_create, test_client, auth_headers):
        mock_create.return_value = MOCK_TOOL_READ_SNAKE
        req = {"tool": {"name": "test_tool", "url": "http://example.com", "description": "A test tool"}, "team_id": None, "visibility": "private"}
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
    @patch("mcpgateway.main.resource_service.update_resource")
    def test_update_resource_not_found(self, mock_update, test_client, auth_headers):
        """Test update_resource returns 404 if resource not found."""
        # First-Party
        from mcpgateway.services.resource_service import ResourceNotFoundError

        mock_update.side_effect = ResourceNotFoundError("Resource not found")
        req = {"description": "Updated description"}
        response = test_client.put("/resources/nonexistent", json=req, headers=auth_headers)
        assert response.status_code == 404

    @patch("mcpgateway.main.resource_service.register_resource")
    def test_create_resource_validation_error(self, mock_create, test_client, auth_headers):
        """Test create_resource returns 422 for missing required fields."""
        mock_create.side_effect = None  # Let validation error happen
        req = {"description": "Missing uri and name"}
        response = test_client.post("/resources/", json=req, headers=auth_headers)
        assert response.status_code == 422

    """Tests for resource management: reading, creation, caching, etc."""

    @patch("mcpgateway.main.resource_service.list_resources")
    def test_list_resources_endpoint(self, mock_list_resources, test_client, auth_headers):
        """Test listing all available resources."""
        mock_list_resources.return_value = ([ResourceRead(**MOCK_RESOURCE_READ)], None)

        response = test_client.get("/resources/", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        # Default response is a plain list (include_pagination=False by default)
        assert isinstance(data, list)
        assert len(data) == 1 and data[0]["name"] == "Test Resource"
        mock_list_resources.assert_called_once()

    @patch("mcpgateway.main.resource_service.register_resource")
    def test_create_resource_endpoint(self, mock_create, test_client, auth_headers):
        """Test registering a new resource."""
        mock_create.return_value = ResourceRead(**MOCK_RESOURCE_READ)

        req = {"resource": {"uri": "test/resource", "name": "Test Resource", "description": "A test resource", "content": "Hello world"}, "team_id": None, "visibility": "private"}
        response = test_client.post("/resources/", json=req, headers=auth_headers)

        assert response.status_code == 200  # route returns 200 on success
        mock_create.assert_called_once()

    @patch("mcpgateway.main.resource_service.read_resource")
    def test_read_resource_endpoint(self, mock_read_resource, test_client, auth_headers):
        """Test reading resource content."""
        # Clear the resource cache to avoid stale/cached values
        from mcpgateway import main as mcpgateway_main

        mcpgateway_main.resource_cache.clear()

        mock_read_resource.return_value = ResourceContent(
            type="resource",
            id="1",
            uri="test/resource",
            mime_type="text/plain",
            text="This is test content",
        )

        response = test_client.get("/resources/1", headers=auth_headers)
        assert response.status_code == 200
        body = response.json()
        assert body["uri"] == "test/resource" and body["text"] == "This is test content"
        mock_read_resource.assert_called_once()

    @patch("mcpgateway.main.resource_service.update_resource")
    def test_update_resource_endpoint(self, mock_update, test_client, auth_headers):
        """Test updating an existing resource."""
        mock_update.return_value = ResourceRead(**MOCK_RESOURCE_READ)
        resource_id = mock_update.return_value.id
        req = {"description": "Updated description"}
        response = test_client.put(f"/resources/{resource_id}", json=req, headers=auth_headers)
        assert response.status_code == 200
        mock_update.assert_called_once()

    @patch("mcpgateway.main.resource_service.delete_resource")
    def test_delete_resource_endpoint(self, mock_delete, test_client, auth_headers):
        """Test deleting a resource."""
        mock_delete.return_value = None
        # Use the same resource_id as in test_update_resource_endpoint
        resource_id = MOCK_RESOURCE_READ["id"]
        response = test_client.delete(f"/resources/{resource_id}", headers=auth_headers)
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
        mock_resource.model_dump.return_value = {"id": "1", "enabled": False}
        mock_toggle.return_value = mock_resource
        response = test_client.post("/resources/1/toggle?activate=false", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["status"] == "success"

    @patch("mcpgateway.main.resource_service.subscribe_events")
    def test_subscribe_resource_events(self, mock_subscribe, test_client, auth_headers):
        """Test subscribing to resource change events via SSE."""
        mock_subscribe.return_value = iter(["data: test\n\n"])
        resource_id = MOCK_RESOURCE_READ["id"]
        response = test_client.post(f"/resources/subscribe", headers=auth_headers)
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"


# ----------------------------------------------------- #
# Prompt Management Tests                               #
# ----------------------------------------------------- #
class TestPromptEndpoints:
    @patch("mcpgateway.main.prompt_service.delete_prompt")
    def test_delete_prompt_not_found(self, mock_delete, test_client, auth_headers):
        """Test delete_prompt returns 404 if prompt not found."""
        # First-Party
        from mcpgateway.services.prompt_service import PromptNotFoundError

        mock_delete.side_effect = PromptNotFoundError("Prompt not found")
        response = test_client.delete("/prompts/nonexistent", headers=auth_headers)
        assert response.status_code == 404

    @patch("mcpgateway.main.prompt_service.update_prompt")
    def test_update_prompt_not_found(self, mock_update, test_client, auth_headers):
        """Test update_prompt returns 404 if prompt not found."""
        # First-Party
        from mcpgateway.services.prompt_service import PromptNotFoundError

        mock_update.side_effect = PromptNotFoundError("Prompt not found")
        req = {"description": "Updated description"}
        response = test_client.put("/prompts/nonexistent", json=req, headers=auth_headers)
        assert response.status_code == 404

    @patch("mcpgateway.main.prompt_service.register_prompt")
    def test_create_prompt_validation_error(self, mock_create, test_client, auth_headers):
        """Test create_prompt returns 422 for missing required fields."""
        mock_create.side_effect = None  # Let validation error happen
        req = {"description": "Missing name and template"}
        response = test_client.post("/prompts/", json=req, headers=auth_headers)
        assert response.status_code == 422

    @patch("mcpgateway.main.prompt_service.get_prompt")
    def test_get_prompt_no_args(self, mock_get, test_client, auth_headers):
        """Test getting a prompt without arguments."""
        mock_get.return_value = {"name": "test", "template": "Hello"}
        response = test_client.get("/prompts/test", headers=auth_headers)
        assert response.status_code == 200
        mock_get.assert_called_once_with(ANY, "test", {}, plugin_context_table=None, plugin_global_context=ANY)

    @patch("mcpgateway.main.prompt_service.update_prompt")
    def test_update_prompt_endpoint(self, mock_update, test_client, auth_headers):
        """Test updating an existing prompt."""
        updated = {**MOCK_PROMPT_READ, "description": "Updated description"}
        mock_update.return_value = PromptRead(**updated)
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
        mock_delete.assert_called_once()

    @patch("mcpgateway.main.prompt_service.toggle_prompt_status")
    def test_toggle_prompt_status(self, mock_toggle, test_client, auth_headers):
        """Test toggling prompt active/inactive status."""
        mock_prompt = MagicMock()
        mock_prompt.model_dump.return_value = {"id": 1, "enabled": False}
        mock_toggle.return_value = mock_prompt
        response = test_client.post("/prompts/1/toggle?activate=false", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["status"] == "success"
        mock_toggle.assert_called_once()

    """Tests for prompt template management: creation, rendering, arguments, etc."""

    @patch("mcpgateway.main.prompt_service.list_prompts")
    def test_list_prompts_endpoint(self, mock_list_prompts, test_client, auth_headers):
        """Test listing all available prompts."""
        prompt_read = PromptRead(**MOCK_PROMPT_READ)
        mock_list_prompts.return_value = ([prompt_read], None)
        response = test_client.get("/prompts/", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        # Default response is a plain list (include_pagination=False by default)
        assert isinstance(data, list)
        assert len(data) == 1
        mock_list_prompts.assert_called_once()

    @patch("mcpgateway.main.prompt_service.register_prompt")
    def test_create_prompt_endpoint(self, mock_create, test_client, auth_headers):
        """Test creating a new prompt template."""
        # Return an actual model instance
        mock_create.return_value = PromptRead(**MOCK_PROMPT_READ)

        req = {"prompt": {"name": "test_prompt", "template": "Hello {name}", "description": "A test prompt"}, "team_id": None, "visibility": "private"}
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
        mock_get.assert_called_once_with(ANY, "test", {}, plugin_context_table=None, plugin_global_context=ANY)

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
        mock_prompt.model_dump.return_value = {"id": 1, "enabled": False}
        mock_toggle.return_value = mock_prompt
        response = test_client.post("/prompts/1/toggle?activate=false", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["status"] == "success"


# ----------------------------------------------------- #
# Gateway Federation Tests                              #
# ----------------------------------------------------- #
class TestGatewayEndpoints:
    @patch("mcpgateway.main.gateway_service.list_gateways")
    def test_list_gateways_endpoint(self, mock_list, test_client, auth_headers):
        """Test listing all registered gateways."""
        gateway_read = GatewayRead(**MOCK_GATEWAY_READ)
        mock_list.return_value = ([gateway_read], None)
        response = test_client.get("/gateways/", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        # Default response is a plain list (include_pagination=False by default)
        assert isinstance(data, list)
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
    @patch("mcpgateway.main.gateway_service.get_gateway")
    def test_delete_gateway_endpoint_no_resources(self, mock_get, mock_delete, test_client, auth_headers):
        """Test deleting a gateway that doesn't have resources."""
        mock_delete.return_value = None
        mock_get.return_value.capabilities = {}
        response = test_client.delete("/gateways/1", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["status"] == "success"
        mock_delete.assert_called_once()

    @patch("mcpgateway.main.gateway_service.delete_gateway")
    @patch("mcpgateway.main.gateway_service.get_gateway")
    @patch("mcpgateway.main.invalidate_resource_cache")
    def test_delete_gateway_endpoint_with_resources(self, mock_invalidate_cache, mock_get, mock_delete, test_client, auth_headers):
        """Test deleting a gateway that does have resources."""
        mock_delete.return_value = None
        mock_get.return_value = MagicMock()
        mock_get.return_value.capabilities = {"resources": {"some": "thing"}}
        response = test_client.delete("/gateways/1", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["status"] == "success"
        mock_delete.assert_called_once()
        mock_invalidate_cache.assert_called_once()

    @patch("mcpgateway.main.gateway_service.toggle_gateway_status")
    def test_toggle_gateway_status(self, mock_toggle, test_client, auth_headers):
        """Test toggling gateway active/inactive status."""
        mock_gateway = MagicMock()
        mock_gateway.model_dump.return_value = {"id": "1", "is_active": False}
        mock_toggle.return_value = mock_gateway
        response = test_client.post("/gateways/1/toggle?activate=false", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["status"] == "success"
        mock_toggle.assert_called_once()

    """Tests for gateway federation: registration, discovery, forwarding, etc."""

    @patch("mcpgateway.main.gateway_service.list_gateways")
    def test_list_gateways_endpoint(self, mock_list, test_client, auth_headers):
        """Test listing all registered gateways."""
        gateway_read = GatewayRead(**MOCK_GATEWAY_READ)
        mock_list.return_value = ([gateway_read], None)
        response = test_client.get("/gateways/", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        # Default response is a plain list (include_pagination=False by default)
        assert isinstance(data, list)
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
    @patch("mcpgateway.main.gateway_service.get_gateway")
    def test_delete_gateway_endpoint(self, mock_get, mock_delete, test_client, auth_headers):
        """Test deleting a gateway."""
        mock_delete.return_value = None
        mock_get.return_value.capabilities = {}
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
        from mcpgateway.common.models import Root

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
        from mcpgateway.common.models import Root

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

        async def mock_async_gen():
            yield {"event": "test"}

        mock_subscribe.return_value = mock_async_gen()
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
        mock_invoke_tool.return_value = {"content": [{"type": "text", "text": "Tool response"}], "is_error": False}

        req = {"jsonrpc": "2.0", "id": "test-id", "method": "tools/call", "params": {"name": "test_tool", "arguments": {"param": "value"}}}
        response = test_client.post("/rpc/", json=req, headers=auth_headers)

        assert response.status_code == 200
        body = response.json()
        assert body["result"]["content"][0]["text"] == "Tool response"
        mock_invoke_tool.assert_called_once_with(
            db=ANY,
            name="test_tool",
            arguments={"param": "value"},
            request_headers=ANY,
            app_user_email="test_user",
            plugin_context_table=None,
            plugin_global_context=ANY,
        )

    @patch("mcpgateway.main.prompt_service.get_prompt")
    # @patch("mcpgateway.main.validate_request")
    def test_rpc_prompt_get(self, mock_get_prompt, test_client, auth_headers):
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
        assert body["result"]["messages"][0]["content"]["text"] == "Rendered prompt"
        mock_get_prompt.assert_called_once_with(ANY, "test_prompt", {"param": "value"}, plugin_context_table=None, plugin_global_context=ANY)

    @patch("mcpgateway.main.tool_service.list_tools")
    # @patch("mcpgateway.main.validate_request")
    def test_rpc_list_tools(self, mock_list_tools, test_client, auth_headers):
        """Test listing tools via JSON-RPC."""
        mock_tool = MagicMock()
        mock_tool.model_dump.return_value = MOCK_TOOL_READ
        mock_list_tools.return_value = ([mock_tool], None)

        req = {
            "jsonrpc": "2.0",
            "id": "test-id",
            "method": "tools/list",
            "params": {},
        }
        response = test_client.post("/rpc/", json=req, headers=auth_headers)

        assert response.status_code == 200
        body = response.json()
        assert isinstance(body["result"]["tools"], list)
        mock_list_tools.assert_called_once()

    @patch("mcpgateway.main.RPCRequest")
    def test_rpc_invalid_request(self, mock_rpc_request, test_client, auth_headers):
        """Test RPC error handling for invalid requests."""
        mock_rpc_request.side_effect = ValueError("Invalid method")

        req = {"jsonrpc": "1.0", "id": "test-id", "method": "invalid_method"}
        response = test_client.post("/rpc/", json=req, headers=auth_headers)

        assert response.status_code == 422
        body = response.json()
        assert "Method invalid" in body.get("message")

    def test_rpc_invalid_json(self, test_client, auth_headers):
        """Test RPC error handling for malformed JSON."""
        headers = auth_headers
        headers["content-type"] = "application/json"
        response = test_client.post("/rpc/", content="invalid json", headers=headers)
        assert response.status_code == 422  # Returns error response, not HTTP error
        body = response.json()
        assert "Method invalid" in body.get("message")

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

    @patch("mcpgateway.main.settings")
    @patch("mcpgateway.main.ResilientHttpClient")  # stub network calls
    def test_websocket_endpoint(self, mock_client, mock_settings, test_client):
        # Standard
        from types import SimpleNamespace

        """Test WebSocket connection and message handling."""
        # Configure mock settings for auth disabled
        mock_settings.mcp_client_auth_enabled = False
        mock_settings.auth_required = False
        mock_settings.federation_timeout = 30
        mock_settings.skip_ssl_verify = False
        mock_settings.port = 4444

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

    @patch("mcpgateway.main.update_url_protocol", new=lambda url: url)
    @patch("mcpgateway.main.session_registry.add_session")
    @patch("mcpgateway.main.session_registry.respond")
    @patch("mcpgateway.main.SSETransport")
    def test_sse_endpoint(self, mock_transport_class, mock_respond, mock_add_session, test_client, auth_headers):
        """Test SSE connection establishment."""
        mock_transport = MagicMock()
        mock_transport.session_id = "test-session"
        mock_transport.create_sse_response.return_value = MagicMock()
        mock_transport_class.return_value = mock_transport

        test_client.get("/sse", headers=auth_headers)

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

    @patch("mcpgateway.main.prompt_service.aggregate_metrics")
    @patch("mcpgateway.main.server_service.aggregate_metrics")
    @patch("mcpgateway.main.resource_service.aggregate_metrics")
    @patch("mcpgateway.main.tool_service.aggregate_metrics")
    def test_get_metrics(self, mock_tool, mock_resource, mock_server, mock_prompt, test_client, auth_headers):
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
        # A2A agents may or may not be present based on configuration

    #    @patch("mcpgateway.main.a2a_service")
    #    @patch("mcpgateway.main.prompt_service.reset_metrics")
    #    @patch("mcpgateway.main.server_service.reset_metrics")
    #    @patch("mcpgateway.main.resource_service.reset_metrics")
    #    @patch("mcpgateway.main.tool_service.reset_metrics")
    #    def test_reset_all_metrics(self, mock_tool_reset, mock_resource_reset, mock_server_reset, mock_prompt_reset, mock_a2a_service, test_client, auth_headers):
    #        """Test resetting metrics for all entity types."""
    #        # Mock A2A service with reset_metrics method
    #        mock_a2a_service.reset_metrics = MagicMock()
    #
    #        response = test_client.post("/metrics/reset", headers=auth_headers)
    #        assert response.status_code == 200
    #
    #        # Verify all services had their metrics reset
    #        mock_tool_reset.assert_called_once()
    #        mock_resource_reset.assert_called_once()
    #        mock_server_reset.assert_called_once()
    #        mock_prompt_reset.assert_called_once()
    #        mock_a2a_service.reset_metrics.assert_called_once()

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
# A2A Agent API Tests                                   #
# ----------------------------------------------------- #
## class TestA2AAgentEndpoints:
##     """Test A2A agent API endpoints."""
#
##     @patch("mcpgateway.main.a2a_service.list_agents")
##     def test_list_a2a_agents(self, mock_list, test_client, auth_headers):
#        """Test listing A2A agents."""
#        mock_list.return_value = []
#        response = test_client.get("/a2a", headers=auth_headers)
#        assert response.status_code == 200
#        mock_list.assert_called_once()
#
#    @patch("mcpgateway.main.a2a_service.get_agent")
#    def test_get_a2a_agent(self, mock_get, test_client, auth_headers):
#        """Test getting specific A2A agent."""
#        mock_agent = {
#            "id": "test-id",
#            "name": "test-agent",
#            "description": "Test agent",
#            "endpoint_url": "https://api.example.com",
#            "agent_type": "generic",
#            "enabled": True,
#            "metrics": MOCK_METRICS,
#        }
#        mock_get.return_value = mock_agent
#
#        response = test_client.get("/a2a/test-id", headers=auth_headers)
#        assert response.status_code == 200
#        mock_get.assert_called_once()
#
#    @patch("mcpgateway.main.a2a_service.register_agent")
#    @patch("mcpgateway.main.MetadataCapture.extract_creation_metadata")
#    def test_create_a2a_agent(self, mock_metadata, mock_register, test_client, auth_headers):
#        """Test creating A2A agent."""
#        mock_metadata.return_value = {
#            "created_by": "test_user",
#            "created_from_ip": "127.0.0.1",
#            "created_via": "api",
#            "created_user_agent": "test",
#            "import_batch_id": None,
#            "federation_source": None,
#        }
#        mock_register.return_value = {"id": "new-id", "name": "new-agent"}
#
#        agent_data = {
#            "name": "new-agent",
#            "endpoint_url": "https://api.example.com/agent",
#            "agent_type": "custom",
#            "description": "New test agent",
#        }
#
#        response = test_client.post("/a2a", json=agent_data, headers=auth_headers)
#        assert response.status_code == 201
#        mock_register.assert_called_once()
#
#    @patch("mcpgateway.main.a2a_service.update_agent")
#    @patch("mcpgateway.main.MetadataCapture.extract_modification_metadata")
#    def test_update_a2a_agent(self, mock_metadata, mock_update, test_client, auth_headers):
#        """Test updating A2A agent."""
#        mock_metadata.return_value = {
#            "modified_by": "test_user",
#            "modified_from_ip": "127.0.0.1",
#            "modified_via": "api",
#            "modified_user_agent": "test",
#        }
#        mock_update.return_value = {"id": "test-id", "name": "updated-agent"}
#
#        update_data = {"description": "Updated description"}
#
#        response = test_client.put("/a2a/test-id", json=update_data, headers=auth_headers)
#        assert response.status_code == 200
#        mock_update.assert_called_once()
#
#    @patch("mcpgateway.main.a2a_service.toggle_agent_status")
#    def test_toggle_a2a_agent_status(self, mock_toggle, test_client, auth_headers):
#        """Test toggling A2A agent status."""
#        mock_toggle.return_value = {"id": "test-id", "enabled": False}
#
#        response = test_client.post("/a2a/test-id/toggle?activate=false", headers=auth_headers)
#        assert response.status_code == 200
#        mock_toggle.assert_called_once()
#
#    @patch("mcpgateway.main.a2a_service.delete_agent")
#    def test_delete_a2a_agent(self, mock_delete, test_client, auth_headers):
#        """Test deleting A2A agent."""
#        mock_delete.return_value = None
#
#        response = test_client.delete("/a2a/test-id", headers=auth_headers)
#        assert response.status_code == 200
#        mock_delete.assert_called_once()
#
#    @patch("mcpgateway.main.a2a_service.invoke_agent")
#    def test_invoke_a2a_agent(self, mock_invoke, test_client, auth_headers):
#        """Test invoking A2A agent."""
#        mock_invoke.return_value = {"response": "Agent response", "status": "success"}
#
#        response = test_client.post(
#            "/a2a/test-agent/invoke",
#            json={"parameters": {"query": "test"}, "interaction_type": "query"},
#            headers=auth_headers
#        )
#        assert response.status_code == 200
#        mock_invoke.assert_called_once()
#


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
    def test_docs_with_invalid_jwt(self, test_client):
        """Test /docs with an invalid JWT returns 401."""
        headers = {"Authorization": "Bearer invalid.token.value"}
        response = test_client.get("/docs", headers=headers)
        assert response.status_code == 401

    def test_docs_with_expired_jwt(self, test_client):
        """Test /docs with an expired JWT returns 401."""
        expired_payload = {"sub": "test_user", "exp": datetime.datetime.now(tz=datetime.timezone.utc) - datetime.timedelta(hours=1)}
        # First-Party
        from mcpgateway.config import settings

        key = settings.jwt_secret_key
        print(f"[DEBUG] settings.jwt_secret_key type: {type(key)}, value: {key}")
        if hasattr(key, "get_secret_value") and callable(getattr(key, "get_secret_value", None)):
            key = key.get_secret_value()
        print(f"[DEBUG] settings.jwt_secret_key after possible unwrap: {type(key)}, value: {key}")
        expired_token = jwt.encode(expired_payload, key, algorithm=settings.jwt_algorithm)
        headers = {"Authorization": f"Bearer {expired_token}"}
        response = test_client.get("/docs", headers=headers)
        assert response.status_code == 401

    def test_post_on_get_only_endpoint(self, test_client, auth_headers):
        """Test POST on a GET-only endpoint returns 405."""
        response = test_client.post("/health", headers=auth_headers)
        assert response.status_code == 405

    def test_delete_on_docs(self, test_client, auth_headers):
        """Test DELETE on /docs returns 405."""
        response = test_client.delete("/docs", headers=auth_headers)
        assert response.status_code == 405

    def test_missing_query_param(self, test_client, auth_headers):
        """Test endpoint requiring query param returns 422 if missing."""
        # /message?session_id=... requires session_id
        message = {"type": "test", "data": "hello"}
        response = test_client.post("/message", json=message, headers=auth_headers)
        assert response.status_code == 400

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

        req = {"tool": {"name": "existing_tool", "url": "http://example.com"}, "team_id": None, "visibility": "private"}
        response = test_client.post("/tools/", json=req, headers=auth_headers)
        assert response.status_code == 409

    def test_missing_required_fields(self, test_client, auth_headers):
        """Test validation errors for missing required fields."""
        req = {"description": "Missing required name field"}
        response = test_client.post("/tools/", json=req, headers=auth_headers)
        assert response.status_code == 422  # Validation error

    def test_openapi_json_with_auth(self, test_client, auth_headers):
        """Test GET /openapi.json with authentication returns 200 and OpenAPI spec."""
        response = test_client.get("/openapi.json", headers=auth_headers)
        assert response.status_code == 200
        assert "openapi" in response.json()

    def test_docs_with_auth(self, test_client, auth_headers):
        """Test GET /docs with authentication returns 200 or redirect."""
        response = test_client.get("/docs", headers=auth_headers)
        assert response.status_code == 200

    def test_redoc_with_auth(self, test_client, auth_headers):
        """Test GET /redoc with authentication returns 200 or redirect."""
        response = test_client.get("/redoc", headers=auth_headers)
        assert response.status_code == 200


# --------------------------------------------------------------------------- #
#                               jsonpath_modifier                             #
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def sample_people():
    return [
        {"name": "Ada", "id": 1},
        {"name": "Bob", "id": 2},
    ]


def test_jsonpath_modifier_basic_match(sample_people):
    # First-Party
    from mcpgateway.main import jsonpath_modifier

    # Pull out names directly
    names = jsonpath_modifier(sample_people, "$[*].name")
    assert names == ["Ada", "Bob"]

    # Same query but with a mapping
    mapped = jsonpath_modifier(sample_people, "$[*]", mappings={"n": "$.name"})
    assert mapped == [{"n": "Ada"}, {"n": "Bob"}]


def test_jsonpath_modifier_single_dict_collapse():
    # First-Party
    from mcpgateway.main import jsonpath_modifier

    person = {"name": "Zoe", "id": 10}
    out = jsonpath_modifier(person, "$")
    assert out == person  # single-item dict collapses to dict, not list


def test_jsonpath_modifier_invalid_expressions(sample_people):
    # First-Party
    from mcpgateway.main import jsonpath_modifier

    with pytest.raises(HTTPException):
        jsonpath_modifier(sample_people, "$[")  # invalid main expr

    with pytest.raises(HTTPException):
        jsonpath_modifier(sample_people, "$[*]", mappings={"bad": "$["})  # invalid mapping expr


# ----------------------------------------------------- #
# Transform data with mappings
# ----------------------------------------------------- #
class TestTransformDataWithMappings:
    def test_transform_data_with_mappings_valid_mapping(self, sample_people):
        from mcpgateway.main import transform_data_with_mappings

        mapping = {"n": "$.name"}
        result = transform_data_with_mappings(sample_people, mapping)
        assert result == [{"n": "Ada"}, {"n": "Bob"}]

    def test_transform_data_with_mappings_invalid_mapping(self, sample_people):
        from mcpgateway.main import transform_data_with_mappings

        with pytest.raises(HTTPException):
            transform_data_with_mappings(sample_people, {"bad": "$["})


# ----------------------------------------------------- #
# Plugin Exception Handler Tests                       #
# ----------------------------------------------------- #
class TestPluginExceptionHandlers:
    """Tests for plugin exception handlers: PluginViolationError and PluginError."""

    def test_plugin_violation_exception_handler_with_full_violation(self):
        """Test plugin_violation_exception_handler with complete violation details."""
        # Standard
        import asyncio

        # First-Party
        from mcpgateway.main import plugin_violation_exception_handler
        from mcpgateway.plugins.framework.errors import PluginViolationError
        from mcpgateway.plugins.framework.models import PluginViolation

        violation = PluginViolation(
            reason="Invalid input",
            description="The input contains prohibited content",
            code="PROHIBITED_CONTENT",
            details={"field": "message", "value": "sensitive_data"},
        )
        violation._plugin_name = "content_filter"
        exc = PluginViolationError(message="Policy violation detected", violation=violation)

        result = asyncio.run(plugin_violation_exception_handler(None, exc))

        assert result.status_code == 200
        content = json.loads(result.body.decode())
        assert "error" in content
        assert content["error"]["code"] == -32602
        assert "Plugin Violation:" in content["error"]["message"]
        assert "The input contains prohibited content" in content["error"]["message"]
        assert content["error"]["data"]["description"] == "The input contains prohibited content"
        assert content["error"]["data"]["details"] == {"field": "message", "value": "sensitive_data"}
        assert content["error"]["data"]["plugin_error_code"] == "PROHIBITED_CONTENT"
        assert content["error"]["data"]["plugin_name"] == "content_filter"

    def test_plugin_violation_exception_handler_with_custom_mcp_error_code(self):
        """Test plugin_violation_exception_handler with custom MCP error code."""
        # Standard
        import asyncio

        # First-Party
        from mcpgateway.main import plugin_violation_exception_handler
        from mcpgateway.plugins.framework.errors import PluginViolationError
        from mcpgateway.plugins.framework.models import PluginViolation

        violation = PluginViolation(
            reason="Rate limit exceeded",
            description="Too many requests from this client",
            code="RATE_LIMIT",
            details={"requests": 100, "limit": 50},
            mcp_error_code=-32000,  # Custom error code
        )
        violation._plugin_name = "rate_limiter"
        exc = PluginViolationError(message="Rate limit violation", violation=violation)

        result = asyncio.run(plugin_violation_exception_handler(None, exc))

        assert result.status_code == 200
        content = json.loads(result.body.decode())
        assert content["error"]["code"] == -32000
        assert "Too many requests from this client" in content["error"]["message"]
        assert content["error"]["data"]["plugin_error_code"] == "RATE_LIMIT"
        assert content["error"]["data"]["plugin_name"] == "rate_limiter"

    def test_plugin_violation_exception_handler_with_minimal_violation(self):
        """Test plugin_violation_exception_handler with minimal violation details."""
        # Standard
        import asyncio

        # First-Party
        from mcpgateway.main import plugin_violation_exception_handler
        from mcpgateway.plugins.framework.errors import PluginViolationError
        from mcpgateway.plugins.framework.models import PluginViolation

        violation = PluginViolation(
            reason="Violation occurred",
            description="Minimal violation",
            code="MIN_VIOLATION",
            details={},
        )
        exc = PluginViolationError(message="Minimal violation", violation=violation)

        result = asyncio.run(plugin_violation_exception_handler(None, exc))

        assert result.status_code == 200
        content = json.loads(result.body.decode())
        assert content["error"]["code"] == -32602
        assert "Minimal violation" in content["error"]["message"]
        assert content["error"]["data"]["plugin_error_code"] == "MIN_VIOLATION"

    def test_plugin_violation_exception_handler_without_violation_object(self):
        """Test plugin_violation_exception_handler when violation object is None."""
        # Standard
        import asyncio

        # First-Party
        from mcpgateway.main import plugin_violation_exception_handler
        from mcpgateway.plugins.framework.errors import PluginViolationError

        exc = PluginViolationError(message="Generic plugin violation", violation=None)

        result = asyncio.run(plugin_violation_exception_handler(None, exc))

        assert result.status_code == 200
        content = json.loads(result.body.decode())
        assert content["error"]["code"] == -32602
        assert "A plugin violation occurred" in content["error"]["message"]
        assert content["error"]["data"] == {}

    def test_plugin_exception_handler_with_full_error(self):
        """Test plugin_exception_handler with complete error details."""
        # Standard
        import asyncio

        # First-Party
        from mcpgateway.main import plugin_exception_handler
        from mcpgateway.plugins.framework.errors import PluginError
        from mcpgateway.plugins.framework.models import PluginErrorModel

        error = PluginErrorModel(
            message="Plugin execution failed",
            code="EXECUTION_ERROR",
            plugin_name="data_processor",
            details={"error_type": "timeout", "duration": 30},
        )
        exc = PluginError(error=error)

        result = asyncio.run(plugin_exception_handler(None, exc))

        assert result.status_code == 200
        content = json.loads(result.body.decode())
        assert "error" in content
        assert content["error"]["code"] == -32603
        assert "Plugin Error:" in content["error"]["message"]
        assert "Plugin execution failed" in content["error"]["message"]
        assert content["error"]["data"]["details"] == {"error_type": "timeout", "duration": 30}
        assert content["error"]["data"]["plugin_error_code"] == "EXECUTION_ERROR"
        assert content["error"]["data"]["plugin_name"] == "data_processor"

    def test_plugin_exception_handler_with_custom_mcp_error_code(self):
        """Test plugin_exception_handler with custom MCP error code."""
        # Standard
        import asyncio

        # First-Party
        from mcpgateway.main import plugin_exception_handler
        from mcpgateway.plugins.framework.errors import PluginError
        from mcpgateway.plugins.framework.models import PluginErrorModel

        error = PluginErrorModel(
            message="Custom error occurred",
            code="CUSTOM_ERROR",
            plugin_name="custom_plugin",
            details={"context": "test"},
            mcp_error_code=-32001,  # Custom MCP error code
        )
        exc = PluginError(error=error)

        result = asyncio.run(plugin_exception_handler(None, exc))

        assert result.status_code == 200
        content = json.loads(result.body.decode())
        assert content["error"]["code"] == -32001
        assert "Custom error occurred" in content["error"]["message"]
        assert content["error"]["data"]["plugin_error_code"] == "CUSTOM_ERROR"

    def test_plugin_exception_handler_with_minimal_error(self):
        """Test plugin_exception_handler with minimal error details."""
        # Standard
        import asyncio

        # First-Party
        from mcpgateway.main import plugin_exception_handler
        from mcpgateway.plugins.framework.errors import PluginError
        from mcpgateway.plugins.framework.models import PluginErrorModel

        error = PluginErrorModel(message="Minimal error", plugin_name="minimal_plugin")
        exc = PluginError(error=error)

        result = asyncio.run(plugin_exception_handler(None, exc))

        assert result.status_code == 200
        content = json.loads(result.body.decode())
        assert content["error"]["code"] == -32603
        assert "Minimal error" in content["error"]["message"]
        assert content["error"]["data"]["plugin_name"] == "minimal_plugin"

    def test_plugin_exception_handler_with_empty_code(self):
        """Test plugin_exception_handler when error has empty code field."""
        # Standard
        import asyncio

        # First-Party
        from mcpgateway.main import plugin_exception_handler
        from mcpgateway.plugins.framework.errors import PluginError
        from mcpgateway.plugins.framework.models import PluginErrorModel

        error = PluginErrorModel(
            message="Error without code",
            code="",
            plugin_name="test_plugin",
            details={"info": "test"},
        )
        exc = PluginError(error=error)

        result = asyncio.run(plugin_exception_handler(None, exc))

        assert result.status_code == 200
        content = json.loads(result.body.decode())
        assert content["error"]["code"] == -32603
        assert "Error without code" in content["error"]["message"]
        # Empty code should not be included in data
        assert "plugin_error_code" not in content["error"]["data"] or content["error"]["data"]["plugin_error_code"] == ""


# --------------------------------------------------------------------------- #
#                         Cache Behavior Tests                                #
# --------------------------------------------------------------------------- #


class TestJsonPathCaching:
    """Tests for JSONPath caching (#1812)."""

    def test_jsonpath_caching_works(self):
        """Verify JSONPath parsing is cached."""
        from mcpgateway.main import jsonpath_modifier, _parse_jsonpath

        _parse_jsonpath.cache_clear()

        result1 = jsonpath_modifier([{"a": 1}, {"a": 2}], "$[*].a")
        assert result1 == [1, 2]

        result2 = jsonpath_modifier([{"a": 3}], "$[*].a")
        assert result2 == [3]

        info = _parse_jsonpath.cache_info()
        assert info.hits == 1

    def test_mappings_parsed_once_per_request(self):
        """Verify mappings are parsed once per request, not per item."""
        from mcpgateway.main import transform_data_with_mappings, _parse_jsonpath

        _parse_jsonpath.cache_clear()

        data = [{"x": 1}, {"x": 2}, {"x": 3}]
        mappings = {"y": "$.x"}

        result = transform_data_with_mappings(data, mappings)
        assert result == [{"y": 1}, {"y": 2}, {"y": 3}]

        info = _parse_jsonpath.cache_info()
        assert info.misses == 1  # Only one parse for "$.x"

    def test_different_jsonpath_cached_separately(self):
        """Verify different JSONPath expressions get separate cache entries."""
        from mcpgateway.main import jsonpath_modifier, _parse_jsonpath

        _parse_jsonpath.cache_clear()

        result1 = jsonpath_modifier({"a": 1, "b": 2}, "$.a")
        result2 = jsonpath_modifier({"a": 1, "b": 2}, "$.b")

        assert result1 == [1]
        assert result2 == [2]

        info = _parse_jsonpath.cache_info()
        assert info.misses == 2
