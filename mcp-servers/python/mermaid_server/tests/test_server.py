# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/mermaid_server/tests/test_server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for Mermaid MCP Server.
"""

import json
import pytest
from mermaid_server.server import handle_call_tool, handle_list_tools


@pytest.mark.asyncio
async def test_list_tools():
    """Test that tools are listed correctly."""
    tools = await handle_list_tools()
    tool_names = [tool.name for tool in tools]
    expected_tools = ["create_diagram", "create_flowchart", "create_sequence_diagram", "create_gantt_chart", "validate_mermaid", "get_templates"]
    for expected in expected_tools:
        assert expected in tool_names


@pytest.mark.asyncio
async def test_get_templates():
    """Test getting diagram templates."""
    result = await handle_call_tool("get_templates", {})
    result_data = json.loads(result[0].text)
    assert "flowchart" in result_data
    assert "sequence" in result_data


@pytest.mark.asyncio
async def test_validate_mermaid():
    """Test Mermaid validation."""
    valid_mermaid = "flowchart TD\n    A --> B"
    result = await handle_call_tool("validate_mermaid", {"mermaid_code": valid_mermaid})
    result_data = json.loads(result[0].text)
    assert result_data["valid"] is True
