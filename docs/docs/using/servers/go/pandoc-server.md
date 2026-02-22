# Pandoc Server

## Overview

The Pandoc MCP Server provides powerful document conversion capabilities using the versatile pandoc tool. This Go-based server enables text conversion between 30+ document formats with support for standalone documents, table of contents generation, and custom metadata. It serves as a bridge between the MCP protocol and pandoc's extensive format conversion capabilities.

### Key Features

- **Convert between 30+ document formats**: Supports markdown, HTML, LaTeX, PDF, DOCX, EPUB, and many more
- **Standalone document generation**: Create complete, self-contained documents
- **Table of contents support**: Automatically generate TOCs for supported formats
- **Custom metadata handling**: Add titles, authors, and other metadata to documents
- **Format discovery tools**: List available input and output formats
- **Health monitoring**: Check pandoc installation and version information

## Quick Start

### Prerequisites

**Pandoc must be installed on the system:**

```bash
# Ubuntu/Debian
sudo apt install pandoc

# macOS
brew install pandoc

# Windows: Download from pandoc.org

# Verify installation
pandoc --version
```

**Go 1.23 or later for building from source.**

### Installation

#### From Source

```bash
# Clone the repository
git clone <repository-url>
cd pandoc-server

# Install dependencies
go mod download

# Build the server
make build
```

#### Using Docker

```bash
# Build the Docker image
docker build -t pandoc-server .

# Run the container
docker run -i pandoc-server
```

### Running the Server

```bash
# Run the built server
./dist/pandoc-server

# Or with ContextForge for HTTP/SSE access
python3 -m mcpgateway.translate --stdio "./dist/pandoc-server" --port 9000
```

## Available Tools

### pandoc
Convert text from one format to another using pandoc.

**Parameters:**

- `from` (required): Input format (e.g., markdown, html, latex, rst, docx, epub)
- `to` (required): Output format (e.g., html, markdown, latex, pdf, docx, plain)
- `input` (required): The text content to convert
- `standalone`: Produce a standalone document (default: false)
- `title`: Document title for standalone documents
- `metadata`: Additional metadata in key=value format
- `toc`: Include table of contents (default: false)

### list-formats
List available pandoc input and output formats.

**Parameters:**

- `type`: Format type to list - 'input', 'output', or 'all' (default: 'all')

### health
Check if pandoc is installed and return version information.

**Returns:**

- Pandoc installation status
- Version information
- Available features and extensions

## Configuration

### MCP Client Configuration

```json
{
  "mcpServers": {
    "pandoc-server": {
      "command": "./dist/pandoc-server"
    }
  }
}
```

### Via ContextForge

```json
{
  "mcpServers": {
    "pandoc-server": {
      "command": "python3",
      "args": ["-m", "mcpgateway.translate", "--stdio", "./dist/pandoc-server", "--port", "9000"]
    }
  }
}
```

## Examples

### Convert Markdown to HTML

```json
{
  "tool": "pandoc",
  "arguments": {
    "from": "markdown",
    "to": "html",
    "input": "# Hello World\n\nThis is **bold** text.",
    "standalone": true,
    "title": "My Document"
  }
}
```

**Response:**
```html
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" lang="" xml:lang="">
<head>
  <meta charset="utf-8" />
  <title>My Document</title>
</head>
<body>
<h1 id="hello-world">Hello World</h1>
<p>This is <strong>bold</strong> text.</p>
</body>
</html>
```

### Convert HTML to Markdown

```json
{
  "tool": "pandoc",
  "arguments": {
    "from": "html",
    "to": "markdown",
    "input": "<h1>Title</h1><p>This is a <em>paragraph</em> with <strong>formatting</strong>.</p>"
  }
}
```

### Create LaTeX Document with TOC

```json
{
  "tool": "pandoc",
  "arguments": {
    "from": "markdown",
    "to": "latex",
    "input": "# Introduction\n\nThis is the introduction.\n\n# Main Content\n\nThis is the main content.\n\n# Conclusion\n\nThis is the conclusion.",
    "standalone": true,
    "title": "Research Paper",
    "toc": true,
    "metadata": "author=John Doe,date=2024-01-15"
  }
}
```

### Convert DOCX to Plain Text

```json
{
  "tool": "pandoc",
  "arguments": {
    "from": "docx",
    "to": "plain",
    "input": "<base64-encoded-docx-content>"
  }
}
```

### List Available Formats

```json
{
  "tool": "list-formats",
  "arguments": {
    "type": "input"
  }
}
```

**Response:**
```json
{
  "success": true,
  "format_type": "input",
  "formats": [
    "markdown",
    "html",
    "latex",
    "rst",
    "docx",
    "epub",
    "json",
    "csv",
    "mediawiki",
    "org"
  ]
}
```

### Check Pandoc Health

```json
{
  "tool": "health",
  "arguments": {}
}
```

**Response:**
```json
{
  "success": true,
  "pandoc_installed": true,
  "version": "2.19.2",
  "features": ["pdf-engine", "lua-filters", "bibliography"],
  "status": "healthy"
}
```

## Integration

### With ContextForge

The Pandoc server integrates seamlessly with ContextForge for HTTP and SSE access:

```bash
# Start pandoc server via ContextForge
python3 -m mcpgateway.translate --stdio "./dist/pandoc-server" --port 9000

# Register with ContextForge
curl -X POST http://localhost:8000/gateways \
  -H "Content-Type: application/json" \
  -d '{
    "name": "pandoc-server",
    "url": "http://localhost:9000",
    "description": "Document conversion server using Pandoc"
  }'
```

