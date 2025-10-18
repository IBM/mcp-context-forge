# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/xlsx_server/tests/test_server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for XLSX MCP Server (FastMCP).
"""

import tempfile
from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_create_workbook():
    """Test workbook creation."""
    from xlsx_server.server_fastmcp import ops

    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.xlsx")

        result = ops.create_workbook(file_path, ["Sheet1", "Sheet2"])

        assert result["success"] is True
        assert Path(file_path).exists()
        assert "sheets" in result
        assert len(result["sheets"]) == 2


@pytest.mark.asyncio
async def test_write_and_read_data():
    """Test writing and reading data to/from a workbook."""
    from xlsx_server.server_fastmcp import ops

    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.xlsx")

        # Create workbook
        ops.create_workbook(file_path, ["Sheet1"])

        # Write data
        data = [["Name", "Age"], ["Alice", 30], ["Bob", 25]]
        write_result = ops.write_data(file_path, data, None, 1, 1, None)
        assert write_result["success"] is True

        # Read data
        read_result = ops.read_data(file_path, "A1:B3", None)
        assert read_result["success"] is True
        assert len(read_result["data"]) == 3
        assert read_result["data"][0] == ["Name", "Age"]


@pytest.mark.asyncio
async def test_add_formula():
    """Test adding formulas to cells."""
    from xlsx_server.server_fastmcp import ops

    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.xlsx")

        # Create workbook
        ops.create_workbook(file_path, ["Sheet1"])

        # Write some data
        data = [[1], [2], [3]]
        ops.write_data(file_path, data, None, 1, 1, None)

        # Add a SUM formula
        formula_result = ops.add_formula(file_path, "A4", "=SUM(A1:A3)", None)
        assert formula_result["success"] is True
        assert formula_result["formula"] == "=SUM(A1:A3)"


@pytest.mark.asyncio
async def test_format_cells():
    """Test cell formatting."""
    from xlsx_server.server_fastmcp import ops

    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.xlsx")

        # Create workbook
        ops.create_workbook(file_path, ["Sheet1"])

        # Write some data
        data = [["Header"]]
        ops.write_data(file_path, data, None, 1, 1, None)

        # Format the cell
        format_result = ops.format_cells(
            file_path,
            "A1",
            None,
            font_bold=True,
            font_italic=False,
            font_color="#FF0000",
            background_color="#FFFF00",
            alignment="center",
        )
        assert format_result["success"] is True


@pytest.mark.asyncio
async def test_analyze_workbook():
    """Test workbook analysis."""
    from xlsx_server.server_fastmcp import ops

    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.xlsx")

        # Create workbook with data
        ops.create_workbook(file_path, ["Sheet1", "Sheet2"])
        data = [["Name", "Score"], ["Alice", 95], ["Bob", 87]]
        ops.write_data(file_path, data, None, 1, 1, None)

        # Analyze workbook
        analysis = ops.analyze_workbook(
            file_path, include_structure=True, include_data_summary=True, include_formulas=True
        )

        assert analysis["success"] is True
        assert "structure" in analysis
        assert analysis["structure"]["sheets"] == 2  # sheets is the sheet count
        assert "Sheet1" in [s["name"] for s in analysis["sheets"]]


@pytest.mark.asyncio
async def test_create_chart():
    """Test chart creation."""
    from xlsx_server.server_fastmcp import ops

    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.xlsx")

        # Create workbook with data
        ops.create_workbook(file_path, ["Sheet1"])
        data = [["Month", "Sales"], ["Jan", 100], ["Feb", 150], ["Mar", 120]]
        ops.write_data(file_path, data, None, 1, 1, None)

        # Create a chart
        chart_result = ops.create_chart(
            file_path,
            sheet_name=None,
            chart_type="column",
            data_range="A1:B4",
            title="Monthly Sales",
            x_axis_title="Month",
            y_axis_title="Sales",
        )

        assert chart_result["success"] is True
        assert chart_result["chart_type"] == "column"
