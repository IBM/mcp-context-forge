# -*- coding: utf-8 -*-
"""Tests for tool deprecation functionality.

Copyright 2026
SPDX-License-Identifier: Apache-2.0
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mcpgateway.db import Tool as DbTool
from mcpgateway.services.tool_service import ToolService, ToolInvocationError


@pytest.fixture
def tool_service():
    """Create a ToolService instance for testing."""
    return ToolService()


@pytest.fixture
def mock_db():
    """Create a mock database session."""
    db = MagicMock()
    db.execute = MagicMock()
    db.commit = MagicMock()
    db.rollback = MagicMock()
    db.close = MagicMock()
    return db


@pytest.fixture
def deprecated_tool():
    """Create a deprecated tool for testing."""
    tool = MagicMock(spec=DbTool)
    tool.id = "deprecated-tool-id"
    tool.name = "deprecated_tool"
    tool.original_name = "deprecated_tool"
    tool.enabled = True
    tool.deprecated = True
    tool.reachable = True
    tool.integration_type = "MCP"
    tool.request_type = "SSE"
    tool.url = "http://example.com/tool"
    tool.gateway_id = "gateway-id"
    tool.gateway = None
    tool.visibility = "public"
    tool.team_id = None
    tool.owner_email = None
    return tool


@pytest.fixture
def active_tool():
    """Create an active (non-deprecated) tool for testing."""
    tool = MagicMock(spec=DbTool)
    tool.id = "active-tool-id"
    tool.name = "active_tool"
    tool.original_name = "active_tool"
    tool.enabled = True
    tool.deprecated = False
    tool.reachable = True
    tool.integration_type = "MCP"
    tool.request_type = "SSE"
    tool.url = "http://example.com/tool"
    tool.gateway_id = "gateway-id"
    tool.gateway = None
    tool.visibility = "public"
    tool.team_id = None
    tool.owner_email = None
    return tool


class TestToolDeprecation:
    """Test suite for tool deprecation functionality."""

    @pytest.mark.asyncio
    async def test_invoke_deprecated_tool_raises_error(self, tool_service, mock_db, deprecated_tool):
        """Test that invoking a deprecated tool raises ToolInvocationError."""
        # Mock the database query to return the deprecated tool
        mock_result = MagicMock()
        mock_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[deprecated_tool])))
        mock_db.execute.return_value = mock_result

        with pytest.raises(ToolInvocationError) as exc_info:
            await tool_service.invoke_tool(
                db=mock_db,
                name="deprecated_tool",
                arguments={},
                user_email="test@example.com",
                token_teams=None,
            )

        assert "deprecated" in str(exc_info.value).lower()
        assert "cannot be executed" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_deprecated_tool_from_cache_raises_error(self, tool_service, mock_db):
        """Test that a deprecated tool from cache also raises ToolInvocationError."""
        # Mock cache to return a deprecated tool payload
        tool_payload = {
            "id": "cached-tool-id",
            "name": "cached_deprecated_tool",
            "enabled": True,
            "deprecated": True,
            "reachable": True,
            "integration_type": "MCP",
            "visibility": "public",
            "team_id": None,
            "owner_email": None,
        }

        with patch('mcpgateway.services.tool_service._get_tool_lookup_cache') as mock_cache_getter:
            mock_cache = MagicMock()
            mock_cache.enabled = True
            mock_cache.get = AsyncMock(return_value={"status": "active", "tool": tool_payload, "gateway": None})
            mock_cache.set_negative = AsyncMock()
            mock_cache_getter.return_value = mock_cache

            with pytest.raises(ToolInvocationError) as exc_info:
                await tool_service.invoke_tool(
                    db=mock_db,
                    name="cached_deprecated_tool",
                    arguments={},
                    user_email="test@example.com",
                    token_teams=None,
                )

            assert "deprecated" in str(exc_info.value).lower()
            assert "cannot be executed" in str(exc_info.value).lower()

    def test_build_tool_cache_payload_includes_deprecated_flag(self, tool_service, deprecated_tool):
        """Test that _build_tool_cache_payload includes the deprecated flag."""
        payload = tool_service._build_tool_cache_payload(deprecated_tool, None)

        assert "tool" in payload
        assert "deprecated" in payload["tool"]
        assert payload["tool"]["deprecated"] is True

    def test_build_tool_cache_payload_includes_deprecated_false_for_active(self, tool_service, active_tool):
        """Test that _build_tool_cache_payload includes deprecated=False for active tools."""
        payload = tool_service._build_tool_cache_payload(active_tool, None)

        assert "tool" in payload
        assert "deprecated" in payload["tool"]
        assert payload["tool"]["deprecated"] is False
