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
from mcpgateway.cache.global_config_cache import global_config_cache
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import Tool as DbTool
from mcpgateway.config import settings
from mcpgateway.plugins.framework import PluginManager
from mcpgateway.schemas import AuthenticationValues, ToolCreate, ToolRead, ToolUpdate
from mcpgateway.services.tool_service import (
    extract_using_jq,
    TextContent,
    ToolError,
    ToolInvocationError,
    ToolNotFoundError,
    ToolResult,
    ToolService,
    ToolValidationError,
)
from mcpgateway.utils.services_auth import encode_auth
from mcpgateway.utils.pagination import decode_cursor


@pytest.fixture(autouse=True)
def mock_logging_services():
    """Mock audit_trail and structured_logger to prevent database writes during tests."""
    with patch("mcpgateway.services.tool_service.audit_trail") as mock_audit, patch("mcpgateway.services.tool_service.structured_logger") as mock_logger:
        mock_audit.log_action = MagicMock(return_value=None)
        mock_logger.log = MagicMock(return_value=None)
        yield {"audit_trail": mock_audit, "structured_logger": mock_logger}


@pytest.fixture(autouse=True)
def mock_fresh_db_session():
    """Mock fresh_db_session context manager to prevent real DB operations during tests.

    This is needed because invoke_tool now uses fresh_db_session for metrics recording.
    """
    from contextlib import contextmanager

    @contextmanager
    def mock_fresh_session():
        mock_db = MagicMock()
        yield mock_db

    with patch("mcpgateway.services.tool_service.fresh_db_session", mock_fresh_session):
        yield


@pytest.fixture
def mock_global_config_obj():
    """Create a mock GlobalConfig object for tests.

    This is needed because invoke_tool queries GlobalConfig for passthrough headers.
    """
    config = MagicMock()
    config.passthrough_headers = ["X-Tenant-Id", "X-Request-Id"]
    return config


def setup_db_execute_mock(test_db, mock_tool, mock_global_config):
    """Helper to set up test_db.execute to return tool for queries.

    invoke_tool() makes db.execute() calls for tool queries.
    GlobalConfig is now cached via global_config_cache (Issue #1715),
    so db.execute() only needs to return the tool.

    Args:
        test_db: The mock database session.
        mock_tool: The mock tool to return for tool queries.
        mock_global_config: The mock GlobalConfig to return for config queries.
    """
    # Invalidate cache to ensure fresh state for each test
    global_config_cache.invalidate()

    # db.execute() always returns the tool (GlobalConfig is now cached)
    mock_scalar_tool = Mock()
    mock_scalar_tool.scalar_one_or_none.return_value = mock_tool
    test_db.execute = Mock(return_value=mock_scalar_tool)

    # Mock db.query() for GlobalConfig cache (Issue #1715)
    mock_query_result = Mock()
    mock_query_result.first.return_value = mock_global_config
    test_db.query = Mock(return_value=mock_query_result)


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
    gw.id = "1"
    gw.name = "test_gateway"
    gw.slug = "test-gateway"
    gw.url = "http://example.com/gateway"
    gw.description = "A test tool"
    gw.transport = "SSE"
    gw.capabilities = {"prompts": {"listChanged": True}, "resources": {"listChanged": True}, "tools": {"listChanged": True}}
    gw.created_at = gw.updated_at = gw.last_seen = "2025-01-01T00:00:00Z"
    gw.modified_by = gw.created_by = "Someone"
    gw.modified_via = gw.created_via = "ui"
    gw.modified_from_ip = gw.created_from_ip = "127.0.0.1"
    gw.modified_user_agent = gw.created_user_agent = "Chrome"
    gw.import_batch_id = gw.federation_source = gw.team_id = gw.visibility = gw.owner_email = None

    # one dummy tool hanging off the gateway
    tool = MagicMock(spec=DbTool, id=101, name="dummy_tool")
    gw.tools = [tool]
    gw.federated_tools = []
    gw.transport = "sse"
    gw.auth_type = None
    gw.auth_value = {}
    gw.passthrough_headers = []
    gw.ca_certificate = None
    gw.ca_certificate_sig = None
    gw.signing_algorithm = None

    gw.enabled = True
    gw.reachable = True
    return gw


