# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/graphviz_server/tests/test_server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for Graphviz MCP Server.
"""

import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from graphviz_server.server import handle_call_tool, handle_list_tools


@pytest.mark.asyncio
async def test_list_tools():
    """Test that tools are listed correctly."""
    tools = await handle_list_tools()

    tool_names = [tool.name for tool in tools]
    expected_tools = [
        "create_graph",
        "render_graph",
        "add_node",
        "add_edge",
        "set_attributes",
        "analyze_graph",
        "validate_graph",
        "list_layouts"
    ]

    for expected in expected_tools:
        assert expected in tool_names


@pytest.mark.asyncio
async def test_list_layouts():
    """Test listing layouts and formats."""
    result = await handle_call_tool("list_layouts", {})

    result_data = json.loads(result[0].text)
    if result_data["success"]:
        assert "layouts" in result_data
        assert "formats" in result_data
        assert "dot" in [layout["name"] for layout in result_data["layouts"]]
        assert "png" in result_data["formats"]
    else:
        # When Graphviz is not available
        assert "Graphviz not available" in result_data["error"]


@pytest.mark.asyncio
async def test_create_graph():
    """Test creating a DOT graph."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.dot")

        result = await handle_call_tool(
            "create_graph",
            {
                "file_path": file_path,
                "graph_type": "digraph",
                "graph_name": "TestGraph",
                "attributes": {"rankdir": "TB", "bgcolor": "white"}
            }
        )

        result_data = json.loads(result[0].text)
        if result_data["success"]:
            assert Path(file_path).exists()
            assert result_data["graph_type"] == "digraph"
            assert result_data["graph_name"] == "TestGraph"

            # Check file content
            with open(file_path, 'r') as f:
                content = f.read()
                assert "digraph TestGraph {" in content
                assert 'rankdir="TB"' in content
                assert 'bgcolor="white"' in content
        else:
            # When Graphviz is not available
            assert "Graphviz not available" in result_data["error"]


@pytest.mark.asyncio
async def test_add_node():
    """Test adding a node to a graph."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.dot")

        # Create graph first
        await handle_call_tool(
            "create_graph",
            {"file_path": file_path, "graph_type": "digraph"}
        )

        # Add node
        result = await handle_call_tool(
            "add_node",
            {
                "file_path": file_path,
                "node_id": "node1",
                "label": "Test Node",
                "attributes": {"shape": "box", "color": "blue"}
            }
        )

        result_data = json.loads(result[0].text)
        if result_data["success"]:
            assert result_data["node_id"] == "node1"
            assert result_data["label"] == "Test Node"

            # Check file content
            with open(file_path, 'r') as f:
                content = f.read()
                assert 'node1 [label="Test Node", shape="box", color="blue"];' in content
        else:
            # When Graphviz is not available or file doesn't exist
            assert "Graphviz not available" in result_data["error"] or "not found" in result_data["error"]


@pytest.mark.asyncio
async def test_add_edge():
    """Test adding an edge to a graph."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.dot")

        # Create graph first
        await handle_call_tool(
            "create_graph",
            {"file_path": file_path, "graph_type": "digraph"}
        )

        # Add edge
        result = await handle_call_tool(
            "add_edge",
            {
                "file_path": file_path,
                "from_node": "A",
                "to_node": "B",
                "label": "edge1",
                "attributes": {"color": "red", "style": "bold"}
            }
        )

        result_data = json.loads(result[0].text)
        if result_data["success"]:
            assert result_data["from_node"] == "A"
            assert result_data["to_node"] == "B"
            assert result_data["label"] == "edge1"

            # Check file content
            with open(file_path, 'r') as f:
                content = f.read()
                assert 'A -> B [label="edge1", color="red", style="bold"];' in content
        else:
            # When Graphviz is not available or file doesn't exist
            assert "Graphviz not available" in result_data["error"] or "not found" in result_data["error"]


