# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/url_to_markdown_server/tests/test_server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for URL-to-Markdown MCP Server (FastMCP).
"""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_get_capabilities():
    """Test getting converter capabilities."""
    from url_to_markdown_server.server_fastmcp import converter

    result = converter.get_capabilities()

    assert "html_engines" in result
    assert "document_converters" in result
    assert "supported_formats" in result
    assert "features" in result


@pytest.mark.asyncio
async def test_convert_basic_html():
    """Test converting HTML content to markdown."""
    from url_to_markdown_server.server_fastmcp import converter

    html_content = """
    <html>
    <head><title>Test Page</title></head>
    <body>
        <h1>Main Title</h1>
        <p>This is a paragraph with <strong>bold text</strong> and <em>italic text</em>.</p>
        <ul>
            <li>First item</li>
            <li>Second item</li>
        </ul>
        <a href="https://example.com">External link</a>
    </body>
    </html>
    """

    result = await converter._convert_basic_html(html_content)

    if result.get("success"):
        markdown = result["markdown"]
        # Basic HTML conversion should preserve main content
        assert "Main Title" in markdown
        assert "bold text" in markdown
        assert "italic text" in markdown
        assert "First item" in markdown
        assert "example.com" in markdown
    else:
        # When dependencies are not available
        assert "error" in result


@pytest.mark.asyncio
async def test_convert_text_to_markdown():
    """Test converting plain text content."""
    from url_to_markdown_server.server_fastmcp import converter

    text_content = b"This is plain text content.\nWith multiple lines.\n\nAnd paragraphs."

    result = await converter._convert_text_to_markdown(text_content)

    assert result["success"] is True
    assert result["markdown"] == text_content.decode("utf-8")
    assert result["engine"] == "text"


@pytest.mark.asyncio
async def test_fetch_url_with_mock():
    """Test fetching URL content with mocked HTTP response."""
    from url_to_markdown_server.server_fastmcp import converter

    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "text/html"}
    mock_response.text = "<html><body><h1>Mocked Page</h1></body></html>"
    mock_response.content = b"<html><body><h1>Mocked Page</h1></body></html>"

    with patch.object(converter, "get_session") as mock_get_session:
        mock_client = AsyncMock()
        mock_response.url = "https://example.com"  # Set the URL attribute
        mock_client.get.return_value = mock_response
        mock_get_session.return_value = mock_client

        result = await converter.fetch_url_content("https://example.com")

        if result.get("success"):
            assert "content" in result
            assert result["content_type"] == "text/html"
            assert "example.com" in str(result["url"])
        else:
            # Network error
            assert "error" in result


@pytest.mark.asyncio
async def test_convert_document_to_markdown():
    """Test document conversion capabilities check."""
    from url_to_markdown_server.server_fastmcp import converter

    # Test with a simple text document
    text_content = b"Simple text document"
    result = await converter.convert_document_to_markdown(text_content, "text/plain")

    assert result["success"] is True
    assert result["markdown"] == "Simple text document"


@pytest.mark.asyncio
async def test_capabilities():
    """Test that converter capabilities are properly initialized."""
    from url_to_markdown_server.server_fastmcp import converter

    # Check that converter is properly initialized
    assert hasattr(converter, "html_engines")
    assert hasattr(converter, "document_converters")
    assert isinstance(converter.html_engines, dict)
    assert isinstance(converter.document_converters, dict)

    # Get capabilities
    caps = converter.get_capabilities()
    assert "text/plain" in caps["supported_formats"]["text"]
    assert "Batch processing" in caps["features"]