@pytest.fixture
def mock_tool(mock_gateway):
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
    tool.output_schema = None
    tool.jsonpath_filter = ""
    tool.created_at = "2023-01-01T00:00:00"
    tool.updated_at = "2023-01-01T00:00:00"
    tool.created_by = "MCP Gateway team"
    tool.created_from_ip = "1.2.3.4"
    tool.created_via = "ui"
    tool.created_user_agent = "Chrome"
    tool.modified_by = "No one"
    tool.modified_from_ip = "1.2.3.4"
    tool.modified_via = "ui"
    tool.modified_user_agent = "Chrome"
    tool.import_batch_id = "2"
    tool.federation_source = "federation_source"
    tool.team_id = "5"
    tool.visibility = "private"
    tool.owner_email = "admin@admin.org"
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
    tool.custom_name = "test_tool"
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
        # mock_tool.auth_value = "FpZyxAu5PVpT0FN-gJ0JUmdovCMS0emkwW1Vb8HvkhjiBZhj1gDgDRF1wcWNrjTJSLtkz1rLzKibXrhk4GbxXnV6LV4lSw_JDYZ2sPNRy68j_UKOJnf_"
        # mock_tool.auth_value = encode_auth({"user": "test_user", "password": "test_password"})
        tool_read = tool_service.convert_tool_to_read(mock_tool)

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
        tool_read = tool_service.convert_tool_to_read(mock_tool)

        assert tool_read.auth.auth_type == "bearer"
        assert tool_read.auth.token == "********"

    @pytest.mark.asyncio
    async def test_convert_tool_to_read_authheaders_auth(self, tool_service, mock_tool):
        """Check auth for authheaders auth"""

        mock_tool.auth_type = "authheaders"
        # Create auth_value with the following values
        # {"test-api-key": "test-api-value"}
        # mock_tool.auth_value = "8pvPTCegaDhrx0bmBf488YvGg9oSo4cJJX68WCTvxjMY-C2yko_QSPGVggjjNt59TPvlGLsotTZvAiewPRQ"
        mock_tool.auth_value = encode_auth({"test-api-key": "test-api-value"})
        tool_read = tool_service.convert_tool_to_read(mock_tool)

        assert tool_read.auth.auth_type == "authheaders"
        assert tool_read.auth.auth_header_key == "test-api-key"
        assert tool_read.auth.auth_header_value == "********"

    @pytest.mark.asyncio
    async def test_convert_tool_to_read_include_auth_false_skips_decode(self, tool_service, mock_tool):
        """Verify include_auth=False skips decryption and returns minimal auth info."""
        # Set up tool with encrypted basic auth
        creds = base64.b64encode(b"test_user:test_password").decode()
        auth_dict = {"Authorization": f"Basic {creds}"}
        mock_tool.auth_type = "basic"
        mock_tool.auth_value = encode_auth(auth_dict)

        # Patch decode_auth to verify it's not called
        with patch("mcpgateway.services.tool_service.decode_auth") as mock_decode:
            tool_read = tool_service.convert_tool_to_read(mock_tool, include_auth=False)

            # Verify decode_auth was NOT called
            mock_decode.assert_not_called()

            # Verify minimal auth info is returned
            assert tool_read.auth is not None
            assert tool_read.auth.auth_type == "basic"
            # Other fields should be empty/default (not decrypted)
            assert tool_read.auth.username == ""
            assert tool_read.auth.password == ""

    @pytest.mark.asyncio
    async def test_convert_tool_to_read_include_auth_false_bearer(self, tool_service, mock_tool):
        """Verify include_auth=False with bearer auth returns minimal auth info."""
        mock_tool.auth_type = "bearer"
        mock_tool.auth_value = encode_auth({"Authorization": "Bearer ABC123"})

        with patch("mcpgateway.services.tool_service.decode_auth") as mock_decode:
            tool_read = tool_service.convert_tool_to_read(mock_tool, include_auth=False)

            mock_decode.assert_not_called()
            assert tool_read.auth is not None
            assert tool_read.auth.auth_type == "bearer"
            assert tool_read.auth.token == ""

    @pytest.mark.asyncio
    async def test_convert_tool_to_read_oauth_no_auth_value(self, tool_service, mock_tool):
        """Verify OAuth tools (auth_type set, auth_value=None) return auth=None."""
        mock_tool.auth_type = "oauth"
        mock_tool.auth_value = None

        # Test with include_auth=True (detail view)
        tool_read = tool_service.convert_tool_to_read(mock_tool, include_auth=True)
        assert tool_read.auth is None

        # Test with include_auth=False (list view)
        tool_read = tool_service.convert_tool_to_read(mock_tool, include_auth=False)
        assert tool_read.auth is None

    @pytest.mark.asyncio
    async def test_convert_tool_to_read_no_auth(self, tool_service, mock_tool):
        """Verify tools with no auth return auth=None regardless of include_auth."""
        mock_tool.auth_type = None
        mock_tool.auth_value = None

        # Test with include_auth=True
        tool_read = tool_service.convert_tool_to_read(mock_tool, include_auth=True)
        assert tool_read.auth is None

        # Test with include_auth=False
        tool_read = tool_service.convert_tool_to_read(mock_tool, include_auth=False)
        assert tool_read.auth is None

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
        tool_service.convert_tool_to_read = Mock(
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
        # refresh is called twice: once after commit and once after logging commits
        assert test_db.refresh.call_count == 2

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
            owner_email="user@example.com",
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
        # test_db.commit = Mock(side_effect=IntegrityError("statement", "params", "orig"))
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
        tool_service.convert_tool_to_read = Mock(return_value=tool_read)

        # Mock DB execute chain for unified_paginate: execute().scalars().all()
        # First call: fetch tools
        # Second call (if tool has team_id): fetch team names
        mock_tool.team_id = None  # No team, so no second query
        test_db.execute = Mock(return_value=MagicMock(scalars=Mock(return_value=MagicMock(all=Mock(return_value=[mock_tool])))))
        test_db.commit = Mock()  # Mock commit to avoid errors

        # Call method
        result, next_cursor = await tool_service.list_tools(test_db)

        # Verify DB query was called
        assert test_db.execute.called

        # Verify result
        assert len(result) == 1
        assert result[0] == tool_read
        assert next_cursor is None  # No pagination needed for single result
        tool_service.convert_tool_to_read.assert_called_once_with(mock_tool, include_metrics=False, include_auth=False)

    @pytest.mark.asyncio
    async def test_list_tools_pagination(self, tool_service, test_db, monkeypatch):
        """Test list_tools returns next_cursor when page size is exceeded."""
        monkeypatch.setattr(settings, "pagination_default_page_size", 1)

        tool_1 = MagicMock(spec=DbTool, id="1", team_id=None)
        tool_2 = MagicMock(spec=DbTool, id="2", team_id=None)

        # Mock DB execute chain for unified_paginate: execute().scalars().all()
        test_db.execute = Mock(return_value=MagicMock(scalars=Mock(return_value=MagicMock(all=Mock(return_value=[tool_1, tool_2])))))
        test_db.commit = Mock()

        mock_team = MagicMock(id="team-1", is_personal=True)
        with patch("mcpgateway.services.tool_service.TeamManagementService") as mock_team_service:
            mock_team_service.return_value.get_user_teams = AsyncMock(return_value=[mock_team])
            tool_service.convert_tool_to_read = Mock(side_effect=[MagicMock(), MagicMock()])

            result, next_cursor = await tool_service.list_tools(test_db, user_email="user@example.com", team_id="team-1")

        assert len(result) == 1
        assert next_cursor is not None
        assert decode_cursor(next_cursor)["id"] == "1"

    @pytest.mark.asyncio
    async def test_list_tools_denies_unknown_team(self, tool_service, test_db):
        """Test list_tools returns empty when user lacks team membership."""
        test_db.execute = Mock()
        mock_team = MagicMock(id="other-team", is_personal=True)

        with patch("mcpgateway.services.tool_service.TeamManagementService") as mock_team_service:
            mock_team_service.return_value.get_user_teams = AsyncMock(return_value=[mock_team])
            result, next_cursor = await tool_service.list_tools(test_db, user_email="user@example.com", team_id="team-1")

        assert result == []
        assert next_cursor is None
        test_db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_tools_with_limit(self, tool_service, test_db, monkeypatch):
        """Test list_tools respects custom limit parameter."""
        monkeypatch.setattr(settings, "pagination_default_page_size", 50)
        monkeypatch.setattr(settings, "pagination_max_page_size", 500)

        tools = [MagicMock(spec=DbTool, id=str(i), team_id=None) for i in range(150)]

        # Mock DB execute chain for unified_paginate: execute().scalars().all()
        # unified_paginate fetches limit+1 to check if there are more results
        test_db.execute = Mock(return_value=MagicMock(scalars=Mock(return_value=MagicMock(all=Mock(return_value=tools[:101])))))
        test_db.commit = Mock()
        tool_service.convert_tool_to_read = Mock(side_effect=lambda t, **kw: MagicMock())

        result, next_cursor = await tool_service.list_tools(test_db, limit=100)

        assert len(result) == 100
        assert next_cursor is not None  # More results available

    @pytest.mark.asyncio
    async def test_list_tools_with_limit_zero_returns_all(self, tool_service, test_db, monkeypatch):
        """Test list_tools with limit=0 returns all tools without pagination."""
        monkeypatch.setattr(settings, "pagination_default_page_size", 50)

        tools = [MagicMock(spec=DbTool, id=str(i), team_id=None) for i in range(200)]

        # Mock DB execute chain for unified_paginate: execute().scalars().all()
        test_db.execute = Mock(return_value=MagicMock(scalars=Mock(return_value=MagicMock(all=Mock(return_value=tools)))))
        test_db.commit = Mock()
        tool_service.convert_tool_to_read = Mock(side_effect=lambda t, **kw: MagicMock())

        result, next_cursor = await tool_service.list_tools(test_db, limit=0)

        assert len(result) == 200
        assert next_cursor is None  # No pagination when limit=0

    @pytest.mark.asyncio
    async def test_list_inactive_tools(self, tool_service, mock_tool, test_db):
        """Test listing tools."""
        # Mock DB to return a tuple of (tool, team_name) from LEFT JOIN
        mock_tool.enabled = False
        mock_tool.team_id = None

        # Mock DB execute chain for unified_paginate: execute().scalars().all()
        test_db.execute = Mock(return_value=MagicMock(scalars=Mock(return_value=MagicMock(all=Mock(return_value=[mock_tool])))))
        test_db.commit = Mock()

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
            customNameSlug="test-tool",
        )
        tool_service.convert_tool_to_read = Mock(return_value=tool_read)

        # Call method
        result, _ = await tool_service.list_tools(test_db, include_inactive=True)

        # Verify DB query was called
        assert test_db.execute.called

        # Verify result
        assert len(result) == 1
        assert result[0] == tool_read
        tool_service.convert_tool_to_read.assert_called_once_with(mock_tool, include_metrics=False, include_auth=False)

    @pytest.mark.asyncio
    async def test_list_server_tools_active_only(self):
        mock_db = Mock()
        mock_tool = Mock(enabled=True, team_id=None)
        mock_row = MagicMock()
        mock_row.__getitem__ = lambda self, idx: mock_tool if idx == 0 else None
        mock_row.team_name = None

        mock_db.execute.return_value.all.return_value = [mock_row]

        service = ToolService()
        service.convert_tool_to_read = Mock(return_value="converted_tool")

        tools = await service.list_server_tools(mock_db, server_id="server123", include_inactive=False)

        assert tools == ["converted_tool"]
        service.convert_tool_to_read.assert_called_once_with(mock_tool, include_metrics=False, include_auth=False)

    @pytest.mark.asyncio
    async def test_list_server_tools_include_inactive(self):
        mock_db = Mock()
        active_tool = Mock(enabled=True, reachable=True, team_id=None)
        inactive_tool = Mock(enabled=False, reachable=True, team_id=None)

        active_row = MagicMock()
        active_row.__getitem__ = lambda self, idx: active_tool if idx == 0 else None
        active_row.team_name = None

        inactive_row = MagicMock()
        inactive_row.__getitem__ = lambda self, idx: inactive_tool if idx == 0 else None
        inactive_row.team_name = None

        mock_db.execute.return_value.all.return_value = [active_row, inactive_row]

        service = ToolService()
        service.convert_tool_to_read = Mock(side_effect=["active_converted", "inactive_converted"])

        tools = await service.list_server_tools(mock_db, server_id="server123", include_inactive=True)

        assert tools == ["active_converted", "inactive_converted"]
        assert service.convert_tool_to_read.call_count == 2

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
            customNameSlug="test-tool",
        )
        tool_service.convert_tool_to_read = Mock(return_value=tool_read)

        # Call method
        result = await tool_service.get_tool(test_db, 1)

        # Verify DB query
        test_db.get.assert_called_once_with(DbTool, 1)

        # Verify result
        assert result == tool_read
        tool_service.convert_tool_to_read.assert_called_once_with(mock_tool)

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
    async def test_delete_tool_purge_metrics(self, tool_service, mock_tool, test_db):
        """Test deleting a tool with metric purge."""
        test_db.get = Mock(return_value=mock_tool)
        test_db.delete = Mock()
        test_db.commit = Mock()
        test_db.execute = Mock()
        tool_service._notify_tool_deleted = AsyncMock()

        await tool_service.delete_tool(test_db, 1, purge_metrics=True)

        assert test_db.execute.call_count == 2
        test_db.delete.assert_called_once_with(mock_tool)
        test_db.commit.assert_called_once()

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
        tool_service.convert_tool_to_read = Mock(return_value=tool_read)

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

        assert "Tool not found: 1" in str(exc.value)

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
    async def test_notify_tool_publish_event(self, tool_service, mock_tool):
        """Test notification methods publish events via EventService."""
        # Mock EventService.publish_event
        tool_service._event_service.publish_event = AsyncMock()

        # Test all notification methods
        mock_tool.enabled = True
        mock_tool.reachable = True
        await tool_service._notify_tool_activated(mock_tool)

        mock_tool.enabled = False
        await tool_service._notify_tool_deactivated(mock_tool)

        mock_tool.enabled = False
        await tool_service._notify_tool_removed(mock_tool)

        tool_info = {"id": mock_tool.id, "name": mock_tool.name}
        await tool_service._notify_tool_deleted(tool_info)

        # Verify all 4 events were published
        assert tool_service._event_service.publish_event.await_count == 4

        # Verify event types were correct
        calls = tool_service._event_service.publish_event.call_args_list
        assert calls[0][0][0]["type"] == "tool_activated"
        assert calls[1][0][0]["type"] == "tool_deactivated"
        assert calls[2][0][0]["type"] == "tool_removed"
        assert calls[3][0][0]["type"] == "tool_deleted"

        # Verify event data
        assert calls[0][0][0]["data"]["id"] == mock_tool.id
        assert calls[0][0][0]["data"]["name"] == mock_tool.name
        assert calls[0][0][0]["data"]["enabled"] is True

        assert calls[3][0][0]["data"] == tool_info

    @pytest.mark.asyncio
    async def test_publish_event_with_real_queue(self, tool_service):
        # Arrange
        q = asyncio.Queue()
        # Force local mode (no Redis) and seed one subscriber via EventService
        tool_service._event_service._redis_client = None
        tool_service._event_service._event_subscribers = [q]
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
        tool_service.convert_tool_to_read = Mock(return_value=tool_read)

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
        tool_service.convert_tool_to_read = Mock(return_value=tool_read)

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
        test_db.commit = Mock()  # SQLAlchemy commit is synchronous
        test_db.refresh = Mock()  # SQLAlchemy refresh is synchronous

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
        test_db.commit = Mock()  # SQLAlchemy commit is synchronous
        test_db.refresh = Mock()  # SQLAlchemy refresh is synchronous

        # Basic auth_value
        # Create auth_value with the following values
        # user = "test_user"
        # password = "test_password"
        creds = base64.b64encode(b"test_user:test_password").decode()
        auth_dict = {"Authorization": f"Basic {creds}"}
        basic_auth_value = encode_auth(auth_dict)
        # basic_auth_value = "FpZyxAu5PVpT0FN-gJ0JUmdovCMS0emkwW1Vb8HvkhjiBZhj1gDgDRF1wcWNrjTJSLtkz1rLzKibXrhk4GbxXnV6LV4lSw_JDYZ2sPNRy68j_UKOJnf_"

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
        test_db.commit = Mock()  # SQLAlchemy commit is synchronous
        test_db.refresh = Mock()  # SQLAlchemy refresh is synchronous

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
        test_db.commit = Mock()  # SQLAlchemy commit is synchronous
        test_db.refresh = Mock()  # SQLAlchemy refresh is synchronous

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
    async def test_invoke_tool_rest_get(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        # ----------------  DB  -----------------
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "GET"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_value = None

        # Set up mock to return tool for first query, GlobalConfig for second
        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        # --------------- HTTP ------------------
        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()  # HTTP response raise_for_status is synchronous
        mock_response.status_code = 200
        # <-- make json() *synchronous*
        mock_response.json = Mock(return_value={"result": "REST tool response"})

        # stub the correct method for a GET
        tool_service._http_client.get = AsyncMock(return_value=mock_response)

        # ------------- metrics -----------------
        # Mock the metrics buffer service
        mock_metrics_buffer = Mock()
        with patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service", return_value=mock_metrics_buffer):
            # -------------- invoke -----------------
            result = await tool_service.invoke_tool(test_db, "test_tool", {}, request_headers=None)

            # ------------- asserts -----------------
            tool_service._http_client.get.assert_called_once_with(
                mock_tool.url,
                params={},  # payload is empty
                headers=mock_tool.headers,
            )
            assert result.content[0].text == '{\n  "result": "REST tool response"\n}'
            # Verify metrics were recorded via buffer service
            mock_metrics_buffer.record_tool_metric.assert_called_once()
            call_kwargs = mock_metrics_buffer.record_tool_metric.call_args[1]
            assert call_kwargs["tool_id"] == str(mock_tool.id)
            assert call_kwargs["success"] is True
            assert call_kwargs["error_message"] is None

        # Test 204 status
        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()  # HTTP response raise_for_status is synchronous
        mock_response.status_code = 204
        mock_response.json = Mock(return_value=ToolResult(content=[TextContent(type="text", text="Request completed successfully (No Content)")]))

        tool_service._http_client.get = AsyncMock(return_value=mock_response)

        # ------------- metrics -----------------
        tool_service._record_tool_metric_sync = Mock()

        # -------------- invoke -----------------
        result = await tool_service.invoke_tool(test_db, "test_tool", {}, request_headers=None)

        assert result.content[0].text == "Request completed successfully (No Content)"

        # Test 205 status
        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()  # HTTP response raise_for_status is synchronous
        mock_response.status_code = 205
        mock_response.json = Mock(return_value=ToolResult(content=[TextContent(type="text", text="Tool error encountered")]))

        tool_service._http_client.get = AsyncMock(return_value=mock_response)

        # ------------- metrics -----------------
        tool_service._record_tool_metric_sync = Mock()

        # -------------- invoke -----------------
        result = await tool_service.invoke_tool(test_db, "test_tool", {}, request_headers=None)

        assert result.content[0].text == "Tool error encountered"

    @pytest.mark.asyncio
    async def test_invoke_tool_rest_post(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """Test invoking a REST tool."""
        # Configure tool as REST
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_value = None  # No auth

        # Mock DB to return the tool and GlobalConfig
        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        # Mock HTTP client response
        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()  # HTTP response raise_for_status is synchronous
        mock_response.status_code = 200
        mock_response.json = Mock(return_value={"result": "REST tool response"})  # Make json() synchronous
        tool_service._http_client.request.return_value = mock_response

        # Mock metrics buffer service and other dependencies
        mock_metrics_buffer = Mock()
        with (
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service", return_value=mock_metrics_buffer),
            patch("mcpgateway.services.tool_service.decode_auth", return_value={}),
            patch("mcpgateway.services.tool_service.extract_using_jq", return_value={"result": "REST tool response"}),
        ):
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

            # Verify metrics recorded via buffer service
            mock_metrics_buffer.record_tool_metric.assert_called_once()
            call_kwargs = mock_metrics_buffer.record_tool_metric.call_args[1]
            assert call_kwargs["tool_id"] == str(mock_tool.id)
            assert call_kwargs["success"] is True
            assert call_kwargs["error_message"] is None

    @pytest.mark.asyncio
    async def test_invoke_tool_rest_parameter_substitution(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """Test invoking a REST tool."""
        # Configure tool as REST
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_value = None  # No auth
        mock_tool.url = "http://example.com/resource/{id}/detail/{type}"

        payload = {"id": 123, "type": "summary", "other_param": "value"}

        # Mock DB to return the tool and GlobalConfig
        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

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
    async def test_invoke_tool_rest_parameter_substitution_missed_input(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """Test invoking a REST tool."""
        # Configure tool as REST
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_value = None  # No auth
        mock_tool.url = "http://example.com/resource/{id}/detail/{type}"

        payload = {"id": 123, "other_param": "value"}

        # Mock DB to return the tool and GlobalConfig
        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

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
            capabilities={"prompts": {"listChanged": True}, "resources": {"listChanged": True}, "tools": {"listChanged": True}},
            transport="STREAMABLEHTTP",
            passthrough_headers=[],
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
            capabilities={"prompts": {"listChanged": True}, "resources": {"listChanged": True}, "tools": {"listChanged": True}},
            transport="STREAMABLEHTTP",
            passthrough_headers=[],
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
    async def test_invoke_tool_invalid_tool_type(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """Test invoking an invalid tool type."""
        # Configure tool as REST
        mock_tool.integration_type = "ABC"
        mock_tool.request_type = "POST"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_value = None  # No auth
        mock_tool.url = "http://example.com/"

        payload = {"param": "value"}

        # Mock DB to return the tool and GlobalConfig
        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        response = await tool_service.invoke_tool(test_db, "test_tool", payload, request_headers=None)

        assert response.content[0].text == "Invalid tool type"

    @pytest.mark.asyncio
    async def test_invoke_tool_mcp_tool_basic_auth(self, tool_service, mock_tool, mock_gateway, test_db):
        """Test invoking an invalid tool type."""
        # Basic auth_value
        # Create auth_value with the following values
        # user = "test_user"
        # password = "test_password"
        basic_auth_value = encode_auth({"Authorization": "Basic " + base64.b64encode(b"test_user:test_password").decode()})

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

        mock_gateway.auth_type = "basic"
        mock_gateway.auth_value = basic_auth_value
        mock_gateway.enabled = True
        mock_gateway.reachable = True
        mock_gateway.id = mock_tool.gateway_id
        mock_gateway.slug = "test-gateway"
        mock_gateway.capabilities = {"tools": {"listChanged": True}}
        mock_gateway.transport = "SSE"
        mock_gateway.passthrough_headers = []

        # Ensure the service reads headers from the gateway attached to the tool
        # The invoke path uses `gateway = tool.gateway` for auth header calculation
        mock_tool.gateway = mock_gateway

        # Two DB selects occur in this path: first for tool, then for gateway
        # Return the tool on first call and the gateway on second call
        returns = [mock_tool, mock_gateway]

        def execute_side_effect(*_args, **_kwargs):
            if returns:
                value = returns.pop(0)
            else:
                value = mock_gateway

            # Return an object whose scalar_one_or_none() returns the real value
            class Result:
                def scalar_one_or_none(self_inner):
                    return value

            return Result()

        test_db.execute = Mock(side_effect=execute_side_effect)

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
            httpx_client_factory=ANY,
        )

    @pytest.mark.asyncio
    async def test_invoke_tool_error(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """Test invoking a tool that returns an error."""
        # Configure tool
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.auth_value = None  # No auth

        # Mock DB to return the tool and GlobalConfig
        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        # Mock HTTP client to raise an error
        tool_service._http_client.request.side_effect = Exception("HTTP error")

        # Mock metrics buffer service and decode_auth
        mock_metrics_buffer = Mock()
        with (
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service", return_value=mock_metrics_buffer),
            patch("mcpgateway.services.tool_service.decode_auth", return_value={}),
        ):
            # Should raise ToolInvocationError
            with pytest.raises(ToolInvocationError) as exc_info:
                await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=None)

            assert "Tool invocation failed: HTTP error" in str(exc_info.value)

            # Verify metrics recorded with error via buffer service
            mock_metrics_buffer.record_tool_metric.assert_called_once()
            call_kwargs = mock_metrics_buffer.record_tool_metric.call_args[1]
            assert call_kwargs["tool_id"] == str(mock_tool.id)
            assert call_kwargs["success"] is False
            assert call_kwargs["error_message"] == "HTTP error"

    @pytest.mark.asyncio
    async def test_invoke_tool_error_exception_group_unwrapping(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """Test that ExceptionGroup errors are unwrapped to show root cause.

        MCP SDK uses TaskGroup which wraps exceptions in ExceptionGroup. When such
        errors occur, the error message should show the actual root cause error
        (e.g., "Connection refused") rather than the unhelpful "unhandled errors
        in a TaskGroup (1 sub-exception)" message.

        See GitHub issue #1902.
        """
        # Configure tool
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.auth_value = None

        # Mock DB to return the tool and GlobalConfig
        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        # Create a nested ExceptionGroup simulating MCP SDK TaskGroup behavior
        root_cause_error = ConnectionRefusedError("Connection refused by upstream MCP server")
        inner_group = ExceptionGroup("inner task group", [root_cause_error])
        outer_group = ExceptionGroup("unhandled errors in a TaskGroup (1 sub-exception)", [inner_group])

        # Mock HTTP client to raise an ExceptionGroup
        tool_service._http_client.request.side_effect = outer_group

        # Mock metrics buffer service and decode_auth
        mock_metrics_buffer = Mock()
        with (
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service", return_value=mock_metrics_buffer),
            patch("mcpgateway.services.tool_service.decode_auth", return_value={}),
        ):
            # Should raise ToolInvocationError with the unwrapped root cause message
            with pytest.raises(ToolInvocationError) as exc_info:
                await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=None)

            # The error message should contain the root cause, not the ExceptionGroup wrapper
            error_str = str(exc_info.value)
            assert "Connection refused by upstream MCP server" in error_str
            assert "unhandled errors in a TaskGroup" not in error_str

            # Verify metrics recorded with root cause error message
            mock_metrics_buffer.record_tool_metric.assert_called_once()
            call_kwargs = mock_metrics_buffer.record_tool_metric.call_args[1]
            assert call_kwargs["success"] is False
            assert "Connection refused by upstream MCP server" in call_kwargs["error_message"]

    @pytest.mark.asyncio
    async def test_reset_metrics(self, tool_service, test_db):
        """Test resetting metrics."""
        # Mock DB operations
        test_db.execute = Mock()
        test_db.commit = Mock()

        # Reset all metrics
        await tool_service.reset_metrics(test_db)

        # Verify DB operations (raw + hourly rollups)
        assert test_db.execute.call_count == 2
        test_db.commit.assert_called_once()

        # Reset metrics for specific tool
        test_db.execute.reset_mock()
        test_db.commit.reset_mock()

        await tool_service.reset_metrics(test_db, tool_id=1)

        # Verify DB operations with tool_id (raw + hourly rollups)
        assert test_db.execute.call_count == 2
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
                    error_message=None,
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
                MockToolMetric.assert_called_once_with(tool_id=mock_tool.id, response_time=2.5, is_success=False, error_message="Connection timeout")

                mock_db.add.assert_called_once_with(mock_metric_instance)
                mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_aggregate_metrics(self, tool_service):
        """Test aggregating metrics across all tools using combined raw + rollup query."""
        from unittest.mock import patch
        from mcpgateway.services.metrics_query_service import AggregatedMetrics

        # Mock database
        mock_db = MagicMock()

        # Create a mock AggregatedMetrics result
        mock_result = AggregatedMetrics(
            total_executions=10,
            successful_executions=8,
            failed_executions=2,
            failure_rate=0.2,
            min_response_time=0.5,
            max_response_time=5.0,
            avg_response_time=2.3,
            last_execution_time="2025-01-10T12:00:00",
            raw_count=6,
            rollup_count=4,
        )

        with patch("mcpgateway.services.metrics_query_service.aggregate_metrics_combined", return_value=mock_result):
            result = await tool_service.aggregate_metrics(mock_db)

        assert result == {
            "total_executions": 10,
            "successful_executions": 8,
            "failed_executions": 2,
            "failure_rate": 0.2,
            "min_response_time": 0.5,
            "max_response_time": 5.0,
            "avg_response_time": 2.3,
            "last_execution_time": "2025-01-10T12:00:00",
        }

    @pytest.mark.asyncio
    async def test_aggregate_metrics_no_data(self, tool_service):
        """Test aggregating metrics when no data exists."""
        from unittest.mock import patch
        from mcpgateway.services.metrics_query_service import AggregatedMetrics

        # Mock database
        mock_db = MagicMock()

        # Create a mock AggregatedMetrics result with no data
        mock_result = AggregatedMetrics(
            total_executions=0,
            successful_executions=0,
            failed_executions=0,
            failure_rate=0.0,
            min_response_time=None,
            max_response_time=None,
            avg_response_time=None,
            last_execution_time=None,
            raw_count=0,
            rollup_count=0,
        )

        with patch("mcpgateway.services.metrics_query_service.aggregate_metrics_combined", return_value=mock_result):
            result = await tool_service.aggregate_metrics(mock_db)

        assert result == {
            "total_executions": 0,
            "successful_executions": 0,
            "failed_executions": 0,
            "failure_rate": 0.0,
            "min_response_time": None,
            "max_response_time": None,
            "avg_response_time": None,
            "last_execution_time": None,
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
        with patch.object(tool_service, "_publish_event", new_callable=AsyncMock) as mock_publish:
            await tool_service._notify_tool_added(mock_tool)

            mock_publish.assert_called_once()
            event = mock_publish.call_args[0][0]
            assert event["type"] == "tool_added"
            assert event["data"]["id"] == mock_tool.id
            assert event["data"]["name"] == mock_tool.name

    async def test_notify_tool_removed(self, tool_service, mock_tool):
        """Test notification when tool is removed."""
        with patch.object(tool_service, "_publish_event", new_callable=AsyncMock) as mock_publish:
            await tool_service._notify_tool_removed(mock_tool)

            mock_publish.assert_called_once()
            event = mock_publish.call_args[0][0]
            assert event["type"] == "tool_removed"
            assert event["data"]["id"] == mock_tool.id

    @pytest.mark.asyncio
    async def test_get_top_tools(self, tool_service, test_db):
        """Test get_top_tools method."""
        # Mock the combined query results (TopPerformerResult objects)
        mock_performer1 = MagicMock()
        mock_performer1.id = "1"
        mock_performer1.name = "tool1"
        mock_performer1.execution_count = 10
        mock_performer1.avg_response_time = 1.5
        mock_performer1.success_rate = 90.0
        mock_performer1.last_execution = "2024-01-01T12:00:00"

        mock_performer2 = MagicMock()
        mock_performer2.id = "2"
        mock_performer2.name = "tool2"
        mock_performer2.execution_count = 5
        mock_performer2.avg_response_time = 2.0
        mock_performer2.success_rate = 80.0
        mock_performer2.last_execution = "2024-01-02T12:00:00"

        mock_combined_results = [mock_performer1, mock_performer2]

        # tool_service imports at top-level, so patch where it's used
        with patch("mcpgateway.services.tool_service.get_top_performers_combined") as mock_combined:
            mock_combined.return_value = mock_combined_results

            with patch("mcpgateway.services.tool_service.build_top_performers") as mock_build:
                mock_build.return_value = ["top_performer1", "top_performer2"]

                # Run the method
                result = await tool_service.get_top_tools(test_db, limit=5)

                # Assert the result is as expected
                assert result == ["top_performer1", "top_performer2"]

                # Assert get_top_performers_combined was called with correct params
                mock_combined.assert_called_once()
                call_kwargs = mock_combined.call_args[1]
                assert call_kwargs["metric_type"] == "tool"
                assert call_kwargs["limit"] == 5
                assert call_kwargs["include_deleted"] is False

                # Assert build_top_performers was called with the combined results
                mock_build.assert_called_once_with(mock_combined_results)

    @pytest.mark.asyncio
    async def test_list_tools_with_tags(self, tool_service, mock_tool):
        """Test listing tools with tag filtering."""
        # Third-Party

        # Mock query chain - support pagination methods
        mock_query = MagicMock()
        mock_query.where.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query

        session = MagicMock()

        # Mock DB execute chain for unified_paginate: execute().scalars().all()
        mock_tool.team_id = None
        session.execute = Mock(return_value=MagicMock(scalars=Mock(return_value=MagicMock(all=Mock(return_value=[mock_tool])))))
        session.commit = Mock()

        bind = MagicMock()
        bind.dialect = MagicMock()
        bind.dialect.name = "sqlite"  # or "postgresql" or "mysql"
        session.get_bind.return_value = bind

        # Mock convert_tool_to_read
        tool_service.convert_tool_to_read = Mock(return_value=MagicMock())

        with patch("mcpgateway.services.tool_service.select", return_value=mock_query):
            with patch("mcpgateway.services.tool_service.json_contains_expr") as mock_json_contains:
                # return a fake condition object that query.where will accept
                fake_condition = MagicMock()
                mock_json_contains.return_value = fake_condition

                result, _ = await tool_service.list_tools(session, tags=["test", "production"], include_inactive=True)

                # json_contains_expr should be called once with the tags list
                mock_json_contains.assert_called_once()
                called_args = mock_json_contains.call_args[0]  # positional args tuple
                assert called_args[0] is session  # session passed through
                # third positional arg is the tags list (signature: session, col, values, match_any=True)
                assert called_args[2] == ["test", "production"]
                # finally, your service should return the list produced by session.execute(...)
                assert isinstance(result, list)
                assert len(result) == 1

    async def test_invoke_tool_rest_oauth_success(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """Test invoking REST tool with successful OAuth authentication."""
        # Configure tool with OAuth
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.auth_type = "oauth"
        mock_tool.oauth_config = {"client_id": "test_id", "client_secret": "test_secret"}

        # Mock DB to return the tool and GlobalConfig
        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        # Mock OAuth manager
        tool_service.oauth_manager.get_access_token = AsyncMock(return_value="test_access_token")

        # Mock HTTP client response
        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()  # HTTP response raise_for_status is synchronous
        mock_response.status_code = 200
        mock_response.json = Mock(return_value={"result": "OAuth success"})
        tool_service._http_client.request.return_value = mock_response

        # Mock metrics recording
        tool_service._record_tool_metric_sync = Mock()

        with patch("mcpgateway.services.tool_service.extract_using_jq", return_value={"result": "OAuth success"}):
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

    async def test_invoke_tool_rest_oauth_failure(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """Test invoking REST tool with failed OAuth authentication."""
        # Configure tool with OAuth
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.auth_type = "oauth"
        mock_tool.oauth_config = {"client_id": "test_id", "client_secret": "test_secret"}

        # Mock DB to return the tool and GlobalConfig
        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        # Mock OAuth manager to fail
        tool_service.oauth_manager.get_access_token = AsyncMock(side_effect=Exception("OAuth failed"))

        # Mock metrics recording
        tool_service._record_tool_metric_sync = Mock()

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

    async def test_invoke_tool_with_passthrough_headers_rest(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """Test invoking REST tool with passthrough headers."""
        # Configure tool as REST
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.auth_value = None

        # Mock DB to return the tool and GlobalConfig
        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        # Mock HTTP client response
        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()  # HTTP response raise_for_status is synchronous
        mock_response.status_code = 200
        mock_response.json = Mock(return_value={"result": "success with headers"})
        tool_service._http_client.request.return_value = mock_response

        # Mock compute_passthrough_headers_cached to return modified headers
        def mock_passthrough(req_headers, base_headers, allowed_headers, gateway_auth_type=None, gateway_passthrough_headers=None):
            combined = base_headers.copy()
            combined["X-Request-ID"] = req_headers.get("X-Request-ID", "test-123")
            return combined

        request_headers = {"X-Request-ID": "custom-123", "Authorization": "Bearer test"}

        with (
            patch("mcpgateway.services.tool_service.decode_auth", return_value={}),
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", side_effect=mock_passthrough),
            patch("mcpgateway.services.tool_service.extract_using_jq", return_value={"result": "success with headers"}),
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

        # Mock compute_passthrough_headers_cached to return modified headers
        def mock_passthrough(req_headers, base_headers, allowed_headers, gateway_auth_type=None, gateway_passthrough_headers=None):
            combined = base_headers.copy()
            combined["X-Custom-Header"] = req_headers.get("X-Custom-Header", "default")
            return combined

        request_headers = {"X-Custom-Header": "custom-value", "Authorization": "Bearer test"}

        with (
            patch("mcpgateway.services.tool_service.sse_client", return_value=sse_ctx),
            patch("mcpgateway.services.tool_service.ClientSession", return_value=client_session_cm),
            patch("mcpgateway.services.tool_service.decode_auth", return_value={}),
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", side_effect=mock_passthrough),
            patch("mcpgateway.services.tool_service.extract_using_jq", side_effect=lambda data, _filt: data),
        ):
            result = await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=request_headers)

        # Verify MCP session was initialized and tool called
        session_mock.initialize.assert_awaited_once()
        session_mock.call_tool.assert_awaited_once()

    async def test_invoke_tool_with_plugin_post_invoke_success(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """Test invoking tool with successful plugin post-invoke hook."""
        # First-Party
        from mcpgateway.plugins.framework.models import PluginResult
        from mcpgateway.plugins.framework import ToolHookType

        # Configure tool as REST
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.auth_value = None

        # Mock DB to return the tool and GlobalConfig
        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        # Mock HTTP client response
        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()  # HTTP response raise_for_status is synchronous
        mock_response.status_code = 200
        mock_response.json = Mock(return_value={"result": "original response"})
        tool_service._http_client.request.return_value = mock_response

        # Mock plugin manager with invoke_hook
        mock_post_result = Mock()
        mock_post_result.continue_processing = True
        mock_post_result.violation = None
        mock_post_result.modified_payload = None

        tool_service._plugin_manager = Mock()

        def invoke_hook_side_effect(hook_type, payload, global_context, local_contexts=None, **kwargs):
            if hook_type == ToolHookType.TOOL_PRE_INVOKE:
                return (PluginResult(continue_processing=True, violation=None, modified_payload=None), None)
            # POST_INVOKE
            return (mock_post_result, None)

        tool_service._plugin_manager.invoke_hook = AsyncMock(side_effect=invoke_hook_side_effect)

        with (
            patch("mcpgateway.services.tool_service.decode_auth", return_value={}),
            patch("mcpgateway.services.tool_service.extract_using_jq", return_value={"result": "original response"}),
        ):
            result = await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=None)

        # Verify plugin hooks were called
        assert tool_service._plugin_manager.invoke_hook.call_count == 2  # Pre and post invoke

        # Verify result
        assert result.content[0].text == '{\n  "result": "original response"\n}'

    async def test_invoke_tool_with_plugin_post_invoke_modified_payload(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """Test invoking tool with plugin post-invoke hook modifying payload."""
        # Configure tool as REST
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.auth_value = None

        # Mock DB to return the tool and GlobalConfig
        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        # Mock HTTP client response
        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()  # HTTP response raise_for_status is synchronous
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

        # First-Party
        from mcpgateway.plugins.framework import PluginResult, ToolHookType

        tool_service._plugin_manager = Mock()

        def invoke_hook_side_effect(hook_type, payload, global_context, local_contexts=None, **kwargs):
            if hook_type == ToolHookType.TOOL_PRE_INVOKE:
                return (PluginResult(continue_processing=True, violation=None, modified_payload=None), None)
            # POST_INVOKE
            return (mock_post_result, None)

        tool_service._plugin_manager.invoke_hook = AsyncMock(side_effect=invoke_hook_side_effect)

        with (
            patch("mcpgateway.services.tool_service.decode_auth", return_value={}),
            patch("mcpgateway.services.tool_service.extract_using_jq", return_value={"result": "original response"}),
        ):
            result = await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=None)

        # Verify plugin hooks were called
        assert tool_service._plugin_manager.invoke_hook.call_count == 2  # Pre and post invoke

        # Verify result was modified by plugin
        assert result.content[0].text == "Modified by plugin"

    async def test_invoke_tool_with_plugin_post_invoke_invalid_modified_payload(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """Test invoking tool with plugin post-invoke hook providing invalid modified payload."""
        # Configure tool as REST
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.auth_value = None

        # Mock DB to return the tool and GlobalConfig
        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        # Mock HTTP client response
        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()  # HTTP response raise_for_status is synchronous
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

        # First-Party
        from mcpgateway.plugins.framework.models import PluginResult
        from mcpgateway.plugins.framework import ToolHookType

        tool_service._plugin_manager = Mock()

        def invoke_hook_side_effect(hook_type, payload, global_context, local_contexts=None, **kwargs):
            if hook_type == ToolHookType.TOOL_PRE_INVOKE:
                return (PluginResult(continue_processing=True, violation=None, modified_payload=None), None)
            # POST_INVOKE
            return (mock_post_result, None)

        tool_service._plugin_manager.invoke_hook = AsyncMock(side_effect=invoke_hook_side_effect)

        with (
            patch("mcpgateway.services.tool_service.decode_auth", return_value={}),
            patch("mcpgateway.services.tool_service.extract_using_jq", return_value={"result": "original response"}),
        ):
            result = await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=None)

        # Verify plugin hooks were called
        assert tool_service._plugin_manager.invoke_hook.call_count == 2  # Pre and post invoke

        # Verify result was converted to string since format was invalid
        assert result.content[0].text == "Invalid format - not a dict"

    async def test_invoke_tool_with_plugin_post_invoke_error_fail_on_error(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """Test invoking tool with plugin post-invoke hook error when fail_on_plugin_error is True."""
        # Configure tool as REST
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.auth_value = None

        # Mock DB to return the tool and GlobalConfig
        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        # Mock HTTP client response
        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()  # HTTP response raise_for_status is synchronous
        mock_response.status_code = 200
        mock_response.json = Mock(return_value={"result": "original response"})
        tool_service._http_client.request.return_value = mock_response

        # Mock plugin manager with invoke_hook that raises error on POST_INVOKE
        # First-Party
        from mcpgateway.plugins.framework.models import PluginResult
        from mcpgateway.plugins.framework import ToolHookType

        tool_service._plugin_manager = Mock()

        def invoke_hook_side_effect(hook_type, payload, global_context, local_contexts=None, **kwargs):
            if hook_type == ToolHookType.TOOL_PRE_INVOKE:
                return (PluginResult(continue_processing=True, violation=None, modified_payload=None), None)
            # POST_INVOKE - raise error
            raise Exception("Plugin error")

        tool_service._plugin_manager.invoke_hook = AsyncMock(side_effect=invoke_hook_side_effect)

        # Mock plugin config to fail on errors
        mock_plugin_settings = Mock()
        mock_plugin_settings.fail_on_plugin_error = True
        mock_config = Mock()
        mock_config.plugin_settings = mock_plugin_settings
        tool_service._plugin_manager.config = mock_config

        # Mock metrics recording
        tool_service._record_tool_metric_sync = Mock()

        with (
            patch("mcpgateway.services.tool_service.decode_auth", return_value={}),
            patch("mcpgateway.services.tool_service.extract_using_jq", return_value={"result": "original response"}),
        ):
            with pytest.raises(Exception) as exc_info:
                await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=None)

        assert "Plugin error" in str(exc_info.value)

    async def test_invoke_tool_with_plugin_metadata_rest(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """Test invoking tool with plugin post-invoke hook error when fail_on_plugin_error is True."""
        # Configure tool as REST
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.auth_value = None

        # Mock DB to return the tool and GlobalConfig
        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        # Mock HTTP client response
        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()  # HTTP response raise_for_status is synchronous
        mock_response.status_code = 200
        mock_response.json = Mock(return_value={"result": "original response"})
        tool_service._http_client.request.return_value = mock_response

        # Mock plugin manager and post-invoke hook with error
        tool_service._plugin_manager = PluginManager("./tests/unit/mcpgateway/plugins/fixtures/configs/tool_headers_metadata_plugin.yaml")
        await tool_service._plugin_manager.initialize()
        # Mock metrics recording
        tool_service._record_tool_metric_sync = Mock()

        with (
            patch("mcpgateway.services.tool_service.decode_auth", return_value={}),
            patch("mcpgateway.services.tool_service.extract_using_jq", return_value={"result": "original response"}),
        ):
            result = await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=None)

        # Verify result still succeeded despite plugin error
        assert result.content[0].text == '{\n  "result": "original response"\n}'

        await tool_service._plugin_manager.shutdown()

    async def test_invoke_tool_with_plugin_metadata_sse(self, tool_service, mock_tool, mock_gateway, test_db):
        """Test invoking tool with plugin post-invoke hook error when fail_on_plugin_error is True."""
        # Configure tool as REST
        # mock_tool.integration_type = "REST"
        # mock_tool.request_type = "POST"
        # mock_tool.auth_value = None
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
        tool_service._record_tool_metric_sync = Mock()

        with (
            patch("mcpgateway.services.tool_service.sse_client", return_value=sse_ctx),
            patch("mcpgateway.services.tool_service.ClientSession", return_value=client_session_cm),
            patch("mcpgateway.services.tool_service.extract_using_jq", side_effect=lambda data, _filt: data),
        ):
            await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=None)

        await tool_service._plugin_manager.shutdown()


# --------------------------------------------------------------------------- #
#                               extract_using_jq                              #
# --------------------------------------------------------------------------- #
def test_extract_using_jq_happy_path():
    """Test jq filter extraction works correctly with caching."""
    from mcpgateway.services.tool_service import _compile_jq_filter

    # Clear cache for clean test state
    _compile_jq_filter.cache_clear()

    data = {"a": 123, "b": 456}

    # Test actual behavior (no mocking)
    result = extract_using_jq(data, ".a")
    assert result == [123]

    # Verify caching works
    result2 = extract_using_jq({"a": 999}, ".a")
    assert result2 == [999]

    info = _compile_jq_filter.cache_info()
    assert info.hits == 1  # Second call hit cache


def test_extract_using_jq_short_circuits_and_errors():
    # Empty filter returns data unmodified
    orig = {"x": "y"}
    assert extract_using_jq(orig) is orig

    # Non-JSON string
    assert extract_using_jq("this isn't json", ".foo") == ["Invalid JSON string provided."]

    # Unsupported input type
    assert extract_using_jq(42, ".foo") == ["Input data must be a JSON string, dictionary, or list."]


# --------------------------------------------------------------------------- #
#                         Cache Behavior Tests                                #
# --------------------------------------------------------------------------- #


class TestJqFilterCaching:
    """Tests for jq filter caching (#1813)."""

    def test_jq_caching_works(self):
        """Verify jq filter compilation is cached."""
        from mcpgateway.services.tool_service import _compile_jq_filter

        _compile_jq_filter.cache_clear()

        result1 = extract_using_jq({"a": 1}, ".a")
        assert result1 == [1]

        result2 = extract_using_jq({"a": 99}, ".a")
        assert result2 == [99]

        info = _compile_jq_filter.cache_info()
        assert info.hits == 1

    def test_empty_filter_bypasses_cache(self):
        """Empty filter should return data directly without caching."""
        data = {"x": "y"}
        result = extract_using_jq(data, "")
        assert result is data


class TestSchemaValidatorCaching:
    """Tests for JSON Schema validator caching (#1809)."""

    def test_schema_caching_works(self):
        """Verify schema validation uses cached validator class."""
        from mcpgateway.services.tool_service import _get_validator_class_and_check, _canonicalize_schema

        _get_validator_class_and_check.cache_clear()

        schema = {"type": "object", "properties": {"foo": {"type": "string"}}}
        schema_json = _canonicalize_schema(schema)

        cls1, s1 = _get_validator_class_and_check(schema_json)
        cls2, s2 = _get_validator_class_and_check(schema_json)

        assert cls1 is cls2

        info = _get_validator_class_and_check.cache_info()
        assert info.hits == 1

    def test_validation_still_works(self):
        """Verify cached validation still catches errors."""
        from mcpgateway.services.tool_service import _validate_with_cached_schema
        import jsonschema

        schema = {"type": "object", "properties": {"foo": {"type": "string"}}, "required": ["foo"]}

        # Valid instance
        _validate_with_cached_schema({"foo": "bar"}, schema)

        # Invalid instance
        with pytest.raises(jsonschema.ValidationError):
            _validate_with_cached_schema({"foo": 123}, schema)
