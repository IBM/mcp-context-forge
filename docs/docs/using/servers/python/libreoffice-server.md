# LibreOffice Server

## Overview

The LibreOffice MCP Server provides comprehensive document conversion capabilities using LibreOffice in headless mode. It supports conversion between various document formats including PDF, DOCX, ODT, HTML, and more, with batch processing, text extraction, and document merging capabilities.

### Key Features

- **Document Conversion**: Convert between multiple formats (PDF, DOCX, ODT, HTML, TXT, etc.)
- **Batch Processing**: Convert multiple documents at once
- **Text Extraction**: Extract text content from documents
- **Document Merging**: Merge PDF documents (requires pdftk)
- **Document Analysis**: Get document information and metadata
- **Format Support**: Wide range of input and output formats via LibreOffice

## Quick Start

### Prerequisites

**LibreOffice must be installed:**

```bash
# Ubuntu/Debian
sudo apt install libreoffice

# macOS
brew install --cask libreoffice

# Windows: Download from libreoffice.org
```

**Optional - for PDF merging:**

```bash
# Ubuntu/Debian
sudo apt install pdftk

# macOS
brew install pdftk-java
```

### Installation

```bash
# Install in development mode
make dev-install

# Or install normally
make install
```

### Running the Server

```bash
# Stdio mode (for Claude Desktop, IDEs)
make dev

# HTTP mode (via ContextForge)
make serve-http
```

## Available Tools

### convert_document
Convert a single document to another format.

**Parameters:**

- `input_file` (required): Path to input document
- `output_format` (required): Target format (pdf, docx, odt, html, txt, etc.)
- `output_dir`: Output directory (default: same as input file)
- `output_filename`: Custom output filename

### convert_batch
Convert multiple documents to the same format.

**Parameters:**

- `input_files` (required): List of input file paths
- `output_format` (required): Target format for all files
- `output_dir`: Output directory (default: "./converted")

### merge_documents
Merge multiple documents (PDF merging requires pdftk).

**Parameters:**

- `input_files` (required): List of document paths to merge
- `output_file` (required): Path for merged document
- `format`: Output format (default: "pdf")

### extract_text
Extract text content from documents.

**Parameters:**

- `input_file` (required): Path to input document
- `output_file`: Path for extracted text file
- `preserve_formatting`: Keep basic formatting (default: false)

### get_document_info
Get document metadata and statistics.

**Parameters:**

- `input_file` (required): Path to document

### list_supported_formats
List all supported input/output formats.

**Returns:**

- Available input formats
- Available output formats
- Format descriptions and capabilities

## Configuration

### MCP Client Configuration

```json
{
  "mcpServers": {
    "libreoffice-server": {
      "command": "python",
      "args": ["-m", "libreoffice_server.server_fastmcp"],
      "cwd": "/path/to/libreoffice_server"
    }
  }
}
```

## Examples

### Convert DOCX to PDF

```json
{
  "input_file": "presentation.docx",
  "output_format": "pdf",
  "output_dir": "./converted",
  "output_filename": "presentation_final.pdf"
}
```

### Batch Convert Multiple Documents

```json
{
  "input_files": ["doc1.docx", "doc2.odt", "doc3.rtf"],
  "output_format": "pdf",
  "output_dir": "./batch_output"
}
```

### Extract Text from PDF

```json
{
  "input_file": "document.pdf",
  "output_file": "extracted_text.txt",
  "preserve_formatting": true
}
```

### Merge PDF Documents

```json
{
  "input_files": ["chapter1.pdf", "chapter2.pdf", "chapter3.pdf"],
  "output_file": "complete_book.pdf",
  "format": "pdf"
}
```

### Get Document Information

```json
{
  "input_file": "./report.docx"
}
```

**Response:**
```json
{
  "success": true,
  "file_info": {
    "filename": "report.docx",
    "size": 245760,
    "format": "Microsoft Word Document",
    "created": "2024-01-15T10:30:00",
    "modified": "2024-01-15T14:20:00"
  },
  "document_info": {
    "title": "Monthly Report",
    "author": "John Doe",
    "subject": "Sales Analysis",
    "page_count": 12,
    "word_count": 2350
  },
  "conversion_capabilities": ["pdf", "odt", "html", "txt", "rtf"]
}
```

### List Supported Formats

```json
{}
```

**Response:**
```json
{
  "success": true,
  "input_formats": [
    {"extension": "docx", "description": "Microsoft Word Document"},
    {"extension": "odt", "description": "OpenDocument Text"},
    {"extension": "pdf", "description": "Portable Document Format"},
    {"extension": "html", "description": "HyperText Markup Language"}
  ],
  "output_formats": [
    {"extension": "pdf", "description": "Portable Document Format"},
    {"extension": "docx", "description": "Microsoft Word Document"},
    {"extension": "odt", "description": "OpenDocument Text"},
    {"extension": "html", "description": "HyperText Markup Language"}
  ]
}
```

