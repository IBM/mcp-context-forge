# -*- coding: utf-8 -*-
"""Tests for the admin module with improved coverage.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

This module tests the admin UI routes for the MCP Gateway, ensuring
they properly handle server, tool, resource, prompt, gateway and root management.
Enhanced with additional test cases for better coverage.
"""

# Standard
from datetime import datetime, timezone
import json
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import ValidationError
from pydantic_core import InitErrorDetails
from pydantic_core import ValidationError as CoreValidationError
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.admin import (
    admin_add_gateway,
    admin_add_prompt,
    admin_add_resource,
    admin_add_root,
    admin_add_server,
    admin_add_tool,
    admin_delete_root,
    admin_delete_server,
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
    admin_test_gateway,
    admin_toggle_gateway,
    admin_toggle_prompt,
    admin_toggle_resource,
    admin_toggle_server,
    admin_toggle_tool,
    admin_ui,
)
from mcpgateway.schemas import (
    GatewayTestRequest,
    PromptMetrics,
    ResourceMetrics,
    ServerMetrics,
    ToolMetrics,
)
from mcpgateway.services.gateway_service import GatewayConnectionError, GatewayService
from mcpgateway.services.prompt_service import PromptService
from mcpgateway.services.resource_service import ResourceService
from mcpgateway.services.root_service import RootService
from mcpgateway.services.server_service import ServerService
from mcpgateway.services.tool_service import (
    ToolError,
    ToolNameConflictError,
    ToolNotFoundError,
    ToolService,
)


class FakeForm(dict):
    """Enhanced fake form with better list handling."""

    def getlist(self, key):
        value = self.get(key, [])
        if isinstance(value, list):
            return value
        return [value] if value else []


@pytest.fixture
def mock_db():
    """Create a mock database session."""
    return MagicMock(spec=Session)


@pytest.fixture
def mock_request():
    """Create a mock FastAPI request with comprehensive form data."""
    request = MagicMock(spec=Request)

    # FastAPI's Request always has a .scope dict
    request.scope = {"root_path": ""}

    # Comprehensive form data with valid names
    request.form = AsyncMock(
        return_value=FakeForm(
            {
                "name": "test_name",  # Valid tool/server name
                "url": "http://example.com",
                "description": "Test description",
                "icon": "http://example.com/icon.png",
                "uri": "/test/resource",
                "mimeType": "text/plain",
                "mime_type": "text/plain",
                "template": "Template content",
                "content": "Test content",
                "associatedTools": ["1", "2", "3"],
                "associatedResources": "4,5",
                "associatedPrompts": "6",
                "requestType": "SSE",
                "integrationType": "MCP",
                "headers": '{"X-Test": "value"}',
                "input_schema": '{"type": "object"}',
                "jsonpath_filter": "$.",
                "jsonpathFilter": "$.",
                "auth_type": "basic",
                "auth_username": "user",
                "auth_password": "pass",
                "auth_token": "token123",
                "auth_header_key": "X-Auth",
                "auth_header_value": "secret",
                "arguments": '[{"name": "arg1", "type": "string"}]',
                "activate": "true",
                "is_inactive_checked": "false",
                "transport": "HTTP",
                "path": "/api/test",
                "method": "GET",
                "body": '{"test": "data"}',
            }
        )
    )

    # Basic template rendering stub
    request.app = MagicMock()
    request.app.state = MagicMock()
    request.app.state.templates = MagicMock()
    request.app.state.templates.TemplateResponse.return_value = HTMLResponse(content="<html></html>")

    request.query_params = {"include_inactive": "false"}
    return request


@pytest.fixture
def mock_metrics():
    """Create mock metrics for all entity types."""
    return {
        "tool": ToolMetrics(
            total_executions=100,
            successful_executions=90,
            failed_executions=10,
            failure_rate=0.1,
            min_response_time=0.01,
            max_response_time=2.0,
            avg_response_time=0.5,
            last_execution_time=datetime.now(timezone.utc),
        ),
        "resource": ResourceMetrics(
            total_executions=50,
            successful_executions=48,
            failed_executions=2,
            failure_rate=0.04,
            min_response_time=0.02,
            max_response_time=1.0,
            avg_response_time=0.3,
            last_execution_time=datetime.now(timezone.utc),
        ),
        "server": ServerMetrics(
            total_executions=75,
            successful_executions=70,
            failed_executions=5,
            failure_rate=0.067,
            min_response_time=0.05,
            max_response_time=3.0,
            avg_response_time=0.8,
            last_execution_time=datetime.now(timezone.utc),
        ),
        "prompt": PromptMetrics(
            total_executions=25,
            successful_executions=24,
            failed_executions=1,
            failure_rate=0.04,
            min_response_time=0.03,
            max_response_time=0.5,
            avg_response_time=0.2,
            last_execution_time=datetime.now(timezone.utc),
        ),
    }


