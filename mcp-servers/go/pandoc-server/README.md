# Pandoc Server

> Author: Mihai Criveti

An MCP server that provides pandoc document conversion capabilities. This server enables text conversion between various formats using the powerful pandoc tool.

## Features

- Convert between 30+ document formats
- Support for standalone documents
- Table of contents generation
- Custom metadata support
- Format discovery tools

## Tools

### `pandoc`
Convert text from one format to another.

**Parameters:**
- `from` (required): Input format (e.g., markdown, html, latex, rst, docx, epub)
- `to` (required): Output format (e.g., html, markdown, latex, pdf, docx, plain)
- `input` (required): The text to convert
- `standalone` (optional): Produce a standalone document (default: false)
- `title` (optional): Document title for standalone documents
- `metadata` (optional): Additional metadata in key=value format
- `toc` (optional): Include table of contents (default: false)

### `list-formats`
List available pandoc input and output formats.

**Parameters:**
- `type` (optional): Format type to list: 'input', 'output', or 'all' (default: 'all')

### `health`
Check if pandoc is installed and return version information.

## Requirements

- Go 1.23 or later
- Pandoc installed on the system

## Installation

### From Source

```bash
# Clone the repository
git clone <repository-url>
cd pandoc-server

# Install dependencies
go mod download

# Build the server
make build
```

### Using Docker

```bash
# Build the Docker image
docker build -t pandoc-server .

# Run the container
docker run -i pandoc-server
```

## Usage

### Direct Execution

```bash
# Run the built server
./dist/pandoc-server
```

### With ContextForge

```bash
# Use ContextForge's translate module to expose via HTTP/SSE
python3 -m mcpgateway.translate --stdio "./dist/pandoc-server" --port 9000
```

### Testing

```bash
# Run tests
make test

# Format code
make fmt

# Tidy dependencies
make tidy
```

## Example Usage

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

### List Available Formats

```json
{
  "tool": "list-formats",
  "arguments": {
    "type": "input"
  }
}
```

## Supported Formats

Pandoc supports numerous input and output formats. Common ones include:

**Input:** markdown, html, latex, rst, docx, epub, json, csv, mediawiki, org

**Output:** html, markdown, latex, pdf, docx, epub, plain, json, asciidoc, rst

Use the `list-formats` tool to see all available formats on your system.

## Development

Contributions are welcome! Please ensure:

1. Code passes all tests: `make test`
2. Code is properly formatted: `make fmt`
3. Dependencies are tidied: `make tidy`
