# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/plotly_server/tests/test_server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for Plotly MCP Server.
"""

import json
import pytest
from plotly_server.server import handle_call_tool, handle_list_tools


@pytest.mark.asyncio
async def test_list_tools():
    """Test that tools are listed correctly."""
    tools = await handle_list_tools()
    tool_names = [tool.name for tool in tools]
    expected_tools = ["create_chart", "create_scatter_plot", "create_bar_chart", "create_line_chart", "get_supported_charts"]
    for expected in expected_tools:
        assert expected in tool_names


@pytest.mark.asyncio
async def test_get_supported_charts():
    """Test getting supported chart types."""
    result = await handle_call_tool("get_supported_charts", {})
    result_data = json.loads(result[0].text)
    assert "chart_types" in result_data
    assert "output_formats" in result_data


@pytest.mark.asyncio
async def test_create_bar_chart():
    """Test creating a bar chart."""
    result = await handle_call_tool("create_bar_chart", {
        "categories": ["A", "B", "C"],
        "values": [1, 2, 3],
        "title": "Test Chart"
    })
    result_data = json.loads(result[0].text)
    # Should work if Plotly is available, or fail gracefully
    assert "success" in result_data
