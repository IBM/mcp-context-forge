# Plotly MCP Server

> Author: Mihai Criveti

Advanced data visualization server using Plotly for creating interactive charts and graphs. Now powered by **FastMCP** for enhanced type safety and automatic validation!

## Features

- **Multiple Chart Types**: Scatter, line, bar, histogram, box, violin, pie, heatmap
- **Interactive Output**: HTML with full Plotly interactivity
- **Static Export**: PNG, SVG, PDF export capabilities
- **Flexible Data Input**: Support for various data formats and structures
- **Customizable Themes**: Multiple built-in themes and styling options
- **FastMCP Implementation**: Modern decorator-based tools with automatic validation

## Tools

- `create_chart` - Create charts with flexible configuration
- `create_scatter_plot` - Specialized scatter plot creation
- `create_bar_chart` - Bar chart for categorical data
- `create_line_chart` - Line chart for time series data
- `get_supported_charts` - List supported chart types and features

## Requirements

- **Plotly**: For chart generation
  ```bash
  pip install plotly pandas numpy
  ```

- **Kaleido** (optional): For static image export (PNG, SVG, PDF)
  ```bash
  pip install kaleido
  ```

## Installation

```bash
# Install in development mode with Plotly dependencies
make dev-install

# Or install normally
make install
pip install plotly pandas numpy kaleido
```

## Usage

### Running the FastMCP Server

```bash
# Start the server
make dev

# Or directly
python -m plotly_server.server_fastmcp
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
    "plotly-server": {
      "command": "python",
      "args": ["-m", "plotly_server.server_fastmcp"],
      "cwd": "/path/to/plotly_server"
    }
  }
}
```

## Examples

### Create Custom Chart

```python
{
  "name": "create_chart",
  "arguments": {
    "chart_type": "scatter",
    "data": {
      "x": [1, 2, 3, 4, 5],
      "y": [2, 4, 3, 5, 6]
    },
    "title": "Sample Scatter Plot",
    "x_title": "X Axis",
    "y_title": "Y Axis",
    "output_format": "html",
    "theme": "plotly_dark"
  }
}
```

### Create Scatter Plot

```python
{
  "name": "create_scatter_plot",
  "arguments": {
    "x_data": [1.5, 2.3, 3.7, 4.1, 5.9],
    "y_data": [2.1, 4.5, 3.2, 5.8, 6.3],
    "labels": ["Point A", "Point B", "Point C", "Point D", "Point E"],
    "colors": [1, 2, 3, 4, 5],
    "title": "Correlation Analysis",
    "output_format": "png",
    "output_file": "scatter.png"
  }
}
```

### Create Bar Chart

```python
{
  "name": "create_bar_chart",
  "arguments": {
    "categories": ["Q1", "Q2", "Q3", "Q4"],
    "values": [45.2, 38.7, 52.1, 61.4],
    "orientation": "vertical",
    "title": "Quarterly Revenue",
    "output_format": "svg"
  }
}
```

### Create Line Chart

```python
{
  "name": "create_line_chart",
  "arguments": {
    "x_data": ["2024-01", "2024-02", "2024-03", "2024-04", "2024-05"],
    "y_data": [100, 110, 105, 120, 115],
    "line_name": "Monthly Sales",
    "title": "Sales Trend",
    "output_format": "html"
  }
}
```

## Chart Types

- **scatter**: Correlation and distribution analysis
- **line**: Time series and trends
- **bar**: Categorical comparisons
- **histogram**: Distribution of single variable
- **box**: Statistical distribution with quartiles
- **violin**: Distribution shape visualization
- **pie**: Part-to-whole relationships
- **heatmap**: Correlation matrices and 2D data

## Output Formats

- **html**: Interactive HTML with full Plotly functionality
- **png**: Static PNG image (requires kaleido)
- **svg**: Scalable vector graphics (requires kaleido)
- **pdf**: PDF document (requires kaleido)
- **json**: Plotly figure JSON specification

## Themes

- **plotly**: Default Plotly theme
- **plotly_white**: Clean white background
- **plotly_dark**: Dark mode theme
- **ggplot2**: R ggplot2-inspired theme
- **seaborn**: Seaborn-inspired theme
- **simple_white**: Minimal white theme

## FastMCP Advantages

The FastMCP implementation provides:

1. **Type-Safe Parameters**: Automatic validation using Pydantic Field constraints
2. **Pattern Validation**: Ensures valid chart types, formats, and themes
3. **Range Validation**: Width/height constrained with `ge=100, le=2000`
4. **Cleaner Code**: Decorator-based tool definitions (`@mcp.tool`)
5. **Better Error Handling**: Built-in exception management
6. **Automatic Schema Generation**: No manual JSON schema definitions

## Development

```bash
# Format code
make format

# Run tests
make test

# Lint code
make lint
```

## Notes

- Plotly must be installed for chart generation
- Kaleido is required for static image export (PNG, SVG, PDF)
- HTML output includes the full Plotly library for offline viewing
- Base64 encoding is available for images when no output file is specified
- Large datasets may impact performance for complex chart types