class TestAdminServerRoutes:
    """Test admin routes for server management with enhanced coverage."""

    @patch.object(ServerService, "list_servers")
    async def test_admin_list_servers_with_various_states(self, mock_list_servers, mock_db):
        """Test listing servers with various states and configurations."""
        # Setup servers with different states
        mock_server_active = MagicMock()
        mock_server_active.model_dump.return_value = {"id": 1, "name": "Active Server", "is_active": True, "associated_tools": ["tool1", "tool2"], "metrics": {"total_executions": 50}}

        mock_server_inactive = MagicMock()
        mock_server_inactive.model_dump.return_value = {"id": 2, "name": "Inactive Server", "is_active": False, "associated_tools": [], "metrics": {"total_executions": 0}}

        # Test with include_inactive=False
        mock_list_servers.return_value = [mock_server_active]
        result = await admin_list_servers(False, mock_db, "test-user")

        assert len(result) == 1
        assert result[0]["name"] == "Active Server"
        mock_list_servers.assert_called_with(mock_db, include_inactive=False)

        # Test with include_inactive=True
        mock_list_servers.return_value = [mock_server_active, mock_server_inactive]
        result = await admin_list_servers(True, mock_db, "test-user")

        assert len(result) == 2
        assert result[1]["name"] == "Inactive Server"
        mock_list_servers.assert_called_with(mock_db, include_inactive=True)

    @patch.object(ServerService, "get_server")
    async def test_admin_get_server_edge_cases(self, mock_get_server, mock_db):
        """Test getting server with edge cases."""
        # Test with non-string ID (should work)
        mock_server = MagicMock()
        mock_server.model_dump.return_value = {"id": 123, "name": "Numeric ID Server"}
        mock_get_server.return_value = mock_server

        result = await admin_get_server(123, mock_db, "test-user")
        assert result["id"] == 123

        # Test with generic exception
        mock_get_server.side_effect = RuntimeError("Database connection lost")

        with pytest.raises(RuntimeError) as excinfo:
            await admin_get_server("error-id", mock_db, "test-user")
        assert "Database connection lost" in str(excinfo.value)

    @patch.object(ServerService, "register_server")
    async def test_admin_add_server_with_validation_error(self, mock_register_server, mock_request, mock_db):
        """Test adding server with validation errors."""
        # Create a proper ValidationError
        error_details = [InitErrorDetails(type="missing", loc=("name",), input={})]
        mock_register_server.side_effect = CoreValidationError.from_exception_data("ServerCreate", error_details)

        result = await admin_add_server(mock_request, mock_db, "test-user")

        assert isinstance(result, JSONResponse)
        assert result.status_code == 422

    @patch.object(ServerService, "register_server")
    async def test_admin_add_server_with_integrity_error(self, mock_register_server, mock_request, mock_db):
        """Test adding server with database integrity error."""
        # Simulate database integrity error
        mock_register_server.side_effect = IntegrityError("Duplicate entry", params={}, orig=Exception("Duplicate key value"))

        result = await admin_add_server(mock_request, mock_db, "test-user")

        assert isinstance(result, JSONResponse)
        assert result.status_code == 409

    @patch.object(ServerService, "register_server")
    async def test_admin_add_server_with_empty_associations(self, mock_register_server, mock_request, mock_db):
        """Test adding server with empty association fields."""
        # Override form data with empty associations
        form_data = FakeForm(
            {
                "name": "Empty_Associations_Server",
                "associatedTools": [],
                "associatedResources": "",
                "associatedPrompts": "",
            }
        )
        mock_request.form = AsyncMock(return_value=form_data)

        result = await admin_add_server(mock_request, mock_db, "test-user")

        # Should still succeed
        assert isinstance(result, RedirectResponse)
        assert result.status_code == 303

    @patch.object(ServerService, "update_server")
    async def test_admin_edit_server_with_root_path(self, mock_update_server, mock_request, mock_db):
        """Test editing server with custom root path."""
        # Set custom root path
        mock_request.scope = {"root_path": "/api/v1"}

        result = await admin_edit_server("server-1", mock_request, mock_db, "test-user")

        assert isinstance(result, RedirectResponse)
        assert "/api/v1/admin#catalog" in result.headers["location"]

    @patch.object(ServerService, "toggle_server_status")
    async def test_admin_toggle_server_with_exception(self, mock_toggle_status, mock_request, mock_db):
        """Test toggling server status with exception handling."""
        mock_toggle_status.side_effect = Exception("Toggle operation failed")

        # Should still return redirect
        result = await admin_toggle_server("server-1", mock_request, mock_db, "test-user")

        assert isinstance(result, RedirectResponse)
        assert result.status_code == 303

    @patch.object(ServerService, "delete_server")
    async def test_admin_delete_server_with_inactive_checkbox(self, mock_delete_server, mock_request, mock_db):
        """Test deleting server with inactive checkbox variations."""
        # Test with uppercase TRUE
        form_data = FakeForm({"is_inactive_checked": "TRUE"})
        mock_request.form = AsyncMock(return_value=form_data)

        result = await admin_delete_server("server-1", mock_request, mock_db, "test-user")

        assert "include_inactive=true" in result.headers["location"]

        # Test with mixed case
        form_data = FakeForm({"is_inactive_checked": "TrUe"})
        mock_request.form = AsyncMock(return_value=form_data)

        result = await admin_delete_server("server-1", mock_request, mock_db, "test-user")

        assert "include_inactive=true" in result.headers["location"]


