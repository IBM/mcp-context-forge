# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/libreoffice_server/tests/test_server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for LibreOffice MCP Server.
"""

import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from libreoffice_server.server import handle_call_tool, handle_list_tools


@pytest.mark.asyncio
async def test_list_tools():
    """Test that tools are listed correctly."""
    tools = await handle_list_tools()

    tool_names = [tool.name for tool in tools]
    expected_tools = [
        "convert_document",
        "convert_batch",
        "merge_documents",
        "extract_text",
        "get_document_info",
        "list_supported_formats"
    ]

    for expected in expected_tools:
        assert expected in tool_names


@pytest.mark.asyncio
async def test_list_supported_formats():
    """Test listing supported formats."""
    result = await handle_call_tool("list_supported_formats", {})

    result_data = json.loads(result[0].text)
    # When LibreOffice is not available, expect failure
    assert result_data["success"] is False
    assert "LibreOffice not available" in result_data["error"]


@pytest.mark.asyncio
@patch('libreoffice_server.server.subprocess.run')
@patch('libreoffice_server.server.shutil.which')
async def test_convert_document_success(mock_which, mock_subprocess):
    """Test successful document conversion."""
    mock_which.return_value = '/usr/bin/libreoffice'

    # Mock successful subprocess call
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "conversion successful"
    mock_result.stderr = ""
    mock_subprocess.return_value = mock_result

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a fake input file
        input_file = Path(tmpdir) / "test.docx"
        input_file.write_text("fake content")

        # Create expected output file
        output_file = Path(tmpdir) / "test.pdf"
        output_file.write_bytes(b"fake pdf content")

        result = await handle_call_tool(
            "convert_document",
            {
                "input_file": str(input_file),
                "output_format": "pdf",
                "output_dir": tmpdir
            }
        )

        result_data = json.loads(result[0].text)
        assert result_data["success"] is True
        assert result_data["output_format"] == "pdf"


@pytest.mark.asyncio
async def test_convert_document_missing_file():
    """Test conversion with missing input file."""
    result = await handle_call_tool(
        "convert_document",
        {
            "input_file": "/nonexistent/file.docx",
            "output_format": "pdf"
        }
    )

    result_data = json.loads(result[0].text)
    assert result_data["success"] is False
    assert "not found" in result_data["error"]


@pytest.mark.asyncio
@patch('libreoffice_server.server.subprocess.run')
@patch('libreoffice_server.server.shutil.which')
async def test_convert_batch(mock_which, mock_subprocess):
    """Test batch conversion."""
    mock_which.return_value = '/usr/bin/libreoffice'

    # Mock successful subprocess call
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "conversion successful"
    mock_result.stderr = ""
    mock_subprocess.return_value = mock_result

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create fake input files
        input_files = []
        for i in range(3):
            input_file = Path(tmpdir) / f"test{i}.docx"
            input_file.write_text(f"fake content {i}")
            input_files.append(str(input_file))

            # Create expected output files
            output_file = Path(tmpdir) / f"test{i}.pdf"
            output_file.write_bytes(b"fake pdf content")

        result = await handle_call_tool(
            "convert_batch",
            {
                "input_files": input_files,
                "output_format": "pdf",
                "output_dir": tmpdir
            }
        )

        result_data = json.loads(result[0].text)
        assert result_data["success"] is True
        assert result_data["total_files"] == 3


@pytest.mark.asyncio
async def test_get_document_info():
    """Test getting document information."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a test file
        test_file = Path(tmpdir) / "test.txt"
        test_file.write_text("This is a test document with some content.")

        result = await handle_call_tool(
            "get_document_info",
            {"input_file": str(test_file)}
        )

        result_data = json.loads(result[0].text)
        assert result_data["success"] is True
        assert result_data["file_name"] == "test.txt"
        assert result_data["file_size"] > 0


@pytest.mark.asyncio
async def test_merge_documents_insufficient_files():
    """Test merging with insufficient files."""
    result = await handle_call_tool(
        "merge_documents",
        {
            "input_files": ["single_file.pdf"],
            "output_file": "merged.pdf"
        }
    )

    result_data = json.loads(result[0].text)
    assert result_data["success"] is False
    assert "At least 2 files required" in result_data["error"]
