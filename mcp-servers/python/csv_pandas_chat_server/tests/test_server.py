# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/csv_pandas_chat_server/tests/test_server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for CSV Pandas Chat MCP Server.
"""

import json
import pandas as pd
import pytest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
from csv_pandas_chat_server.server import handle_call_tool, handle_list_tools


@pytest.mark.asyncio
async def test_list_tools():
    """Test that tools are listed correctly."""
    tools = await handle_list_tools()

    tool_names = [tool.name for tool in tools]
    expected_tools = [
        "chat_with_csv",
        "get_csv_info",
        "analyze_csv"
    ]

    for expected in expected_tools:
        assert expected in tool_names


@pytest.mark.asyncio
async def test_get_csv_info_with_content():
    """Test getting CSV info from content."""
    csv_content = "name,age,city\nJohn,25,NYC\nJane,30,Boston\nBob,35,LA"

    result = await handle_call_tool(
        "get_csv_info",
        {"csv_content": csv_content}
    )

    result_data = json.loads(result[0].text)
    if result_data["success"]:
        assert result_data["shape"] == [3, 3]  # 3 rows, 3 columns
        assert "name" in result_data["columns"]
        assert "age" in result_data["columns"]
        assert "city" in result_data["columns"]
        assert len(result_data["sample_data"]) <= 5
    else:
        # When dependencies are not available
        assert "error" in result_data


@pytest.mark.asyncio
async def test_analyze_csv_basic():
    """Test basic CSV analysis."""
    csv_content = "product,sales,region\nWidget A,1000,North\nWidget B,1500,South\nGadget X,800,East"

    result = await handle_call_tool(
        "analyze_csv",
        {
            "csv_content": csv_content,
            "analysis_type": "basic"
        }
    )

    result_data = json.loads(result[0].text)
    if result_data["success"]:
        assert result_data["analysis_type"] == "basic"
        assert result_data["shape"] == [3, 3]
        assert "data_quality" in result_data
        assert "column_types" in result_data
    else:
        # When dependencies are not available
        assert "error" in result_data


@pytest.mark.asyncio
async def test_analyze_csv_detailed():
    """Test detailed CSV analysis."""
    csv_content = "product,sales,price,quantity\nWidget A,1000,10.5,95\nWidget B,1500,12.0,125\nGadget X,800,8.5,94"

    result = await handle_call_tool(
        "analyze_csv",
        {
            "csv_content": csv_content,
            "analysis_type": "detailed"
        }
    )

    result_data = json.loads(result[0].text)
    if result_data["success"]:
        assert result_data["analysis_type"] == "detailed"
        assert "statistical_summary" in result_data
        assert "correlations" in result_data
    else:
        # When dependencies are not available
        assert "error" in result_data


@pytest.mark.asyncio
async def test_analyze_csv_statistical():
    """Test statistical CSV analysis."""
    csv_content = "value1,value2,value3\n1,2,3\n4,5,6\n7,8,9\n10,11,12"

    result = await handle_call_tool(
        "analyze_csv",
        {
            "csv_content": csv_content,
            "analysis_type": "statistical"
        }
    )

    result_data = json.loads(result[0].text)
    if result_data["success"]:
        assert result_data["analysis_type"] == "statistical"
        assert "advanced_stats" in result_data
    else:
        # When dependencies are not available
        assert "error" in result_data


@pytest.mark.asyncio
@patch('csv_pandas_chat_server.server.openai')
async def test_chat_with_csv_success(mock_openai):
    """Test successful chat with CSV."""
    # Mock OpenAI response
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message = MagicMock()
    mock_response.choices[0].message.content = json.dumps({
        "code": "result = df.nlargest(2, 'sales')[['product', 'sales']]",
        "explanation": "This code finds the top 2 products by sales"
    })

    mock_client = AsyncMock()
    mock_client.chat.completions.create.return_value = mock_response
    mock_openai.AsyncOpenAI.return_value = mock_client

    csv_content = "product,sales,region\nWidget A,1000,North\nWidget B,1500,South\nGadget X,800,East"

    result = await handle_call_tool(
        "chat_with_csv",
        {
            "query": "What are the top 2 products by sales?",
            "csv_content": csv_content,
            "openai_api_key": "test-key",
            "model": "gpt-3.5-turbo"
        }
    )

    result_data = json.loads(result[0].text)
    if result_data["success"]:
        assert "explanation" in result_data
        assert "generated_code" in result_data
        assert "result" in result_data
        assert "Widget B" in result_data["result"]  # Should be top product
    else:
        # When dependencies are not available or OpenAI call fails
        assert "error" in result_data


@pytest.mark.asyncio
async def test_chat_with_csv_missing_api_key():
    """Test chat with CSV without API key."""
    csv_content = "product,sales\nWidget A,1000\nWidget B,1500"

    result = await handle_call_tool(
        "chat_with_csv",
        {
            "query": "Show me the data",
            "csv_content": csv_content
        }
    )

    result_data = json.loads(result[0].text)
    assert result_data["success"] is False
    assert "API key" in result_data["error"]


@pytest.mark.asyncio
async def test_chat_with_csv_invalid_csv():
    """Test chat with invalid CSV content."""
    invalid_csv = "invalid,csv,content\nrow1\nrow2,too,many,columns"

    result = await handle_call_tool(
        "chat_with_csv",
        {
            "query": "Analyze this data",
            "csv_content": invalid_csv,
            "openai_api_key": "test-key"
        }
    )

    result_data = json.loads(result[0].text)
    # Should handle pandas parsing errors gracefully
    assert "success" in result_data


@pytest.mark.asyncio
async def test_get_csv_info_missing_source():
    """Test CSV info without providing any data source."""
    result = await handle_call_tool(
        "get_csv_info",
        {}  # No data source provided
    )

    result_data = json.loads(result[0].text)
    assert result_data["success"] is False
    assert "must be provided" in result_data["error"]


@pytest.mark.asyncio
async def test_get_csv_info_multiple_sources():
    """Test CSV info with multiple data sources."""
    result = await handle_call_tool(
        "get_csv_info",
        {
            "csv_content": "a,b\n1,2",
            "file_path": "/some/file.csv"  # Multiple sources
        }
    )

    result_data = json.loads(result[0].text)
    assert result_data["success"] is False
    assert "Exactly one" in result_data["error"]


@pytest.mark.asyncio
async def test_analyze_csv_empty_content():
    """Test analysis with empty CSV content."""
    result = await handle_call_tool(
        "analyze_csv",
        {"csv_content": ""}
    )

    result_data = json.loads(result[0].text)
    assert result_data["success"] is False


@pytest.mark.asyncio
async def test_chat_with_csv_large_dataframe():
    """Test chat with dataframe exceeding size limits."""
    # Create CSV content that would exceed limits
    large_csv_rows = ["col1,col2,col3"] + [f"{i},{i+1},{i+2}" for i in range(200000)]
    large_csv = "\n".join(large_csv_rows)

    result = await handle_call_tool(
        "chat_with_csv",
        {
            "query": "Count rows",
            "csv_content": large_csv,
            "openai_api_key": "test-key"
        }
    )

    result_data = json.loads(result[0].text)
    assert result_data["success"] is False
    assert "exceeds maximum" in result_data["error"] or "rows" in result_data["error"]


@pytest.mark.asyncio
async def test_unknown_tool():
    """Test calling unknown tool."""
    result = await handle_call_tool(
        "unknown_tool",
        {"some": "argument"}
    )

    result_data = json.loads(result[0].text)
    assert result_data["success"] is False
    assert "Unknown tool" in result_data["error"]


@pytest.fixture
def sample_csv_content():
    """Fixture providing sample CSV content for tests."""
    return """product,sales,region,date
