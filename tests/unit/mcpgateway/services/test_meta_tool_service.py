# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_meta_tool_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Unit tests for the Meta-Tool Service with mocked database layer.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

# Third-Party
import pytest

# First-Party
from mcpgateway.meta_server.schemas import DescribeToolResponse, ExecuteToolResponse
from mcpgateway.services.meta_tool_service import MetaToolService


class TestDescribeTool:
    """Tests for describe_tool functionality."""

    @pytest.mark.asyncio
    async def test_describe_tool_success(self, test_db):
        """Test successful tool description."""
        service = MetaToolService(test_db)
        
        # Create mock server
        mock_server = MagicMock()
        mock_server.id = "server-123"
        mock_server.name = "test-server"
        
        # Create mock tool
        mock_tool = MagicMock()
        mock_tool.id = str(uuid.uuid4())
        mock_tool.name = "test_tool"
        mock_tool.description = "Test tool description"
        mock_tool.input_schema = {"type": "object", "properties": {"arg1": {"type": "string"}}}
        mock_tool.output_schema = {"type": "object"}
        mock_tool.tags = ["test", "sample"]
        mock_tool.annotations = {"example": "data"}
        mock_tool.servers = [mock_server]
        
        # Mock the _resolve_tool method
        with patch.object(service, '_resolve_tool', new_callable=AsyncMock) as mock_resolve:
            mock_resolve.return_value = mock_tool
            
            response = await service.describe_tool(
                tool_name="test_tool",
                include_metrics=False,
                user_email="test@example.com",
                token_teams=[],
                is_admin=False,
                scope=None,
            )

        assert isinstance(response, DescribeToolResponse)
        assert response.name == "test_tool"
        assert response.description == "Test tool description"
        assert response.server_name == "test-server"
        assert "test" in response.tags

    @pytest.mark.asyncio
    async def test_describe_tool_not_found(self, test_db):
        """Test describe_tool with non-existent tool."""
        service = MetaToolService(test_db)

        with patch.object(service, '_resolve_tool', new_callable=AsyncMock, return_value=None):
            with pytest.raises(ValueError, match="Tool not found"):
                await service.describe_tool(
                    tool_name="nonexistent_tool",
                    include_metrics=False,
                    user_email="test@example.com",
                    token_teams=[],
                    is_admin=False,
                    scope=None,
                )


class TestExecuteTool:
    """Tests for execute_tool functionality."""

    @pytest.mark.asyncio
    async def test_execute_tool_validation_error_returns_400(self, test_db):
        """Test execute_tool returns validation error for invalid arguments."""
        service = MetaToolService(test_db)
        
        # Create mock tool with strict schema
        mock_tool = MagicMock()
        mock_tool.id = str(uuid.uuid4())
        mock_tool.name = "strict_tool"
        mock_tool.input_schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
        
        with patch.object(service, '_resolve_tool', new_callable=AsyncMock, return_value=mock_tool):
            # Missing required argument should raise ValueError
            with pytest.raises(ValueError, match="Argument validation failed"):
                await service.execute_tool(
                    tool_name="strict_tool",
                    arguments={},  # Missing 'name'
                    user_email="test@example.com",
                    token_teams=[],
                    is_admin=False,
                    scope=None,
                )

    @pytest.mark.asyncio
    async def test_execute_tool_backend_error_surfaces_cleanly(self, test_db):
        """Test backend errors are surfaced cleanly in response."""
        service = MetaToolService(test_db)
        
        # Create mock tool
        mock_tool = MagicMock()
        mock_tool.id = str(uuid.uuid4())
        mock_tool.name = "failing_tool"
        mock_tool.input_schema = {}
        
        with patch.object(service, '_resolve_tool', new_callable=AsyncMock, return_value=mock_tool):
            # Mock tool_service.invoke_tool to raise an exception
            with patch.object(service.tool_service, 'invoke_tool', new_callable=AsyncMock) as mock_invoke:
                mock_invoke.side_effect = Exception("Backend connection failed")
                
                response = await service.execute_tool(
                    tool_name="failing_tool",
                    arguments={},
                    user_email="test@example.com",
                    token_teams=[],
                    is_admin=False,
                    scope=None,
                )
                
                assert response.success is False
                assert response.error == "Backend connection failed"
                assert response.execution_time_ms is not None

    @pytest.mark.asyncio
    async def test_execute_tool_metadata_present(self, test_db):
        """Test execution metadata is present in response."""
        service = MetaToolService(test_db)
        
        # Create mock tool
        mock_tool = MagicMock()
        mock_tool.id = str(uuid.uuid4())
        mock_tool.name = "meta_tool"
        mock_tool.input_schema = {}
        
        # Create mock result
        mock_result = MagicMock()
        mock_result.isError = False
        mock_content = MagicMock()
        mock_content.text = "success"
        mock_result.content = [mock_content]
        
        with patch.object(service, '_resolve_tool', new_callable=AsyncMock, return_value=mock_tool):
            with patch.object(service.tool_service, 'invoke_tool', new_callable=AsyncMock, return_value=mock_result) as mock_invoke:
                response = await service.execute_tool(
                    tool_name="meta_tool",
                    arguments={},
                    user_email="test@example.com",
                    token_teams=[],
                    is_admin=False,
                    scope=None,
                )
                
                # Verify metadata
                assert response.tool_name == "meta_tool"
                assert response.execution_time_ms is not None
                assert isinstance(response.execution_time_ms, (int, float))
                assert response.execution_time_ms >= 0
                
                # Verify invoke_tool was called with proper metadata
                mock_invoke.assert_called_once()
                call_kwargs = mock_invoke.call_args.kwargs
                assert "meta_data" in call_kwargs
                assert call_kwargs["meta_data"]["meta_tool"] == "execute_tool"
                assert "request_id" in call_kwargs["meta_data"]
