# -*- coding: utf-8 -*-
"""

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for tool service implementation.
"""

from unittest.mock import ANY, AsyncMock, MagicMock, Mock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from mcpgateway.db import Tool as DbTool
from mcpgateway.schemas import ToolCreate, ToolRead, ToolUpdate
from mcpgateway.services.tool_service import (
    ToolError,
    ToolInvocationError,
    ToolNotFoundError,
    ToolService,
)


@pytest.fixture
def tool_service():
    """Create a tool service instance."""
    service = ToolService()
    service._http_client = AsyncMock()
    return service


@pytest.fixture
def mock_tool():
    """Create a mock tool model."""
    tool = MagicMock(spec=DbTool)
    tool.id = 1
    tool.name = "test_tool"
    tool.url = "http://example.com/tools/test"
    tool.description = "A test tool"
    tool.integration_type = "MCP"
    tool.request_type = "POST"
    tool.headers = {"Content-Type": "application/json"}
    tool.input_schema = {"type": "object", "properties": {"param": {"type": "string"}}}
    tool.jsonpath_filter = ""
    tool.created_at = "2023-01-01T00:00:00"
    tool.updated_at = "2023-01-01T00:00:00"
    tool.is_active = True
    tool.auth_type = None
    tool.auth_username = None
    tool.auth_password = None
    tool.auth_token = None
    tool.auth_value = None  # Add this field
    tool.gateway_id = None

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


