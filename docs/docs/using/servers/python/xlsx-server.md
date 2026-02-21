# XLSX Server

## Overview

The XLSX MCP Server provides comprehensive capabilities for creating, editing, and analyzing Microsoft Excel (.xlsx) spreadsheets. It supports workbook creation with multiple sheets, data operations, cell formatting, formulas, charts, and detailed analysis. The server is powered by FastMCP for enhanced type safety and automatic validation.

### Key Features

- **Workbook Creation**: Create new XLSX workbooks with multiple sheets
- **Data Operations**: Read and write data to/from worksheets
- **Cell Formatting**: Apply fonts, colors, alignment, and styles
- **Formulas**: Add and manage Excel formulas
- **Charts**: Create various chart types (column, bar, line, pie, scatter)
- **Analysis**: Analyze workbook structure, data types, and formulas

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
- openpyxl library for Excel file manipulation
- MCP framework for protocol implementation

### Running the Server

```bash
# Stdio mode (for Claude Desktop, IDEs)
make dev

# HTTP mode (via ContextForge)
make serve-http
```

## Available Tools

### create_workbook
Create a new XLSX workbook with optional sheet names.

**Parameters:**

- `file_path` (required): Path where the workbook will be saved
- `sheet_names`: List of sheet names to create (default: ["Sheet1"])
- `include_default_sheet`: Include default sheet (default: true)

### write_data
Write data to a worksheet with optional headers.

**Parameters:**

- `file_path` (required): Path to XLSX workbook
- `sheet_name` (required): Name of worksheet
- `data` (required): 2D array of data to write
- `headers`: List of column headers
- `start_row`: Starting row number (default: 1)
- `start_col`: Starting column number (default: 1)
- `overwrite`: Overwrite existing data (default: false)

### read_data
Read data from a worksheet or specific range.

**Parameters:**

- `file_path` (required): Path to XLSX workbook
- `sheet_name` (required): Name of worksheet
- `range`: Cell range to read (e.g., "A1:C10")
- `include_headers`: Include first row as headers (default: true)
- `max_rows`: Maximum rows to read
- `max_cols`: Maximum columns to read

### format_cells
Apply formatting to cell ranges.

**Parameters:**

- `file_path` (required): Path to XLSX workbook
- `sheet_name` (required): Name of worksheet
- `range` (required): Cell range to format (e.g., "A1:C10")
- `font_name`: Font family
- `font_size`: Font size
- `bold`: Bold formatting (boolean)
- `italic`: Italic formatting (boolean)
- `color`: Font color in hex format
- `background_color`: Cell background color in hex format
- `alignment`: Text alignment ("left", "center", "right")

### add_formula
Add Excel formulas to cells.

**Parameters:**

- `file_path` (required): Path to XLSX workbook
- `sheet_name` (required): Name of worksheet
- `cell` (required): Cell address (e.g., "A1")
- `formula` (required): Excel formula (e.g., "=SUM(A1:A10)")

### analyze_workbook
Analyze workbook structure and content.

**Parameters:**

- `file_path` (required): Path to XLSX workbook

**Returns:**

- Workbook metadata and structure
- Sheet information and statistics
- Data type analysis
- Formula analysis

### create_chart
Create charts from data ranges.

**Parameters:**

- `file_path` (required): Path to XLSX workbook
- `sheet_name` (required): Name of worksheet
- `chart_type` (required): Chart type ("column", "bar", "line", "pie", "scatter")
- `data_range` (required): Data range for chart
- `chart_title`: Chart title
- `x_axis_title`: X-axis title
- `y_axis_title`: Y-axis title
- `position`: Chart position (cell address)

## Configuration

### MCP Client Configuration

```json
{
  "mcpServers": {
    "xlsx-server": {
      "command": "python",
      "args": ["-m", "xlsx_server.server_fastmcp"],
      "cwd": "/path/to/xlsx_server"
    }
  }
}
```

## Examples

### Create a New Workbook

```json
{
  "file_path": "./report.xlsx",
  "sheet_names": ["Sales", "Summary", "Analysis"],
  "include_default_sheet": false
}
```

### Add Data with Headers

```json
{
  "file_path": "./report.xlsx",
  "sheet_name": "Sales",
  "headers": ["Product", "Q1", "Q2", "Q3", "Q4"],
  "data": [
    ["Widget A", 100, 120, 110, 130],
    ["Widget B", 80, 90, 95, 100],
    ["Widget C", 120, 110, 125, 140]
  ],
  "start_row": 1,
  "start_col": 1
}
```