class TestAdminToolRoutes:
    """Test admin routes for tool management with enhanced coverage."""

    @patch.object(ToolService, "list_tools")
    async def test_admin_list_tools_empty_and_exception(self, mock_list_tools, mock_db):
        """Test listing tools with empty results and exceptions."""
        # Test empty list
        mock_list_tools.return_value = []
        result = await admin_list_tools(False, mock_db, "test-user")
        assert result == []

        # Test with exception
        mock_list_tools.side_effect = RuntimeError("Service unavailable")

        with pytest.raises(RuntimeError):
            await admin_list_tools(False, mock_db, "test-user")

    @patch.object(ToolService, "get_tool")
    async def test_admin_get_tool_various_exceptions(self, mock_get_tool, mock_db):
        """Test getting tool with various exception types."""
        # Test with ToolNotFoundError
        mock_get_tool.side_effect = ToolNotFoundError("Tool not found")

        with pytest.raises(HTTPException) as excinfo:
            await admin_get_tool("missing-tool", mock_db, "test-user")
        assert excinfo.value.status_code == 404

        # Test with generic exception
        mock_get_tool.side_effect = ValueError("Invalid tool ID format")

        with pytest.raises(ValueError):
            await admin_get_tool("bad-id", mock_db, "test-user")

    @patch.object(ToolService, "register_tool")
    async def test_admin_add_tool_with_invalid_json(self, mock_register_tool, mock_request, mock_db):
        """Test adding tool with invalid JSON in form fields."""
        # Override form with invalid JSON
        form_data = FakeForm(
            {
                "name": "Invalid_JSON_Tool",  # Valid name format
                "url": "http://example.com",
                "headers": "invalid-json",
                "input_schema": "{broken json",
            }
        )
        mock_request.form = AsyncMock(return_value=form_data)

        # Should handle JSON decode error
        with pytest.raises(json.JSONDecodeError):
            await admin_add_tool(mock_request, mock_db, "test-user")

    @patch.object(ToolService, "register_tool")
    async def test_admin_add_tool_with_tool_error(self, mock_register_tool, mock_request, mock_db):
        """Test adding tool with ToolError."""
        mock_register_tool.side_effect = ToolError("Tool service error")

        result = await admin_add_tool(mock_request, mock_db, "test-user")

        assert isinstance(result, JSONResponse)
        assert result.status_code == 500
        assert json.loads(result.body)["success"] is False

    @patch.object(ToolService, "register_tool")
    async def test_admin_add_tool_with_missing_fields(self, mock_register_tool, mock_request, mock_db):
        """Test adding tool with missing required fields."""
        # Override form with missing name
        form_data = FakeForm(
            {
                "url": "http://example.com",
                "requestType": "HTTP",
            }
        )
        mock_request.form = AsyncMock(return_value=form_data)

        result = await admin_add_tool(mock_request, mock_db, "test-user")

        assert isinstance(result, JSONResponse)
        assert result.status_code == 422

    @patch.object(ToolService, "update_tool")
    async def test_admin_edit_tool_all_error_paths(self, mock_update_tool, mock_request, mock_db):
        """Test editing tool with all possible error paths."""
        tool_id = "tool-1"

        # Test ToolNameConflictError
        mock_update_tool.side_effect = ToolNameConflictError("Name already exists")
        result = await admin_edit_tool(tool_id, mock_request, mock_db, "test-user")
        assert result.status_code == 400

        # Test ToolError
        mock_update_tool.side_effect = ToolError("Tool configuration error")
        result = await admin_edit_tool(tool_id, mock_request, mock_db, "test-user")
        assert result.status_code == 500

        # Test generic exception
        mock_update_tool.side_effect = Exception("Unexpected error")
        result = await admin_edit_tool(tool_id, mock_request, mock_db, "test-user")
        assert result.status_code == 500

    @patch.object(ToolService, "update_tool")
    async def test_admin_edit_tool_with_empty_optional_fields(self, mock_update_tool, mock_request, mock_db):
        """Test editing tool with empty optional fields."""
        # Override form with empty optional fields and valid name
        form_data = FakeForm(
            {
                "name": "Updated_Tool",  # Valid tool name format
                "url": "http://updated.com",
                "description": "",
                "headers": "",
                "input_schema": "",
                "jsonpathFilter": "",
                "auth_type": "",
            }
        )
        mock_request.form = AsyncMock(return_value=form_data)

        result = await admin_edit_tool("tool-1", mock_request, mock_db, "test-user")

        assert isinstance(result, RedirectResponse)

        # Verify empty strings are handled correctly
        call_args = mock_update_tool.call_args[0]
        tool_update = call_args[2]
        assert tool_update.headers == {}
        assert tool_update.input_schema == {}

    @patch.object(ToolService, "toggle_tool_status")
    async def test_admin_toggle_tool_various_activate_values(self, mock_toggle_status, mock_request, mock_db):
        """Test toggling tool with various activate values."""
        tool_id = "tool-1"

        # Test with "false"
        form_data = FakeForm({"activate": "false"})
        mock_request.form = AsyncMock(return_value=form_data)

        await admin_toggle_tool(tool_id, mock_request, mock_db, "test-user")
        mock_toggle_status.assert_called_with(mock_db, tool_id, False, reachable=False)

        # Test with "FALSE"
        form_data = FakeForm({"activate": "FALSE"})
        mock_request.form = AsyncMock(return_value=form_data)

        await admin_toggle_tool(tool_id, mock_request, mock_db, "test-user")
        mock_toggle_status.assert_called_with(mock_db, tool_id, False, reachable=False)

        # Test with missing activate field (defaults to true)
        form_data = FakeForm({})
        mock_request.form = AsyncMock(return_value=form_data)

        await admin_toggle_tool(tool_id, mock_request, mock_db, "test-user")
        mock_toggle_status.assert_called_with(mock_db, tool_id, True, reachable=True)