@pytest.mark.asyncio
async def test_analyze_graph():
    """Test analyzing a graph."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.dot")

        # Create a graph with some content
        graph_content = '''digraph TestGraph {
    rankdir=TB;

    A [label="Node A"];
    B [label="Node B"];
    C [label="Node C"];

    A -> B [label="edge1"];
    B -> C [label="edge2"];
    A -> C [label="edge3"];
}'''

        with open(file_path, 'w') as f:
            f.write(graph_content)

        result = await handle_call_tool(
            "analyze_graph",
            {
                "file_path": file_path,
                "include_structure": True,
                "include_metrics": True
            }
        )

        result_data = json.loads(result[0].text)
        if result_data["success"]:
            assert "structure" in result_data
            assert "metrics" in result_data
            assert "graph_info" in result_data

            # Check structure analysis
            structure = result_data["structure"]
            assert structure["total_nodes"] >= 3  # A, B, C
            assert structure["total_edges"] == 3  # A->B, B->C, A->C

            # Check graph info
            graph_info = result_data["graph_info"]
            assert graph_info["is_directed"] is True
            assert graph_info["graph_type"] == "digraph"
        else:
            # When Graphviz is not available or file doesn't exist
            assert "Graphviz not available" in result_data["error"] or "not found" in result_data["error"]


@pytest.mark.asyncio
@patch('graphviz_server.server.subprocess.run')
async def test_render_graph_success(mock_subprocess):
    """Test successful graph rendering."""
    # Mock successful subprocess call
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "rendering successful"
    mock_result.stderr = ""
    mock_subprocess.return_value = mock_result

    with tempfile.TemporaryDirectory() as tmpdir:
        input_file = str(Path(tmpdir) / "test.dot")
        output_file = str(Path(tmpdir) / "test.png")

        # Create a simple DOT file
        with open(input_file, 'w') as f:
            f.write('digraph G { A -> B; }')

        # Create expected output file (mock the rendering result)
        with open(output_file, 'wb') as f:
            f.write(b"fake png content")

        result = await handle_call_tool(
            "render_graph",
            {
                "input_file": input_file,
                "output_file": output_file,
                "format": "png",
                "layout": "dot"
            }
        )

        result_data = json.loads(result[0].text)
        if result_data["success"]:
            assert result_data["format"] == "png"
            assert result_data["layout"] == "dot"
            assert result_data["output_file"] == output_file
        else:
            # When Graphviz is not available
            assert "Graphviz not available" in result_data["error"]


@pytest.mark.asyncio
@patch('graphviz_server.server.subprocess.run')
async def test_validate_graph_success(mock_subprocess):
    """Test successful graph validation."""
    # Mock successful validation
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "validation successful"
    mock_result.stderr = ""
    mock_subprocess.return_value = mock_result

    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.dot")

        # Create a valid DOT file
        with open(file_path, 'w') as f:
            f.write('digraph G { A -> B; }')

        result = await handle_call_tool(
            "validate_graph",
            {"file_path": file_path}
        )

        result_data = json.loads(result[0].text)
        if result_data["success"]:
            assert result_data["valid"] is True
            assert result_data["file_path"] == file_path
        else:
            # When Graphviz is not available
            assert "Graphviz not available" in result_data["error"]


@pytest.mark.asyncio
async def test_set_attributes():
    """Test setting graph attributes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.dot")

        # Create graph first
        await handle_call_tool(
            "create_graph",
            {"file_path": file_path, "graph_type": "digraph"}
        )

        # Set graph attributes
        result = await handle_call_tool(
            "set_attributes",
            {
                "file_path": file_path,
                "target_type": "graph",
                "attributes": {"splines": "curved", "overlap": "false"}
            }
        )

        result_data = json.loads(result[0].text)
        if result_data["success"]:
            assert result_data["target_type"] == "graph"
            assert result_data["attributes"]["splines"] == "curved"

            # Check file content
            with open(file_path, 'r') as f:
                content = f.read()
                assert 'splines="curved"' in content
                assert 'overlap="false"' in content
        else:
            # When Graphviz is not available or file doesn't exist
            assert "Graphviz not available" in result_data["error"] or "not found" in result_data["error"]


@pytest.mark.asyncio
async def test_create_graph_missing_directory():
    """Test creating graph in non-existent directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "subdir" / "test.dot")

        result = await handle_call_tool(
            "create_graph",
            {"file_path": file_path, "graph_type": "digraph"}
        )

        result_data = json.loads(result[0].text)
        if result_data["success"]:
            # Should create directory and file
            assert Path(file_path).exists()
            assert Path(file_path).parent.exists()
        else:
            # When Graphviz is not available
            assert "Graphviz not available" in result_data["error"]
