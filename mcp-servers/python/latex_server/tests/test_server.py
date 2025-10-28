# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/latex_server/tests/test_server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for LaTeX MCP Server (FastMCP).
"""

import tempfile
from pathlib import Path

from latex_server.server_fastmcp import processor


def test_create_document():
    """Test document creation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.tex")

        result = processor.create_document(file_path, "article", "Test Doc", "Test Author")

        assert result["success"] is True
        assert Path(file_path).exists()


def test_add_content():
    """Test adding content to a document."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.tex")
        processor.create_document(file_path, "article")

        result = processor.add_content(file_path, "This is test content")

        assert result["success"] is True


def test_add_section():
    """Test adding section to a document."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.tex")
        processor.create_document(file_path, "article")

        result = processor.add_section(file_path, "section", "Test Section")

        assert result["success"] is True


def test_add_table():
    """Test adding table to a document."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.tex")
        processor.create_document(file_path, "article")

        data = [["A1", "B1"], ["A2", "B2"]]
        result = processor.add_table(file_path, data, headers=["Col1", "Col2"])

        assert result["success"] is True


def test_analyze_document():
    """Test document analysis."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.tex")
        processor.create_document(file_path, "article")
        processor.add_section(file_path, "section", "Test")

        result = processor.analyze_document(file_path)

        assert result["success"] is True
        assert "structure" in result


def test_create_from_template():
    """Test creating document from template."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.tex")

        result = processor.create_from_template(
            "article", file_path, {"title": "Test", "author": "Test Author"}
        )

        assert result["success"] is True
        assert Path(file_path).exists()


def test_create_document_invalid_path():
    """Test document creation with invalid path."""
    result = processor.create_document("/invalid/path/doc.tex", "article")

    assert result["success"] is False
    assert "error" in result


def test_add_content_nonexistent_file():
    """Test adding content to non-existent file."""
    result = processor.add_content("/nonexistent/file.tex", "Text")

    assert result["success"] is False
    assert "error" in result