class TestToolService:
    """Tests for the ToolService class."""

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
                id=1,
                name="test_tool",
                url="http://example.com/tools/test",
                description="A test tool",
                integration_type="MCP",
                request_type="POST",
                headers={"Content-Type": "application/json"},
                input_schema={"type": "object", "properties": {"param": {"type": "string"}}},
                jsonpath_filter="",
                created_at="2023-01-01T00:00:00",
                updated_at="2023-01-01T00:00:00",
                is_active=True,
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
        )

        # Create tool request
        tool_create = ToolCreate(
            name="test_tool",
            url="http://example.com/tools/test",
            description="A test tool",
            integration_type="MCP",
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
        assert result.name == "test_tool"
        assert result.url == "http://example.com/tools/test"
        assert result.integration_type == "MCP"
        assert result.is_active is True

        # Verify notification
        tool_service._notify_tool_added.assert_called_once()

    @pytest.mark.asyncio
    async def test_register_tool_name_conflict(self, tool_service, mock_tool, test_db):
        """Test tool registration with name conflict."""
        # Mock DB to return existing tool
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = mock_tool
        test_db.execute = Mock(return_value=mock_scalar)

        # Create tool request with conflicting name
        tool_create = ToolCreate(
            name="test_tool",  # Same name as mock_tool
            url="http://example.com/tools/new",
            description="A new tool",
            integration_type="MCP",
            request_type="POST",
        )

        # Should raise ToolError wrapping ToolNameConflictError
        with pytest.raises(ToolError) as exc_info:
            await tool_service.register_tool(test_db, tool_create)

        # The service wraps exceptions, so check the message
        assert "Tool already exists with name" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_register_tool_db_integrity_error(self, tool_service, test_db):
        """Test tool registration with database IntegrityError."""
        # Mock DB to raise IntegrityError on commit
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = None
        test_db.execute = Mock(return_value=mock_scalar)
        test_db.add = Mock()
        test_db.commit = Mock(side_effect=IntegrityError("statement", "params", "orig"))
        test_db.rollback = Mock()

        # Create tool request
        tool_create = ToolCreate(
            name="test_tool",
            url="http://example.com/tools/test",
            description="A test tool",
            integration_type="MCP",
            request_type="POST",
        )

        # Should raise ToolError
        with pytest.raises(ToolError) as exc_info:
            await tool_service.register_tool(test_db, tool_create)

        assert "Tool already exists" in str(exc_info.value)
        test_db.rollback.assert_called_once()

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
            id=1,
            name="test_tool",
            url="http://example.com/tools/test",
            description="A test tool",
            integration_type="MCP",
            request_type="POST",
            headers={"Content-Type": "application/json"},
            input_schema={"type": "object", "properties": {"param": {"type": "string"}}},
            jsonpath_filter="",
            created_at="2023-01-01T00:00:00",
            updated_at="2023-01-01T00:00:00",
            is_active=True,
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
    async def test_get_tool(self, tool_service, mock_tool, test_db):
        """Test getting a tool by ID."""
        # Mock DB get to return tool
        test_db.get = Mock(return_value=mock_tool)

        # Mock conversion
        tool_read = ToolRead(
            id=1,
            name="test_tool",
            url="http://example.com/tools/test",
            description="A test tool",
            integration_type="MCP",
            request_type="POST",
            headers={"Content-Type": "application/json"},
            input_schema={"type": "object", "properties": {"param": {"type": "string"}}},
            jsonpath_filter="",
            created_at="2023-01-01T00:00:00",
            updated_at="2023-01-01T00:00:00",
            is_active=True,
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
            id=1,
            name="test_tool",
            url="http://example.com/tools/test",
            description="A test tool",
            integration_type="MCP",
            request_type="POST",
            headers={"Content-Type": "application/json"},
            input_schema={"type": "object", "properties": {"param": {"type": "string"}}},
            jsonpath_filter="",
            created_at="2023-01-01T00:00:00",
            updated_at="2023-01-01T00:00:00",
            is_active=False,  # Changed to False
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
        result = await tool_service.toggle_tool_status(test_db, 1, activate=False)

        # Verify DB operations
        test_db.get.assert_called_once_with(DbTool, 1)
        test_db.commit.assert_called_once()
        test_db.refresh.assert_called_once()

        # Verify properties were updated
        assert mock_tool.is_active is False

        # Verify notification
        tool_service._notify_tool_deactivated.assert_called_once()
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
            id=1,
            name="updated_tool",  # Updated name
            url="http://example.com/tools/updated",  # Updated URL
            description="An updated test tool",  # Updated description
            integration_type="MCP",
            request_type="POST",
            headers={"Content-Type": "application/json"},
            input_schema={"type": "object", "properties": {"param": {"type": "string"}}},
            jsonpath_filter="",
            created_at="2023-01-01T00:00:00",
            updated_at="2023-01-01T00:00:00",
            is_active=True,
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
            name="updated_tool",
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
        assert mock_tool.name == "updated_tool"
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
        conflicting_tool.is_active = True

        # Mock DB query to check for name conflicts (returns the conflicting tool)
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = conflicting_tool
        test_db.execute = Mock(return_value=mock_scalar)

        test_db.rollback = Mock()

        # Create update request with conflicting name
        tool_update = ToolUpdate(
            name="existing_tool",  # Name that conflicts with another tool
        )

        # The service wraps the exception in ToolError
        with pytest.raises(ToolError) as exc_info:
            await tool_service.update_tool(test_db, 1, tool_update)

        assert "Tool already exists with name" in str(exc_info.value)

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
    async def test_invoke_tool_not_found(self, tool_service, test_db):
        """Test invoking a non-existent tool."""
        # Mock DB to return no tool
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = None
        test_db.execute = Mock(return_value=mock_scalar)

        # Should raise NotFoundError
        with pytest.raises(ToolNotFoundError) as exc_info:
            await tool_service.invoke_tool(test_db, "nonexistent_tool", {})

        assert "Tool not found: nonexistent_tool" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_invoke_tool_inactive(self, tool_service, mock_tool, test_db):
        """Test invoking an inactive tool."""
        # Set tool to inactive
        mock_tool.is_active = False

        # Mock DB to return inactive tool for first query, None for second query
        mock_scalar1 = Mock()
        mock_scalar1.scalar_one_or_none.return_value = None

        mock_scalar2 = Mock()
        mock_scalar2.scalar_one_or_none.return_value = mock_tool

        test_db.execute = Mock(side_effect=[mock_scalar1, mock_scalar2])

        # Should raise NotFoundError with "inactive" message
        with pytest.raises(ToolNotFoundError) as exc_info:
            await tool_service.invoke_tool(test_db, "test_tool", {})

        assert "Tool 'test_tool' exists but is inactive" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_invoke_tool_rest(self, tool_service, mock_tool, test_db):
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
            result = await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"})

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
                await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"})

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