## Integration

### With ContextForge

```bash
# Start the LibreOffice server via HTTP
make serve-http

# Register with ContextForge
curl -X POST http://localhost:8000/gateways \
  -H "Content-Type: application/json" \
  -d '{
    "name": "libreoffice-server",
    "url": "http://localhost:9000",
    "description": "Document conversion server using LibreOffice"
  }'
```

### Programmatic Usage

```python
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def convert_documents():
    server_params = StdioServerParameters(
        command="python",
        args=["-m", "libreoffice_server.server_fastmcp"]
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Convert single document
            result = await session.call_tool("convert_document", {
                "input_file": "./document.docx",
                "output_format": "pdf",
                "output_dir": "./converted"
            })

            # Batch convert
            batch_result = await session.call_tool("convert_batch", {
                "input_files": ["file1.docx", "file2.odt"],
                "output_format": "pdf",
                "output_dir": "./batch_converted"
            })

asyncio.run(convert_documents())
```

## Supported Formats

### Input Formats

- **Documents**: DOC, DOCX, ODT, RTF, TXT, HTML, HTM, PDF
- **Spreadsheets**: XLS, XLSX, ODS, CSV
- **Presentations**: PPT, PPTX, ODP

### Output Formats

- **Documents**: PDF, DOCX, ODT, HTML, TXT, RTF
- **Spreadsheets**: XLSX, ODS, CSV
- **Presentations**: PPTX, ODP
- **Images**: PNG, JPG, SVG (for presentations)

## Advanced Features

### Batch Processing with Custom Output

```python
# Convert multiple files with custom naming
files_to_convert = [
    {"input": "report_q1.docx", "output_name": "Q1_Report_Final.pdf"},
    {"input": "report_q2.docx", "output_name": "Q2_Report_Final.pdf"},
    {"input": "report_q3.docx", "output_name": "Q3_Report_Final.pdf"}
]

for file_info in files_to_convert:
    await session.call_tool("convert_document", {
        "input_file": file_info["input"],
        "output_format": "pdf",
        "output_filename": file_info["output_name"]
    })
```

### Document Pipeline Processing

```python
# Multi-step document processing
async def process_document_pipeline(input_file):
    # Step 1: Get document info
    info = await session.call_tool("get_document_info", {
        "input_file": input_file
    })

    # Step 2: Extract text for analysis
    await session.call_tool("extract_text", {
        "input_file": input_file,
        "output_file": f"{input_file}_text.txt"
    })

    # Step 3: Convert to PDF for archival
    await session.call_tool("convert_document", {
        "input_file": input_file,
        "output_format": "pdf",
        "output_dir": "./archive"
    })

    # Step 4: Convert to HTML for web display
    await session.call_tool("convert_document", {
        "input_file": input_file,
        "output_format": "html",
        "output_dir": "./web"
    })
```

### Document Merging Workflow

```python
# Merge multiple documents into a single PDF
chapters = ["intro.docx", "chapter1.docx", "chapter2.docx", "conclusion.docx"]

# First convert all to PDF
pdf_files = []
for chapter in chapters:
    result = await session.call_tool("convert_document", {
        "input_file": chapter,
        "output_format": "pdf",
        "output_dir": "./temp_pdfs"
    })
    pdf_files.append(f"./temp_pdfs/{chapter.replace('.docx', '.pdf')}")

# Then merge all PDFs
await session.call_tool("merge_documents", {
    "input_files": pdf_files,
    "output_file": "./final_book.pdf"
})
```

## Use Cases

### Document Workflow Automation
- Convert incoming documents to standardized formats
- Batch process document archives
- Create PDF versions for legal compliance

### Content Management Systems
- Convert user uploads to web-friendly formats
- Generate multiple format versions for different platforms
- Extract text for search indexing

### Publishing Workflows
- Convert manuscripts between formats
- Generate print and digital versions
- Merge chapters into complete publications

### Business Process Automation
- Convert reports to PDF for distribution
- Extract data from documents for processing
- Standardize document formats across organization

### Digital Archive Management
- Convert legacy documents to modern formats
- Create searchable text versions
- Generate preservation-quality PDFs

## Performance Considerations

- LibreOffice startup overhead affects single conversions
- Batch processing is more efficient for multiple files
- Large documents may require increased timeout values
- Complex formatting may not be perfectly preserved

## Error Handling

The server provides comprehensive error handling for:

- **LibreOffice Installation**: Detection and guidance for missing LibreOffice
- **Format Support**: Clear messages for unsupported format combinations
- **File Access**: Permission and file existence errors
- **Conversion Failures**: Detailed error messages from LibreOffice
- **Resource Limits**: Handling of large files and memory constraints

## Limitations

- LibreOffice conversion quality depends on the version installed
- Some complex formatting may not be preserved during conversion
- PDF merging requires additional tools like `pdftk`
- Large files may take longer to process
- Some proprietary formats may have limited support