### Read Data from Worksheet

```json
{
  "file_path": "./report.xlsx",
  "sheet_name": "Sales",
  "range": "A1:E4",
  "include_headers": true
}
```

**Response:**
```json
{
  "success": true,
  "sheet_name": "Sales",
  "range": "A1:E4",
  "headers": ["Product", "Q1", "Q2", "Q3", "Q4"],
  "data": [
    ["Widget A", 100, 120, 110, 130],
    ["Widget B", 80, 90, 95, 100],
    ["Widget C", 120, 110, 125, 140]
  ],
  "row_count": 3,
  "col_count": 5
}
```

### Add Formulas

```json
{
  "file_path": "./report.xlsx",
  "sheet_name": "Sales",
  "cell": "F2",
  "formula": "=SUM(B2:E2)"
}
```

```json
{
  "file_path": "./report.xlsx",
  "sheet_name": "Sales",
  "cell": "F5",
  "formula": "=AVERAGE(F2:F4)"
}
```

### Format Cells

```json
{
  "file_path": "./report.xlsx",
  "sheet_name": "Sales",
  "range": "A1:F1",
  "font_name": "Arial",
  "font_size": 12,
  "bold": true,
  "background_color": "E6E6FA",
  "alignment": "center"
}
```

### Create Chart

```json
{
  "file_path": "./report.xlsx",
  "sheet_name": "Sales",
  "chart_type": "column",
  "data_range": "A1:E4",
  "chart_title": "Quarterly Sales by Product",
  "x_axis_title": "Products",
  "y_axis_title": "Sales ($)",
  "position": "H2"
}
```

### Analyze Workbook

```json
{
  "file_path": "./report.xlsx"
}
```

**Response:**
```json
{
  "success": true,
  "file_info": {
    "filename": "report.xlsx",
    "size": 15423,
    "created": "2024-01-15T10:30:00",
    "modified": "2024-01-15T14:20:00"
  },
  "workbook_info": {
    "sheet_count": 3,
    "sheet_names": ["Sales", "Summary", "Analysis"],
    "active_sheet": "Sales"
  },
  "sheets": [
    {
      "name": "Sales",
      "max_row": 4,
      "max_column": 6,
      "data_range": "A1:F4",
      "has_formulas": true,
      "has_charts": true,
      "formula_count": 4
    }
  ],
  "statistics": {
    "total_cells": 24,
    "filled_cells": 20,
    "formula_cells": 4,
    "chart_count": 1
  }
}
```

## Integration

### With ContextForge

```bash
# Start the XLSX server via HTTP
make serve-http

# Register with ContextForge
curl -X POST http://localhost:8000/gateways \
  -H "Content-Type: application/json" \
  -d '{
    "name": "xlsx-server",
    "url": "http://localhost:9000",
    "description": "Microsoft Excel spreadsheet processing server"
  }'
```

### Programmatic Usage

```python
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def create_excel_report():
    server_params = StdioServerParameters(
        command="python",
        args=["-m", "xlsx_server.server_fastmcp"]
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Create workbook
            await session.call_tool("create_workbook", {
                "file_path": "./monthly_report.xlsx",
                "sheet_names": ["Data", "Charts", "Summary"]
            })

            # Add data
            await session.call_tool("write_data", {
                "file_path": "./monthly_report.xlsx",
                "sheet_name": "Data",
                "headers": ["Month", "Revenue", "Expenses", "Profit"],
                "data": [
                    ["Jan", 10000, 7000, 3000],
                    ["Feb", 12000, 8000, 4000],
                    ["Mar", 11000, 7500, 3500]
                ]
            })

            # Add formulas
            await session.call_tool("add_formula", {
                "file_path": "./monthly_report.xlsx",
                "sheet_name": "Data",
                "cell": "E5",
                "formula": "=SUM(E2:E4)"
            })

            # Format headers
            await session.call_tool("format_cells", {
                "file_path": "./monthly_report.xlsx",
                "sheet_name": "Data",
                "range": "A1:E1",
                "bold": True,
                "background_color": "D3D3D3"
            })

            # Create chart
            await session.call_tool("create_chart", {
                "file_path": "./monthly_report.xlsx",
                "sheet_name": "Charts",
                "chart_type": "column",
                "data_range": "Data!A1:D4",
                "chart_title": "Monthly Financial Performance"
            })

asyncio.run(create_excel_report())
```

## Supported Features

