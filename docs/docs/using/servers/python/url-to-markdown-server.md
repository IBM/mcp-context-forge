# URL to Markdown Server

## Overview

The URL-to-Markdown MCP Server is the ultimate solution for retrieving web content and files, then converting them to high-quality markdown format. It supports multiple content types, conversion engines, and processing options, available in both original MCP and FastMCP implementations with enhanced type safety and automatic validation.

### Key Features

- **Universal Content Retrieval**: Fetch content from any HTTP/HTTPS URL
- **Multi-Format Support**: HTML, PDF, DOCX, PPTX, XLSX, TXT, and more
- **Multiple Conversion Engines**: Choose the best engine for your needs
- **Content Optimization**: Clean, format, and optimize markdown output
- **Batch Processing**: Convert multiple URLs concurrently
- **Image Handling**: Extract and reference images in markdown
- **Metadata Extraction**: Comprehensive document metadata
- **Error Resilience**: Robust error handling and fallback mechanisms

## Quick Start

### Installation Options

```bash
# Basic installation (core functionality only)
make install

# With HTML engines (includes html2text, markdownify, BeautifulSoup, readability)
make install-html

# With document converters (includes PDF, DOCX, XLSX, PPTX support)
make install-docs

# Full installation (recommended - all features enabled)
make install-full
```

### Running the Server

```bash
# FastMCP server (recommended)
make dev-fastmcp

# Original MCP server
make dev

# HTTP bridge for REST API access
make serve-http-fastmcp  # FastMCP version
make serve-http          # Original version
```

## Available Tools

### convert_url
Convert any URL to markdown with full control over processing.

**Parameters:**

- `url` (required): URL to convert to markdown
- `markdown_engine`: Engine to use ("html2text", "markdownify", "beautifulsoup", "readability", "basic")
- `extraction_method`: Content extraction method ("auto", "readability", "raw")
- `include_images`: Include images in markdown (default: true)
- `include_links`: Include links in markdown (default: true)
- `clean_content`: Clean and optimize content (default: true)
- `timeout`: Request timeout in seconds (default: 30, max: 120)

### convert_content
Convert raw content (HTML, text) to markdown.

**Parameters:**

- `content` (required): Raw content to convert
- `content_type` (required): MIME type of content
- `base_url`: Base URL for resolving relative links
- `markdown_engine`: Engine to use for conversion
- `clean_content`: Clean and optimize content (default: true)

### convert_file
Convert local files to markdown.

**Parameters:**

- `file_path` (required): Path to local file
- `markdown_engine`: Engine to use for conversion
- `include_images`: Include images in markdown (default: true)
- `clean_content`: Clean and optimize content (default: true)

### batch_convert
Convert multiple URLs concurrently.

**Parameters:**

- `urls` (required): List of URLs to convert
- `max_concurrent`: Maximum concurrent requests (default: 3, max: 10)
- `markdown_engine`: Engine to use for all conversions
- `include_images`: Include images in markdown (default: false)
- `clean_content`: Clean and optimize content (default: true)
- `timeout`: Request timeout per URL (default: 20)

### get_capabilities
List available engines and supported formats.

**Returns:**

- Available conversion engines and their capabilities
- Supported input and output formats
- Engine recommendations for different content types

## Configuration

### Environment Variables

```bash
export MARKDOWN_DEFAULT_TIMEOUT=30       # Default request timeout
export MARKDOWN_MAX_TIMEOUT=120          # Maximum allowed timeout
export MARKDOWN_MAX_CONTENT_SIZE=50971520 # Max content size (50MB)
export MARKDOWN_MAX_REDIRECT_HOPS=10     # Max redirect follows
export MARKDOWN_USER_AGENT="Custom-Agent/1.0"  # Custom user agent
```

### MCP Client Configuration

#### For FastMCP Server (Recommended)
```json
{
  "mcpServers": {
    "url-to-markdown": {
      "command": "python",
      "args": ["-m", "url_to_markdown_server.server_fastmcp"]
    }
  }
}
```

#### For Original Server
```json
{
  "mcpServers": {
    "url-to-markdown": {
      "command": "python",
      "args": ["-m", "url_to_markdown_server.server"]
    }
  }
}
```

## Examples

### Convert Web Page

```json
{
  "url": "https://example.com/article",
  "markdown_engine": "readability",
  "extraction_method": "auto",
  "include_images": true,
  "clean_content": true,
  "timeout": 30
}
```

### Convert Documentation

```json
{
  "url": "https://docs.python.org/3/library/asyncio.html",
  "markdown_engine": "html2text",
  "include_links": true,
  "include_images": false,
  "clean_content": true
}
```

### Convert PDF Document

```json
{
  "url": "https://example.com/document.pdf",
  "clean_content": true
}
```

### Batch Convert Multiple URLs

```json
{
  "urls": [
    "https://example.com/page1",
    "https://example.com/page2",
    "https://example.com/page3"
  ],
  "max_concurrent": 3,
  "include_images": false,
  "clean_content": true,
  "timeout": 20
}
```

### Convert Raw HTML Content

```json
{
  "content": "<html><body><h1>Title</h1><p>Content here</p></body></html>",
  "content_type": "text/html",
  "base_url": "https://example.com",
  "markdown_engine": "html2text"
}
```

### Convert Local File

```json
{
  "file_path": "./document.pdf",
  "include_images": true,
  "clean_content": true
}
```

## Integration

### With MCP Gateway

```bash
# Start the URL-to-markdown server via HTTP
make serve-http-fastmcp

# Register with MCP Gateway
curl -X POST http://localhost:8000/gateways \
  -H "Content-Type: application/json" \
  -d '{
    "name": "url-to-markdown",
    "url": "http://localhost:9000",
    "description": "Universal content to markdown conversion server"
  }'
```

