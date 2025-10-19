# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/graphviz_server/tests/test_server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for Graphviz MCP Server (FastMCP).
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from graphviz_server.server_fastmcp import processor


def test_create_graph():
    """Test creating a DOT graph."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.dot")

        result = processor.create_graph(
            file_path=file_path,
            graph_type="digraph",
            graph_name="TestGraph",
            attributes={"rankdir": "TB", "bgcolor": "white"},
        )

        assert result["success"] is True
        assert Path(file_path).exists()
        assert result["graph_type"] == "digraph"
        assert result["graph_name"] == "TestGraph"

        # Check file content
        with open(file_path) as f:
            content = f.read()
            assert "digraph TestGraph {" in content
            assert 'rankdir="TB"' in content
            assert 'bgcolor="white"' in content


def test_add_node():
    """Test adding a node to a graph."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.dot")

        # Create graph first
        processor.create_graph(file_path=file_path, graph_type="digraph")

        # Add node
        result = processor.add_node(
            file_path=file_path,
            node_id="node1",
            label="Test Node",
            attributes={"shape": "box", "color": "blue"},
        )

        assert result["success"] is True
        assert result["node_id"] == "node1"
        assert result["label"] == "Test Node"

        # Check file content
        with open(file_path) as f:
            content = f.read()
            assert 'node1 [label="Test Node", shape="box", color="blue"];' in content


def test_add_edge():
    """Test adding an edge to a graph."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.dot")

        # Create graph first
        processor.create_graph(file_path=file_path, graph_type="digraph")

        # Add edge
        result = processor.add_edge(
            file_path=file_path,
            from_node="A",
            to_node="B",
            label="edge1",
            attributes={"color": "red", "style": "bold"},
        )

        assert result["success"] is True
        assert result["from_node"] == "A"
        assert result["to_node"] == "B"
        assert result["label"] == "edge1"

        # Check file content
        with open(file_path) as f:
            content = f.read()
            assert 'A -> B [label="edge1", color="red", style="bold"];' in content


def test_analyze_graph():
    """Test analyzing a graph."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.dot")

        # Create a graph with some content
        graph_content = """digraph TestGraph {
    rankdir=TB;

    A [label="Node A"];
    B [label="Node B"];
    C [label="Node C"];

    A -> B [label="edge1"];
    B -> C [label="edge2"];
    A -> C [label="edge3"];
}"""

        with open(file_path, "w") as f:
            f.write(graph_content)

        result = processor.analyze_graph(
            file_path=file_path, include_structure=True, include_metrics=True
        )

        assert result["success"] is True
        assert "structure" in result
        assert "metrics" in result

        # Check structure analysis
        structure = result["structure"]
        assert structure["edge_count"] == 3  # A->B, B->C, A->C


@patch("graphviz_server.server_fastmcp.subprocess.run")
def test_validate_graph_success(mock_subprocess):
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
        with open(file_path, "w") as f:
            f.write("digraph G { A -> B; }")

        result = processor.validate_graph(file_path=file_path)

        assert result["success"] is True
        assert result["file_path"] == file_path


def test_set_attributes():
    """Test setting graph attributes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.dot")

        # Create graph first
        processor.create_graph(file_path=file_path, graph_type="digraph")

        # Set graph attributes
        result = processor.set_attributes(
            file_path=file_path,
            target_type="graph",
            attributes={"splines": "curved", "overlap": "false"},
        )

        assert result["success"] is True

        # Check file content
        with open(file_path) as f:
            content = f.read()
            assert 'splines="curved"' in content
            assert 'overlap="false"' in content


def test_create_graph_missing_directory():
    """Test creating graph in non-existent directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "subdir" / "test.dot")

        result = processor.create_graph(file_path=file_path, graph_type="digraph")

        assert result["success"] is True
        # Should create directory and file
        assert Path(file_path).exists()
        assert Path(file_path).parent.exists()


def test_list_layouts():
    """Test listing layouts and formats."""
    result = processor.list_layouts()

    assert result["success"] is True
    assert "layouts" in result
    assert "formats" in result
    assert "dot" in result["layouts"]
    assert "png" in result["formats"]


def test_add_node_duplicate():
    """Test adding duplicate node to a graph."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.dot")

        # Create graph and add a node
        processor.create_graph(file_path=file_path, graph_type="digraph")
        processor.add_node(file_path=file_path, node_id="node1")

        # Try to add the same node again
        result = processor.add_node(file_path=file_path, node_id="node1")

        assert result["success"] is False
        assert "already exists" in result["error"]


def test_undirected_graph_edge():
    """Test adding edge to undirected graph uses correct operator."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.dot")

        # Create undirected graph
        processor.create_graph(file_path=file_path, graph_type="graph")

        # Add edge
        result = processor.add_edge(file_path=file_path, from_node="A", to_node="B")

        assert result["success"] is True

        # Check file content for undirected edge operator
        with open(file_path) as f:
            content = f.read()
            assert "A -- B;" in content
            assert "A -> B" not in content  # Should not have directed edge
