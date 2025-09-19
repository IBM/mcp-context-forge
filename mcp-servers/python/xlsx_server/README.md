# XLSX MCP Server

> Author: Mihai Criveti

A comprehensive MCP server for creating, editing, and analyzing Microsoft Excel (.xlsx) spreadsheets. Now powered by **FastMCP** for enhanced type safety and automatic validation!

## Features

- **Workbook Creation**: Create new XLSX workbooks with multiple sheets
- **Data Operations**: Read and write data to/from worksheets
- **Cell Formatting**: Apply fonts, colors, alignment, and styles
- **Formulas**: Add and manage Excel formulas
- **Charts**: Create various chart types (column, bar, line, pie, scatter)
- **Analysis**: Analyze workbook structure, data types, and formulas

## Tools

- `create_workbook` - Create a new XLSX workbook with optional sheet names
- `write_data` - Write data to a worksheet with optional headers
- `read_data` - Read data from a worksheet or specific range
- `format_cells` - Apply formatting to cell ranges
- `add_formula` - Add Excel formulas to cells
- `analyze_workbook` - Analyze workbook structure and content
- `create_chart` - Create charts from data ranges

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

### HTTP Mode (via MCP Gateway)

```bash
make serve-http
```

### Test Tools

```bash
# Test tool listing
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | python -m xlsx_server.server

# Create a workbook
echo '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"create_workbook","arguments":{"file_path":"test.xlsx","sheet_names":["Data","Analysis"]}}}' | python -m xlsx_server.server
```

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
- openpyxl library for Excel file manipulation
- MCP framework for protocol implementation

## Examples

### Creating a workbook with data

```python
# Create workbook
{"name": "create_workbook", "arguments": {"file_path": "report.xlsx", "sheet_names": ["Sales", "Summary"]}}

# Add data with headers
{"name": "write_data", "arguments": {
    "file_path": "report.xlsx",
    "sheet_name": "Sales",
    "headers": ["Product", "Q1", "Q2", "Q3", "Q4"],
    "data": [
        ["Widget A", 100, 120, 110, 130],
        ["Widget B", 80, 90, 95, 100]
    ]
}}

# Add formulas
{"name": "add_formula", "arguments": {
    "file_path": "report.xlsx",
    "sheet_name": "Sales",
    "cell": "F2",
    "formula": "=SUM(B2:E2)"
}}
```