class TestAdminResourceRoutes:
    """Test admin routes for resource management with enhanced coverage."""

    @patch.object(ResourceService, "list_resources")
    async def test_admin_list_resources_with_complex_data(self, mock_list_resources, mock_db):
        """Test listing resources with complex data structures."""
        mock_resource = MagicMock()
        mock_resource.model_dump.return_value = {
            "id": 1,
            "uri": "complex://resource",
            "name": "Complex Resource",
            "mime_type": "application/json",
            "content": {"nested": {"data": "value"}},
            "metrics": {"total_executions": 100},
        }

        mock_list_resources.return_value = [mock_resource]
        result = await admin_list_resources(False, mock_db, "test-user")

        assert len(result) == 1
        assert result[0]["uri"] == "complex://resource"

    @patch.object(ResourceService, "get_resource_by_uri")
    @patch.object(ResourceService, "read_resource")
    async def test_admin_get_resource_with_read_error(self, mock_read_resource, mock_get_resource, mock_db):
        """Test getting resource when content read fails."""
        # Resource exists
        mock_resource = MagicMock()
        mock_resource.model_dump.return_value = {"id": 1, "uri": "/test/resource"}
        mock_get_resource.return_value = mock_resource

        # But reading content fails
        mock_read_resource.side_effect = IOError("Cannot read resource content")

        with pytest.raises(IOError):
            await admin_get_resource("/test/resource", mock_db, "test-user")

    @patch.object(ResourceService, "register_resource")
    async def test_admin_add_resource_with_valid_mime_type(self, mock_register_resource, mock_request, mock_db):
        """Test adding resource with valid MIME type."""
        # Use a valid MIME type
        form_data = FakeForm(
            {
                "uri": "/template/resource",
                "name": "Template-Resource",  # Valid resource name
                "mimeType": "text/plain",  # Valid MIME type
                "template": "Hello {{name}}!",
                "content": "Default content",
            }
        )
        mock_request.form = AsyncMock(return_value=form_data)

        result = await admin_add_resource(mock_request, mock_db, "test-user")

        # Assert
        mock_register_resource.assert_called_once()
        assert result.status_code == 200

        # Verify template was passed
        call_args = mock_register_resource.call_args[0]
        resource_create = call_args[1]
        assert resource_create.template == "Hello {{name}}!"

    @patch.object(ResourceService, "register_resource")
    async def test_admin_add_resource_database_errors(self, mock_register_resource, mock_request, mock_db):
        """Test adding resource with various database errors."""
        # Test IntegrityError
        mock_register_resource.side_effect = IntegrityError("URI already exists", params={}, orig=Exception("Duplicate key"))

        result = await admin_add_resource(mock_request, mock_db, "test-user")
        assert isinstance(result, JSONResponse)
        assert result.status_code == 409

        # Test generic exception
        mock_register_resource.side_effect = Exception("Generic error")

        result = await admin_add_resource(mock_request, mock_db, "test-user")
        assert isinstance(result, JSONResponse)
        assert result.status_code == 500

    @patch.object(ResourceService, "update_resource")
    async def test_admin_edit_resource_special_uri_characters(self, mock_update_resource, mock_request, mock_db):
        """Test editing resource with special characters in URI."""
        # URI with encoded special characters (valid)
        uri = "/test/resource%3Fparam%3Dvalue%26other%3D123"

        result = await admin_edit_resource(uri, mock_request, mock_db, "test-user")

        assert isinstance(result, RedirectResponse)
        # Verify URI was passed correctly
        mock_update_resource.assert_called_once()
        assert mock_update_resource.call_args[0][1] == uri

    @patch.object(ResourceService, "toggle_resource_status")
    async def test_admin_toggle_resource_numeric_id(self, mock_toggle_status, mock_request, mock_db):
        """Test toggling resource with numeric ID."""
        # Test with integer ID
        await admin_toggle_resource(123, mock_request, mock_db, "test-user")
        mock_toggle_status.assert_called_with(mock_db, 123, True)

        # Test with string number
        await admin_toggle_resource("456", mock_request, mock_db, "test-user")
        mock_toggle_status.assert_called_with(mock_db, "456", True)


class TestAdminPromptRoutes:
    """Test admin routes for prompt management with enhanced coverage."""

    @patch.object(PromptService, "list_prompts")
    async def test_admin_list_prompts_with_complex_arguments(self, mock_list_prompts, mock_db):
        """Test listing prompts with complex argument structures."""
        mock_prompt = MagicMock()
        mock_prompt.model_dump.return_value = {
            "id": 1,
            "name": "Complex Prompt",
            "arguments": [
                {"name": "arg1", "type": "string", "required": True},
                {"name": "arg2", "type": "number", "default": 0},
                {"name": "arg3", "type": "array", "items": {"type": "string"}},
            ],
            "metrics": {"total_executions": 50},
        }

        mock_list_prompts.return_value = [mock_prompt]
        result = await admin_list_prompts(False, mock_db, "test-user")

        assert len(result[0]["arguments"]) == 3

    @patch.object(PromptService, "get_prompt_details")
    async def test_admin_get_prompt_with_detailed_metrics(self, mock_get_prompt_details, mock_db):
        """Test getting prompt with detailed metrics."""
        mock_get_prompt_details.return_value = {
            "id": 1,
            "name": "test-prompt",
            "template": "Test {{var}}",
            "description": "Test prompt",
            "arguments": [{"name": "var", "type": "string"}],
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "is_active": True,
            "metrics": {
                "total_executions": 1000,
                "successful_executions": 950,
                "failed_executions": 50,
                "failure_rate": 0.05,
                "min_response_time": 0.001,
                "max_response_time": 5.0,
                "avg_response_time": 0.25,
                "last_execution_time": datetime.now(timezone.utc),
                "percentile_95": 0.8,
                "percentile_99": 2.0,
            },
        }

        result = await admin_get_prompt("test-prompt", mock_db, "test-user")

        assert result["name"] == "test-prompt"
        assert "metrics" in result

    @patch.object(PromptService, "register_prompt")
    async def test_admin_add_prompt_with_empty_arguments(self, mock_register_prompt, mock_request, mock_db):
        """Test adding prompt with empty or missing arguments."""
        # Test with empty arguments
        form_data = FakeForm(
            {
                "name": "No-Args-Prompt",  # Valid prompt name
                "template": "Simple template",
                "arguments": "[]",
            }
        )
        mock_request.form = AsyncMock(return_value=form_data)

        result = await admin_add_prompt(mock_request, mock_db, "test-user")
        assert isinstance(result, RedirectResponse)

        # Test with missing arguments field
        form_data = FakeForm(
            {
                "name": "Missing-Args-Prompt",  # Valid prompt name
                "template": "Another template",
            }
        )
        mock_request.form = AsyncMock(return_value=form_data)

        result = await admin_add_prompt(mock_request, mock_db, "test-user")
        assert isinstance(result, RedirectResponse)

    @patch.object(PromptService, "register_prompt")
    async def test_admin_add_prompt_with_invalid_arguments_json(self, mock_register_prompt, mock_request, mock_db):
        """Test adding prompt with invalid arguments JSON."""
        form_data = FakeForm(
            {
                "name": "Bad-JSON-Prompt",  # Valid prompt name
                "template": "Template",
                "arguments": "not-json",
            }
        )
        mock_request.form = AsyncMock(return_value=form_data)

        with pytest.raises(json.JSONDecodeError):
            await admin_add_prompt(mock_request, mock_db, "test-user")

    @patch.object(PromptService, "update_prompt")
    async def test_admin_edit_prompt_name_change(self, mock_update_prompt, mock_request, mock_db):
        """Test editing prompt with name change."""
        # Override form to change name
        form_data = FakeForm(
            {
                "name": "new-prompt-name",
                "template": "Updated template",
                "arguments": "[]",
            }
        )
        mock_request.form = AsyncMock(return_value=form_data)

        result = await admin_edit_prompt("old-prompt-name", mock_request, mock_db, "test-user")

        assert isinstance(result, RedirectResponse)

        # Verify old name was passed to service
        mock_update_prompt.assert_called_once()
        assert mock_update_prompt.call_args[0][1] == "old-prompt-name"

    @patch.object(PromptService, "toggle_prompt_status")
    async def test_admin_toggle_prompt_edge_cases(self, mock_toggle_status, mock_request, mock_db):
        """Test toggling prompt with edge cases."""
        # Test with string ID that looks like number
        await admin_toggle_prompt("123", mock_request, mock_db, "test-user")
        mock_toggle_status.assert_called_with(mock_db, "123", True)

        # Test with negative number
        await admin_toggle_prompt(-1, mock_request, mock_db, "test-user")
        mock_toggle_status.assert_called_with(mock_db, -1, True)


