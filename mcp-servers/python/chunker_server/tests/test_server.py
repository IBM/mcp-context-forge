# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/chunker_server/tests/test_server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for Chunker MCP Server.
"""

from chunker_server.server_fastmcp import chunker


def test_recursive_chunk():
    """Test recursive text chunking."""
    text = "This is a test. " * 100  # Long text
    result = chunker.recursive_chunk(text, chunk_size=200)
    assert result["success"] is True
    assert result["chunk_count"] > 1
    assert "chunks" in result


def test_markdown_chunk():
    """Test markdown chunking."""
    markdown_text = "# Header 1\nContent here.\n## Header 2\nMore content."
    result = chunker.markdown_chunk(markdown_text)
    assert result["success"] is True
    assert "chunks" in result


def test_analyze_text():
    """Test text analysis."""
    markdown_text = "# Header 1\nContent here.\n## Header 2\nMore content."
    result = chunker.analyze_text(markdown_text)
    assert result["success"] is True
    assert result["analysis"]["has_markdown_headers"] is True


def test_get_strategies():
    """Test getting available strategies."""
    result = chunker.get_chunking_strategies()
    assert "strategies" in result
    assert len(result["strategies"]) > 0
    assert "available_strategies" in result
    assert result["available_strategies"]["basic"] is True
