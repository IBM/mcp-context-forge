# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/docx_server/tests/test_server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for DOCX MCP Server.
"""

import json
import pytest
import tempfile
from pathlib import Path
from docx_server.server import handle_call_tool, handle_list_tools


@pytest.mark.asyncio
async def test_list_tools():
    """Test that tools are listed correctly."""
    tools = await handle_list_tools()

    tool_names = [tool.name for tool in tools]
    expected_tools = [
        "create_document",
        "add_text",
        "add_heading",
        "format_text",
        "add_table",
        "analyze_document",
        "extract_text"
    ]

    for expected in expected_tools:
        assert expected in tool_names


@pytest.mark.asyncio
async def test_create_document():
    """Test document creation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.docx")

        result = await handle_call_tool(
            "create_document",
            {"file_path": file_path, "title": "Test Doc", "author": "Test Author"}
        )

        result_data = json.loads(result[0].text)
        assert result_data["success"] is True
        assert Path(file_path).exists()


@pytest.mark.asyncio
async def test_add_text():
    """Test adding text to document."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.docx")

        # Create document first
        await handle_call_tool(
            "create_document",
            {"file_path": file_path}
        )

        # Add text
        result = await handle_call_tool(
            "add_text",
            {"file_path": file_path, "text": "Hello, World!"}
        )

        result_data = json.loads(result[0].text)
        assert result_data["success"] is True
        assert result_data["text"] == "Hello, World!"


@pytest.mark.asyncio
async def test_analyze_document():
    """Test document analysis."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.docx")

        # Create document and add content
        await handle_call_tool("create_document", {"file_path": file_path})
        await handle_call_tool("add_text", {"file_path": file_path, "text": "Test content"})

        # Analyze
        result = await handle_call_tool(
            "analyze_document",
            {"file_path": file_path}
        )

        result_data = json.loads(result[0].text)
        assert result_data["success"] is True
        assert "structure" in result_data
        assert "statistics" in result_data


@pytest.mark.asyncio
async def test_extract_text():
    """Test text extraction."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.docx")

        # Create document and add content
        await handle_call_tool("create_document", {"file_path": file_path})
        await handle_call_tool("add_text", {"file_path": file_path, "text": "Extract this text"})

        # Extract
        result = await handle_call_tool(
            "extract_text",
            {"file_path": file_path}
        )

        result_data = json.loads(result[0].text)
        assert result_data["success"] is True
        assert "Extract this text" in result_data["full_text"]
