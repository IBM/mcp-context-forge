# DOCX Server

## Overview

The DOCX MCP Server provides comprehensive capabilities for creating, editing, and analyzing Microsoft Word (.docx) documents. It supports document creation with metadata, text operations, formatting, tables, and detailed document analysis. The server is powered by FastMCP for enhanced type safety and automatic validation.

### Key Features

- **Document Creation**: Create new DOCX documents with metadata
- **Text Operations**: Add text, headings, and paragraphs
- **Formatting**: Apply fonts, colors, alignment, and styles
- **Tables**: Create and populate tables with data
- **Analysis**: Analyze document structure, formatting, and statistics
- **Text Extraction**: Extract all content from existing documents
- **FastMCP Implementation**: Modern decorator-based tools with automatic validation

## Quick Start

### Installation

```bash
# Install in development mode
make dev-install

# Or install normally
make install
```

### Prerequisites

- Python 3.11+
- python-docx library for document manipulation
- MCP framework for protocol implementation

### Running the Server

```bash
# Start the FastMCP server
make dev

# Or directly
python -m docx_server.server_fastmcp

# HTTP bridge for REST API access
make serve-http
```

## Available Tools

### create_document
Create a new DOCX document.

**Parameters:**

- `file_path` (required): Path where the document will be saved
- `title`: Document title for metadata
- `author`: Document author
- `subject`: Document subject
- `keywords`: Keywords for the document

### add_text
Add text content to a document.

**Parameters:**

- `file_path` (required): Path to the DOCX document
- `text` (required): Text content to add
- `font_name`: Font family (e.g., "Arial", "Times New Roman")
- `font_size`: Font size in points
- `bold`: Make text bold (boolean)
- `italic`: Make text italic (boolean)
- `color`: Text color in hex format (e.g., "FF0000" for red)

### add_heading
Add formatted headings (levels 1-9).

**Parameters:**

- `file_path` (required): Path to the DOCX document
- `text` (required): Heading text
- `level`: Heading level from 1-9 (default: 1)

### format_text
Apply formatting to text (bold, italic, fonts, etc.).

**Parameters:**

- `file_path` (required): Path to the DOCX document
- `paragraph_index` (required): Index of paragraph to format
- `font_name`: Font family
- `font_size`: Font size in points
- `bold`: Bold formatting (boolean)
- `italic`: Italic formatting (boolean)
- `underline`: Underline formatting (boolean)
- `color`: Text color in hex format
- `alignment`: Text alignment ("left", "center", "right", "justify")

### add_table
Create tables with optional headers and data.

**Parameters:**

- `file_path` (required): Path to the DOCX document
- `rows` (required): Number of rows
- `cols` (required): Number of columns
- `headers`: List of header texts for the first row
- `data`: 2D list of data to populate the table
- `style`: Table style name

### analyze_document
Analyze document structure and content.

**Parameters:**

- `file_path` (required): Path to the DOCX document

**Returns:**

- Document metadata (title, author, creation date)
- Structure information (paragraphs, tables, headings)
- Text statistics (word count, character count)
- Formatting analysis

### extract_text
Extract all text content from a document.

**Parameters:**

- `file_path` (required): Path to the DOCX document
- `include_tables`: Include table content (default: true)
- `preserve_formatting`: Preserve basic formatting markers (default: false)

## Configuration

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

## Examples

### Create a New Document

```json
{
  "file_path": "./report.docx",
  "title": "Monthly Report",
  "author": "John Doe",
  "subject": "Sales Analysis",
  "keywords": "sales, report, monthly"
}
```

### Add Content with Formatting

```json
{
  "file_path": "./report.docx",
  "text": "This is the introduction to our monthly report.",
  "font_name": "Arial",
  "font_size": 12,
  "bold": false,
  "italic": false
}
```

### Add Headings

```json
{
  "file_path": "./report.docx",
  "text": "Executive Summary",
  "level": 1
}
```

### Create a Table

