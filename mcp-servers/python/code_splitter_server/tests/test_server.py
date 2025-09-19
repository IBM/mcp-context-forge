# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/code_splitter_server/tests/test_server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for Code Splitter MCP Server.
"""

import json
import pytest
from code_splitter_server.server import handle_call_tool, handle_list_tools


@pytest.mark.asyncio
async def test_list_tools():
    """Test that tools are listed correctly."""
    tools = await handle_list_tools()
    tool_names = [tool.name for tool in tools]
    expected_tools = ["split_code", "analyze_code", "extract_functions", "extract_classes"]
    for expected in expected_tools:
        assert expected in tool_names


@pytest.mark.asyncio
async def test_analyze_code():
    """Test code analysis."""
    python_code = '''
def hello_world():
    """Print hello world."""
    print("Hello, World!")

class MyClass:
    def method(self):
        return "test"
'''
    result = await handle_call_tool("analyze_code", {"code": python_code})
    result_data = json.loads(result[0].text)
    if result_data.get("success"):
        assert result_data["function_count"] == 2  # hello_world + method
        assert result_data["class_count"] == 1


@pytest.mark.asyncio
async def test_extract_functions():
    """Test function extraction."""
    python_code = '''
def func1():
    return 1

def func2(x, y):
    """Add two numbers."""
    return x + y
'''
    result = await handle_call_tool("extract_functions", {"code": python_code})
    result_data = json.loads(result[0].text)
    if result_data.get("success"):
        assert result_data["function_count"] == 2
        assert len(result_data["functions"]) == 2