Widget A,1000,North,2023-01-01
Widget B,1500,South,2023-01-02
Gadget X,800,East,2023-01-03
Tool Y,1200,West,2023-01-04
Device Z,900,North,2023-01-05"""


@pytest.mark.asyncio
async def test_csv_info_with_sample_data(sample_csv_content):
    """Test CSV info with realistic sample data."""
    result = await handle_call_tool(
        "get_csv_info",
        {"csv_content": sample_csv_content}
    )

    result_data = json.loads(result[0].text)
    if result_data["success"]:
        assert result_data["shape"] == [5, 4]  # 5 rows, 4 columns
        assert set(result_data["columns"]) == {"product", "sales", "region", "date"}
        assert result_data["missing_values"]["product"] == 0  # No missing values
    else:
        assert "error" in result_data


@pytest.mark.asyncio
async def test_analyze_csv_with_sample_data(sample_csv_content):
    """Test CSV analysis with realistic sample data."""
    result = await handle_call_tool(
        "analyze_csv",
        {
            "csv_content": sample_csv_content,
            "analysis_type": "detailed"
        }
    )

    result_data = json.loads(result[0].text)
    if result_data["success"]:
        assert "numeric" in result_data["column_types"]
        assert "categorical" in result_data["column_types"]
        assert "sales" in result_data["column_types"]["numeric"]
        assert "product" in result_data["column_types"]["categorical"]
    else:
        assert "error" in result_data