```json
{
  "file_path": "./report.docx",
  "rows": 4,
  "cols": 3,
  "headers": ["Product", "Sales", "Growth"],
  "data": [
    ["Widget A", "$10,000", "5%"],
    ["Widget B", "$15,000", "8%"],
    ["Widget C", "$8,000", "3%"]
  ],
  "style": "Table Grid"
}
```

### Analyze Document Structure

```json
{
  "file_path": "./report.docx"
}
```

**Response:**
```json
{
  "success": true,
  "metadata": {
    "title": "Monthly Report",
    "author": "John Doe",
    "created": "2024-01-15T10:30:00",
    "modified": "2024-01-15T11:45:00"
  },
  "structure": {
    "paragraph_count": 15,
    "table_count": 2,
    "heading_count": 5
  },
  "statistics": {
    "word_count": 1250,
    "character_count": 7830,
    "page_count": 3
  }
}
```

### Extract Text Content

```json
{
  "file_path": "./report.docx",
  "include_tables": true,
  "preserve_formatting": false
}
```

## Integration

### With ContextForge

```bash
# Start the DOCX server via HTTP
make serve-http

# Register with ContextForge
curl -X POST http://localhost:8000/gateways \
  -H "Content-Type: application/json" \
  -d '{
    "name": "docx-server",
    "url": "http://localhost:9000",
    "description": "Microsoft Word document processing server"
  }'
```

### Programmatic Usage

```python
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def create_docx():
    server_params = StdioServerParameters(
        command="python",
        args=["-m", "docx_server.server_fastmcp"]
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Create a new document
            await session.call_tool("create_document", {
                "file_path": "./test.docx",
                "title": "Test Document"
            })

            # Add a heading
            await session.call_tool("add_heading", {
                "file_path": "./test.docx",
                "text": "Introduction",
                "level": 1
            })

            # Add content
            await session.call_tool("add_text", {
                "file_path": "./test.docx",
                "text": "This is a test document created programmatically."
            })

asyncio.run(create_docx())
```

## Document Features

### Supported Formatting Options

- **Fonts**: Arial, Times New Roman, Calibri, and other system fonts
- **Styles**: Bold, italic, underline
- **Colors**: Hex color codes (e.g., "FF0000" for red)
- **Alignment**: Left, center, right, justify
- **Sizes**: Font sizes in points

### Table Capabilities

- **Headers**: Optional header rows with formatting
- **Data Population**: Bulk data insertion from 2D arrays
- **Styling**: Built-in table styles
- **Structure**: Configurable rows and columns

### Metadata Support

- **Core Properties**: Title, author, subject, keywords
- **Timestamps**: Creation and modification dates
- **Statistics**: Word count, character count, page count

## Use Cases

### Report Generation
Create formatted business reports with tables, headings, and styled content.

### Document Template Creation
Build reusable document templates with predefined structure and formatting.

### Data Export
Convert structured data into formatted Word documents for sharing.

### Content Management
Programmatically manage and update existing Word documents.

### Document Analysis
Analyze document structure and extract metadata for content management systems.

## Advanced Features

### Batch Document Processing
Process multiple documents by calling tools in sequence:

```python
documents = ["doc1.docx", "doc2.docx", "doc3.docx"]
for doc in documents:
    # Analyze each document
    result = await session.call_tool("analyze_document", {"file_path": doc})
    # Process results...
```

### Dynamic Content Generation
Generate documents based on data templates:

```python
# Generate report with dynamic data
await session.call_tool("create_document", {"file_path": f"report_{date}.docx"})
await session.call_tool("add_heading", {"text": f"Report for {date}", "level": 1})

for section in report_data:
    await session.call_tool("add_heading", {"text": section["title"], "level": 2})
    await session.call_tool("add_text", {"text": section["content"]})
```

## Error Handling

The server provides comprehensive error handling for:

- **File Access Errors**: Missing files, permission issues
- **Format Errors**: Invalid DOCX files, corrupted documents
- **Parameter Validation**: Invalid formatting options, out-of-range values
- **Content Errors**: Table dimension mismatches, invalid data types
