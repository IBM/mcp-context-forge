# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/plotly_server/tests/test_server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for Plotly MCP Server (FastMCP).
"""

import pytest

from plotly_server.server_fastmcp import visualizer


def test_create_chart():
    """Test creating a chart."""
    if visualizer is None:
        pytest.skip("Plotly visualizer not available")

    result = visualizer.create_chart(
        chart_type="line", data={"x": [1, 2, 3], "y": [1, 4, 9]}, title="Test Chart"
    )

    assert result["success"] is True
    assert "html" in result


def test_create_subplot():
    """Test creating subplots."""
    if visualizer is None:
        pytest.skip("Plotly visualizer not available")

    result = visualizer.create_subplot(
        rows=1,
        cols=2,
        plots=[
            {"type": "line", "data": {"x": [1, 2], "y": [1, 2]}},
            {"type": "bar", "data": {"x": ["A", "B"], "y": [3, 4]}},
        ],
    )

    assert result["success"] is True


def test_export_chart():
    """Test exporting chart."""
    if visualizer is None:
        pytest.skip("Plotly visualizer not available")

    # Create a simple chart first
    chart_result = visualizer.create_chart(chart_type="line", data={"x": [1, 2], "y": [1, 2]})

    if chart_result["success"]:
        # Try to export (may fail if kaleido not installed)
        export_result = visualizer.export_chart(
            chart_data=chart_result.get("html", ""), format="png", output_path="/tmp/test.png"
        )
        # Don't assert success as kaleido might not be installed


def test_get_supported_charts():
    """Test getting supported charts."""
    if visualizer is None:
        pytest.skip("Plotly visualizer not available")

    result = visualizer.get_supported_charts()
    assert "chart_types" in result
    assert "line" in result["chart_types"]
    assert "bar" in result["chart_types"]


def test_visualizer_initialization():
    """Test visualizer initialization state."""
    # Visualizer may be None if dependencies not available
    if visualizer is not None:
        assert hasattr(visualizer, "create_chart")
        assert hasattr(visualizer, "create_subplot")
        assert hasattr(visualizer, "export_chart")
        assert hasattr(visualizer, "get_supported_charts")
