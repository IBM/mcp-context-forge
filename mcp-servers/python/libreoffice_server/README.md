# LibreOffice MCP Server

> Author: Mihai Criveti

A comprehensive MCP server for document conversion using LibreOffice in headless mode. Supports conversion between various document formats including PDF, DOCX, ODT, HTML, and more. Now powered by **FastMCP** for enhanced type safety and automatic validation!

## Features

- **Document Conversion**: Convert between multiple formats (PDF, DOCX, ODT, HTML, TXT, etc.)
- **Batch Processing**: Convert multiple documents at once
- **Text Extraction**: Extract text content from documents
- **Document Merging**: Merge PDF documents (requires pdftk)
- **Document Analysis**: Get document information and metadata
- **Format Support**: Wide range of input and output formats via LibreOffice

## Tools

- `convert_document` - Convert a single document to another format
- `convert_batch` - Convert multiple documents to the same format
- `merge_documents` - Merge multiple documents (PDF merging requires pdftk)
- `extract_text` - Extract text content from documents
- `get_document_info` - Get document metadata and statistics
- `list_supported_formats` - List all supported input/output formats

## Requirements

- **LibreOffice**: Must be installed and accessible via command line
  ```bash
  # Ubuntu/Debian
  sudo apt install libreoffice

  # macOS
  brew install --cask libreoffice

  # Windows: Download from libreoffice.org
  ```

- **Optional**: `pdftk` for PDF merging
  ```bash
  # Ubuntu/Debian
  sudo apt install pdftk

  # macOS
  brew install pdftk-java
  ```

## Installation

```bash
# Install in development mode
make dev-install

# Or install normally
make install
```

## Usage

### Stdio Mode (for Claude Desktop, IDEs)

```bash
make dev
```

### HTTP Mode (via ContextForge)

```bash
make serve-http
```

### Example Commands

```bash
# Convert DOCX to PDF
echo '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"convert_document","arguments":{"input_file":"document.docx","output_format":"pdf","output_dir":"./output"}}}' | python -m libreoffice_server.server_fastmcp

# Batch convert multiple files
echo '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"convert_batch","arguments":{"input_files":["file1.docx","file2.odt"],"output_format":"pdf","output_dir":"./converted"}}}' | python -m libreoffice_server.server_fastmcp

# Extract text from document
echo '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"extract_text","arguments":{"input_file":"document.pdf","output_file":"extracted.txt"}}}' | python -m libreoffice_server.server_fastmcp
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
- **Images**: PNG, JPG, SVG

## Development

```bash
# Format code
make format

# Run tests
make test

# Lint code
make lint
```

## Examples

### Convert Document
```python
{
  "name": "convert_document",
  "arguments": {
    "input_file": "presentation.pptx",
    "output_format": "pdf",
    "output_dir": "./converted",
    "output_filename": "presentation_final.pdf"
  }
}
```

### Batch Conversion
```python
{
  "name": "convert_batch",
  "arguments": {
    "input_files": ["doc1.docx", "doc2.odt", "doc3.rtf"],
    "output_format": "pdf",
    "output_dir": "./batch_output"
  }
}
```

### Text Extraction
```python
{
  "name": "extract_text",
  "arguments": {
    "input_file": "document.pdf",
    "output_file": "extracted_text.txt"
  }
}
```

## FastMCP Implementation

This server leverages the FastMCP framework to provide:

1. **Type-Safe Parameters**: Automatic validation using Pydantic Field constraints
2. **Pattern Validation**: Ensures valid output formats with regex patterns
3. **Cleaner Code**: Decorator-based tool definitions (`@mcp.tool`)
4. **Better Error Handling**: Built-in exception management
5. **Automatic Schema Generation**: No manual JSON schema definitions

## Notes

- LibreOffice conversion quality depends on the LibreOffice version installed
- Some complex formatting may not be preserved during conversion
- PDF merging requires additional tools like `pdftk`
- Large files may take longer to process
