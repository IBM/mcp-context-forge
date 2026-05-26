# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_tool_deprecated.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for tool deprecation functionality.

NOTE: These tests verify that deprecated tools ARE still executable.
Only sunset tools (enabled=False) are blocked from execution.
"""

import pytest
from unittest.mock import MagicMock

from mcpgateway.db import Tool as DbTool
from mcpgateway.services.tool_service import ToolService


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
    tool.sunset_date = None
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
    tool.sunset_date = None
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
    """Test suite for tool deprecation functionality.

    IMPORTANT: Deprecated tools ARE executable until they reach sunset.
    Only sunset tools (enabled=False) are blocked from execution.
    """

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