class TestAdminGatewayRoutes:
    """Test admin routes for gateway management with enhanced coverage."""

    @patch.object(GatewayService, "list_gateways")
    async def test_admin_list_gateways_with_auth_info(self, mock_list_gateways, mock_db):
        """Test listing gateways with authentication information."""
        mock_gateway = MagicMock()
        mock_gateway.model_dump.return_value = {
            "id": "gateway-1",
            "name": "Secure Gateway",
            "url": "https://secure.example.com",
            "transport": "HTTP",
            "enabled": True,
            "auth_type": "bearer",
            "auth_token": "hidden",  # Should be masked
        }

        mock_list_gateways.return_value = [mock_gateway]
        result = await admin_list_gateways(False, mock_db, "test-user")

        assert result[0]["auth_type"] == "bearer"

    @patch.object(GatewayService, "get_gateway")
    async def test_admin_get_gateway_all_transports(self, mock_get_gateway, mock_db):
        """Test getting gateway with different transport types."""
        transports = ["HTTP", "SSE", "WebSocket"]

        for transport in transports:
            mock_gateway = MagicMock()
            mock_gateway.model_dump.return_value = {
                "id": f"gateway-{transport}",
                "transport": transport,
            }
            mock_get_gateway.return_value = mock_gateway

            result = await admin_get_gateway(f"gateway-{transport}", mock_db, "test-user")
            assert result["transport"] == transport

    @patch.object(GatewayService, "register_gateway")
    async def test_admin_add_gateway_valid_auth_types(self, mock_register_gateway, mock_request, mock_db):
        """Test adding gateway with valid authentication types."""
        auth_configs = [
            {
                "auth_type": "basic",
                "auth_username": "user",
                "auth_password": "pass",
                "auth_token": "",  # Empty strings for unused fields
                "auth_header_key": "",
                "auth_header_value": "",
            },
            {
                "auth_type": "bearer",
                "auth_token": "token123",
                "auth_username": "",  # Empty strings for unused fields
                "auth_password": "",
                "auth_header_key": "",
                "auth_header_value": "",
            },
            {
                "auth_type": "authheaders",
                "auth_header_key": "X-API-Key",
                "auth_header_value": "secret",
                "auth_username": "",  # Empty strings for unused fields
                "auth_password": "",
                "auth_token": "",
            },
        ]

        for auth_config in auth_configs:
            form_data = FakeForm({"name": f"Gateway_{auth_config.get('auth_type', 'none')}", "url": "http://example.com", **auth_config})
            mock_request.form = AsyncMock(return_value=form_data)

            result = await admin_add_gateway(mock_request, mock_db, "test-user")
            assert isinstance(result, JSONResponse)
            assert result.status_code == 200

    @patch.object(GatewayService, "register_gateway")
    async def test_admin_add_gateway_without_auth(self, mock_register_gateway, mock_request, mock_db):
        """Test adding gateway without authentication."""
        # Test gateway without auth_type (should default to empty string which is valid)
        form_data = FakeForm(
            {
                "name": "No_Auth_Gateway",
                "url": "http://example.com",
                # No auth_type specified
            }
        )
        mock_request.form = AsyncMock(return_value=form_data)

        result = await admin_add_gateway(mock_request, mock_db, "test-user")
        assert isinstance(result, JSONResponse)
        assert result.status_code == 200

    @patch.object(GatewayService, "register_gateway")
    async def test_admin_add_gateway_connection_error(self, mock_register_gateway, mock_request, mock_db):
        """Test adding gateway with connection error."""
        mock_register_gateway.side_effect = GatewayConnectionError("Cannot connect to gateway")

        result = await admin_add_gateway(mock_request, mock_db, "test-user")

        assert isinstance(result, JSONResponse)
        assert result.status_code == 502

    @patch.object(GatewayService, "register_gateway")
    async def test_admin_add_gateway_missing_name(self, mock_register_gateway, mock_request, mock_db):
        """Test adding gateway with missing required name field."""
        form_data = FakeForm(
            {
                "url": "http://example.com",
                # name is missing
            }
        )
        mock_request.form = AsyncMock(return_value=form_data)

        result = await admin_add_gateway(mock_request, mock_db, "test-user")

        assert isinstance(result, JSONResponse)
        assert result.status_code == 422

    @patch.object(GatewayService, "update_gateway")
    async def test_admin_edit_gateway_url_validation(self, mock_update_gateway, mock_request, mock_db):
        """Test editing gateway with URL validation."""
        # Test with invalid URL
        form_data = FakeForm(
            {
                "name": "Updated_Gateway",
                "url": "not-a-valid-url",
            }
        )
        mock_request.form = AsyncMock(return_value=form_data)

        # Should handle validation in GatewayUpdate
        result = await admin_edit_gateway("gateway-1", mock_request, mock_db, "test-user")

        # Even with invalid URL, should return redirect (validation happens in service)
        assert isinstance(result, RedirectResponse)

    @patch.object(GatewayService, "toggle_gateway_status")
    async def test_admin_toggle_gateway_concurrent_calls(self, mock_toggle_status, mock_request, mock_db):
        """Test toggling gateway with simulated concurrent calls."""
        # Simulate race condition
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Gateway is being modified by another process")
            return None

        mock_toggle_status.side_effect = side_effect

        # First call should fail
        result1 = await admin_toggle_gateway("gateway-1", mock_request, mock_db, "test-user")
        assert isinstance(result1, RedirectResponse)

        # Second call should succeed
        result2 = await admin_toggle_gateway("gateway-1", mock_request, mock_db, "test-user")
        assert isinstance(result2, RedirectResponse)


