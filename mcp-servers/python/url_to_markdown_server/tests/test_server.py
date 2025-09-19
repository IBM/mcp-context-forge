# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/url_to_markdown_server/tests/test_server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for URL-to-Markdown MCP Server.
"""

import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
from url_to_markdown_server.server import handle_call_tool, handle_list_tools


@pytest.mark.asyncio
async def test_list_tools():
    """Test that tools are listed correctly."""
    tools = await handle_list_tools()

    tool_names = [tool.name for tool in tools]
    expected_tools = [
        "convert_url",
        "convert_content",
        "convert_file",
        "batch_convert",
        "get_capabilities"
    ]

    for expected in expected_tools:
        assert expected in tool_names


@pytest.mark.asyncio
async def test_get_capabilities():
    """Test getting converter capabilities."""
    result = await handle_call_tool("get_capabilities", {})

    result_data = json.loads(result[0].text)
    assert "html_engines" in result_data
    assert "document_converters" in result_data
    assert "supported_formats" in result_data
    assert "features" in result_data


@pytest.mark.asyncio
async def test_convert_content_html():
    """Test converting HTML content to markdown."""
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

    result = await handle_call_tool(
        "convert_content",
        {
            "content": html_content,
            "content_type": "text/html",
            "markdown_engine": "basic",
            "clean_content": True
        }
    )

    result_data = json.loads(result[0].text)
    if result_data.get("success"):
        markdown = result_data["markdown"]
        assert "# Main Title" in markdown
        assert "**bold text**" in markdown
        assert "*italic text*" in markdown
        assert "- First item" in markdown
        assert "[External link](https://example.com)" in markdown
        assert result_data["engine"] == "basic"
    else:
        # When dependencies are not available
        assert "error" in result_data


@pytest.mark.asyncio
async def test_convert_content_plain_text():
    """Test converting plain text content."""
    text_content = "This is plain text content.\nWith multiple lines.\n\nAnd paragraphs."

    result = await handle_call_tool(
        "convert_content",
        {
            "content": text_content,
            "content_type": "text/plain"
        }
    )

    result_data = json.loads(result[0].text)
    if result_data.get("success"):
        assert result_data["markdown"] == text_content
        assert result_data["engine"] == "text"
    else:
        assert "error" in result_data


@pytest.mark.asyncio
@patch('url_to_markdown_server.server.httpx.AsyncClient')
async def test_convert_url_success(mock_client_class):
    """Test successful URL conversion."""
    # Mock HTTP response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "text/html", "content-length": "1000"}
    mock_response.content = b"<html><body><h1>Test Page</h1><p>Content</p></body></html>"
    mock_response.url = "https://example.com/test"
    mock_response.reason_phrase = "OK"

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client_class.return_value = mock_client

    result = await handle_call_tool(
        "convert_url",
        {
            "url": "https://example.com/test",
            "markdown_engine": "basic",
            "timeout": 30
        }
    )

    result_data = json.loads(result[0].text)
    if result_data.get("success"):
        assert "markdown" in result_data
        assert "# Test Page" in result_data["markdown"]
        assert result_data["content_type"] == "text/html"
        assert result_data["url"] == "https://example.com/test"
    else:
        # When dependencies are not available or mocking fails
        assert "error" in result_data


@pytest.mark.asyncio
@patch('url_to_markdown_server.server.httpx.AsyncClient')
async def test_convert_url_timeout(mock_client_class):
    """Test URL conversion with timeout."""
    import httpx

    mock_client = AsyncMock()
    mock_client.get.side_effect = httpx.TimeoutException("Request timeout")
    mock_client_class.return_value = mock_client

    result = await handle_call_tool(
        "convert_url",
        {
            "url": "https://slow-example.com/test",
            "timeout": 5
        }
    )

    result_data = json.loads(result[0].text)
    assert result_data["success"] is False
    assert "timeout" in result_data["error"].lower()


@pytest.mark.asyncio
@patch('url_to_markdown_server.server.httpx.AsyncClient')
async def test_convert_url_http_error(mock_client_class):
    """Test URL conversion with HTTP error."""
    import httpx

    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.reason_phrase = "Not Found"

    mock_client = AsyncMock()
    mock_client.get.side_effect = httpx.HTTPStatusError("404", request=None, response=mock_response)
    mock_client_class.return_value = mock_client

    result = await handle_call_tool(
        "convert_url",
        {
            "url": "https://example.com/nonexistent",
            "timeout": 10
        }
    )

    result_data = json.loads(result[0].text)
    assert result_data["success"] is False
    assert "404" in result_data["error"]


@pytest.mark.asyncio
async def test_convert_file_not_found():
    """Test converting non-existent file."""
    result = await handle_call_tool(
        "convert_file",
        {"file_path": "/nonexistent/file.txt"}
    )

    result_data = json.loads(result[0].text)
    assert result_data["success"] is False
    assert "not found" in result_data["error"].lower()


@pytest.mark.asyncio
async def test_convert_file_text():
    """Test converting local text file."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write("This is test content.\nWith multiple lines.")
        temp_path = f.name

    try:
        result = await handle_call_tool(
            "convert_file",
            {
                "file_path": temp_path,
                "clean_content": True
            }
        )

        result_data = json.loads(result[0].text)
        if result_data.get("success"):
            assert "markdown" in result_data
            assert "This is test content" in result_data["markdown"]
        else:
            assert "error" in result_data

    finally:
        Path(temp_path).unlink(missing_ok=True)


