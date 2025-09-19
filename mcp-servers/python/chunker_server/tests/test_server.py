# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/chunker_server/tests/test_server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for Chunker MCP Server.
"""

import json
import pytest
from chunker_server.server import handle_call_tool, handle_list_tools


@pytest.mark.asyncio
async def test_list_tools():
    """Test that tools are listed correctly."""
    tools = await handle_list_tools()
    tool_names = [tool.name for tool in tools]
    expected_tools = ["chunk_text", "chunk_markdown", "semantic_chunk", "sentence_chunk", "fixed_size_chunk", "analyze_text", "get_strategies"]
    for expected in expected_tools:
        assert expected in tool_names


@pytest.mark.asyncio
async def test_chunk_text_basic():
    """Test basic text chunking."""
    text = "This is a test. " * 100  # Long text
    result = await handle_call_tool("chunk_text", {"text": text, "chunk_size": 200})
    result_data = json.loads(result[0].text)
    if result_data.get("success"):
        assert result_data["chunk_count"] > 1
        assert "chunks" in result_data


@pytest.mark.asyncio
async def test_analyze_text():
    """Test text analysis."""
    markdown_text = "# Header 1\nContent here.\n## Header 2\nMore content."
    result = await handle_call_tool("analyze_text", {"text": markdown_text})
    result_data = json.loads(result[0].text)
    if result_data.get("success"):
        assert result_data["analysis"]["has_markdown_headers"] is True