class TestAdminRootRoutes:
    """Test admin routes for root management with enhanced coverage."""

    @patch("mcpgateway.admin.root_service.add_root", new_callable=AsyncMock)
    async def test_admin_add_root_with_special_characters(self, mock_add_root, mock_request):
        """Test adding root with special characters in URI."""
        form_data = FakeForm(
            {
                "uri": "/test/root-with-dashes_and_underscores",  # Valid URI
                "name": "Special-Root_Name",  # Valid name
            }
        )
        mock_request.form = AsyncMock(return_value=form_data)

        result = await admin_add_root(mock_request, "test-user")

        mock_add_root.assert_called_once_with("/test/root-with-dashes_and_underscores", "Special-Root_Name")

    @patch("mcpgateway.admin.root_service.add_root", new_callable=AsyncMock)
    async def test_admin_add_root_without_name(self, mock_add_root, mock_request):
        """Test adding root without optional name."""
        form_data = FakeForm(
            {
                "uri": "/nameless/root",
                # name is optional
            }
        )
        mock_request.form = AsyncMock(return_value=form_data)

        result = await admin_add_root(mock_request, "test-user")

        mock_add_root.assert_called_once_with("/nameless/root", None)

    @patch("mcpgateway.admin.root_service.remove_root", new_callable=AsyncMock)
    async def test_admin_delete_root_with_error(self, mock_remove_root, mock_request):
        """Test deleting root with error handling."""
        mock_remove_root.side_effect = Exception("Root is in use")

        # Should raise the exception (not caught in the admin route)
        with pytest.raises(Exception) as excinfo:
            await admin_delete_root("/test/root", mock_request, "test-user")

        assert "Root is in use" in str(excinfo.value)


class TestAdminMetricsRoutes:
    """Test admin routes for metrics management with enhanced coverage."""

    @patch.object(ToolService, "aggregate_metrics", new_callable=AsyncMock)
    @patch.object(ResourceService, "aggregate_metrics", new_callable=AsyncMock)
    @patch.object(ServerService, "aggregate_metrics", new_callable=AsyncMock)
    @patch.object(PromptService, "aggregate_metrics", new_callable=AsyncMock)
    async def test_admin_get_metrics_with_nulls(self, mock_prompt_metrics, mock_server_metrics, mock_resource_metrics, mock_tool_metrics, mock_db):
        """Test getting metrics with null values."""
        # Some services return metrics with null values
        mock_tool_metrics.return_value = ToolMetrics(
            total_executions=0,
            successful_executions=0,
            failed_executions=0,
            failure_rate=0.0,
            min_response_time=None,  # No executions yet
            max_response_time=None,
            avg_response_time=None,
            last_execution_time=None,
        )

        mock_resource_metrics.return_value = ResourceMetrics(
            total_executions=100,
            successful_executions=100,
            failed_executions=0,
            failure_rate=0.0,
            min_response_time=0.1,
            max_response_time=1.0,
            avg_response_time=0.5,
            last_execution_time=datetime.now(timezone.utc),
        )

        mock_server_metrics.return_value = None  # No metrics available
        mock_prompt_metrics.return_value = None

        result = await admin_get_metrics(mock_db, "test-user")

        assert result["tools"].total_executions == 0
        assert result["resources"].total_executions == 100
        assert result["servers"] is None
        assert result["prompts"] is None

    @patch.object(ToolService, "reset_metrics", new_callable=AsyncMock)
    @patch.object(ResourceService, "reset_metrics", new_callable=AsyncMock)
    @patch.object(ServerService, "reset_metrics", new_callable=AsyncMock)
    @patch.object(PromptService, "reset_metrics", new_callable=AsyncMock)
    async def test_admin_reset_metrics_partial_failure(self, mock_prompt_reset, mock_server_reset, mock_resource_reset, mock_tool_reset, mock_db):
        """Test resetting metrics with partial failure."""
        # Some services fail to reset
        mock_tool_reset.return_value = None
        mock_resource_reset.side_effect = Exception("Resource metrics locked")
        mock_server_reset.return_value = None
        mock_prompt_reset.return_value = None

        # Should raise the exception
        with pytest.raises(Exception) as excinfo:
            await admin_reset_metrics(mock_db, "test-user")

        assert "Resource metrics locked" in str(excinfo.value)


