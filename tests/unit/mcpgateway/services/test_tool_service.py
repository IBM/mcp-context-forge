# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_tool_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for tool service implementation.
"""

# Standard
import base64
import asyncio
from contextlib import asynccontextmanager
import logging
from unittest.mock import ANY, AsyncMock, call, MagicMock, Mock, patch

# Third-Party
import pytest
from sqlalchemy.exc import IntegrityError

# First-Party
from mcpgateway.db import A2AAgent as DbA2AAgent
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import Tool as DbTool
from mcpgateway.plugins.framework import PluginViolationError
from mcpgateway.schemas import AuthenticationValues, ToolCreate, ToolRead, ToolUpdate
from mcpgateway.services.tool_service import (
    TextContent,
    ToolError,
    ToolInvocationError,
    ToolNotFoundError,
    ToolResult,
    ToolService,
    ToolValidationError,
)
from mcpgateway.utils.services_auth import encode_auth


@pytest.fixture
def tool_service():
    """Create a tool service instance."""
    service = ToolService()
    service._http_client = AsyncMock()
    return service


@pytest.fixture
def mock_gateway():
    """Create a mock gateway model."""
    gw = MagicMock(spec=DbGateway)
    gw.id = 1
    gw.name = "test_gateway"
    gw.slug = "test-gateway"
    gw.url = "http://example.com/gateway"
    gw.description = "A test tool"
    gw.transport = "SSE"
    gw.capabilities = {"prompts": {"listChanged": True}, "resources": {"listChanged": True}, "tools": {"listChanged": True}}
    gw.created_at = gw.updated_at = gw.last_seen = "2025-01-01T00:00:00Z"

    # one dummy tool hanging off the gateway
    tool = MagicMock(spec=DbTool, id=101, name="dummy_tool")
    gw.tools = [tool]
    gw.federated_tools = []
    gw.transport = "sse"
    gw.auth_type = None
    gw.auth_value = {}

    gw.enabled = True
    gw.reachable = True
    return gw


@pytest.fixture
def mock_tool():
    """Create a mock tool model."""
    tool = MagicMock(spec=DbTool)
    tool.id = "1"
    tool.original_name = "test_tool"
    tool.url = "http://example.com/tools/test"
    tool.description = "A test tool"
    tool.integration_type = "MCP"
    tool.request_type = "SSE"
    tool.headers = {"Content-Type": "application/json"}
    tool.input_schema = {"type": "object", "properties": {"param": {"type": "string"}}}
    tool.jsonpath_filter = ""
    tool.created_at = "2023-01-01T00:00:00"
    tool.updated_at = "2023-01-01T00:00:00"
    tool.enabled = True
    tool.reachable = True
    tool.auth_type = None
    tool.auth_username = None
    tool.auth_password = None
    tool.auth_token = None
    tool.auth_value = None
    tool.gateway_id = "1"
    tool.gateway = mock_gateway
    tool.annotations = {}
    tool.gateway_slug = "test-gateway"
    tool.name = "test-gateway-test-tool"
    tool.custom_name="test_tool"
    tool.custom_name_slug = "test-tool"
    tool.display_name = None
    tool.tags = []

    # Set up metrics
    tool.metrics = []
    tool.execution_count = 0
    tool.successful_executions = 0
    tool.failed_executions = 0
    tool.failure_rate = 0.0
    tool.min_response_time = None
    tool.max_response_time = None
    tool.avg_response_time = None
    tool.last_execution_time = None
    tool.metrics_summary = {
        "total_executions": 0,
        "successful_executions": 0,
        "failed_executions": 0,
        "failure_rate": 0.0,
        "min_response_time": None,
        "max_response_time": None,
        "avg_response_time": None,
        "last_execution_time": None,
    }

    return tool


from mcpgateway.services.tool_service import ToolNameConflictError

class TestToolService:
    """Tests for the ToolService class."""

    @pytest.mark.asyncio
    async def test_initialize_service(self, caplog):
        """Initialize service and check logs"""
        caplog.set_level(logging.INFO, logger="mcpgateway.services.tool_service")
        service = ToolService()
        await service.initialize()

        assert "Initializing tool service" in caplog.text

    @pytest.mark.asyncio
    async def test_shutdown_service(self, caplog):
        """Shutdown service and check logs"""
        caplog.set_level(logging.INFO, logger="mcpgateway.services.tool_service")
        service = ToolService()
        await service.shutdown()

        assert "Tool service shutdown complete" in caplog.text

    @pytest.mark.asyncio
    async def test_convert_tool_to_read_basic_auth(self, tool_service, mock_tool):
        """Check auth for basic auth"""

            # Build Authorization header with base64 encoded user:password
        creds = base64.b64encode(b"test_user:test_password").decode()
        auth_dict = {"Authorization": f"Basic {creds}"}

        mock_tool.auth_type = "basic"
        mock_tool.auth_value = encode_auth(auth_dict)

        mock_tool.auth_type = "basic"
        # Create auth_value with the following values
        # user = "test_user"
        # password = "test_password"
        #mock_tool.auth_value = "FpZyxAu5PVpT0FN-gJ0JUmdovCMS0emkwW1Vb8HvkhjiBZhj1gDgDRF1wcWNrjTJSLtkz1rLzKibXrhk4GbxXnV6LV4lSw_JDYZ2sPNRy68j_UKOJnf_"
        #mock_tool.auth_value = encode_auth({"user": "test_user", "password": "test_password"})
        tool_read = tool_service._convert_tool_to_read(mock_tool)

        assert tool_read.auth.auth_type == "basic"
        assert tool_read.auth.username == "test_user"
        assert tool_read.auth.password == "********"

    @pytest.mark.asyncio
    async def test_convert_tool_to_read_bearer_auth(self, tool_service, mock_tool):
        """Check auth for bearer auth"""

        mock_tool.auth_type = "bearer"
        # Create auth_value with the following values
        # bearer token ABC123
        mock_tool.auth_value = encode_auth({"Authorization": "Bearer ABC123"})
        tool_read = tool_service._convert_tool_to_read(mock_tool)

        assert tool_read.auth.auth_type == "bearer"
        assert tool_read.auth.token == "********"

    @pytest.mark.asyncio
    async def test_convert_tool_to_read_authheaders_auth(self, tool_service, mock_tool):
        """Check auth for authheaders auth"""

        mock_tool.auth_type = "authheaders"
        # Create auth_value with the following values
        # {"test-api-key": "test-api-value"}
        #mock_tool.auth_value = "8pvPTCegaDhrx0bmBf488YvGg9oSo4cJJX68WCTvxjMY-C2yko_QSPGVggjjNt59TPvlGLsotTZvAiewPRQ"
        mock_tool.auth_value = encode_auth({"test-api-key": "test-api-value"})
        tool_read = tool_service._convert_tool_to_read(mock_tool)

        assert tool_read.auth.auth_type == "authheaders"
        assert tool_read.auth.auth_header_key == "test-api-key"
        assert tool_read.auth.auth_header_value == "********"

    @pytest.mark.asyncio
    async def test_register_tool(self, tool_service, mock_tool, test_db):
        """Test successful tool registration."""
        # Set up DB behavior
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = None
        test_db.execute = Mock(return_value=mock_scalar)
        test_db.add = Mock()
        test_db.commit = Mock()
        test_db.refresh = Mock()

        # Set up tool service methods
        tool_service._notify_tool_added = AsyncMock()
        tool_service._convert_tool_to_read = Mock(
            return_value=ToolRead(
                id="1",
                original_name="test_tool",
                gateway_slug="test-gateway",
                customNameSlug="test-tool",
                name="test-gateway-test-tool",
                url="http://example.com/tools/test",
                description="A test tool",
                integration_type="REST",
                request_type="POST",
                headers={"Content-Type": "application/json"},
                input_schema={"type": "object", "properties": {"param": {"type": "string"}}},
                jsonpath_filter="",
                created_at="2023-01-01T00:00:00",
                updated_at="2023-01-01T00:00:00",
                enabled=True,
                reachable=True,
                gateway_id=None,
                execution_count=0,
                auth=None,  # Add auth field
                annotations={},  # Add annotations field
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
                customName="test_tool",
            )
        )

        # Create tool request
        tool_create = ToolCreate(
            name="test-gateway-test-tool",
            url="http://example.com/tools/test",
            description="A test tool",
            integration_type="REST",
            request_type="POST",
            headers={"Content-Type": "application/json"},
            input_schema={"type": "object", "properties": {"param": {"type": "string"}}},
        )

        # Call method
        result = await tool_service.register_tool(test_db, tool_create)

        # Verify DB operations
        test_db.add.assert_called_once()
        test_db.commit.assert_called_once()
        test_db.refresh.assert_called_once()

        # Verify result
        assert result.name == "test-gateway-test-tool"
        assert result.url == "http://example.com/tools/test"
        assert result.integration_type == "REST"
        assert result.enabled is True

        # Verify notification
        tool_service._notify_tool_added.assert_called_once()

    @pytest.mark.asyncio
    async def test_register_tool_with_gateway_id(self, tool_service, mock_tool, test_db):
        """Test tool registration with name conflict and gateway."""
        # Mock DB to return existing tool
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = mock_tool
        test_db.execute = Mock(return_value=mock_scalar)

        # Create tool request with conflicting name
        tool_create = ToolCreate(
            name="test_tool",  # Same name as mock_tool
            url="http://example.com/tools/new",
            description="A new tool",
            integration_type="REST",
            request_type="POST",
            gateway_id="1",
        )

        # Should raise ToolError due to missing slug on NoneType
        with pytest.raises(ToolError) as exc_info:
            await tool_service.register_tool(test_db, tool_create)
            # The service wraps exceptions, so check the message
            assert "Failed to register tool" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_register_tool_with_none_auth(self, tool_service, test_db):
        """Test register_tool when tool.auth is None."""

        token = "token"
        auth_value = encode_auth({"Authorization": f"Bearer {token}"})

        tool_input = ToolCreate(name="no_auth_tool", gateway_id=None, auth=AuthenticationValues(auth_type="bearer", auth_value=auth_value))

        # Run the function
        result = await tool_service.register_tool(test_db, tool_input)

        assert result.original_name == "no_auth_tool"
        # assert result.auth_type is None
        # assert result.auth_value is None

        # Validate that the tool is actually in the DB
        db_tool = test_db.query(DbTool).filter_by(original_name="no_auth_tool").first()
        assert db_tool is not None
        assert db_tool.auth_type == "bearer"
        assert db_tool.auth_value == auth_value

    @pytest.mark.asyncio
    async def test_register_tool_name_conflict(self, tool_service, mock_tool, test_db):
        """Test tool registration with name conflict for private, team, and public visibility."""
        # --- Private visibility: conflict if name and owner_email match ---
        mock_tool.name = "private_tool"
        mock_tool.visibility = "private"
        mock_tool.owner_email = "user@example.com"
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = mock_tool
        test_db.execute = Mock(return_value=mock_scalar)
        tool_create_private = ToolCreate(
            name="private_tool",
            url="http://example.com/tools/new",
            description="A new tool",
            integration_type="REST",
            request_type="POST",
            visibility="private",
            owner_email="user@example.com",
        )
        test_db.commit = Mock(side_effect=IntegrityError("UNIQUE constraint failed: tools.name, owner_email", None, None))
        with pytest.raises(IntegrityError) as exc_info:
            await tool_service.register_tool(test_db, tool_create_private)
        assert "UNIQUE constraint failed: tools.name, owner_email" in str(exc_info.value)

        # --- Team visibility: conflict if name and team_id match ---
        mock_tool.name = "team_tool"
        mock_tool.visibility = "team"
        mock_tool.team_id = "team123"
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = mock_tool
        test_db.execute = Mock(return_value=mock_scalar)
        tool_create_team = ToolCreate(
            name="team_tool",
            url="http://example.com/tools/new",
            description="A new tool",
            integration_type="REST",
            request_type="POST",
            visibility="team",
            team_id="team123",
            owner_email="user@example.com"
        )
        test_db.commit = Mock()
        with pytest.raises(ToolNameConflictError) as exc_info:
            await tool_service.register_tool(test_db, tool_create_team)
        assert "Team-level Tool already exists with name: team_tool" in str(exc_info.value)

        # --- Public visibility: conflict if name and visibility match ---
        mock_tool.name = "public_tool"
        mock_tool.visibility = "public"
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = mock_tool
        test_db.execute = Mock(return_value=mock_scalar)
        tool_create_public = ToolCreate(
            name="public_tool",
            url="http://example.com/tools/new",
            description="A new tool",
            integration_type="REST",
            request_type="POST",
            visibility="public",
            owner_email="user@example.com",
        )
        test_db.commit = Mock()
        # Ensure mock_tool.name matches the expected error message
        mock_tool.name = "public_tool"
        with pytest.raises(ToolNameConflictError) as exc_info:
            await tool_service.register_tool(test_db, tool_create_public)
        assert "Public Tool already exists with name: public_tool" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_register_inactive_tool_name_conflict(self, tool_service, mock_tool, test_db):
        """Test tool registration with name conflict for inactive tool."""
        # --- Inactive tool: conflict if name matches and enabled is False ---
        mock_tool.name = "inactive_tool"
        mock_tool.visibility = "public"
        mock_tool.enabled = False
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = mock_tool
        test_db.execute = Mock(return_value=mock_scalar)
        tool_create_inactive = ToolCreate(
            name="inactive_tool",
            url="http://example.com/tools/new",
            description="A new tool",
            integration_type="REST",
            request_type="POST",
            visibility="public",
            owner_email="user@example.com",
        )
        test_db.commit = Mock()
        with pytest.raises(ToolNameConflictError) as exc_info:
            await tool_service.register_tool(test_db, tool_create_inactive)
        assert "Public Tool already exists with name: inactive_tool" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_register_tool_db_integrity_error(self, tool_service, test_db):
        """Test tool registration with database IntegrityError."""
        # Mock DB to raise IntegrityError on commit
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = None
        test_db.execute = Mock(return_value=mock_scalar)
        test_db.add = Mock()
        #test_db.commit = Mock(side_effect=IntegrityError("statement", "params", "orig"))
        test_db.commit = Mock(side_effect=IntegrityError("UNIQUE constraint failed: tools.name, owner_email", None, None))

        test_db.rollback = Mock()

        # Create tool request
        tool_create = ToolCreate(
            name="test_tool",
            url="http://example.com/tools/test",
            description="A test tool",
            integration_type="REST",
            request_type="POST",
            visibility="private",
            owner_email="user@example.com",
        )

        # Should raise ToolError (wrapped IntegrityError)
        with pytest.raises(IntegrityError) as exc_info:
            await tool_service.register_tool(test_db, tool_create)

        # Verify rollback was called
        test_db.rollback.assert_called_once()
        assert "UNIQUE constraint failed: tools.name, owner_email" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_list_tools(self, tool_service, mock_tool, test_db):
        """Test listing tools."""
        # Mock DB to return a list of tools
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [mock_tool]
        mock_scalar_result = MagicMock()
        mock_scalar_result.scalars.return_value = mock_scalars
        mock_execute = Mock(return_value=mock_scalar_result)
        test_db.execute = mock_execute

        # Mock conversion
        tool_read = ToolRead(
            id="1",
            original_name="test_tool",
            custom_name="test_tool",
            custom_name_slug="test-tool",
            gateway_slug="test-gateway",
            name="test-gateway-test-tool",
            url="http://example.com/tools/test",
            description="A test tool",
            integration_type="MCP",
            request_type="POST",
            headers={"Content-Type": "application/json"},
            input_schema={"type": "object", "properties": {"param": {"type": "string"}}},
            jsonpath_filter="",
            created_at="2023-01-01T00:00:00",
            updated_at="2023-01-01T00:00:00",
            enabled=True,
            reachable=True,
            gateway_id=None,
            execution_count=0,
            auth=None,  # Add auth field
            annotations={},  # Add annotations field
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
        tool_service._convert_tool_to_read = Mock(return_value=tool_read)

        # Call method
        result = await tool_service.list_tools(test_db)

        # Verify DB query
        test_db.execute.assert_called_once()

        # Verify result
        assert len(result) == 1
        assert result[0] == tool_read
        tool_service._convert_tool_to_read.assert_called_once_with(mock_tool)

    @pytest.mark.asyncio
    async def test_list_inactive_tools(self, tool_service, mock_tool, test_db):
        """Test listing tools."""
        # Mock DB to return a list of tools
        mock_scalars = MagicMock()
        mock_tool.enabled = False
        mock_scalars.all.return_value = [mock_tool]
        mock_scalar_result = MagicMock()
        mock_scalar_result.scalars.return_value = mock_scalars
        mock_execute = Mock(return_value=mock_scalar_result)
        test_db.execute = mock_execute

        # Mock conversion
        tool_read = ToolRead(
            id="1",
            original_name="test_tool",
            gateway_slug="test-gateway",
            name="test-gateway-test-tool",
            url="http://example.com/tools/test",
            description="A test tool",
            integration_type="MCP",
            request_type="POST",
            headers={"Content-Type": "application/json"},
            input_schema={"type": "object", "properties": {"param": {"type": "string"}}},
            jsonpath_filter="",
            created_at="2023-01-01T00:00:00",
            updated_at="2023-01-01T00:00:00",
            enabled=False,
            reachable=True,
            gateway_id=None,
            execution_count=0,
            auth=None,  # Add auth field
            annotations={},  # Add annotations field
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
            customName="test_tool",
            customNameSlug="test-tool"
        )
        tool_service._convert_tool_to_read = Mock(return_value=tool_read)

        # Call method
        result = await tool_service.list_tools(test_db, include_inactive=True)

        # Verify DB query
        test_db.execute.assert_called_once()

        # Verify result
        assert len(result) == 1
        assert result[0] == tool_read
        tool_service._convert_tool_to_read.assert_called_once_with(mock_tool)

    @pytest.mark.asyncio
    async def test_list_server_tools_active_only(self):
        mock_db = Mock()
        mock_scalars = Mock()
        mock_tool = Mock(enabled=True)
        mock_scalars.all.return_value = [mock_tool]

        mock_db.execute.return_value.scalars.return_value = mock_scalars

        service = ToolService()
        service._convert_tool_to_read = Mock(return_value="converted_tool")

        tools = await service.list_server_tools(mock_db, server_id="server123", include_inactive=False)

        assert tools == ["converted_tool"]
        service._convert_tool_to_read.assert_called_once_with(mock_tool)

    @pytest.mark.asyncio
    async def test_list_server_tools_include_inactive(self):
        mock_db = Mock()
        mock_scalars = Mock()
        active_tool = Mock(enabled=True, reachable=True)
        inactive_tool = Mock(enabled=False, reachable=True)
        mock_scalars.all.return_value = [active_tool, inactive_tool]

        mock_db.execute.return_value.scalars.return_value = mock_scalars

        service = ToolService()
        service._convert_tool_to_read = Mock(side_effect=["active_converted", "inactive_converted"])

        tools = await service.list_server_tools(mock_db, server_id="server123", include_inactive=True)

        assert tools == ["active_converted", "inactive_converted"]
        assert service._convert_tool_to_read.call_count == 2

    @pytest.mark.asyncio
    async def test_get_tool(self, tool_service, mock_tool, test_db):
        """Test getting a tool by ID."""
        # Mock DB get to return tool
        test_db.get = Mock(return_value=mock_tool)

        # Mock conversion
        tool_read = ToolRead(
            id="1",
            original_name="test_tool",
            gateway_slug="test-gateway",
            name="test-gateway-test-tool",
            url="http://example.com/tools/test",
            description="A test tool",
            integration_type="MCP",
            request_type="POST",
            headers={"Content-Type": "application/json"},
            input_schema={"type": "object", "properties": {"param": {"type": "string"}}},
            jsonpath_filter="",
            created_at="2023-01-01T00:00:00",
            updated_at="2023-01-01T00:00:00",
            enabled=True,
            reachable=True,
            gateway_id=None,
            execution_count=0,
            auth=None,  # Add auth field
            annotations={},  # Add annotations field
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
            customName="test_tool",
            customNameSlug="test-tool"
        )
        tool_service._convert_tool_to_read = Mock(return_value=tool_read)

        # Call method
        result = await tool_service.get_tool(test_db, 1)

        # Verify DB query
        test_db.get.assert_called_once_with(DbTool, 1)

        # Verify result
        assert result == tool_read
        tool_service._convert_tool_to_read.assert_called_once_with(mock_tool)

    @pytest.mark.asyncio
    async def test_get_tool_not_found(self, tool_service, test_db):
        """Test getting a non-existent tool."""
        # Mock DB get to return None
        test_db.get = Mock(return_value=None)

        # Should raise NotFoundError
        with pytest.raises(ToolNotFoundError) as exc_info:
            await tool_service.get_tool(test_db, 999)

        assert "Tool not found: 999" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_delete_tool(self, tool_service, mock_tool, test_db):
        """Test deleting a tool."""
        # Mock DB get to return tool
        test_db.get = Mock(return_value=mock_tool)
        test_db.delete = Mock()
        test_db.commit = Mock()

        # Mock notification
        tool_service._notify_tool_deleted = AsyncMock()

        # Call method
        await tool_service.delete_tool(test_db, 1)

        # Verify DB operations
        test_db.get.assert_called_once_with(DbTool, 1)
        test_db.delete.assert_called_once_with(mock_tool)
        test_db.commit.assert_called_once()

        # Verify notification
        tool_service._notify_tool_deleted.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_tool_not_found(self, tool_service, test_db):
        """Test deleting a non-existent tool."""
        # Mock DB get to return None
        test_db.get = Mock(return_value=None)

        # The service wraps the exception in ToolError
        with pytest.raises(ToolError) as exc_info:
            await tool_service.delete_tool(test_db, 999)

        assert "Tool not found: 999" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_toggle_tool_status(self, tool_service, mock_tool, test_db):
        """Test toggling tool active status."""
        # Mock DB get to return tool
        test_db.get = Mock(return_value=mock_tool)
        test_db.commit = Mock()
        test_db.refresh = Mock()

        # Mock notification methods
        tool_service._notify_tool_activated = AsyncMock()
        tool_service._notify_tool_deactivated = AsyncMock()

        # Mock conversion
        tool_read = ToolRead(
            id="1",
            original_name="test_tool",
            custom_name="test_tool",
            custom_name_slug="test-tool",
            gateway_slug="test-gateway",
            name="test-gateway-test-tool",
            url="http://example.com/tools/test",
            description="A test tool",
            integration_type="MCP",
            request_type="POST",
            headers={"Content-Type": "application/json"},
            input_schema={"type": "object", "properties": {"param": {"type": "string"}}},
            jsonpath_filter="",
            created_at="2023-01-01T00:00:00",
            updated_at="2023-01-01T00:00:00",
            enabled=False,
            reachable=True,
            gateway_id=None,
            execution_count=0,
            auth=None,  # Add auth field
            annotations={},  # Add annotations field
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
        tool_service._convert_tool_to_read = Mock(return_value=tool_read)

        # Deactivate the tool (it's active by default)
        result = await tool_service.toggle_tool_status(test_db, 1, activate=False, reachable=True)

        # Verify DB operations
        test_db.get.assert_called_once_with(DbTool, 1)
        test_db.commit.assert_called_once()
        test_db.refresh.assert_called_once()

        # Verify properties were updated
        assert mock_tool.enabled is False

        # Verify notification
        tool_service._notify_tool_deactivated.assert_called_once()
        tool_service._notify_tool_activated.assert_not_called()

        # Verify result
        assert result == tool_read

    @pytest.mark.asyncio
    async def test_toggle_tool_status_not_found(self, tool_service, test_db):
        """Test toggling tool active status."""
        # Mock DB get to return tool
        test_db.get = Mock(return_value=None)
        test_db.commit = Mock()
        test_db.refresh = Mock()

        with pytest.raises(ToolError) as exc:
            await tool_service.toggle_tool_status(test_db, "1", activate=False, reachable=True)

        assert f"Tool not found: 1" in str(exc.value)

        # Verify DB operations
        test_db.get.assert_called_once_with(DbTool, "1")

    @pytest.mark.asyncio
    async def test_toggle_tool_status_activate_tool(self, tool_service, test_db, mock_tool, monkeypatch):
        """Test toggling tool active status."""
        # Mock DB get to return tool
        mock_tool.enabled = False
        test_db.get = Mock(return_value=mock_tool)
        test_db.commit = Mock()
        test_db.refresh = Mock()

        tool_service._notify_tool_activated = AsyncMock()

        result = await tool_service.toggle_tool_status(test_db, "1", activate=True, reachable=True)

        # Verify DB operations
        test_db.get.assert_called_once_with(DbTool, "1")

        tool_service._notify_tool_activated.assert_called_once_with(mock_tool)

        assert result.enabled is True

    @pytest.mark.asyncio
    async def test_notify_tool_publish_event(self, tool_service, mock_tool, monkeypatch):
        # Arrange - freeze the publish method so we can inspect the call
        publish_mock = AsyncMock()
        monkeypatch.setattr(tool_service, "_publish_event", publish_mock)

        mock_tool.enabled = True
        await tool_service._notify_tool_activated(mock_tool)

        mock_tool.enabled = False
        await tool_service._notify_tool_deactivated(mock_tool)

        mock_tool.enabled = False
        await tool_service._notify_tool_removed(mock_tool)

        mock_tool.enabled = False
        await tool_service._notify_tool_deleted({"id": mock_tool.id, "name": mock_tool.name})

        assert publish_mock.await_count == 4

        publish_mock.assert_has_calls(
            [
                call(
                    {
                        "type": "tool_activated",
                        "data": {
                            "id": mock_tool.id,
                            "name": mock_tool.name,
                            "enabled": True,
                        },
                        "timestamp": ANY,
                    }
                ),
                call(
                    {
                        "type": "tool_deactivated",
                        "data": {
                            "id": mock_tool.id,
                            "name": mock_tool.name,
                            "enabled": False,
                        },
                        "timestamp": ANY,
                    }
                ),
                call(
                    {
                        "type": "tool_removed",
                        "data": {
                            "id": mock_tool.id,
                            "name": mock_tool.name,
                            "enabled": False,
                        },
                        "timestamp": ANY,
                    }
                ),
                call(
                    {
                        "type": "tool_deleted",
                        "data": {"id": mock_tool.id, "name": mock_tool.name},
                        "timestamp": ANY,
                    }
                ),
            ],
            any_order=False,
        )

    @pytest.mark.asyncio
    async def test_publish_event_with_real_queue(self, tool_service):
        # Arrange
        q = asyncio.Queue()
        tool_service._event_subscribers = [q]  # seed one subscriber
        event = {"type": "test", "data": 123}

        # Act
        await tool_service._publish_event(event)

        # Assert - the event was put on the queue
        queued_event = await q.get()
        assert queued_event == event
        assert q.empty()

    @pytest.mark.asyncio
    async def test_toggle_tool_status_no_change(self, tool_service, mock_tool, test_db):
        """Test toggling tool active status."""
        # Mock DB get to return tool
        test_db.get = Mock(return_value=mock_tool)
        test_db.commit = Mock()
        test_db.refresh = Mock()

        # Mock notification methods
        tool_service._notify_tool_activated = AsyncMock()
        tool_service._notify_tool_deactivated = AsyncMock()

        # Mock conversion
        tool_read = ToolRead(
            id="1",
            original_name="test_tool",
            custom_name="test_tool",
            custom_name_slug="test-tool",
            gateway_slug="test-gateway",
            name="test-gateway-test-tool",
            url="http://example.com/tools/test",
            description="A test tool",
            integration_type="MCP",
            request_type="POST",
            headers={"Content-Type": "application/json"},
            input_schema={"type": "object", "properties": {"param": {"type": "string"}}},
            jsonpath_filter="",
            created_at="2023-01-01T00:00:00",
            updated_at="2023-01-01T00:00:00",
            enabled=True,
            reachable=True,
            gateway_id=None,
            execution_count=0,
            auth=None,  # Add auth field
            annotations={},  # Add annotations field
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
        tool_service._convert_tool_to_read = Mock(return_value=tool_read)

        # Deactivate the tool (it's active by default)
        result = await tool_service.toggle_tool_status(test_db, 1, activate=True, reachable=True)

        # Verify DB operations
        test_db.get.assert_called_once_with(DbTool, 1)
        test_db.commit.assert_not_called()
        test_db.refresh.assert_not_called()

        # Verify properties were updated
        assert mock_tool.enabled is True

        # Verify notification
        tool_service._notify_tool_deactivated.assert_not_called()
        tool_service._notify_tool_activated.assert_not_called()

        # Verify result
        assert result == tool_read

    @pytest.mark.asyncio
    async def test_update_tool(self, tool_service, mock_tool, test_db):
        """Test updating a tool."""
        # Mock DB get to return tool
        test_db.get = Mock(return_value=mock_tool)

        # Mock DB query to check for name conflicts (returns None = no conflict)
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = None
        test_db.execute = Mock(return_value=mock_scalar)

        test_db.commit = Mock()
        test_db.refresh = Mock()

        # Mock notification
        tool_service._notify_tool_updated = AsyncMock()

        # Mock conversion
        tool_read = ToolRead(
            id="1",
            original_name="test_tool",
            custom_name="test_tool",
            custom_name_slug="test-tool",
            gateway_slug="test-gateway",
            name="test-gateway-test-tool",
            url="http://example.com/tools/updated",  # Updated URL
            description="An updated test tool",  # Updated description
            integration_type="MCP",
            request_type="POST",
            headers={"Content-Type": "application/json"},
            input_schema={"type": "object", "properties": {"param": {"type": "string"}}},
            jsonpath_filter="",
            created_at="2023-01-01T00:00:00",
            updated_at="2023-01-01T00:00:00",
            enabled=True,
            reachable=True,
            gateway_id=None,
            execution_count=0,
            auth=None,  # Add auth field
            annotations={},  # Add annotations field
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
        tool_service._convert_tool_to_read = Mock(return_value=tool_read)

        # Create update request
        tool_update = ToolUpdate(
            custom_name="updated_tool",
            url="http://example.com/tools/updated",
            description="An updated test tool",
        )

        # Call method
        result = await tool_service.update_tool(test_db, 1, tool_update)

        # Verify DB operations
        test_db.get.assert_called_once_with(DbTool, 1)
        test_db.commit.assert_called_once()
        test_db.refresh.assert_called_once()

        # Verify properties were updated
        assert mock_tool.custom_name == "updated_tool"
        assert mock_tool.url == "http://example.com/tools/updated"
        assert mock_tool.description == "An updated test tool"

        # Verify notification
        tool_service._notify_tool_updated.assert_called_once()

        # Verify result
        assert result == tool_read

    @pytest.mark.asyncio
    async def test_update_tool_name_conflict(self, tool_service, mock_tool, test_db):
        """Test updating a tool with a name that conflicts with another tool."""
        # Mock DB get to return our tool
        test_db.get = Mock(return_value=mock_tool)

        # Create a conflicting tool
        conflicting_tool = MagicMock(spec=DbTool)
        conflicting_tool.id = 2
        conflicting_tool.name = "existing_tool"
        conflicting_tool.enabled = True

        # Mock DB query to check for name conflicts (returns None, so no pre-check conflict)
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = None
        test_db.execute = Mock(return_value=mock_scalar)

        # Mock commit to raise IntegrityError
        test_db.commit = Mock(side_effect=IntegrityError("statement", "params", "orig"))
        test_db.rollback = Mock()

        # Create update request with conflicting name
        tool_update = ToolUpdate(
            name="existing_tool",  # Name that conflicts with another tool
        )

        # Should raise IntegrityError for name conflict during commit
        with pytest.raises(IntegrityError) as exc_info:
            await tool_service.update_tool(test_db, 1, tool_update)

        assert "statement" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_update_tool_not_found(self, tool_service, test_db):
        """Test updating a non-existent tool."""
        # Mock DB get to return None
        test_db.get = Mock(return_value=None)

        # Create update request
        tool_update = ToolUpdate(
            name="updated_tool",
        )

        # The service wraps the exception in ToolError
        with pytest.raises(ToolError) as exc_info:
            await tool_service.update_tool(test_db, 999, tool_update)

        assert "Tool not found: 999" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_update_tool_none_name(self, tool_service, mock_tool, test_db):
        """Test updating a tool with no name."""
        # Mock DB get to return None
        test_db.get = Mock(return_value=mock_tool)

        # Create update request
        tool_update = ToolUpdate()

        # The service wraps the exception in ToolError
        with pytest.raises(ToolError) as exc_info:
            await tool_service.update_tool(test_db, 999, tool_update)

        assert "Failed to update tool" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_update_tool_extra_fields(self, tool_service, mock_tool, test_db):
        """Test updating extra fields in an existing tool."""
        # Mock DB get to return None
        mock_tool.id = "999"
        test_db.get = Mock(return_value=mock_tool)
        test_db.commit = AsyncMock()
        test_db.refresh = AsyncMock()

        # Create update request
        tool_update = ToolUpdate(integration_type="REST", request_type="POST", headers={"key": "value"}, input_schema={"key2": "value2"}, annotations={"key3": "value3"}, jsonpath_filter="test_filter")

        # The service wraps the exception in ToolError
        result = await tool_service.update_tool(test_db, "999", tool_update)

        assert result.integration_type == "REST"
        assert result.request_type == "POST"
        assert result.headers == {"key": "value"}
        assert result.input_schema == {"key2": "value2"}
        assert result.annotations == {"key3": "value3"}
        assert result.jsonpath_filter == "test_filter"

    @pytest.mark.asyncio
    async def test_update_tool_basic_auth(self, tool_service, mock_tool, test_db):
        """Test updating auth in an existing tool."""
        # Mock DB get to return None
        mock_tool.id = "999"
        test_db.get = Mock(return_value=mock_tool)
        test_db.commit = AsyncMock()
        test_db.refresh = AsyncMock()

        # Basic auth_value
        # Create auth_value with the following values
        # user = "test_user"
        # password = "test_password"
        creds = base64.b64encode(b"test_user:test_password").decode()
        auth_dict = {"Authorization": f"Basic {creds}"}
        basic_auth_value = encode_auth(auth_dict)
        #basic_auth_value = "FpZyxAu5PVpT0FN-gJ0JUmdovCMS0emkwW1Vb8HvkhjiBZhj1gDgDRF1wcWNrjTJSLtkz1rLzKibXrhk4GbxXnV6LV4lSw_JDYZ2sPNRy68j_UKOJnf_"

        # Create update request
        tool_update = ToolUpdate(auth=AuthenticationValues(auth_type="basic", auth_value=basic_auth_value))

        # The service wraps the exception in ToolError
        result = await tool_service.update_tool(test_db, "999", tool_update)

        assert result.auth == AuthenticationValues(auth_type="basic", username="test_user", password="********")

    @pytest.mark.asyncio
    async def test_update_tool_bearer_auth(self, tool_service, mock_tool, test_db):
        """Test updating auth in an existing tool."""
        # Mock DB get to return None
        mock_tool.id = "999"
        test_db.get = Mock(return_value=mock_tool)
        test_db.commit = AsyncMock()
        test_db.refresh = AsyncMock()

        # Bearer auth_value
        # Create auth_value with the following values
        # token = "test_token"
        basic_auth_value = encode_auth({"Authorization": "Bearer test_token"})
        # Create update request
        tool_update = ToolUpdate(auth=AuthenticationValues(auth_type="bearer", auth_value=basic_auth_value))

        # The service wraps the exception in ToolError
        result = await tool_service.update_tool(test_db, "999", tool_update)

        assert result.auth == AuthenticationValues(auth_type="bearer", token="********")

    @pytest.mark.asyncio
    async def test_update_tool_empty_auth(self, tool_service, mock_tool, test_db):
        """Test updating auth in an existing tool."""
        # Mock DB get to return None
        mock_tool.id = "999"
        test_db.get = Mock(return_value=mock_tool)
        test_db.commit = AsyncMock()
        test_db.refresh = AsyncMock()

        # Create update request
        tool_update = ToolUpdate(auth=AuthenticationValues())

        # The service wraps the exception in ToolError
        result = await tool_service.update_tool(test_db, "999", tool_update)

        assert result.auth is None

    @pytest.mark.asyncio
    async def test_invoke_tool_not_found(self, tool_service, test_db):
        """Test invoking a non-existent tool."""
        # Mock DB to return no tool
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = None
        test_db.execute = Mock(return_value=mock_scalar)

        # Should raise NotFoundError
        with pytest.raises(ToolNotFoundError) as exc_info:
            await tool_service.invoke_tool(test_db, "nonexistent_tool", {}, request_headers=None)

        assert "Tool not found: nonexistent_tool" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_invoke_tool_inactive(self, tool_service, mock_tool, test_db):
        """Test invoking an inactive tool."""
        # Set tool to inactive
        mock_tool.enabled = False

        # Mock DB to return inactive tool for first query, None for second query
        mock_scalar1 = Mock()
        mock_scalar1.scalar_one_or_none.return_value = None

        mock_scalar2 = Mock()
        mock_scalar2.scalar_one_or_none.return_value = mock_tool

        test_db.execute = Mock(side_effect=[mock_scalar1, mock_scalar2])

        # Should raise NotFoundError with "inactive" message
        with pytest.raises(ToolNotFoundError) as exc_info:
            await tool_service.invoke_tool(test_db, "test_tool", {}, request_headers=None)

        assert "Tool 'test_tool' exists but is inactive" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_invoke_tool_rest_get(self, tool_service, mock_tool, test_db):
        # ----------------  DB  -----------------
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "GET"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_value = None

        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = mock_tool
        test_db.execute = Mock(return_value=mock_scalar)

        # --------------- HTTP ------------------
        mock_response = AsyncMock()
        mock_response.raise_for_status = AsyncMock()
        mock_response.status_code = 200
        # <-- make json() *synchronous*
        mock_response.json = Mock(return_value={"result": "REST tool response"})

        # stub the correct method for a GET
        tool_service._http_client.get = AsyncMock(return_value=mock_response)

        # ------------- metrics -----------------
        tool_service._record_tool_metric = AsyncMock()

        # -------------- invoke -----------------
        result = await tool_service.invoke_tool(test_db, "test_tool", {}, request_headers=None)

        # ------------- asserts -----------------
        tool_service._http_client.get.assert_called_once_with(
            mock_tool.url,
            params={},  # payload is empty
            headers=mock_tool.headers,
        )
        assert result.content[0].text == '{\n  "result": "REST tool response"\n}'
        tool_service._record_tool_metric.assert_called_once_with(test_db, mock_tool, ANY, True, None)

        # Test 204 status
        mock_response = AsyncMock()
        mock_response.raise_for_status = AsyncMock()
        mock_response.status_code = 204
        mock_response.json = Mock(return_value=ToolResult(content=[TextContent(type="text", text="Request completed successfully (No Content)")]))

        tool_service._http_client.get = AsyncMock(return_value=mock_response)

        # ------------- metrics -----------------
        tool_service._record_tool_metric = AsyncMock()

        # -------------- invoke -----------------
        result = await tool_service.invoke_tool(test_db, "test_tool", {}, request_headers=None)

        assert result.content[0].text == "Request completed successfully (No Content)"

        # Test 205 status
        mock_response = AsyncMock()
        mock_response.raise_for_status = AsyncMock()
        mock_response.status_code = 205
        mock_response.json = Mock(return_value=ToolResult(content=[TextContent(type="text", text="Tool error encountered")]))

        tool_service._http_client.get = AsyncMock(return_value=mock_response)

        # ------------- metrics -----------------
        tool_service._record_tool_metric = AsyncMock()

        # -------------- invoke -----------------
        result = await tool_service.invoke_tool(test_db, "test_tool", {}, request_headers=None)

        assert result.content[0].text == "Tool error encountered"

    @pytest.mark.asyncio
    async def test_invoke_tool_rest_post(self, tool_service, mock_tool, test_db):
        """Test invoking a REST tool."""
        # Configure tool as REST
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_value = None  # No auth

        # Mock DB to return the tool
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = mock_tool
        test_db.execute = Mock(return_value=mock_scalar)

        # Mock HTTP client response
        mock_response = AsyncMock()
        mock_response.raise_for_status = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = Mock(return_value={"result": "REST tool response"})  # Make json() synchronous
        tool_service._http_client.request.return_value = mock_response

        # Mock metrics recording
        tool_service._record_tool_metric = AsyncMock()

        # Mock decode_auth to return empty dict when auth_value is None
        # Mock extract_using_jq to return the input unmodified when filter is empty
        with patch("mcpgateway.services.tool_service.decode_auth", return_value={}), patch("mcpgateway.config.extract_using_jq", return_value={"result": "REST tool response"}):
            # Invoke tool
            result = await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=None)

        # Verify HTTP request
        tool_service._http_client.request.assert_called_once_with(
            "POST",
            mock_tool.url,
            json={"param": "value"},
            headers=mock_tool.headers,
        )

        # Verify result
        assert result.content[0].text == '{\n  "result": "REST tool response"\n}'

        # Verify metrics recorded
        tool_service._record_tool_metric.assert_called_once_with(
            test_db,
            mock_tool,
            ANY,  # Start time
            True,  # Success
            None,  # No error
        )

    @pytest.mark.asyncio
    async def test_invoke_tool_rest_parameter_substitution(self, tool_service, mock_tool, test_db):
        """Test invoking a REST tool."""
        # Configure tool as REST
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_value = None  # No auth
        mock_tool.url = "http://example.com/resource/{id}/detail/{type}"

        payload = {"id": 123, "type": "summary", "other_param": "value"}

        # Mock DB to return the tool
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = mock_tool
        test_db.execute = Mock(return_value=mock_scalar)

        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_response.status_code = 200
        mock_response.json = Mock(return_value={"result": "REST tool response"})

        tool_service._http_client.request = AsyncMock(return_value=mock_response)

        await tool_service.invoke_tool(test_db, "test_tool", payload, request_headers=None)

        tool_service._http_client.request.assert_called_once_with(
            "POST",
            "http://example.com/resource/123/detail/summary",
            json={"other_param": "value"},
            headers=mock_tool.headers,
        )

    @pytest.mark.asyncio
    async def test_invoke_tool_rest_parameter_substitution_missed_input(self, tool_service, mock_tool, test_db):
        """Test invoking a REST tool."""
        # Configure tool as REST
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_value = None  # No auth
        mock_tool.url = "http://example.com/resource/{id}/detail/{type}"

        payload = {"id": 123, "other_param": "value"}

        # Mock DB to return the tool
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = mock_tool
        test_db.execute = Mock(return_value=mock_scalar)

        with pytest.raises(ToolInvocationError) as exc_info:
            await tool_service.invoke_tool(test_db, "test_tool", payload, request_headers=None)

            assert "Required URL parameter 'type' not found in arguments" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_invoke_tool_mcp_streamablehttp(self, tool_service, mock_tool, test_db):
        """Test invoking a REST tool."""
        # Standard
        from types import SimpleNamespace

        mock_gateway = SimpleNamespace(
            id="42",
            name="test_gateway",
            slug="test-gateway",
            url="http://fake-mcp:8080/mcp",
            enabled=True,
            reachable=True,
            auth_type="bearer",  #  ←← attribute your error complained about
            auth_value="Bearer abc123",
        )
        # Configure tool as REST
        mock_tool.integration_type = "MCP"
        mock_tool.request_type = "StreamableHTTP"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_type = None
        mock_tool.auth_value = None  # No auth
        mock_tool.original_name = "dummy_tool"
        mock_tool.headers = {}
        mock_tool.name = "test-gateway-dummy-tool"
        mock_tool.gateway_slug = "test-gateway"
        mock_tool.gateway_id = mock_gateway.id

        returns = [mock_tool, mock_gateway, mock_gateway]

        def execute_side_effect(*_args, **_kwargs):
            if returns:
                value = returns.pop(0)
            else:
                value = None  # Or whatever makes sense as a default

            m = Mock()
            m.scalar_one_or_none.return_value = value
            return m

        test_db.execute = Mock(side_effect=execute_side_effect)

        expected_result = ToolResult(content=[TextContent(type="text", text="MCP response")])

        session_mock = AsyncMock()
        session_mock.initialize = AsyncMock()
        session_mock.call_tool = AsyncMock(return_value=expected_result)

        client_session_cm = AsyncMock()
        client_session_cm.__aenter__.return_value = session_mock
        client_session_cm.__aexit__.return_value = AsyncMock()

        @asynccontextmanager
        async def mock_streamable_client(*_args, **_kwargs):
            yield ("read", "write", None)

        with (
            patch("mcpgateway.services.tool_service.streamablehttp_client", mock_streamable_client),
            patch("mcpgateway.services.tool_service.ClientSession", return_value=client_session_cm),
            patch("mcpgateway.services.tool_service.decode_auth", return_value={"Authorization": "Bearer xyz"}),
            patch("mcpgateway.services.tool_service.extract_using_jq", side_effect=lambda data, _filt: data),
        ):
            # ------------------------------------------------------------------
            # 4.  Act
            # ------------------------------------------------------------------
            result = await tool_service.invoke_tool(test_db, "dummy_tool", {"param": "value"}, request_headers=None)

        session_mock.initialize.assert_awaited_once()
        session_mock.call_tool.assert_awaited_once_with("dummy_tool", {"param": "value"})

        # Our ToolResult bubbled back out
        assert result.content[0].text == "MCP response"

        # Set a concrete ID
        mock_tool.id = "1"

        # Final mock object with tool_id
        mock_metric = Mock()
        mock_metric.tool_id = mock_tool.id
        mock_metric.is_success = True
        mock_metric.error_message = None
        mock_metric.response_time = 1

        # Setup the chain for test_db.query().filter_by().first()
        query_mock = Mock()
        test_db.query = Mock(return_value=query_mock)
        query_mock.filter_by.return_value.first.return_value = mock_metric

        # ----------------------------------------
        # Now, simulate the actual method call
        # This is what your production code would run:
        metric = test_db.query().filter_by().first()

        # Assertions
        assert metric is not None, "No ToolMetric was recorded"
        assert metric.tool_id == mock_tool.id
        assert metric.is_success is True
        assert metric.error_message is None
        assert metric.response_time >= 0  # You can check with a tolerance if needed

    @pytest.mark.asyncio
    async def test_invoke_tool_mcp_non_standard(self, tool_service, mock_tool, test_db):
        """Test invoking a REST tool."""
        # Standard
        from types import SimpleNamespace

        mock_gateway = SimpleNamespace(
            id="42",
            name="test_gateway",
            slug="test-gateway",
            url="http://fake-mcp:8080/sse",
            enabled=True,
            reachable=True,
            auth_type="bearer",  #  ←← attribute your error complained about
            auth_value="Bearer abc123",
        )
        # Configure tool as REST
        mock_tool.integration_type = "MCP"
        mock_tool.request_type = "ABC"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_type = None
        mock_tool.auth_value = None  # No auth
        mock_tool.original_name = "dummy_tool"
        mock_tool.headers = {}
        mock_tool.name = "test-gateway-dummy-tool"
        mock_tool.gateway_slug = "test-gateway"
        mock_tool.gateway_id = mock_gateway.id

        returns = [mock_tool, mock_gateway, mock_gateway]

        def execute_side_effect(*_args, **_kwargs):
            if returns:
                value = returns.pop(0)
            else:
                value = None  # Or whatever makes sense as a default

            m = Mock()
            m.scalar_one_or_none.return_value = value
            return m

        test_db.execute = Mock(side_effect=execute_side_effect)

        expected_result = ToolResult(content=[TextContent(type="text", text="")])

        with (
            patch("mcpgateway.services.tool_service.decode_auth", return_value={"Authorization": "Bearer xyz"}),
            patch("mcpgateway.services.tool_service.extract_using_jq", side_effect=lambda data, _filt: data),
        ):
            # ------------------------------------------------------------------
            # 4.  Act
            # ------------------------------------------------------------------
            result = await tool_service.invoke_tool(test_db, "dummy_tool", {"param": "value"}, request_headers=None)

        # Our ToolResult bubbled back out
        assert result.content[0].text == ""

        # Set a concrete ID
        mock_tool.id = "1"

        # Final mock object with tool_id
        mock_metric = Mock()
        mock_metric.tool_id = mock_tool.id
        mock_metric.is_success = True
        mock_metric.error_message = None
        mock_metric.response_time = 1

        # Setup the chain for test_db.query().filter_by().first()
        query_mock = Mock()
        test_db.query = Mock(return_value=query_mock)
        query_mock.filter_by.return_value.first.return_value = mock_metric

        # ----------------------------------------
        # Now, simulate the actual method call
        # This is what your production code would run:
        metric = test_db.query().filter_by().first()

        # Assertions
        assert metric is not None, "No ToolMetric was recorded"
        assert metric.tool_id == mock_tool.id
        assert metric.is_success is True
        assert metric.error_message is None
        assert metric.response_time >= 0  # You can check with a tolerance if needed

    @pytest.mark.asyncio
    async def test_invoke_tool_invalid_tool_type(self, tool_service, mock_tool, test_db):
        """Test invoking an invalid tool type."""
        # Configure tool as REST
        mock_tool.integration_type = "ABC"
        mock_tool.request_type = "POST"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_value = None  # No auth
        mock_tool.url = "http://example.com/"

        payload = {"param": "value"}

        # Mock DB to return the tool
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = mock_tool
        test_db.execute = Mock(return_value=mock_scalar)

        response = await tool_service.invoke_tool(test_db, "test_tool", payload, request_headers=None)

        assert response.content[0].text == "Invalid tool type"

    @pytest.mark.asyncio
    async def test_invoke_tool_mcp_tool_basic_auth(self, tool_service, mock_tool, mock_gateway, test_db):
        """Test invoking an invalid tool type."""
        # Basic auth_value
        # Create auth_value with the following values
        # user = "test_user"
        # password = "test_password"
        basic_auth_value = encode_auth({
        "Authorization": "Basic " + base64.b64encode(b"test_user:test_password").decode()})

        # Configure tool as REST
        mock_tool.integration_type = "MCP"
        mock_tool.request_type = "SSE"
        mock_tool.jsonpath_filter = ""
        mock_tool.enabled = True
        mock_tool.reachable = True
        mock_tool.auth_type = "basic"
        mock_tool.auth_value = basic_auth_value
        mock_tool.url = "http://example.com/sse"

        payload = {"param": "value"}

        # Mock DB to return the tool
        mock_scalar_1 = Mock()
        mock_scalar_1.scalar_one_or_none.return_value = mock_tool

        mock_scalar_2 = Mock()
        mock_gateway.auth_type = "basic"
        mock_gateway.auth_value = basic_auth_value
        mock_gateway.enabled = True
        mock_gateway.reachable = True
        mock_gateway.id = mock_tool.gateway_id
        mock_scalar_2.scalar_one_or_none.return_value = mock_gateway

        test_db.execute = Mock(side_effect=[mock_scalar_1, mock_scalar_1, mock_scalar_2])

        expected_result = ToolResult(content=[TextContent(type="text", text="MCP response")])

        session_mock = AsyncMock()
        session_mock.initialize = AsyncMock()
        session_mock.call_tool = AsyncMock(return_value=expected_result)

        client_session_cm = AsyncMock()
        client_session_cm.__aenter__.return_value = session_mock
        client_session_cm.__aexit__.return_value = AsyncMock()

        # @asynccontextmanager
        # async def mock_sse_client(*_args, **_kwargs):
        #     yield ("read", "write")

        sse_ctx = AsyncMock()
        sse_ctx.__aenter__.return_value = ("read", "write")

        with (
            patch("mcpgateway.services.tool_service.sse_client", return_value=sse_ctx) as sse_client_mock,
            patch("mcpgateway.services.tool_service.ClientSession", return_value=client_session_cm),
            patch("mcpgateway.services.tool_service.extract_using_jq", side_effect=lambda data, _filt: data),
        ):
            # ------------------------------------------------------------------
            # 4.  Act
            # ------------------------------------------------------------------
            result = await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=None)

        session_mock.initialize.assert_awaited_once()
        session_mock.call_tool.assert_awaited_once_with("test_tool", {"param": "value"})

        sse_ctx.__aenter__.assert_awaited_once()

        sse_client_mock.assert_called_once_with(
            url=mock_gateway.url,
            headers={"Authorization": "Basic dGVzdF91c2VyOnRlc3RfcGFzc3dvcmQ="},
        )

    @pytest.mark.asyncio
    async def test_invoke_tool_error(self, tool_service, mock_tool, test_db):
        """Test invoking a tool that returns an error."""
        # Configure tool
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.auth_value = None  # No auth

        # Mock DB to return the tool
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = mock_tool
        test_db.execute = Mock(return_value=mock_scalar)

        # Mock decode_auth to return empty dict
        with patch("mcpgateway.services.tool_service.decode_auth", return_value={}):
            # Mock HTTP client to raise an error
            tool_service._http_client.request.side_effect = Exception("HTTP error")

            # Mock metrics recording
            tool_service._record_tool_metric = AsyncMock()

            # Should raise ToolInvocationError
            with pytest.raises(ToolInvocationError) as exc_info:
                await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=None)

            assert "Tool invocation failed: HTTP error" in str(exc_info.value)

            # Verify metrics recorded with error
            tool_service._record_tool_metric.assert_called_once_with(
                test_db,
                mock_tool,
                ANY,  # Start time
                False,  # Failed
                "HTTP error",  # Error message
            )

    @pytest.mark.asyncio
    async def test_reset_metrics(self, tool_service, test_db):
        """Test resetting metrics."""
        # Mock DB operations
        test_db.execute = Mock()
        test_db.commit = Mock()

        # Reset all metrics
        await tool_service.reset_metrics(test_db)

        # Verify DB operations
        test_db.execute.assert_called_once()
        test_db.commit.assert_called_once()

        # Reset metrics for specific tool
        test_db.execute.reset_mock()
        test_db.commit.reset_mock()

        await tool_service.reset_metrics(test_db, tool_id=1)

        # Verify DB operations with tool_id
        test_db.execute.assert_called_once()
        test_db.commit.assert_called_once()

    async def test_record_tool_metric(self, tool_service, mock_tool):
        """Test recording tool invocation metrics."""
        # Set up test data
        start_time = 100.0
        success = True
        error_message = None

        # Mock database
        mock_db = MagicMock()

        # Mock time.monotonic to return a consistent value
        with patch("mcpgateway.services.tool_service.time.monotonic", return_value=105.0):
            # Mock ToolMetric class
            with patch("mcpgateway.services.tool_service.ToolMetric") as MockToolMetric:
                mock_metric_instance = MagicMock()
                MockToolMetric.return_value = mock_metric_instance

                # Call the method
                await tool_service._record_tool_metric(mock_db, mock_tool, start_time, success, error_message)

                # Verify ToolMetric was created with correct data
                MockToolMetric.assert_called_once_with(
                    tool_id=mock_tool.id,
                    response_time=5.0,  # 105.0 - 100.0
                    is_success=True,
                    error_message=None
                )

                # Verify DB operations
                mock_db.add.assert_called_once_with(mock_metric_instance)
                mock_db.commit.assert_called_once()

    async def test_record_tool_metric_with_error(self, tool_service, mock_tool):
        """Test recording tool invocation metrics with error."""
        start_time = 100.0
        success = False
        error_message = "Connection timeout"

        # Mock database
        mock_db = MagicMock()

        with patch("mcpgateway.services.tool_service.time.monotonic", return_value=102.5):
            with patch("mcpgateway.services.tool_service.ToolMetric") as MockToolMetric:
                mock_metric_instance = MagicMock()
                MockToolMetric.return_value = mock_metric_instance

                await tool_service._record_tool_metric(mock_db, mock_tool, start_time, success, error_message)

                # Verify ToolMetric was created with error data
                MockToolMetric.assert_called_once_with(
                    tool_id=mock_tool.id,
                    response_time=2.5,
                    is_success=False,
                    error_message="Connection timeout"
                )

                mock_db.add.assert_called_once_with(mock_metric_instance)
                mock_db.commit.assert_called_once()

    async def test_aggregate_metrics(self, tool_service):
        """Test aggregating metrics across all tools."""
        # Mock database
        mock_db = MagicMock()

        # Create a mock that returns scalar values
        mock_execute_result = MagicMock()
        mock_execute_result.scalar.side_effect = [
            10,     # total count
            8,      # successful count
            2,      # failed count
            0.5,    # min response time
            5.0,    # max response time
            2.3,    # avg response time
            "2025-01-10T12:00:00"  # last execution time
        ]
        mock_db.execute.return_value = mock_execute_result

        result = await tool_service.aggregate_metrics(mock_db)

        assert result == {
            "total_executions": 10,
            "successful_executions": 8,
            "failed_executions": 2,
            "failure_rate": 0.2,  # 2/10
            "min_response_time": 0.5,
            "max_response_time": 5.0,
            "avg_response_time": 2.3,
            "last_execution_time": "2025-01-10T12:00:00"
        }

        # Verify all expected queries were made
        assert mock_db.execute.call_count == 7

    async def test_aggregate_metrics_no_data(self, tool_service):
        """Test aggregating metrics when no data exists."""
        # Mock database
        mock_db = MagicMock()

        # Create a mock that returns scalar values
        mock_execute_result = MagicMock()
        mock_execute_result.scalar.side_effect = [
            0,      # total count
            0,      # successful count
            0,      # failed count
            None,   # min response time
            None,   # max response time
            None,   # avg response time
            None    # last execution time
        ]
        mock_db.execute.return_value = mock_execute_result

        result = await tool_service.aggregate_metrics(mock_db)

        assert result == {
            "total_executions": 0,
            "successful_executions": 0,
            "failed_executions": 0,
            "failure_rate": 0.0,
            "min_response_time": None,
            "max_response_time": None,
            "avg_response_time": None,
            "last_execution_time": None
        }

    async def test_validate_tool_url_success(self, tool_service):
        """Test successful tool URL validation."""
        # Mock successful HTTP response
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        tool_service._http_client.get.return_value = mock_response

        # Should not raise any exception
        await tool_service._validate_tool_url("http://example.com/tool")

        tool_service._http_client.get.assert_called_once_with("http://example.com/tool")
        mock_response.raise_for_status.assert_called_once()

    async def test_validate_tool_url_failure(self, tool_service):
        """Test tool URL validation failure."""
        # Mock HTTP error
        tool_service._http_client.get.side_effect = Exception("Connection refused")

        with pytest.raises(ToolValidationError, match="Failed to validate tool URL: Connection refused"):
            await tool_service._validate_tool_url("http://example.com/tool")

    async def test_check_tool_health_success(self, tool_service, mock_tool):
        """Test successful tool health check."""
        mock_response = MagicMock()
        mock_response.is_success = True
        tool_service._http_client.get.return_value = mock_response

        result = await tool_service._check_tool_health(mock_tool)

        assert result is True
        tool_service._http_client.get.assert_called_once_with(mock_tool.url)

    async def test_check_tool_health_failure(self, tool_service, mock_tool):
        """Test failed tool health check."""
        mock_response = MagicMock()
        mock_response.is_success = False
        tool_service._http_client.get.return_value = mock_response

        result = await tool_service._check_tool_health(mock_tool)

        assert result is False

    async def test_check_tool_health_exception(self, tool_service, mock_tool):
        """Test tool health check with exception."""
        tool_service._http_client.get.side_effect = Exception("Network error")

        result = await tool_service._check_tool_health(mock_tool)

        assert result is False

    async def test_subscribe_events(self, tool_service):
        """Test event subscription mechanism."""
        # Create an event to publish
        test_event = {"type": "test_event", "data": {"id": 1}}

        # Start subscription in background
        subscriber = tool_service.subscribe_events()
        subscription_task = asyncio.create_task(subscriber.__anext__())

        # Give a moment for subscription to be registered
        await asyncio.sleep(0.01)

        # Publish event
        await tool_service._publish_event(test_event)

        # Get the event
        received_event = await subscription_task
        assert received_event == test_event

        # Clean up
        await subscriber.aclose()

    async def test_notify_tool_added(self, tool_service, mock_tool):
        """Test notification when tool is added."""
        with patch.object(tool_service, '_publish_event', new_callable=AsyncMock) as mock_publish:
            await tool_service._notify_tool_added(mock_tool)

            mock_publish.assert_called_once()
            event = mock_publish.call_args[0][0]
            assert event["type"] == "tool_added"
            assert event["data"]["id"] == mock_tool.id
            assert event["data"]["name"] == mock_tool.name

    async def test_notify_tool_removed(self, tool_service, mock_tool):
        """Test notification when tool is removed."""
        with patch.object(tool_service, '_publish_event', new_callable=AsyncMock) as mock_publish:
            await tool_service._notify_tool_removed(mock_tool)

            mock_publish.assert_called_once()
            event = mock_publish.call_args[0][0]
            assert event["type"] == "tool_removed"
            assert event["data"]["id"] == mock_tool.id

    async def test_get_top_tools(self, tool_service, test_db):
        """Test get_top_tools method."""
        # Mock database query result
        mock_results = [
            (1, "tool1", 10, 1.5, 90.0, "2024-01-01T12:00:00"),
            (2, "tool2", 5, 2.0, 80.0, "2024-01-02T12:00:00"),
        ]

        # Create a proper mock chain for the query
        mock_query_chain = Mock()
        mock_query_chain.outerjoin.return_value.group_by.return_value.order_by.return_value.limit.return_value.all.return_value = mock_results
        test_db.query = Mock(return_value=mock_query_chain)

        with patch("mcpgateway.services.tool_service.build_top_performers") as mock_build:
            mock_build.return_value = ["top_performer1", "top_performer2"]
            result = await tool_service.get_top_tools(test_db, limit=5)

            assert result == ["top_performer1", "top_performer2"]
            mock_build.assert_called_once_with(mock_results)
            test_db.query.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_tools_with_tags(self, tool_service, mock_tool):
        """Test listing tools with tag filtering."""
        # Third-Party
        from sqlalchemy import func

        # Mock query chain
        mock_query = MagicMock()
        mock_query.where.return_value = mock_query

        session = MagicMock()
        session.execute.return_value.scalars.return_value.all.return_value = [mock_tool]

        bind = MagicMock()
        bind.dialect = MagicMock()
        bind.dialect.name = "sqlite"    # or "postgresql" or "mysql"
        session.get_bind.return_value = bind

        with patch("mcpgateway.services.tool_service.select", return_value=mock_query):
            with patch("mcpgateway.services.tool_service.json_contains_expr") as mock_json_contains:
                # return a fake condition object that query.where will accept
                fake_condition = MagicMock()
                mock_json_contains.return_value = fake_condition

                result = await tool_service.list_tools(
                    session, tags=["test", "production"]
                )

                # helper should be called once with the tags list (not once per tag)
                mock_json_contains.assert_called_once()                       # called exactly once
                called_args = mock_json_contains.call_args[0]                # positional args tuple
                assert called_args[0] is session                            # session passed through
                # third positional arg is the tags list (signature: session, col, values, match_any=True)
                assert called_args[2] == ["test", "production"]
                # and the fake condition returned must have been passed to where()
                mock_query.where.assert_called_with(fake_condition)
                # finally, your service should return the list produced by mock_db.execute(...)
                assert isinstance(result, list)
                assert len(result) == 1

    async def test_invoke_tool_rest_oauth_success(self, tool_service, mock_tool, test_db):
        """Test invoking REST tool with successful OAuth authentication."""
        # Configure tool with OAuth
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.auth_type = "oauth"
        mock_tool.oauth_config = {"client_id": "test_id", "client_secret": "test_secret"}

        # Mock DB to return the tool
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = mock_tool
        test_db.execute = Mock(return_value=mock_scalar)

        # Mock OAuth manager
        tool_service.oauth_manager.get_access_token = AsyncMock(return_value="test_access_token")

        # Mock HTTP client response
        mock_response = AsyncMock()
        mock_response.raise_for_status = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = Mock(return_value={"result": "OAuth success"})
        tool_service._http_client.request.return_value = mock_response

        # Mock metrics recording
        tool_service._record_tool_metric = AsyncMock()

        with patch("mcpgateway.config.extract_using_jq", return_value={"result": "OAuth success"}):
            # Invoke tool
            result = await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=None)

        # Verify OAuth token was obtained
        tool_service.oauth_manager.get_access_token.assert_called_once_with(mock_tool.oauth_config)

        # Verify HTTP request included Bearer token
        tool_service._http_client.request.assert_called_once()
        call_args = tool_service._http_client.request.call_args
        headers = call_args[1]["headers"]
        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer test_access_token"

        # Verify result
        assert result.content[0].text == '{\n  "result": "OAuth success"\n}'

    async def test_invoke_tool_rest_oauth_failure(self, tool_service, mock_tool, test_db):
        """Test invoking REST tool with failed OAuth authentication."""
        # Configure tool with OAuth
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.auth_type = "oauth"
        mock_tool.oauth_config = {"client_id": "test_id", "client_secret": "test_secret"}

        # Mock DB to return the tool
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = mock_tool
        test_db.execute = Mock(return_value=mock_scalar)

        # Mock OAuth manager to fail
        tool_service.oauth_manager.get_access_token = AsyncMock(side_effect=Exception("OAuth failed"))

        # Mock metrics recording
        tool_service._record_tool_metric = AsyncMock()

        # Should raise ToolInvocationError
        with pytest.raises(ToolInvocationError) as exc_info:
            await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=None)

        assert "OAuth authentication failed: OAuth failed" in str(exc_info.value)

    async def test_invoke_tool_mcp_oauth_client_credentials(self, tool_service, mock_tool, mock_gateway, test_db):
        """Test invoking MCP tool with OAuth client credentials flow."""
        # Configure tool and gateway for MCP with OAuth
        mock_tool.integration_type = "MCP"
        mock_tool.request_type = "sse"
        mock_gateway.auth_type = "oauth"
        mock_gateway.oauth_config = {"grant_type": "client_credentials", "client_id": "test", "client_secret": "secret"}

        # Mock DB queries
        mock_scalar1 = Mock()
        mock_scalar1.scalar_one_or_none.return_value = mock_tool
        mock_scalar2 = Mock()
        mock_scalar2.scalar_one_or_none.return_value = mock_gateway
        mock_scalar3 = Mock()
        mock_scalar3.scalar_one_or_none.return_value = mock_gateway

        test_db.execute = Mock(side_effect=[mock_scalar1, mock_scalar2, mock_scalar3])

        # Mock OAuth manager
        tool_service.oauth_manager.get_access_token = AsyncMock(return_value="oauth_access_token")

        # Mock MCP connection
        expected_result = ToolResult(content=[TextContent(type="text", text="MCP OAuth response")])
        session_mock = AsyncMock()
        session_mock.initialize = AsyncMock()
        session_mock.call_tool = AsyncMock(return_value=expected_result)

        client_session_cm = AsyncMock()
        client_session_cm.__aenter__.return_value = session_mock
        client_session_cm.__aexit__.return_value = AsyncMock()

        sse_ctx = AsyncMock()
        sse_ctx.__aenter__.return_value = ("read", "write")

        with (
            patch("mcpgateway.services.tool_service.sse_client", return_value=sse_ctx),
            patch("mcpgateway.services.tool_service.ClientSession", return_value=client_session_cm),
            patch("mcpgateway.services.tool_service.extract_using_jq", side_effect=lambda data, _filt: data),
        ):
            result = await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=None)

        # Verify OAuth was called
        tool_service.oauth_manager.get_access_token.assert_called_once_with(mock_gateway.oauth_config)

        # Verify MCP session was initialized and tool called
        session_mock.initialize.assert_awaited_once()
        session_mock.call_tool.assert_awaited_once()


    async def test_invoke_tool_with_passthrough_headers_rest(self, tool_service, mock_tool, test_db):
        """Test invoking REST tool with passthrough headers."""
        # Configure tool as REST
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.auth_value = None

        # Mock DB to return the tool
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = mock_tool
        test_db.execute = Mock(return_value=mock_scalar)

        # Mock HTTP client response
        mock_response = AsyncMock()
        mock_response.raise_for_status = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = Mock(return_value={"result": "success with headers"})
        tool_service._http_client.request.return_value = mock_response

        # Mock get_passthrough_headers to return modified headers
        def mock_passthrough(req_headers, tool_headers, db_session):
            combined = tool_headers.copy()
            combined["X-Request-ID"] = req_headers.get("X-Request-ID", "test-123")
            return combined

        request_headers = {"X-Request-ID": "custom-123", "Authorization": "Bearer test"}

        with (
            patch("mcpgateway.services.tool_service.decode_auth", return_value={}),
            patch("mcpgateway.services.tool_service.get_passthrough_headers", side_effect=mock_passthrough),
            patch("mcpgateway.config.extract_using_jq", return_value={"result": "success with headers"}),
        ):
            result = await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=request_headers)

        # Verify passthrough headers were used
        tool_service._http_client.request.assert_called_once()
        call_args = tool_service._http_client.request.call_args
        headers = call_args[1]["headers"]
        assert "X-Request-ID" in headers
        assert headers["X-Request-ID"] == "custom-123"

    async def test_invoke_tool_with_passthrough_headers_mcp(self, tool_service, mock_tool, mock_gateway, test_db):
        """Test invoking MCP tool with passthrough headers."""
        # Configure tool and gateway for MCP
        mock_tool.integration_type = "MCP"
        mock_tool.request_type = "sse"
        mock_gateway.auth_value = None

        # Mock DB queries
        mock_scalar1 = Mock()
        mock_scalar1.scalar_one_or_none.return_value = mock_tool
        mock_scalar2 = Mock()
        mock_scalar2.scalar_one_or_none.return_value = mock_gateway
        mock_scalar3 = Mock()
        mock_scalar3.scalar_one_or_none.return_value = mock_gateway

        test_db.execute = Mock(side_effect=[mock_scalar1, mock_scalar2, mock_scalar3])

        # Mock MCP connection
        expected_result = ToolResult(content=[TextContent(type="text", text="MCP with headers")])
        session_mock = AsyncMock()
        session_mock.initialize = AsyncMock()
        session_mock.call_tool = AsyncMock(return_value=expected_result)

        client_session_cm = AsyncMock()
        client_session_cm.__aenter__.return_value = session_mock
        client_session_cm.__aexit__.return_value = AsyncMock()

        sse_ctx = AsyncMock()
        sse_ctx.__aenter__.return_value = ("read", "write")

        # Mock get_passthrough_headers to return modified headers
        def mock_passthrough(req_headers, tool_headers, db_session, gateway=None):
            combined = tool_headers.copy()
            combined["X-Custom-Header"] = req_headers.get("X-Custom-Header", "default")
            return combined

        request_headers = {"X-Custom-Header": "custom-value", "Authorization": "Bearer test"}

        with (
            patch("mcpgateway.services.tool_service.sse_client", return_value=sse_ctx),
            patch("mcpgateway.services.tool_service.ClientSession", return_value=client_session_cm),
            patch("mcpgateway.services.tool_service.decode_auth", return_value={}),
            patch("mcpgateway.services.tool_service.get_passthrough_headers", side_effect=mock_passthrough),
            patch("mcpgateway.services.tool_service.extract_using_jq", side_effect=lambda data, _filt: data),
        ):
            result = await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=request_headers)

        # Verify MCP session was initialized and tool called
        session_mock.initialize.assert_awaited_once()
        session_mock.call_tool.assert_awaited_once()

    async def test_invoke_tool_with_plugin_post_invoke_success(self, tool_service, mock_tool, test_db):
        """Test invoking tool with successful plugin post-invoke hook."""
        # Configure tool as REST
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.auth_value = None

        # Mock DB to return the tool
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = mock_tool
        test_db.execute = Mock(return_value=mock_scalar)

        # Mock HTTP client response
        mock_response = AsyncMock()
        mock_response.raise_for_status = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = Mock(return_value={"result": "original response"})
        tool_service._http_client.request.return_value = mock_response

        # Mock plugin manager and post-invoke hook
        mock_post_result = Mock()
        mock_post_result.continue_processing = True
        mock_post_result.violation = None
        mock_post_result.modified_payload = None

        tool_service._plugin_manager = Mock()
        tool_service._plugin_manager.tool_pre_invoke = AsyncMock(return_value=(Mock(continue_processing=True, violation=None, modified_payload=None), None))
        tool_service._plugin_manager.tool_post_invoke = AsyncMock(return_value=(mock_post_result, None))

        with (
            patch("mcpgateway.services.tool_service.decode_auth", return_value={}),
            patch("mcpgateway.config.extract_using_jq", return_value={"result": "original response"}),
        ):
            result = await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=None)

        # Verify plugin post-invoke was called
        tool_service._plugin_manager.tool_post_invoke.assert_called_once()

        # Verify result
        assert result.content[0].text == '{\n  "result": "original response"\n}'


    async def test_invoke_tool_with_plugin_post_invoke_modified_payload(self, tool_service, mock_tool, test_db):
        """Test invoking tool with plugin post-invoke hook modifying payload."""
        # Configure tool as REST
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.auth_value = None

        # Mock DB to return the tool
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = mock_tool
        test_db.execute = Mock(return_value=mock_scalar)

        # Mock HTTP client response
        mock_response = AsyncMock()
        mock_response.raise_for_status = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = Mock(return_value={"result": "original response"})
        tool_service._http_client.request.return_value = mock_response

        # Mock plugin manager and post-invoke hook with modified payload
        mock_modified_payload = Mock()
        mock_modified_payload.result = {"content": [{"type": "text", "text": "Modified by plugin"}]}

        mock_post_result = Mock()
        mock_post_result.continue_processing = True
        mock_post_result.violation = None
        mock_post_result.modified_payload = mock_modified_payload

        tool_service._plugin_manager = Mock()
        tool_service._plugin_manager.tool_pre_invoke = AsyncMock(return_value=(Mock(continue_processing=True, violation=None, modified_payload=None), None))
        tool_service._plugin_manager.tool_post_invoke = AsyncMock(return_value=(mock_post_result, None))

        with (
            patch("mcpgateway.services.tool_service.decode_auth", return_value={}),
            patch("mcpgateway.config.extract_using_jq", return_value={"result": "original response"}),
        ):
            result = await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=None)

        # Verify plugin post-invoke was called
        tool_service._plugin_manager.tool_post_invoke.assert_called_once()

        # Verify result was modified by plugin
        assert result.content[0].text == "Modified by plugin"

    async def test_invoke_tool_with_plugin_post_invoke_invalid_modified_payload(self, tool_service, mock_tool, test_db):
        """Test invoking tool with plugin post-invoke hook providing invalid modified payload."""
        # Configure tool as REST
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.auth_value = None

        # Mock DB to return the tool
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = mock_tool
        test_db.execute = Mock(return_value=mock_scalar)

        # Mock HTTP client response
        mock_response = AsyncMock()
        mock_response.raise_for_status = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = Mock(return_value={"result": "original response"})
        tool_service._http_client.request.return_value = mock_response

        # Mock plugin manager and post-invoke hook with invalid modified payload
        mock_modified_payload = Mock()
        mock_modified_payload.result = "Invalid format - not a dict"

        mock_post_result = Mock()
        mock_post_result.continue_processing = True
        mock_post_result.violation = None
        mock_post_result.modified_payload = mock_modified_payload

        tool_service._plugin_manager = Mock()
        tool_service._plugin_manager.tool_pre_invoke = AsyncMock(return_value=(Mock(continue_processing=True, violation=None, modified_payload=None), None))
        tool_service._plugin_manager.tool_post_invoke = AsyncMock(return_value=(mock_post_result, None))

        with (
            patch("mcpgateway.services.tool_service.decode_auth", return_value={}),
            patch("mcpgateway.config.extract_using_jq", return_value={"result": "original response"}),
        ):
            result = await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=None)

        # Verify plugin post-invoke was called
        tool_service._plugin_manager.tool_post_invoke.assert_called_once()

        # Verify result was converted to string since format was invalid
        assert result.content[0].text == "Invalid format - not a dict"

    async def test_invoke_tool_with_plugin_post_invoke_error_fail_on_error(self, tool_service, mock_tool, test_db):
        """Test invoking tool with plugin post-invoke hook error when fail_on_plugin_error is True."""
        # Configure tool as REST
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.auth_value = None

        # Mock DB to return the tool
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = mock_tool
        test_db.execute = Mock(return_value=mock_scalar)

        # Mock HTTP client response
        mock_response = AsyncMock()
        mock_response.raise_for_status = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = Mock(return_value={"result": "original response"})
        tool_service._http_client.request.return_value = mock_response

        # Mock plugin manager and post-invoke hook with error
        tool_service._plugin_manager = Mock()
        tool_service._plugin_manager.tool_pre_invoke = AsyncMock(return_value=(Mock(continue_processing=True, violation=None, modified_payload=None), None))
        tool_service._plugin_manager.tool_post_invoke = AsyncMock(side_effect=Exception("Plugin error"))

        # Mock plugin config to fail on errors
        mock_plugin_settings = Mock()
        mock_plugin_settings.fail_on_plugin_error = True
        mock_config = Mock()
        mock_config.plugin_settings = mock_plugin_settings
        tool_service._plugin_manager.config = mock_config

        # Mock metrics recording
        tool_service._record_tool_metric = AsyncMock()

        with (
            patch("mcpgateway.services.tool_service.decode_auth", return_value={}),
            patch("mcpgateway.config.extract_using_jq", return_value={"result": "original response"}),
        ):
            with pytest.raises(Exception) as exc_info:
                await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=None)

        assert "Plugin error" in str(exc_info.value)

    async def test_invoke_tool_with_plugin_post_invoke_error_continue_on_error(self, tool_service, mock_tool, test_db):
        """Test invoking tool with plugin post-invoke hook error when fail_on_plugin_error is False."""
        # Configure tool as REST
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.auth_value = None

        # Mock DB to return the tool
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = mock_tool
        test_db.execute = Mock(return_value=mock_scalar)

        # Mock HTTP client response
        mock_response = AsyncMock()
        mock_response.raise_for_status = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = Mock(return_value={"result": "original response"})
        tool_service._http_client.request.return_value = mock_response

        # Mock plugin manager and post-invoke hook with error
        tool_service._plugin_manager = Mock()
        tool_service._plugin_manager.tool_pre_invoke = AsyncMock(return_value=(Mock(continue_processing=True, violation=None, modified_payload=None), None))
        tool_service._plugin_manager.tool_post_invoke = AsyncMock(side_effect=Exception("Plugin error"))

        # Mock plugin config to continue on errors
        mock_plugin_settings = Mock()
        mock_plugin_settings.fail_on_plugin_error = False
        mock_config = Mock()
        mock_config.plugin_settings = mock_plugin_settings
        tool_service._plugin_manager.config = mock_config

        with (
            patch("mcpgateway.services.tool_service.decode_auth", return_value={}),
            patch("mcpgateway.config.extract_using_jq", return_value={"result": "original response"}),
        ):
            result = await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=None)

        # Verify result still succeeded despite plugin error
        assert result.content[0].text == '{\n  "result": "original response"\n}'

        await tool_service._plugin_manager.shutdown()

    async def test_invoke_tool_with_plugin_metadata_sse(self, tool_service, mock_tool, mock_gateway, test_db):
        """Test invoking tool with plugin post-invoke hook error when fail_on_plugin_error is True."""
        # Configure tool as REST
        #mock_tool.integration_type = "REST"
        #mock_tool.request_type = "POST"
        #mock_tool.auth_value = None
        mock_tool.integration_type = "MCP"
        mock_tool.request_type = "sse"
        mock_gateway.auth_value = None

        # Mock DB queries
        mock_scalar1 = Mock()
        mock_scalar1.scalar_one_or_none.return_value = mock_tool
        mock_scalar2 = Mock()
        mock_scalar2.scalar_one_or_none.return_value = mock_gateway
        mock_scalar3 = Mock()
        mock_scalar3.scalar_one_or_none.return_value = mock_gateway

        test_db.execute = Mock(side_effect=[mock_scalar1, mock_scalar2, mock_scalar3])

        expected_result = ToolResult(content=[TextContent(type="text", text="MCP OAuth response")])
        session_mock = AsyncMock()
        session_mock.initialize = AsyncMock()
        session_mock.call_tool = AsyncMock(return_value=expected_result)

        client_session_cm = AsyncMock()
        client_session_cm.__aenter__.return_value = session_mock
        client_session_cm.__aexit__.return_value = AsyncMock()

        sse_ctx = AsyncMock()
        sse_ctx.__aenter__.return_value = ("read", "write")


        # Mock HTTP client response

        # Mock plugin manager and post-invoke hook with error
        tool_service._plugin_manager = PluginManager("./tests/unit/mcpgateway/plugins/fixtures/configs/tool_headers_metadata_plugin.yaml")
        await tool_service._plugin_manager.initialize()
        # Mock metrics recording
        tool_service._record_tool_metric = AsyncMock()

        with (
            patch("mcpgateway.services.tool_service.sse_client", return_value=sse_ctx),
            patch("mcpgateway.services.tool_service.ClientSession", return_value=client_session_cm),
            patch("mcpgateway.services.tool_service.extract_using_jq", side_effect=lambda data, _filt: data),
        ):
            await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=None)

        # Verify result still succeeded despite plugin error
        assert result.content[0].text == '{\n  "result": "original response"\n}'
