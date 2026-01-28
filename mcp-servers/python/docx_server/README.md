# DOCX MCP Server

> Author: Mihai Criveti

A comprehensive MCP server for creating, editing, and analyzing Microsoft Word (.docx) documents. Now powered by **FastMCP** for enhanced type safety and automatic validation!

## Features

- **Document Creation**: Create new DOCX documents with metadata
- **Text Operations**: Add text, headings, and paragraphs
- **Formatting**: Apply fonts, colors, alignment, and styles
- **Tables**: Create and populate tables with data
- **Analysis**: Analyze document structure, formatting, and statistics
- **Text Extraction**: Extract all content from existing documents
- **FastMCP Implementation**: Modern decorator-based tools with automatic validation

## Tools

- `create_document` - Create a new DOCX document
- `add_text` - Add text content to a document
- `add_heading` - Add formatted headings (levels 1-9)
- `format_text` - Apply formatting to text (bold, italic, fonts, etc.)
- `add_table` - Create tables with optional headers and data
- `analyze_document` - Analyze document structure and content
- `extract_text` - Extract all text content from a document

## Installation

```bash
# Install in development mode
make dev-install

# Or install normally
make install
```

## Usage

### Running the FastMCP Server

```bash
# Start the server
make dev

# Or directly
python -m docx_server.server_fastmcp
```

### HTTP Bridge

Expose the server over HTTP for REST API access:

```bash
make serve-http
```

### MCP Client Configuration

```json
{
  "mcpServers": {
    "docx-server": {
      "command": "python",
      "args": ["-m", "docx_server.server_fastmcp"],
      "cwd": "/path/to/docx_server"
    }
  }
}
```

### Test Tools

```bash
# Test tool listing
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | python -m docx_server.server

# Create a document
echo '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"create_document","arguments":{"file_path":"test.docx","title":"Test Document"}}}' | python -m docx_server.server
```

## FastMCP Advantages

The FastMCP implementation provides:

1. **Type-Safe Parameters**: Automatic validation using Pydantic Field constraints
2. **Range Validation**: Ensures heading level is between 1-9 with `ge=1, le=9`
3. **Cleaner Code**: Decorator-based tool definitions (`@mcp.tool`)
4. **Better Error Handling**: Built-in exception management
5. **Automatic Schema Generation**: No manual JSON schema definitions

## Development

```bash
# Format code
make format

# Run tests
make test

# Lint code
make lint
```

## Requirements

- Python 3.11+
- python-docx library for document manipulation
- MCP framework for protocol implementation
