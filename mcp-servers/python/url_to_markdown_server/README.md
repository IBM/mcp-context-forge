# URL-to-Markdown MCP Server

> Author: Mihai Criveti

The ultimate MCP server for retrieving web content and files, then converting them to high-quality markdown format. Supports multiple content types, conversion engines, and processing options.

**Now with FastMCP implementation!** Choose between the original MCP server or the new FastMCP-powered version with enhanced type safety and automatic validation.

## Features

- **Universal Content Retrieval**: Fetch content from any HTTP/HTTPS URL
- **Multi-Format Support**: HTML, PDF, DOCX, PPTX, XLSX, TXT, and more
- **Multiple Conversion Engines**: Choose the best engine for your needs
- **Content Optimization**: Clean, format, and optimize markdown output
- **Batch Processing**: Convert multiple URLs concurrently
- **Image Handling**: Extract and reference images in markdown
- **Metadata Extraction**: Comprehensive document metadata
- **Error Resilience**: Robust error handling and fallback mechanisms

## Tools

- `convert_url` - Convert any URL to markdown with full control over processing
- `convert_content` - Convert raw content (HTML, text) to markdown
- `convert_file` - Convert local files to markdown
- `batch_convert` - Convert multiple URLs concurrently
- `get_capabilities` - List available engines and supported formats

## Installation Options

### Basic Installation
```bash
make install  # Core functionality only (includes FastMCP)
```

### With HTML Engines
```bash
make install-html  # Includes html2text, markdownify, BeautifulSoup, readability
```

### With Document Converters
```bash
make install-docs  # Includes PDF, DOCX, XLSX, PPTX support
```

### Full Installation (Recommended)
```bash
make install-full  # All features enabled, including FastMCP
```

### FastMCP Requirements
The new FastMCP implementation requires:
- `fastmcp>=0.1.0` - Modern MCP framework with decorator-based tools
- All other dependencies remain the same

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

### Conversion Engines

#### HTML-to-Markdown Engines

1. **html2text** (Recommended)
   - Most accurate HTML parsing
   - Excellent link and image handling
   - Configurable output options
   - Best for general web content

2. **markdownify**
   - Clean, minimal output
   - Good for simple HTML
   - Flexible configuration options
   - Fast processing

3. **beautifulsoup** (Custom)
   - Intelligent content extraction
   - Removes navigation and sidebar elements
   - Good for complex websites
   - Custom markdown generation

4. **readability**
   - Extracts main article content
   - Removes ads and navigation
   - Best for news articles and blog posts
   - Clean, focused output

5. **basic** (Fallback)
   - No external dependencies
   - Basic regex-based conversion
   - Always available
   - Limited functionality

#### Content Extraction Methods

- **auto**: Smart selection of best engine for content type
- **readability**: Focus on main article content (removes navigation, ads)
- **raw**: Full page conversion with all elements

## Usage

### Running with FastMCP (Recommended)

#### Stdio Mode (for Claude Desktop, IDEs)
```bash
make dev-fastmcp  # Run FastMCP implementation
```

#### HTTP Mode (via ContextForge)
```bash
make serve-http-fastmcp  # Expose FastMCP server over HTTP
```

### Running Original MCP Implementation

#### Stdio Mode
```bash
make dev  # Run original MCP server
```

#### HTTP Mode
```bash
make serve-http  # Expose original server over HTTP
```

### MCP Client Configuration

#### For FastMCP Server
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
```python
{
  "name": "convert_url",
  "arguments": {
    "url": "https://example.com/article",
    "markdown_engine": "readability",
    "extraction_method": "auto",
    "include_images": true,
    "clean_content": true,
    "timeout": 30
  }
}
```

### Convert Documentation
```python
{
  "name": "convert_url",
  "arguments": {
    "url": "https://docs.python.org/3/library/asyncio.html",
    "markdown_engine": "html2text",
    "include_links": true,
    "include_images": false,
    "clean_content": true
  }
}
```

### Convert PDF Document
```python
{
  "name": "convert_url",
  "arguments": {
    "url": "https://example.com/document.pdf",
    "clean_content": true
  }
}
```

### Batch Convert Multiple URLs
```python
{
  "name": "batch_convert",
  "arguments": {
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
}
```

