# -*- coding: utf-8 -*-
"""Tests for the admin module.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

This module tests the admin UI routes for the MCP Gateway, ensuring
they properly handle server, tool, resource, prompt, gateway and root management.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from mcpgateway.admin import (
    admin_add_gateway,
    admin_add_prompt,
    admin_add_resource,
    admin_add_root,
    admin_add_server,
    admin_add_tool,
    admin_delete_gateway,
    admin_delete_prompt,
    admin_delete_resource,
    admin_delete_root,
    admin_delete_server,
    admin_delete_tool,
    admin_edit_gateway,
    admin_edit_prompt,
    admin_edit_resource,
    admin_edit_server,
    admin_edit_tool,
    admin_get_gateway,
    admin_get_metrics,
    admin_get_prompt,
    admin_get_resource,
    admin_get_server,
    admin_get_tool,
    admin_list_gateways,
    admin_list_prompts,
    admin_list_resources,
    admin_list_servers,
    admin_list_tools,
    admin_reset_metrics,
    admin_toggle_gateway,
    admin_toggle_prompt,
    admin_toggle_resource,
    admin_toggle_server,
    admin_toggle_tool,
)
from mcpgateway.services.gateway_service import GatewayService
from mcpgateway.services.prompt_service import PromptService
from mcpgateway.services.resource_service import ResourceService
from mcpgateway.services.root_service import RootService
from mcpgateway.services.server_service import ServerNotFoundError, ServerService
from mcpgateway.services.tool_service import (
    ToolNameConflictError,
    ToolService,
)


@pytest.fixture
def mock_db():
    """Create a mock database session."""
    return MagicMock(spec=Session)


@pytest.fixture
def mock_request():
    """Create a mock FastAPI request."""
    request = MagicMock(spec=Request)

    # FastAPI's Request always has a .scope dict; many admin helpers read "root_path".
    request.scope = {"root_path": ""}

    # Pretend form() returns the full set of fields our admin helpers expect
    request.form = AsyncMock(
        return_value={
            "name": "test-name",
            "url": "http://example.com",
            "description": "Test description",
            "icon": "http://example.com/icon.png",
            "uri": "/test/resource",
            "mimeType": "text/plain",
            "template": "Template content",
            "content": "Test content",
            "associatedTools": "1,2,3",
            "associatedResources": "4,5",
            "associatedPrompts": "6",
            "requestType": "POST",
            "integrationType": "MCP",
            "headers": "{}",
            "input_schema": "{}",
            "jsonpath_filter": "$.",
            "auth_type": "",
            "auth_username": "",
            "auth_password": "",
            "auth_token": "",
            "auth_header_key": "",
            "auth_header_value": "",
            "arguments": "[]",
            "activate": "true",
        }
    )

    # Basic template rendering stub
    request.app = MagicMock()           # ensure .app exists
    request.app.state = MagicMock()     # ensure .app.state exists
    request.app.state.templates = MagicMock()
    request.app.state.templates.TemplateResponse.return_value = HTMLResponse(
        content="<html></html>"
    )

    request.query_params = {"include_inactive": "false"}
    return request



class TestAdminServerRoutes:
    """Test admin routes for server management."""

    @patch.object(ServerService, "list_servers")
    async def test_admin_list_servers(self, mock_list_servers, mock_db):
        """Test listing servers through admin UI."""
        # Setup
        mock_server1 = MagicMock()
        mock_server1.dict.return_value = {"id": 1, "name": "Server 1"}
        mock_server2 = MagicMock()
        mock_server2.dict.return_value = {"id": 2, "name": "Server 2"}
        mock_list_servers.return_value = [mock_server1, mock_server2]

        # Execute
        result = await admin_list_servers(False, mock_db, "test-user")

        # Assert
        mock_list_servers.assert_called_once_with(mock_db, include_inactive=False)
        assert len(result) == 2
        assert result[0] == {"id": 1, "name": "Server 1"}
        assert result[1] == {"id": 2, "name": "Server 2"}

    @patch.object(ServerService, "get_server")
    async def test_admin_get_server(self, mock_get_server, mock_db):
        """Test getting a single server through admin UI."""
        # Setup
        mock_server = MagicMock()
        mock_server.dict.return_value = {"id": 1, "name": "Server 1"}
        mock_get_server.return_value = mock_server

        # Execute
        result = await admin_get_server(1, mock_db, "test-user")

        # Assert
        mock_get_server.assert_called_once_with(mock_db, 1)
        assert result == {"id": 1, "name": "Server 1"}

    @patch.object(ServerService, "get_server")
    async def test_admin_get_server_not_found(self, mock_get_server, mock_db):
        """Test getting a non-existent server through admin UI."""
        # Setup
        mock_get_server.side_effect = ServerNotFoundError("Server not found")

        # Execute and Assert
        with pytest.raises(HTTPException) as excinfo:
            await admin_get_server(999, mock_db, "test-user")

        assert excinfo.value.status_code == 404
        assert "Server not found" in str(excinfo.value.detail)

    @patch.object(ServerService, "register_server")
    async def test_admin_add_server(self, mock_register_server, mock_request, mock_db):
        """Test adding a server through admin UI."""
        # Execute
        result = await admin_add_server(mock_request, mock_db, "test-user")

        # Assert
        mock_register_server.assert_called_once()
        assert isinstance(result, RedirectResponse)
        assert result.status_code == 303
        assert "/admin#catalog" in result.headers["location"]

    @patch.object(ServerService, "update_server")
    async def test_admin_edit_server(self, mock_update_server, mock_request, mock_db):
        """Test editing a server through admin UI."""
        # Execute
        result = await admin_edit_server(1, mock_request, mock_db, "test-user")

        # Assert
        mock_update_server.assert_called_once()
        assert isinstance(result, RedirectResponse)
        assert result.status_code == 303
        assert "/admin#catalog" in result.headers["location"]

    @patch.object(ServerService, "toggle_server_status")
    async def test_admin_toggle_server(self, mock_toggle_status, mock_request, mock_db):
        """Test toggling server status through admin UI."""
        # Execute
        result = await admin_toggle_server(1, mock_request, mock_db, "test-user")

        # Assert
        mock_toggle_status.assert_called_once_with(mock_db, 1, True)
        assert isinstance(result, RedirectResponse)
        assert result.status_code == 303
        assert "/admin#catalog" in result.headers["location"]

    @patch.object(ServerService, "delete_server")
    async def test_admin_delete_server(self, mock_delete_server, mock_request, mock_db):
        """Test deleting a server through admin UI."""
        result = await admin_delete_server(1, mock_request, mock_db, "test-user")

        mock_delete_server.assert_called_once_with(mock_db, 1)
        assert isinstance(result, RedirectResponse)
        assert result.status_code == 303
        assert "/admin#catalog" in result.headers["location"]

class TestAdminToolRoutes:
    """Test admin routes for tool management."""

    @patch.object(ToolService, "list_tools")
    async def test_admin_list_tools(self, mock_list_tools, mock_db):
        """Test listing tools through admin UI."""
        # Setup
        mock_tool1 = MagicMock()
        mock_tool1.dict.return_value = {"id": 1, "name": "Tool 1"}
        mock_tool2 = MagicMock()
        mock_tool2.dict.return_value = {"id": 2, "name": "Tool 2"}
        mock_list_tools.return_value = [mock_tool1, mock_tool2]

        # Execute
        result = await admin_list_tools(False, mock_db, "test-user")

        # Assert
        mock_list_tools.assert_called_once_with(mock_db, include_inactive=False)
        assert len(result) == 2
        assert result[0] == {"id": 1, "name": "Tool 1"}
        assert result[1] == {"id": 2, "name": "Tool 2"}

    @patch.object(ToolService, "get_tool")
    async def test_admin_get_tool(self, mock_get_tool, mock_db):
        """Test getting a single tool through admin UI."""
        # Setup
        mock_tool = MagicMock()
        mock_tool.dict.return_value = {"id": 1, "name": "Tool 1"}
        mock_get_tool.return_value = mock_tool

        # Execute
        result = await admin_get_tool(1, mock_db, "test-user")

        # Assert
        mock_get_tool.assert_called_once_with(mock_db, 1)
        assert result == {"id": 1, "name": "Tool 1"}

    @patch.object(ToolService, "register_tool")
    async def test_admin_add_tool(self, mock_register_tool, mock_request, mock_db):
        """Test adding a tool through admin UI."""
        # Execute
        result = await admin_add_tool(mock_request, mock_db, "test-user")

        # Assert
        mock_register_tool.assert_called_once()
        assert isinstance(result, JSONResponse)
        assert result.status_code == 200
        assert json.loads(result.body)["success"] is True

    @patch.object(ToolService, "register_tool")
    async def test_admin_add_tool_conflict(self, mock_register_tool, mock_request, mock_db):
        """Test adding a tool with a conflicting name."""
        # Setup
        mock_register_tool.side_effect = ToolNameConflictError("Tool name exists")

        # Execute
        result = await admin_add_tool(mock_request, mock_db, "test-user")

        # Assert
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400
        assert json.loads(result.body)["success"] is False

    @patch.object(ToolService, "update_tool")
    async def test_admin_edit_tool(self, mock_update_tool, mock_request, mock_db):
        """Test editing a tool through admin UI."""
        # Execute
        result = await admin_edit_tool(1, mock_request, mock_db, "test-user")

        # Assert
        mock_update_tool.assert_called_once()
        assert isinstance(result, RedirectResponse)
        assert result.status_code == 303
        assert "/admin#tools" in result.headers["location"]

    @patch.object(ToolService, "update_tool")
    async def test_admin_edit_tool_conflict(self, mock_update_tool, mock_request, mock_db):
        """Test editing a tool with a conflicting name."""
        # Setup
        mock_update_tool.side_effect = ToolNameConflictError("Tool name exists")

        # Execute
        result = await admin_edit_tool(1, mock_request, mock_db, "test-user")

        # Assert
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400
        assert json.loads(result.body)["success"] is False

    @patch.object(ToolService, "toggle_tool_status")
    async def test_admin_toggle_tool(self, mock_toggle_status, mock_request, mock_db):
        """Test toggling tool status through admin UI."""
        # Execute
        result = await admin_toggle_tool(1, mock_request, mock_db, "test-user")

        # Assert
        mock_toggle_status.assert_called_once_with(mock_db, 1, True)
        assert isinstance(result, RedirectResponse)
        assert result.status_code == 303
        assert "/admin#tools" in result.headers["location"]

    @patch.object(ToolService, "delete_tool")
    async def test_admin_delete_tool(self, mock_delete_tool, mock_request, mock_db):
        """Test deleting a tool through admin UI."""
        result = await admin_delete_tool(1, mock_request, mock_db, "test-user")

        mock_delete_tool.assert_called_once_with(mock_db, 1)
        assert isinstance(result, RedirectResponse)
        assert result.status_code == 303
        assert "/admin#tools" in result.headers["location"]


class TestAdminResourceRoutes:
    """Test admin routes for resource management."""

    @patch.object(ResourceService, "list_resources")
    async def test_admin_list_resources(self, mock_list_resources, mock_db):
        """Test listing resources through admin UI."""
        # Setup
        mock_resource1 = MagicMock()
        mock_resource1.dict.return_value = {"id": 1, "name": "Resource 1"}
        mock_resource2 = MagicMock()
        mock_resource2.dict.return_value = {"id": 2, "name": "Resource 2"}
        mock_list_resources.return_value = [mock_resource1, mock_resource2]

        # Execute
        result = await admin_list_resources(False, mock_db, "test-user")

        # Assert
        mock_list_resources.assert_called_once_with(mock_db, include_inactive=False)
        assert len(result) == 2
        assert result[0] == {"id": 1, "name": "Resource 1"}
        assert result[1] == {"id": 2, "name": "Resource 2"}

    @patch.object(ResourceService, "get_resource_by_uri")
    @patch.object(ResourceService, "read_resource")
    async def test_admin_get_resource(self, mock_read_resource, mock_get_resource, mock_db):
        """Test getting a single resource through admin UI."""
        # Setup
        mock_resource = MagicMock()
        mock_resource.dict.return_value = {"id": 1, "name": "Resource 1"}
        mock_get_resource.return_value = mock_resource
        mock_read_resource.return_value = {"type": "resource", "text": "content"}

        # Execute
        result = await admin_get_resource("/test/resource", mock_db, "test-user")

        # Assert
        mock_get_resource.assert_called_once_with(mock_db, "/test/resource")
        mock_read_resource.assert_called_once_with(mock_db, "/test/resource")
        assert result["resource"] == {"id": 1, "name": "Resource 1"}
        assert result["content"] == {"type": "resource", "text": "content"}

    @patch.object(ResourceService, "register_resource")
    async def test_admin_add_resource(self, mock_register_resource, mock_request, mock_db):
        """Test adding a resource through admin UI."""
        # Execute
        result = await admin_add_resource(mock_request, mock_db, "test-user")

        # Assert
        mock_register_resource.assert_called_once()
        assert isinstance(result, RedirectResponse)
        assert result.status_code == 303
        assert "/admin#resources" in result.headers["location"]

    @patch.object(ResourceService, "update_resource")
    async def test_admin_edit_resource(self, mock_update_resource, mock_request, mock_db):
        """Test editing a resource through admin UI."""
        # Execute
        result = await admin_edit_resource("/test/resource", mock_request, mock_db, "test-user")

        # Assert
        mock_update_resource.assert_called_once()
        assert isinstance(result, RedirectResponse)
        assert result.status_code == 303
        assert "/admin#resources" in result.headers["location"]

    @patch.object(ResourceService, "toggle_resource_status")
    async def test_admin_toggle_resource(self, mock_toggle_status, mock_request, mock_db):
        """Test toggling resource status through admin UI."""
        # Execute
        result = await admin_toggle_resource(1, mock_request, mock_db, "test-user")

        # Assert
        mock_toggle_status.assert_called_once_with(mock_db, 1, True)
        assert isinstance(result, RedirectResponse)
        assert result.status_code == 303
        assert "/admin#resources" in result.headers["location"]

    @patch.object(ResourceService, "delete_resource")
    async def test_admin_delete_resource(self, mock_delete_resource, mock_request, mock_db):
        """Test deleting a resource through admin UI."""
        result = await admin_delete_resource("/test/resource", mock_request, mock_db, "test-user")

        mock_delete_resource.assert_called_once_with(mock_db, "/test/resource")
        assert isinstance(result, RedirectResponse)
        assert result.status_code == 303
        assert "/admin#resources" in result.headers["location"]


class TestAdminPromptRoutes:
    """Test admin routes for prompt management."""

    @patch.object(PromptService, "list_prompts")
    async def test_admin_list_prompts(self, mock_list_prompts, mock_db):
        """Test listing prompts through admin UI."""
        # Setup
        mock_prompt1 = MagicMock()
        mock_prompt1.dict.return_value = {"id": 1, "name": "Prompt 1"}
        mock_prompt2 = MagicMock()
        mock_prompt2.dict.return_value = {"id": 2, "name": "Prompt 2"}
        mock_list_prompts.return_value = [mock_prompt1, mock_prompt2]

        # Execute
        result = await admin_list_prompts(False, mock_db, "test-user")

        # Assert
        mock_list_prompts.assert_called_once_with(mock_db, include_inactive=False)
        assert len(result) == 2
        assert result[0] == {"id": 1, "name": "Prompt 1"}
        assert result[1] == {"id": 2, "name": "Prompt 2"}

    @patch.object(PromptService, "get_prompt_details")
    async def test_admin_get_prompt(self, mock_get_prompt_details, mock_db):
        """Test getting a single prompt through admin UI."""
        # Setup
        mock_get_prompt_details.return_value = {
            "id": 1,
            "name": "Prompt 1",
            "template": "Example template",
            "description": "Test prompt",
            "arguments": [],
            "created_at": "2023-01-01T00:00:00",
            "updated_at": "2023-01-01T00:00:00",
            "is_active": True,
            "metrics": {
                "total_executions": 10,
                "successful_executions": 9,
                "failed_executions": 1,
                "failure_rate": 0.1,
                "min_response_time": 0.1,
                "max_response_time": 0.5,
                "avg_response_time": 0.2,
                "last_execution_time": "2023-01-01T00:00:00",
            },
        }

        # Execute
        result = await admin_get_prompt("test-prompt", mock_db, "test-user")

        # Assert
        mock_get_prompt_details.assert_called_once_with(mock_db, "test-prompt")
        assert "id" in result
        assert result["name"] == "Prompt 1"

    @patch.object(PromptService, "register_prompt")
    async def test_admin_add_prompt(self, mock_register_prompt, mock_request, mock_db):
        """Test adding a prompt through admin UI."""
        # Execute
        result = await admin_add_prompt(mock_request, mock_db, "test-user")

        # Assert
        mock_register_prompt.assert_called_once()
        assert isinstance(result, RedirectResponse)
        assert result.status_code == 303
        assert "/admin#prompts" in result.headers["location"]

    @patch.object(PromptService, "update_prompt")
    async def test_admin_edit_prompt(self, mock_update_prompt, mock_request, mock_db):
        """Test editing a prompt through admin UI."""
        # Execute
        result = await admin_edit_prompt("test-prompt", mock_request, mock_db, "test-user")

        # Assert
        mock_update_prompt.assert_called_once()
        assert isinstance(result, RedirectResponse)
        assert result.status_code == 303
        assert "/admin#prompts" in result.headers["location"]

    @patch.object(PromptService, "toggle_prompt_status")
    async def test_admin_toggle_prompt(self, mock_toggle_status, mock_request, mock_db):
        """Test toggling prompt status through admin UI."""
        # Execute
        result = await admin_toggle_prompt(1, mock_request, mock_db, "test-user")

        # Assert
        mock_toggle_status.assert_called_once_with(mock_db, 1, True)
        assert isinstance(result, RedirectResponse)
        assert result.status_code == 303
        assert "/admin#prompts" in result.headers["location"]

    @patch.object(PromptService, "delete_prompt")
    async def test_admin_delete_prompt(self, mock_delete_prompt, mock_request, mock_db):
        """Test deleting a prompt through admin UI."""
        result = await admin_delete_prompt("test-prompt", mock_request, mock_db, "test-user")

        mock_delete_prompt.assert_called_once_with(mock_db, "test-prompt")
        assert isinstance(result, RedirectResponse)
        assert result.status_code == 303
        assert "/admin#prompts" in result.headers["location"]


class TestAdminGatewayRoutes:
    """Test admin routes for gateway management."""

    @patch.object(GatewayService, "list_gateways")
    async def test_admin_list_gateways(self, mock_list_gateways, mock_db):
        """Test listing gateways through admin UI."""
        # Setup
        mock_gateway1 = MagicMock()
        mock_gateway1.dict.return_value = {"id": 1, "name": "Gateway 1"}
        mock_gateway2 = MagicMock()
        mock_gateway2.dict.return_value = {"id": 2, "name": "Gateway 2"}
        mock_list_gateways.return_value = [mock_gateway1, mock_gateway2]

        # Execute
        result = await admin_list_gateways(False, mock_db, "test-user")

        # Assert
        mock_list_gateways.assert_called_once_with(mock_db, include_inactive=False)
        assert len(result) == 2
        assert result[0] == {"id": 1, "name": "Gateway 1"}
        assert result[1] == {"id": 2, "name": "Gateway 2"}

    @patch.object(GatewayService, "get_gateway")
    async def test_admin_get_gateway(self, mock_get_gateway, mock_db):
        """Test getting a single gateway through admin UI."""
        # Setup
        mock_gateway = MagicMock()
        mock_gateway.dict.return_value = {"id": 1, "name": "Gateway 1"}
        mock_get_gateway.return_value = mock_gateway

        # Execute
        result = await admin_get_gateway(1, mock_db, "test-user")

        # Assert
        mock_get_gateway.assert_called_once_with(mock_db, 1)
        assert result == {"id": 1, "name": "Gateway 1"}

    @patch.object(GatewayService, "register_gateway")
    async def test_admin_add_gateway(self, mock_register_gateway, mock_request, mock_db):
        """Test adding a gateway through admin UI."""
        # Execute
        result = await admin_add_gateway(mock_request, mock_db, "test-user")

        # Assert
        mock_register_gateway.assert_called_once()
        assert isinstance(result, RedirectResponse)
        assert result.status_code == 303
        assert "/admin#gateways" in result.headers["location"]

    @patch.object(GatewayService, "update_gateway")
    async def test_admin_edit_gateway(self, mock_update_gateway, mock_request, mock_db):
        """Test editing a gateway through admin UI."""
        # Execute
        result = await admin_edit_gateway(1, mock_request, mock_db, "test-user")

        # Assert
        mock_update_gateway.assert_called_once()
        assert isinstance(result, RedirectResponse)
        assert result.status_code == 303
        assert "/admin#gateways" in result.headers["location"]

    @patch.object(GatewayService, "toggle_gateway_status")
    async def test_admin_toggle_gateway(self, mock_toggle_status, mock_request, mock_db):
        """Test toggling gateway status through admin UI."""
        # Execute
        result = await admin_toggle_gateway(1, mock_request, mock_db, "test-user")

        # Assert
        mock_toggle_status.assert_called_once_with(mock_db, 1, True)
        assert isinstance(result, RedirectResponse)
        assert result.status_code == 303
        assert "/admin#gateways" in result.headers["location"]

    @patch.object(GatewayService, "delete_gateway")
    async def test_admin_delete_gateway(self, mock_delete_gateway, mock_request, mock_db):
        """Test deleting a gateway through admin UI."""
        result = await admin_delete_gateway(1, mock_request, mock_db, "test-user")

        mock_delete_gateway.assert_called_once_with(mock_db, 1)
        assert isinstance(result, RedirectResponse)
        assert result.status_code == 303
        assert "/admin#gateways" in result.headers["location"]

class TestAdminRootRoutes:
    """Test admin routes for root management."""

    @patch("mcpgateway.admin.root_service.add_root", new_callable=AsyncMock)
    async def test_admin_add_root(self, mock_add_root, mock_request):
        """Test adding a root through admin UI."""
        result = await admin_add_root(mock_request, "test-user")

        # expect ("uri", "name") → "test-name" comes from the form fixture
        mock_add_root.assert_called_once_with("/test/resource", "test-name")
        assert isinstance(result, RedirectResponse)
        assert result.status_code == 303
        assert "/admin#roots" in result.headers["location"]

    @patch("mcpgateway.admin.root_service.remove_root", new_callable=AsyncMock)
    async def test_admin_delete_root(self, mock_remove_root, mock_request):
        """Test deleting a root through admin UI."""
        result = await admin_delete_root("/test/root", mock_request, "test-user")

        mock_remove_root.assert_called_once_with("/test/root")
        assert isinstance(result, RedirectResponse)
        assert result.status_code == 303
        assert "/admin#roots" in result.headers["location"]

class TestAdminMetricsRoutes:
    """Test admin routes for metrics management."""

    @patch.multiple(
        ToolService,
        aggregate_metrics=AsyncMock(return_value={"total_executions": 100}),
    )
    @patch.multiple(
        ResourceService,
        aggregate_metrics=AsyncMock(return_value={"total_executions": 50}),
    )
    @patch.multiple(
        ServerService,
        aggregate_metrics=AsyncMock(return_value={"total_executions": 30}),
    )
    @patch.multiple(
        PromptService,
        aggregate_metrics=AsyncMock(return_value={"total_executions": 20}),
    )
    async def test_admin_get_metrics(self, mock_db):
        """Test getting metrics through admin UI."""
        # Execute
        result = await admin_get_metrics(mock_db, "test-user")

        # Assert
        assert "tools" in result
        assert "resources" in result
        assert "servers" in result
        assert "prompts" in result
        assert result["tools"]["total_executions"] == 100
        assert result["resources"]["total_executions"] == 50
        assert result["servers"]["total_executions"] == 30
        assert result["prompts"]["total_executions"] == 20

    @patch.multiple(
        ToolService,
        reset_metrics=AsyncMock(),
    )
    @patch.multiple(
        ResourceService,
        reset_metrics=AsyncMock(),
    )
    @patch.multiple(
        ServerService,
        reset_metrics=AsyncMock(),
    )
    @patch.multiple(
        PromptService,
        reset_metrics=AsyncMock(),
    )
    async def test_admin_reset_metrics(self, mock_db):
        """Test resetting metrics through admin UI."""
        # Execute
        result = await admin_reset_metrics(mock_db, "test-user")

        # Assert
        assert result["message"] == "All metrics reset successfully"
        assert result["success"] is True
        ToolService.reset_metrics.assert_called_once()
        ResourceService.reset_metrics.assert_called_once()
        ServerService.reset_metrics.assert_called_once()
        PromptService.reset_metrics.assert_called_once()