class TestAdminGatewayTestRoute:
    """Test the gateway test endpoint with enhanced coverage."""

    async def test_admin_test_gateway_various_methods(self):
        """Test gateway testing with various HTTP methods."""
        methods = ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]

        for method in methods:
            request = GatewayTestRequest(
                base_url="http://example.com",
                path="/api/test",
                method=method,
                headers={"X-Test": "value"},
                body={"test": "data"} if method in ["POST", "PUT", "PATCH"] else None,
            )

            with patch("mcpgateway.admin.ResilientHttpClient") as mock_client_class:
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {"result": "success"}

                mock_client = AsyncMock()
                mock_client.request = AsyncMock(return_value=mock_response)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)

                mock_client_class.return_value = mock_client

                result = await admin_test_gateway(request, "test-user")

                assert result.status_code == 200
                mock_client.request.assert_called_once()
                call_args = mock_client.request.call_args
                assert call_args[1]["method"] == method

    async def test_admin_test_gateway_url_construction(self):
        """Test gateway testing with various URL constructions."""
        test_cases = [
            ("http://example.com", "/api/test", "http://example.com/api/test"),
            ("http://example.com/", "/api/test", "http://example.com/api/test"),
            ("http://example.com", "api/test", "http://example.com/api/test"),
            ("http://example.com/", "api/test", "http://example.com/api/test"),
            ("http://example.com/base", "/api/test", "http://example.com/base/api/test"),
            ("http://example.com/base/", "/api/test/", "http://example.com/base/api/test"),
        ]

        for base_url, path, expected_url in test_cases:
            request = GatewayTestRequest(
                base_url=base_url,
                path=path,
                method="GET",
                headers={},
                body=None,
            )

            with patch("mcpgateway.admin.ResilientHttpClient") as mock_client_class:
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {}

                mock_client = AsyncMock()
                mock_client.request = AsyncMock(return_value=mock_response)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)

                mock_client_class.return_value = mock_client

                await admin_test_gateway(request, "test-user")

                call_args = mock_client.request.call_args
                assert call_args[1]["url"] == expected_url

    async def test_admin_test_gateway_timeout_handling(self):
        """Test gateway testing with timeout."""
        # Third-Party
        import httpx

        request = GatewayTestRequest(
            base_url="http://slow.example.com",
            path="/timeout",
            method="GET",
            headers={},
            body=None,
        )

        with patch("mcpgateway.admin.ResilientHttpClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(side_effect=httpx.TimeoutException("Request timed out"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            mock_client_class.return_value = mock_client

            result = await admin_test_gateway(request, "test-user")

            assert result.status_code == 502
            assert "Request timed out" in str(result.body)

    async def test_admin_test_gateway_non_json_response(self):
        """Test gateway testing with various non-JSON responses."""
        responses = [
            ("Plain text response", "text/plain"),
            ("<html>HTML response</html>", "text/html"),
            ("", "text/plain"),  # Empty response
            ("Invalid JSON: {broken", "application/json"),
        ]

        for response_text, content_type in responses:
            request = GatewayTestRequest(
                base_url="http://example.com",
                path="/non-json",
                method="GET",
                headers={},
                body=None,
            )

            with patch("mcpgateway.admin.ResilientHttpClient") as mock_client_class:
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.text = response_text
                mock_response.headers = {"content-type": content_type}
                mock_response.json.side_effect = json.JSONDecodeError("Invalid", "", 0)

                mock_client = AsyncMock()
                mock_client.request = AsyncMock(return_value=mock_response)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)

                mock_client_class.return_value = mock_client

                result = await admin_test_gateway(request, "test-user")

                assert result.status_code == 200
                assert result.body["details"] == response_text


class TestAdminUIRoute:
    """Test the main admin UI route with enhanced coverage."""

    @patch.object(ServerService, "list_servers", new_callable=AsyncMock)
    @patch.object(ToolService, "list_tools", new_callable=AsyncMock)
    @patch.object(ResourceService, "list_resources", new_callable=AsyncMock)
    @patch.object(PromptService, "list_prompts", new_callable=AsyncMock)
    @patch.object(GatewayService, "list_gateways", new_callable=AsyncMock)
    @patch.object(RootService, "list_roots", new_callable=AsyncMock)
    async def test_admin_ui_with_service_failures(self, mock_roots, mock_gateways, mock_prompts, mock_resources, mock_tools, mock_servers, mock_request, mock_db):
        """Test admin UI when some services fail."""
        # Some services succeed
        mock_servers.return_value = []
        mock_tools.return_value = []

        # Some services fail
        mock_resources.side_effect = Exception("Resource service down")

        # Should propagate the exception
        with pytest.raises(Exception) as excinfo:
            await admin_ui(mock_request, False, mock_db, "admin", "jwt.token")

        assert "Resource service down" in str(excinfo.value)

    @patch.object(ServerService, "list_servers", new_callable=AsyncMock)
    @patch.object(ToolService, "list_tools", new_callable=AsyncMock)
    @patch.object(ResourceService, "list_resources", new_callable=AsyncMock)
    @patch.object(PromptService, "list_prompts", new_callable=AsyncMock)
    @patch.object(GatewayService, "list_gateways", new_callable=AsyncMock)
    @patch.object(RootService, "list_roots", new_callable=AsyncMock)
    async def test_admin_ui_template_context(self, mock_roots, mock_gateways, mock_prompts, mock_resources, mock_tools, mock_servers, mock_request, mock_db):
        """Test admin UI template context is properly populated."""
        # Mock all services to return empty lists
        mock_servers.return_value = []
        mock_tools.return_value = []
        mock_resources.return_value = []
        mock_prompts.return_value = []
        mock_gateways.return_value = []
        mock_roots.return_value = []

        # Mock settings
        with patch("mcpgateway.admin.settings") as mock_settings:
            mock_settings.app_root_path = "/custom/root"
            mock_settings.gateway_tool_name_separator = "__"

            response = await admin_ui(mock_request, True, mock_db, "admin", "jwt.token")

            # Check template was called with correct context
            template_call = mock_request.app.state.templates.TemplateResponse.call_args
            context = template_call[0][2]

            assert context["include_inactive"] is True
            assert context["root_path"] == "/custom/root"
            assert context["gateway_tool_name_separator"] == "__"
            assert "servers" in context
            assert "tools" in context
            assert "resources" in context
            assert "prompts" in context
            assert "gateways" in context
            assert "roots" in context

    @patch.object(ServerService, "list_servers", new_callable=AsyncMock)
    @patch.object(ToolService, "list_tools", new_callable=AsyncMock)
    @patch.object(ResourceService, "list_resources", new_callable=AsyncMock)
    @patch.object(PromptService, "list_prompts", new_callable=AsyncMock)
    @patch.object(GatewayService, "list_gateways", new_callable=AsyncMock)
    @patch.object(RootService, "list_roots", new_callable=AsyncMock)
    async def test_admin_ui_cookie_settings(self, mock_roots, mock_gateways, mock_prompts, mock_resources, mock_tools, mock_servers, mock_request, mock_db):
        """Test admin UI JWT cookie settings."""
        # Mock all services
        for mock in [mock_servers, mock_tools, mock_resources, mock_prompts, mock_gateways, mock_roots]:
            mock.return_value = []

        # Create a mock response that we can inspect
        mock_response = HTMLResponse("<html></html>")
        mock_response.set_cookie = MagicMock()
        mock_request.app.state.templates.TemplateResponse.return_value = mock_response

        jwt_token = "test.jwt.token"
        response = await admin_ui(mock_request, False, mock_db, "admin", jwt_token)

        # Verify cookie was set with correct parameters
        mock_response.set_cookie.assert_called_once_with(key="jwt_token", value=jwt_token, httponly=True, secure=False, samesite="Strict")