### Convert Raw HTML Content
```python
{
  "name": "convert_content",
  "arguments": {
    "content": "<html><body><h1>Title</h1><p>Content here</p></body></html>",
    "content_type": "text/html",
    "base_url": "https://example.com",
    "markdown_engine": "html2text"
  }
}
```

### Convert Local File
```python
{
  "name": "convert_file",
  "arguments": {
    "file_path": "./document.pdf",
    "include_images": true,
    "clean_content": true
  }
}
```

## Response Format

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

## Configuration

Environment variables for customization:

```bash
export MARKDOWN_DEFAULT_TIMEOUT=30       # Default request timeout
export MARKDOWN_MAX_TIMEOUT=120          # Maximum allowed timeout
export MARKDOWN_MAX_CONTENT_SIZE=50971520 # Max content size (50MB)
export MARKDOWN_MAX_REDIRECT_HOPS=10     # Max redirect follows
export MARKDOWN_USER_AGENT="Custom-Agent/1.0"  # Custom user agent
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

## Use Cases

### Documentation Conversion
```python
# Convert API documentation
{
  "name": "convert_url",
  "arguments": {
    "url": "https://docs.example.com/api/reference",
    "markdown_engine": "html2text",
    "include_links": true,
    "clean_content": true
  }
}
```

### Research Paper Processing
```python
# Convert academic papers
{
  "name": "convert_url",
  "arguments": {
    "url": "https://arxiv.org/pdf/2301.12345.pdf",
    "clean_content": true
  }
}
```

### News Article Extraction
```python
# Extract clean article content
{
  "name": "convert_url",
  "arguments": {
    "url": "https://news.example.com/article/123",
    "extraction_method": "readability",
    "markdown_engine": "readability",
    "include_images": false
  }
}
```

### Bulk Content Migration
```python
# Convert multiple pages for migration
{
  "name": "batch_convert",
  "arguments": {
    "urls": [
      "https://old-site.com/page1",
      "https://old-site.com/page2",
      "https://old-site.com/page3"
    ],
    "max_concurrent": 5,
    "clean_content": true,
    "timeout": 45
  }
}
```

## Development

```bash
# Format code
make format

# Run tests
make test

# Lint code
make lint

# Install with all features for development
make install-full
```

## Troubleshooting

### Common Issues

1. **Dependencies Missing**: Install appropriate extras (`[html]`, `[documents]`, `[full]`)
2. **Timeout Errors**: Increase timeout value for slow sites
3. **Content Too Large**: Adjust `MARKDOWN_MAX_CONTENT_SIZE`
4. **Poor Quality Output**: Try different engines (readability for articles)
5. **Missing Images**: Enable `include_images` and check image URLs

### Debug Mode

Enable debug logging:
```bash
export LOG_LEVEL=DEBUG
make dev
```

### Engine Selection Guide

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

## FastMCP vs Original Implementation

### Why Choose FastMCP?

The FastMCP implementation provides:

1. **Type-Safe Parameters**: Automatic validation using Pydantic Field constraints
2. **Cleaner Code**: Decorator-based tool definitions (`@mcp.tool`)
3. **Better Error Handling**: Built-in exception management
4. **Automatic Schema Generation**: No manual JSON schema definitions
5. **Modern Async Patterns**: Improved async/await implementation

### Feature Comparison

| Feature | Original MCP | FastMCP |
|---------|-------------|---------|
| Tool Definition | Manual JSON schemas | `@mcp.tool` decorator |
| Parameter Validation | Manual checks | Automatic Pydantic validation |
| Type Hints | Basic | Full typing support |
| Error Handling | Manual try/catch | Built-in error management |
| Schema Generation | Manual | Automatic from type hints |
| Code Structure | Procedural | Object-oriented with decorators |

### Code Example Comparison

#### Original MCP:
```python
@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    return [
        Tool(
            name="convert_url",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "timeout": {"type": "integer"}
                }
            }
        )
    ]
```

#### FastMCP:
```python
@mcp.tool
async def convert_url(
    url: str = Field(..., description="URL to convert"),
    timeout: int = Field(30, le=120, description="Timeout")
) -> Dict[str, Any]:
    # Implementation here
```

## Contributing

When adding new engines or formats:
1. Add converter to appropriate category
2. Update capability detection
3. Add comprehensive tests
4. Document engine characteristics
5. Update README examples
6. Consider implementing in both original and FastMCP versions for compatibility
