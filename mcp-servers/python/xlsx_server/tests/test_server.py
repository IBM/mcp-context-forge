# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/xlsx_server/tests/test_server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for XLSX MCP Server.
"""

import json
import pytest
import tempfile
from pathlib import Path
from xlsx_server.server import handle_call_tool, handle_list_tools


@pytest.mark.asyncio
async def test_list_tools():
    """Test that tools are listed correctly."""
    tools = await handle_list_tools()

    tool_names = [tool.name for tool in tools]
    expected_tools = [
        "create_workbook",
        "write_data",
        "read_data",
        "format_cells",
        "add_formula",
        "analyze_workbook",
        "create_chart"
    ]

    for expected in expected_tools:
        assert expected in tool_names


@pytest.mark.asyncio
async def test_create_workbook():
    """Test workbook creation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.xlsx")

        result = await handle_call_tool(
            "create_workbook",
            {"file_path": file_path, "sheet_names": ["Sheet1", "Sheet2"]}
        )

        result_data = json.loads(result[0].text)
        assert result_data["success"] is True
        assert Path(file_path).exists()
        assert "Sheet1" in result_data["sheets"]
        assert "Sheet2" in result_data["sheets"]


@pytest.mark.asyncio
async def test_write_and_read_data():
    """Test writing and reading data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.xlsx")

        # Create workbook
        await handle_call_tool("create_workbook", {"file_path": file_path})

        # Write data
        test_data = [["A", "B", "C"], [1, 2, 3], [4, 5, 6]]
        result = await handle_call_tool(
            "write_data",
            {"file_path": file_path, "data": test_data, "headers": ["Col1", "Col2", "Col3"]}
        )

        result_data = json.loads(result[0].text)
        assert result_data["success"] is True

        # Read data back
        result = await handle_call_tool(
            "read_data",
            {"file_path": file_path}
        )

        result_data = json.loads(result[0].text)
        assert result_data["success"] is True
        assert len(result_data["data"]) > 0


@pytest.mark.asyncio
async def test_add_formula():
    """Test adding formulas."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.xlsx")

        # Create workbook and add data
        await handle_call_tool("create_workbook", {"file_path": file_path})
        await handle_call_tool("write_data", {"file_path": file_path, "data": [[1, 2], [3, 4]]})

        # Add formula
        result = await handle_call_tool(
            "add_formula",
            {"file_path": file_path, "cell": "C1", "formula": "=A1+B1"}
        )

        result_data = json.loads(result[0].text)
        assert result_data["success"] is True
        assert result_data["formula"] == "=A1+B1"


@pytest.mark.asyncio
async def test_analyze_workbook():
    """Test workbook analysis."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.xlsx")

        # Create workbook and add content
        await handle_call_tool("create_workbook", {"file_path": file_path})
        await handle_call_tool("write_data", {"file_path": file_path, "data": [[1, 2, 3]]})

        # Analyze
        result = await handle_call_tool(
            "analyze_workbook",
            {"file_path": file_path}
        )

        result_data = json.loads(result[0].text)
        assert result_data["success"] is True
        assert "structure" in result_data
        assert "data_summary" in result_data


@pytest.mark.asyncio
async def test_format_cells():
    """Test cell formatting."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.xlsx")

        # Create workbook and add data
        await handle_call_tool("create_workbook", {"file_path": file_path})
        await handle_call_tool("write_data", {"file_path": file_path, "data": [[1, 2, 3]]})

        # Format cells
        result = await handle_call_tool(
            "format_cells",
            {
                "file_path": file_path,
                "cell_range": "A1:C1",
                "font_bold": True,
                "background_color": "#FF0000"
            }
        )

        result_data = json.loads(result[0].text)
        assert result_data["success"] is True