class TestEdgeCasesAndErrorHandling:
    """Test edge cases and error handling across all routes."""

    @pytest.mark.parametrize(
        "form_field,value",
        [
            ("activate", "yes"),  # Invalid boolean
            ("activate", "1"),  # Numeric string
            ("activate", ""),  # Empty string
            ("is_inactive_checked", "YES"),
            ("is_inactive_checked", "1"),
            ("is_inactive_checked", " true "),  # With spaces
        ],
    )
    async def test_boolean_field_parsing(self, form_field, value, mock_request, mock_db):
        """Test parsing of boolean form fields with various inputs."""
        form_data = FakeForm({form_field: value})
        mock_request.form = AsyncMock(return_value=form_data)

        # Test with toggle operations which use boolean parsing
        with patch.object(ServerService, "toggle_server_status", new_callable=AsyncMock) as mock_toggle:
            await admin_toggle_server("server-1", mock_request, mock_db, "test-user")

            # Check how the value was parsed
            if form_field == "activate":
                # Only "true" (case-insensitive) should be True
                expected = value.lower() == "true"
                mock_toggle.assert_called_with(mock_db, "server-1", expected)

    async def test_json_field_valid_cases(self, mock_request, mock_db):
        """Test JSON field parsing with valid cases."""
        # Use valid tool names and flat headers dict (no nested objects)
        test_cases = [
            ('{"X-Custom-Header": "value"}', {"X-Custom-Header": "value"}),
            ('{"Authorization": "Bearer token123"}', {"Authorization": "Bearer token123"}),
            ("{}", {}),
        ]

        for json_str, expected in test_cases:
            form_data = FakeForm(
                {
                    "name": "Test_Tool",  # Valid tool name
                    "url": "http://example.com",
                    "headers": json_str,
                    "input_schema": "{}",
                }
            )
            mock_request.form = AsyncMock(return_value=form_data)

            with patch.object(ToolService, "register_tool", new_callable=AsyncMock) as mock_register:
                result = await admin_add_tool(mock_request, mock_db, "test-user")

                # Should succeed
                assert isinstance(result, JSONResponse)
                assert result.status_code == 200

                # Check parsed value
                call_args = mock_register.call_args[0]
                tool_create = call_args[1]
                assert tool_create.headers == expected

    async def test_valid_characters_handling(self, mock_request, mock_db):
        """Test handling of valid characters in form fields."""
        valid_data = {
            "name": "Test_Resource_123",  # Valid resource name
            "description": "Multi-line\ntext with\ttabs",
            "uri": "/test/resource/valid-uri",  # Valid URI
            "content": "Content with various characters",
        }

        form_data = FakeForm(valid_data)
        mock_request.form = AsyncMock(return_value=form_data)

        with patch.object(ResourceService, "register_resource", new_callable=AsyncMock) as mock_register:
            result = await admin_add_resource(mock_request, mock_db, "test-user")

            assert isinstance(result, RedirectResponse)

            # Verify data was preserved
            call_args = mock_register.call_args[0]
            resource_create = call_args[1]
            assert resource_create.name == valid_data["name"]
            assert resource_create.content == valid_data["content"]

    async def test_concurrent_modification_handling(self, mock_request, mock_db):
        """Test handling of concurrent modification scenarios."""
        # Simulate optimistic locking failure
        with patch.object(ServerService, "update_server", new_callable=AsyncMock) as mock_update:
            mock_update.side_effect = IntegrityError("Concurrent modification detected", params={}, orig=Exception("Version mismatch"))

            # Should handle gracefully
            result = await admin_edit_server("server-1", mock_request, mock_db, "test-user")
            assert isinstance(result, RedirectResponse)

    async def test_large_form_data_handling(self, mock_request, mock_db):
        """Test handling of large form data."""
        # Create large JSON data
        large_json = json.dumps({f"field_{i}": f"value_{i}" for i in range(1000)})

        form_data = FakeForm(
            {
                "name": "Large_Data_Tool",  # Valid tool name
                "url": "http://example.com",
                "headers": large_json,
                "input_schema": large_json,
            }
        )
        mock_request.form = AsyncMock(return_value=form_data)

        with patch.object(ToolService, "register_tool", new_callable=AsyncMock):
            result = await admin_add_tool(mock_request, mock_db, "test-user")
            assert isinstance(result, JSONResponse)

    @pytest.mark.parametrize(
        "exception_type,expected_status",
        [
            (ValidationError.from_exception_data("Test", []), 422),
            (IntegrityError("Test", {}, Exception()), 409),
            (ValueError("Test"), 500),
            (RuntimeError("Test"), 500),
            (KeyError("Test"), 500),
            (TypeError("Test"), 500),
        ],
    )
    async def test_exception_handling_consistency(self, exception_type, expected_status, mock_request, mock_db):
        """Test consistent exception handling across different routes."""
        # Test with add operations
        with patch.object(ServerService, "register_server", new_callable=AsyncMock) as mock_register:
            mock_register.side_effect = exception_type

            result = await admin_add_server(mock_request, mock_db, "test-user")

            if expected_status in [422, 409]:
                assert isinstance(result, JSONResponse)
                assert result.status_code == expected_status
            else:
                # Generic exceptions return redirect
                assert isinstance(result, RedirectResponse)