### Data Types
- **Numbers**: Integers, floats, percentages
- **Text**: Strings, formatted text
- **Dates**: Date and time values
- **Formulas**: Excel formulas and functions
- **Boolean**: True/false values

### Formatting Options
- **Fonts**: Font family, size, color
- **Styles**: Bold, italic, underline
- **Colors**: Font and background colors
- **Alignment**: Left, center, right alignment
- **Borders**: Cell borders and styles

### Chart Types
- **Column**: Vertical bar charts
- **Bar**: Horizontal bar charts
- **Line**: Line charts for trends
- **Pie**: Pie charts for proportions
- **Scatter**: Scatter plots for correlations

### Formula Support
- **Basic Functions**: SUM, AVERAGE, COUNT, MAX, MIN
- **Mathematical**: Mathematical operations and functions
- **Logical**: IF, AND, OR functions
- **Text**: Text manipulation functions
- **Date/Time**: Date and time functions

## Advanced Features

### Batch Data Processing

```python
# Process multiple data sets
datasets = [
    {"sheet": "Q1", "data": q1_data},
    {"sheet": "Q2", "data": q2_data},
    {"sheet": "Q3", "data": q3_data},
    {"sheet": "Q4", "data": q4_data}
]

for dataset in datasets:
    await session.call_tool("write_data", {
        "file_path": "./annual_report.xlsx",
        "sheet_name": dataset["sheet"],
        "data": dataset["data"],
        "headers": ["Product", "Sales", "Growth"]
    })
```

### Dynamic Chart Creation

```python
# Create multiple charts based on data
chart_configs = [
    {"type": "column", "range": "A1:C10", "title": "Sales by Product"},
    {"type": "line", "range": "A1:B10", "title": "Growth Trend"},
    {"type": "pie", "range": "A1:B5", "title": "Market Share"}
]

for i, config in enumerate(chart_configs):
    await session.call_tool("create_chart", {
        "file_path": "./dashboard.xlsx",
        "sheet_name": "Charts",
        "chart_type": config["type"],
        "data_range": config["range"],
        "chart_title": config["title"],
        "position": f"A{1 + i * 15}"  # Offset charts vertically
    })
```

### Template-based Report Generation

```python
# Generate reports from templates
async def generate_monthly_report(month_data):
    # Create workbook from template structure
    await session.call_tool("create_workbook", {
        "file_path": f"./report_{month_data['month']}.xlsx",
        "sheet_names": ["Summary", "Details", "Charts"]
    })

    # Add summary data
    await session.call_tool("write_data", {
        "file_path": f"./report_{month_data['month']}.xlsx",
        "sheet_name": "Summary",
        "headers": ["Metric", "Value", "Change"],
        "data": month_data["summary"]
    })

    # Add detailed data
    await session.call_tool("write_data", {
        "file_path": f"./report_{month_data['month']}.xlsx",
        "sheet_name": "Details",
        "headers": month_data["detail_headers"],
        "data": month_data["details"]
    })

    # Add calculated fields
    for formula in month_data["formulas"]:
        await session.call_tool("add_formula", {
            "file_path": f"./report_{month_data['month']}.xlsx",
            "sheet_name": formula["sheet"],
            "cell": formula["cell"],
            "formula": formula["formula"]
        })
```

## Use Cases

### Financial Reporting
Create comprehensive financial reports with calculations, charts, and formatted presentations.

### Data Analysis
Import, analyze, and visualize data from various sources with Excel's powerful calculation capabilities.

### Business Dashboards
Build interactive dashboards with charts, KPIs, and summary statistics.

### Inventory Management
Track inventory levels, calculate reorder points, and generate inventory reports.

### Project Tracking
Monitor project progress, timelines, and resource allocation with Gantt-like charts.

### Sales Reporting
Generate sales reports with performance metrics, trend analysis, and forecasting.

## Error Handling

The server provides comprehensive error handling for:

- **File Access Errors**: Missing files, permission issues
- **Sheet Operations**: Invalid sheet names, non-existent sheets
- **Range Validation**: Invalid cell ranges and addresses
- **Formula Errors**: Invalid Excel formulas and syntax
- **Data Type Errors**: Incompatible data types and formatting
- **Chart Creation**: Invalid chart configurations and data ranges

## Performance Considerations

- **Large Datasets**: Consider chunking large data sets for better performance
- **Formula Calculation**: Complex formulas may require additional processing time
- **Chart Generation**: Multiple charts can increase file size and processing time
- **Memory Usage**: Large workbooks with extensive formatting may consume more memory