### Programmatic Usage

```python
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def convert_content():
    server_params = StdioServerParameters(
        command="python",
        args=["-m", "url_to_markdown_server.server_fastmcp"]
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Convert a web page
            result = await session.call_tool("convert_url", {
                "url": "https://example.com/article",
                "markdown_engine": "readability",
                "clean_content": True
            })

            print(result.content[0].text)

asyncio.run(convert_content())
```

## Supported Formats

### Web Content
- **HTML/XHTML**: Full HTML parsing and conversion
- **XML**: Basic XML to markdown conversion
- **JSON**: Structured JSON to markdown

### Document Formats
- **PDF**: Text extraction with PyMuPDF
- **DOCX**: Microsoft Word documents
- **PPTX**: PowerPoint presentations
- **XLSX**: Excel spreadsheets
- **TXT**: Plain text files

## Conversion Engines

### HTML-to-Markdown Engines

#### html2text (Recommended)
- Most accurate HTML parsing
- Excellent link and image handling
- Configurable output options
- Best for general web content

#### markdownify
- Clean, minimal output
- Good for simple HTML
- Flexible configuration options
- Fast processing

#### beautifulsoup (Custom)
- Intelligent content extraction
- Removes navigation and sidebar elements
- Good for complex websites
- Custom markdown generation

#### readability
- Extracts main article content
- Removes ads and navigation
- Best for news articles and blog posts
- Clean, focused output

#### basic (Fallback)
- No external dependencies
- Basic regex-based conversion
- Always available
- Limited functionality

## Response Formats

### Successful Conversion
```json
{
  "success": true,
  "conversion_id": "uuid-here",
  "url": "https://example.com/article",
  "content_type": "text/html",
  "markdown": "# Article Title\n\nThis is the converted content...",
  "length": 1542,
  "engine": "readability",
  "metadata": {
    "original_size": 45123,
    "compression_ratio": 0.034,
    "processing_time": 1234567890
  }
}
```

### Batch Conversion Response
```json
{
  "success": true,
  "batch_id": "uuid-here",
  "total_urls": 3,
  "successful": 2,
  "failed": 1,
  "results": [
    {
      "success": true,
      "url": "https://example.com/page1",
      "markdown": "# Page 1\n\nContent...",
      "engine": "html2text"
    },
    {
      "success": false,
      "url": "https://example.com/page2",
      "error": "HTTP 404: Not Found"
    }
  ]
}
```

### Error Response
```json
{
  "success": false,
  "error": "Request timeout after 30 seconds",
  "conversion_id": "uuid-here"
}
```

## Engine Comparison

| Engine | Quality | Speed | Dependencies | Best For |
|--------|---------|-------|--------------|----------|
| html2text | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | html2text | General web content |
| readability | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | readability-lxml | News articles, blogs |
| markdownify | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | markdownify | Simple HTML |
| beautifulsoup | ⭐⭐⭐ | ⭐⭐⭐ | beautifulsoup4 | Complex sites |
| basic | ⭐⭐ | ⭐⭐⭐⭐⭐ | None | Fallback option |

## Advanced Features

### Content Cleaning
- Removes excessive whitespace
- Fixes heading spacing
- Optimizes list formatting
- Removes empty links
- Standardizes formatting

### Image Processing
- Extracts image URLs
- Resolves relative image paths
- Handles different image formats
- Optional image size filtering

### Link Handling
- Preserves all link types
- Resolves relative URLs
- Maintains link text and structure
- Optional link filtering

### Error Recovery
- Automatic fallback to alternative engines
- Graceful handling of network issues
- Comprehensive error reporting
- Retry mechanisms for transient failures

## Use Cases

### Documentation Conversion
```python
# Convert API documentation
{
  "url": "https://docs.example.com/api/reference",
  "markdown_engine": "html2text",
  "include_links": True,
  "clean_content": True
}
```

### Research Paper Processing
```python
# Convert academic papers
{
  "url": "https://arxiv.org/pdf/2301.12345.pdf",
  "clean_content": True
}
```

### News Article Extraction
```python
# Extract clean article content
{
  "url": "https://news.example.com/article/123",
  "extraction_method": "readability",
  "markdown_engine": "readability",
  "include_images": False
}
```

### Bulk Content Migration
```python
# Convert multiple pages for migration
{
  "urls": [
    "https://old-site.com/page1",
    "https://old-site.com/page2",
    "https://old-site.com/page3"
  ],
  "max_concurrent": 5,
  "clean_content": True,
  "timeout": 45
}
```

## Security Features

- **Input Validation**: URL and content validation
- **Size Limits**: Configurable content size limits
- **Timeout Protection**: Prevents hanging requests
- **User Agent Control**: Configurable user agent strings
- **Redirect Limits**: Prevents redirect loops
- **Content Type Validation**: Verifies expected content types

## Performance Optimizations

- **Concurrent Processing**: Async HTTP with connection pooling
- **Streaming Downloads**: Memory-efficient content retrieval
- **Lazy Loading**: Load engines only when needed
- **Caching**: HTTP response caching where appropriate
- **Batch Processing**: Efficient multi-URL processing

## Engine Selection Guide

- **News/Blog Articles**: Use `readability` engine
- **Technical Documentation**: Use `html2text` engine
- **Simple Web Pages**: Use `markdownify` engine
- **Complex Layouts**: Use `beautifulsoup` engine
- **No Dependencies**: Use `basic` engine

## Limitations

- **JavaScript Content**: Does not execute JavaScript (static content only)
- **Authentication**: No built-in authentication support
- **Rate Limiting**: Implements basic rate limiting only
- **Image Processing**: Images are referenced, not embedded
- **Large Files**: Size limits prevent processing very large documents
