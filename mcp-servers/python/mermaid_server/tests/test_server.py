# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/mermaid_server/tests/test_server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for Mermaid MCP Server (FastMCP).
"""

import pytest

from mermaid_server.server_fastmcp import processor


def test_create_flowchart():
    """Test creating flowchart diagram."""
    if processor is None:
        pytest.skip("Mermaid processor not available")

    result = processor.create_flowchart(
        nodes=["A", "B", "C"], edges=[("A", "B", "Step 1"), ("B", "C", "Step 2")]
    )

    assert result["success"] is True
    assert "graph" in result["diagram"]


def test_create_sequence_diagram():
    """Test creating sequence diagram."""
    if processor is None:
        pytest.skip("Mermaid processor not available")

    result = processor.create_sequence_diagram(
        participants=["Alice", "Bob"], messages=[("Alice", "Bob", "Hello")]
    )

    assert result["success"] is True
    assert "sequenceDiagram" in result["diagram"]


def test_create_gantt_chart():
    """Test creating Gantt chart."""
    if processor is None:
        pytest.skip("Mermaid processor not available")

    result = processor.create_gantt_chart(
        title="Project",
        tasks=[{"id": "task1", "name": "Task 1", "start": "2024-01-01", "duration": "5d"}],
    )

    assert result["success"] is True
    assert "gantt" in result["diagram"]


def test_validate_mermaid():
    """Test Mermaid validation."""
    if processor is None:
        pytest.skip("Mermaid processor not available")

    # Valid diagram
    result = processor.validate_mermaid("graph TD\n  A --> B")
    assert result["valid"] is True

    # Invalid diagram (empty)
    result = processor.validate_mermaid("")
    assert result["valid"] is False


def test_get_templates():
    """Test getting templates."""
    if processor is None:
        pytest.skip("Mermaid processor not available")

    result = processor.get_diagram_templates()
    assert "flowchart" in result
    assert "sequence" in result


def test_processor_initialization():
    """Test processor initialization state."""
    # Processor may be None if dependencies not available
    if processor is not None:
        assert hasattr(processor, "create_flowchart")
        assert hasattr(processor, "create_sequence_diagram")
        assert hasattr(processor, "validate_mermaid")