### Programmatic Usage

```go
// Example Go client usage
package main

import (
    "context"
    "fmt"
    "log"

    "github.com/your-org/mcp-go-client"
)

func main() {
    client, err := mcp.NewStdioClient("./dist/pandoc-server")
    if err != nil {
        log.Fatal(err)
    }
    defer client.Close()

    // Convert markdown to HTML
    result, err := client.CallTool(context.Background(), "pandoc", map[string]any{
        "from":       "markdown",
        "to":         "html",
        "input":      "# Hello\n\nWorld!",
        "standalone": true,
    })
    if err != nil {
        log.Fatal(err)
    }

    fmt.Println(result)
}
```

## Supported Formats

Pandoc supports numerous input and output formats. Use the `list-formats` tool to see all available formats on your system.

### Common Input Formats

- **markdown**: Pandoc's extended Markdown
- **html**: HTML documents
- **latex**: LaTeX documents
- **rst**: reStructuredText
- **docx**: Microsoft Word documents
- **epub**: EPUB e-books
- **json**: Pandoc JSON format
- **csv**: Comma-separated values
- **mediawiki**: MediaWiki markup
- **org**: Emacs Org mode

### Common Output Formats

- **html**: HTML documents
- **markdown**: Markdown format
- **latex**: LaTeX documents
- **pdf**: PDF documents (requires LaTeX)
- **docx**: Microsoft Word documents
- **epub**: EPUB e-books
- **plain**: Plain text
- **json**: Pandoc JSON format
- **asciidoc**: AsciiDoc format
- **rst**: reStructuredText

## Advanced Features

### Metadata Handling

```json
{
  "tool": "pandoc",
  "arguments": {
    "from": "markdown",
    "to": "html",
    "input": "# Document\n\nContent here.",
    "standalone": true,
    "title": "My Article",
    "metadata": "author=John Doe,date=2024-01-15,keywords=documentation pandoc"
  }
}
```

### Table of Contents Generation

```json
{
  "tool": "pandoc",
  "arguments": {
    "from": "markdown",
    "to": "html",
    "input": "# Chapter 1\n\n## Section 1.1\n\n### Subsection 1.1.1\n\n# Chapter 2\n\n## Section 2.1",
    "standalone": true,
    "toc": true,
    "title": "Technical Manual"
  }
}
```

### Batch Processing

```go
// Example batch conversion
documents := []struct {
    input  string
    format string
}{
    {"# Doc 1\n\nContent 1", "html"},
    {"# Doc 2\n\nContent 2", "latex"},
    {"# Doc 3\n\nContent 3", "docx"},
}

for i, doc := range documents {
    result, err := client.CallTool(context.Background(), "pandoc", map[string]any{
        "from":       "markdown",
        "to":         doc.format,
        "input":      doc.input,
        "standalone": true,
        "title":      fmt.Sprintf("Document %d", i+1),
    })
    if err != nil {
        log.Printf("Error converting doc %d: %v", i+1, err)
        continue
    }

    // Process result...
}
```

## Use Cases

### Documentation Workflows
- Convert Markdown documentation to HTML for web publishing
- Generate PDF versions of documentation from Markdown sources
- Transform reStructuredText to various output formats

### Content Publishing
- Convert blog posts between different markup formats
- Generate e-books (EPUB) from Markdown sources
- Create presentation slides from Markdown

### Academic Writing
- Convert between LaTeX and Word formats for collaboration
- Generate bibliographies and citations
- Create formatted academic papers

### Report Generation
- Convert data reports to multiple output formats
- Generate executive summaries in different formats
- Create standardized document templates

### Migration Projects
- Convert legacy document formats to modern alternatives
- Batch process document archives
- Standardize document formats across organizations

## Error Handling

The server provides comprehensive error handling for:

- **Missing Pandoc Installation**: Clear error messages with installation guidance
- **Unsupported Format Combinations**: Validation of input/output format compatibility
- **Invalid Input Content**: Proper error reporting for malformed documents
- **Conversion Failures**: Detailed pandoc error messages
- **Resource Limits**: Handling of large documents and memory constraints

## Development

### Building from Source

```bash
# Format code
make fmt

# Run tests
make test

# Tidy dependencies
make tidy

# Build binary
make build
```

### Testing

```bash
# Run all tests
make test

# Test specific functionality
go test -v ./...

# Test with coverage
go test -cover ./...
```

### Docker Development

```bash
# Build development image
docker build -t pandoc-server:dev .

# Run tests in container
docker run --rm pandoc-server:dev make test

# Interactive development shell
docker run --rm -it pandoc-server:dev /bin/sh
```

## Performance Considerations

- **Pandoc Startup Overhead**: Each conversion spawns a new pandoc process
- **Large Documents**: Memory usage scales with document size
- **Complex Formats**: PDF generation requires LaTeX installation and is slower
- **Concurrent Requests**: The server can handle multiple simultaneous conversions
- **Caching**: Consider implementing caching for frequently converted content

## Security Considerations

- **Input Validation**: The server validates input formats and content
- **Process Isolation**: Each pandoc conversion runs in a separate process
- **Resource Limits**: Consider implementing timeouts for long-running conversions
- **File System Access**: Pandoc may access local files for includes and templates

## Limitations

- **Format Support**: Available formats depend on pandoc installation and features
- **Binary Content**: Some formats require special handling for binary content
- **Template Dependencies**: Custom templates and includes may require additional setup
- **PDF Generation**: Requires LaTeX installation for PDF output
- **Large Files**: Very large documents may hit memory or processing limits
