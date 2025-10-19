# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/csv_pandas_chat_server/tests/test_server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for CSV Pandas Chat MCP Server (FastMCP).
"""

import pytest

from csv_pandas_chat_server.server_fastmcp import (
    analyze_csv,
    chat_with_csv,
    get_csv_info,
    processor,
)


@pytest.mark.asyncio
async def test_get_csv_info():
    """Test getting CSV info from content."""
    csv_content = "name,age,city\nJohn,25,NYC\nJane,30,Boston\nBob,35,LA"

    result = await get_csv_info(csv_content=csv_content)

    assert result["success"] is True
    assert result["shape"] == [3, 3]  # 3 rows, 3 columns
    assert "name" in result["columns"]
    assert "age" in result["columns"]
    assert "city" in result["columns"]


@pytest.mark.asyncio
async def test_analyze_csv_basic():
    """Test basic CSV analysis."""
    csv_content = (
        "product,sales,region\nWidget A,1000,North\nWidget B,1500,South\nGadget X,800,East"
    )

    result = await analyze_csv(csv_content=csv_content, analysis_type="basic")

    assert result["success"] is True
    assert result["analysis_type"] == "basic"
    assert result["shape"] == [3, 3]
    assert "data_quality" in result
    assert "column_types" in result


@pytest.mark.asyncio
async def test_analyze_csv_statistical():
    """Test statistical CSV analysis."""
    csv_content = "value1,value2,value3\n1,2,3\n4,5,6\n7,8,9\n10,11,12"

    result = await analyze_csv(csv_content=csv_content, analysis_type="statistical")

    assert result["success"] is True
    assert result["analysis_type"] == "statistical"
    assert "advanced_stats" in result


@pytest.mark.asyncio
async def test_chat_with_csv_missing_api_key():
    """Test chat with CSV without API key."""
    csv_content = "product,sales\nWidget A,1000\nWidget B,1500"

    result = await chat_with_csv(query="Show me the data", csv_content=csv_content)

    assert result["success"] is False
    assert "API key" in result["error"]


@pytest.mark.asyncio
async def test_get_csv_info_missing_source():
    """Test CSV info without providing any data source."""
    with pytest.raises(ValueError, match="Exactly one"):
        await get_csv_info()


@pytest.mark.asyncio
async def test_get_csv_info_multiple_sources():
    """Test CSV info with multiple data sources."""
    with pytest.raises(ValueError, match="Exactly one"):
        await get_csv_info(csv_content="a,b\n1,2", file_path="/some/file.csv")


@pytest.mark.asyncio
async def test_analyze_csv_empty():
    """Test analysis with empty CSV content."""
    result = await analyze_csv(csv_content="")

    assert result["success"] is False


@pytest.mark.asyncio
async def test_load_dataframe():
    """Test loading dataframe directly from processor."""
    csv_content = "col1,col2\n1,2\n3,4"

    df = await processor.load_dataframe(csv_content=csv_content)

    assert df.shape == (2, 2)
    assert list(df.columns) == ["col1", "col2"]
