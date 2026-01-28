# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/docx_server/tests/test_server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for DOCX MCP Server (FastMCP).
"""

import tempfile
from pathlib import Path

from docx_server.server_fastmcp import doc_ops


def test_create_document():
    """Test document creation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.docx")

        result = doc_ops.create_document(file_path, "Test Doc", "Test Author")

        assert result["success"] is True
        assert Path(file_path).exists()


def test_add_text():
    """Test adding text to a document."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.docx")
        doc_ops.create_document(file_path)

        result = doc_ops.add_text(file_path, "This is test text")

        assert result["success"] is True


def test_add_heading():
    """Test adding heading to a document."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.docx")
        doc_ops.create_document(file_path)

        result = doc_ops.add_heading(file_path, "Test Heading", level=1)

        assert result["success"] is True


def test_add_table():
    """Test adding table to a document."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.docx")
        doc_ops.create_document(file_path)

        result = doc_ops.add_table(
            file_path,
            rows=2,
            cols=3,
            data=[["A1", "B1", "C1"], ["A2", "B2", "C2"]],
            headers=["Col1", "Col2", "Col3"],
        )

        assert result["success"] is True


def test_extract_text():
    """Test extracting text from a document."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.docx")
        doc_ops.create_document(file_path)
        doc_ops.add_heading(file_path, "Test Heading")
        doc_ops.add_text(file_path, "Test content")

        result = doc_ops.extract_text(file_path)

        assert result["success"] is True
        assert "Test Heading" in result["text"]
        assert "Test content" in result["text"]


def test_analyze_document():
    """Test document analysis."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.docx")
        doc_ops.create_document(file_path)
        doc_ops.add_heading(file_path, "Heading 1", level=1)
        doc_ops.add_text(file_path, "Some text here")

        result = doc_ops.analyze_document(file_path)

        assert result["success"] is True
        assert "structure" in result
        assert result["structure"]["total_paragraphs"] > 0


def test_format_text():
    """Test text formatting."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.docx")
        doc_ops.create_document(file_path)
        doc_ops.add_text(file_path, "Text to format")

        result = doc_ops.format_text(
            file_path, paragraph_index=0, run_index=0, bold=True, italic=True
        )

        assert result["success"] is True


def test_create_document_invalid_path():
    """Test document creation with invalid path."""
    result = doc_ops.create_document("/invalid/path/doc.docx")

    assert result["success"] is False
    assert "error" in result


def test_add_text_nonexistent_file():
    """Test adding text to non-existent file."""
    result = doc_ops.add_text("/nonexistent/file.docx", "Text")

    assert result["success"] is False
    assert "error" in result
