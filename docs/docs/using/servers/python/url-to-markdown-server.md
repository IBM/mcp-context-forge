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
export MARKDOWN_SSRF_PROTECTION_ENABLED=true   # Block private/internal network destinations (default: true)
export MARKDOWN_ALLOWED_HOSTS=""               # Comma-separated allowlist (exact host or *.suffix); empty = no allowlist restriction
export MARKDOWN_BLOCKED_NETWORKS=""            # Extra comma-separated CIDRs to block
export MARKDOWN_ALLOW_PRIVATE_NETWORKS=false   # Dev-only: allow RFC1918 destinations
export MARKDOWN_ALLOW_LOCALHOST=false          # Dev-only: allow loopback destinations
export MARKDOWN_DNS_TIMEOUT=10                 # Max seconds to wait for hostname resolution
export MARKDOWN_DNS_RESOLVER_THREADS=16        # Size of the dedicated DNS resolver thread pool; also bounds concurrent lookup admission
export MARKDOWN_ALLOW_UNSAFE_PROXY_PINNING=false  # Dev/ops-only: route matched destinations through a configured egress proxy, unpinned
```

#### Egress proxies

The standard `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, and `NO_PROXY` variables are
honored, per-destination, exactly as HTTPX itself would route them - the session always
mounts the configured proxy so its routing reflects the operator's configuration. But by
default, a request to a destination that matches the proxy is **refused outright, before
any connection to either the proxy or the destination**. A proxy-routed request's socket
is opened to the proxy, which resolves the real destination itself, so the address
validated by the SSRF guard cannot be enforced end to end on that path; falling back to
a direct connection instead would silently bypass whatever egress policy (audit logging,
DLP, destination allowlisting) the operator configured the proxy to enforce, which is
its own kind of control bypass distinct from the DNS-rebinding risk pinning addresses.

Operators who need an egress proxy and accept the pinning trade-off can opt in with
`MARKDOWN_ALLOW_UNSAFE_PROXY_PINNING=true`. Once set, matching destinations are routed
through the proxy instead of being refused, with a warning logged since connect-time IP
pinning is not applied on that path. `NO_PROXY`-excluded destinations, and any
destination that doesn't match a configured proxy, keep IP pinning regardless - opting
in for some traffic never weakens pinning for traffic that bypasses the proxy. Every
other SSRF control (scheme allowlist, host allowlist, resolved-IP deny rules, and
per-hop redirect re-validation) still applies everywhere, with or without this flag.

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

### With ContextForge

```bash
# Start the URL-to-markdown server via HTTP
make serve-http-fastmcp

# Register with ContextForge
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

- **SSRF Protection**: Blocks private, loopback, link-local, unspecified, multicast, reserved,
  and carrier-grade-NAT (100.64.0.0/10) destinations by default; validates every redirect hop,
  not just the initial request; resolves DNS and pins the outbound connection to the validated
  IP to close the DNS-rebinding gap. See Environment Variables below to configure.
- **Scheme Allowlist**: Only `http`/`https` targets are fetched.
- **Streaming Size Limits**: Content is streamed and aborted as soon as it exceeds the
  configured maximum — never fully buffered before the limit is enforced.
- **Timeout Protection**: Prevents hanging requests.
- **Redirect Limits**: Bounded, re-validated redirect chain (no unchecked hop can reach a
  blocked destination).
- **User Agent Control**: Configurable user agent strings

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