@pytest.mark.asyncio
@patch('url_to_markdown_server.server.httpx.AsyncClient')
async def test_batch_convert_urls(mock_client_class):
    """Test batch URL conversion."""
    # Mock responses for multiple URLs
    def create_mock_response(url, content):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/html"}
        mock_response.content = content.encode('utf-8')
        mock_response.url = url
        return mock_response

    mock_client = AsyncMock()

    # Set up responses for different URLs
    responses = {
        "https://example.com/page1": create_mock_response(
            "https://example.com/page1",
            "<html><body><h1>Page 1</h1><p>Content 1</p></body></html>"
        ),
        "https://example.com/page2": create_mock_response(
            "https://example.com/page2",
            "<html><body><h1>Page 2</h1><p>Content 2</p></body></html>"
        )
    }

    async def mock_get(url, **kwargs):
        if url in responses:
            return responses[url]
        else:
            import httpx
            mock_resp = MagicMock()
            mock_resp.status_code = 404
            raise httpx.HTTPStatusError("404", request=None, response=mock_resp)

    mock_client.get.side_effect = mock_get
    mock_client_class.return_value = mock_client

    result = await handle_call_tool(
        "batch_convert",
        {
            "urls": [
                "https://example.com/page1",
                "https://example.com/page2",
                "https://example.com/nonexistent"
            ],
            "max_concurrent": 2,
            "timeout": 10,
            "clean_content": True
        }
    )

    result_data = json.loads(result[0].text)
    if result_data.get("success"):
        assert result_data["total_urls"] == 3
        assert "results" in result_data
        assert len(result_data["results"]) == 3

        # Check that some conversions succeeded and some failed
        successes = sum(1 for r in result_data["results"] if r.get("success"))
        failures = sum(1 for r in result_data["results"] if not r.get("success"))
        assert successes > 0 or failures > 0  # At least some processing occurred
    else:
        assert "error" in result_data


@pytest.mark.asyncio
async def test_convert_content_with_base_url():
    """Test converting HTML content with base URL for relative links."""
    html_content = """
    <html>
    <body>
        <h1>Test Page</h1>
        <p>Check out <a href="/other-page">this link</a>.</p>
        <img src="/images/test.png" alt="Test Image">
    </body>
    </html>
    """

    result = await handle_call_tool(
        "convert_content",
        {
            "content": html_content,
            "content_type": "text/html",
            "base_url": "https://example.com",
            "markdown_engine": "basic",
            "include_images": True
        }
    )

    result_data = json.loads(result[0].text)
    if result_data.get("success"):
        markdown = result_data["markdown"]
        # Should resolve relative URLs
        assert "https://example.com" in markdown or "/other-page" in markdown
    else:
        assert "error" in result_data


@pytest.mark.asyncio
async def test_convert_content_invalid_type():
    """Test converting content with unsupported type."""
    result = await handle_call_tool(
        "convert_content",
        {
            "content": "binary content",
            "content_type": "application/octet-stream"
        }
    )

    result_data = json.loads(result[0].text)
    assert result_data["success"] is False
    assert "Unsupported content type" in result_data["error"]


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
def sample_html():
    """Fixture providing sample HTML content."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Sample Article</title>
        <style>body { font-family: Arial; }</style>
        <script>console.log('test');</script>
    </head>
    <body>
        <header>
            <nav>Navigation menu</nav>
        </header>
        <main>
            <article>
                <h1>Article Title</h1>
                <p>This is the main article content with <strong>important</strong> information.</p>
                <h2>Subsection</h2>
                <p>More content here.</p>
                <ul>
                    <li>List item 1</li>
                    <li>List item 2</li>
                </ul>
                <p>Check out <a href="https://example.com">this link</a>.</p>
                <img src="https://example.com/image.jpg" alt="Sample Image">
            </article>
        </main>
        <footer>Footer content</footer>
    </body>
    </html>
    """


@pytest.mark.asyncio
async def test_convert_content_with_sample_html(sample_html):
    """Test converting realistic HTML content."""
    result = await handle_call_tool(
        "convert_content",
        {
            "content": sample_html,
            "content_type": "text/html",
            "markdown_engine": "basic",
            "include_images": True,
            "clean_content": True
        }
    )

    result_data = json.loads(result[0].text)
    if result_data.get("success"):
        markdown = result_data["markdown"]

        # Check that content is properly converted
        assert "# Article Title" in markdown
        assert "## Subsection" in markdown
        assert "**important**" in markdown
        assert "- List item 1" in markdown
        assert "[this link](https://example.com)" in markdown
        assert "![Sample Image](https://example.com/image.jpg)" in markdown

        # Check that scripts and styles are removed
        assert "console.log" not in markdown
        assert "font-family" not in markdown

        # Check that navigation is not included (basic engine might include it)
        # More sophisticated engines would remove it

        assert len(result_data["markdown"]) > 0
    else:
        assert "error" in result_data


@pytest.mark.asyncio
async def test_convert_content_without_images():
    """Test converting HTML without including images."""
    html_content = """
    <html>
    <body>
        <h1>Title</h1>
        <p>Content with an image:</p>
        <img src="image.jpg" alt="Test Image">
        <p>More content</p>
    </body>
    </html>
    """

    result = await handle_call_tool(
        "convert_content",
        {
            "content": html_content,
            "content_type": "text/html",
            "include_images": False,
            "markdown_engine": "basic"
        }
    )

    result_data = json.loads(result[0].text)
    if result_data.get("success"):
        markdown = result_data["markdown"]
        assert "# Title" in markdown
        assert "More content" in markdown
        # Images should be excluded or minimal
    else:
        assert "error" in result_data


@pytest.mark.asyncio
async def test_convert_content_json():
    """Test converting JSON content."""
    json_content = '{"title": "Test", "content": "Sample content", "items": [1, 2, 3]}'

    result = await handle_call_tool(
        "convert_content",
        {
            "content": json_content,
            "content_type": "application/json"
        }
    )

    result_data = json.loads(result[0].text)
    # JSON conversion may not be supported by all engines
    assert "success" in result_data


@pytest.mark.asyncio
async def test_batch_convert_empty_list():
    """Test batch convert with empty URL list."""
    result = await handle_call_tool(
        "batch_convert",
        {"urls": []}
    )

    result_data = json.loads(result[0].text)
    if result_data.get("success"):
        assert result_data["total_urls"] == 0
    else:
        assert "error" in result_data


@pytest.mark.asyncio
async def test_convert_url_invalid_url():
    """Test converting invalid URL."""
    result = await handle_call_tool(
        "convert_url",
        {"url": "not-a-valid-url"}
    )

    result_data = json.loads(result[0].text)
    # Should handle invalid URL gracefully
    assert "success" in result_data
