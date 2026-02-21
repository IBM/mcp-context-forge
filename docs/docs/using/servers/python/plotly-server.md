# Plotly Server

## Overview

The Plotly MCP Server provides advanced data visualization capabilities using Plotly for creating interactive charts and graphs. It supports multiple chart types, interactive HTML output, static export options, and flexible data input formats. The server is powered by FastMCP for enhanced type safety and automatic validation.

### Key Features

- **Multiple Chart Types**: Scatter, line, bar, histogram, box, violin, pie, heatmap
- **Interactive Output**: HTML with full Plotly interactivity
- **Static Export**: PNG, SVG, PDF export capabilities
- **Flexible Data Input**: Support for various data formats and structures
- **Customizable Themes**: Multiple built-in themes and styling options
- **FastMCP Implementation**: Modern decorator-based tools with automatic validation

## Quick Start

### Prerequisites

**Plotly and dependencies:**

```bash
pip install plotly pandas numpy

# For static image export (optional)
pip install kaleido
```

### Installation

```bash
# Install in development mode with Plotly dependencies
make dev-install

# Or install normally and add dependencies
make install
pip install plotly pandas numpy kaleido
```

### Running the Server

```bash
# Start the FastMCP server
make dev

# Or directly
python -m plotly_server.server_fastmcp

# HTTP bridge for REST API access
make serve-http
```

## Available Tools

### create_chart
Create charts with flexible configuration.

**Parameters:**

- `chart_type` (required): Chart type ("scatter", "line", "bar", "histogram", "box", "violin", "pie", "heatmap")
- `data` (required): Chart data (dictionary with x, y, etc.)
- `title`: Chart title
- `x_title`: X-axis title
- `y_title`: Y-axis title
- `output_format`: Output format ("html", "png", "svg", "pdf", "json") - default: "html"
- `output_file`: Path for output file
- `theme`: Plotly theme - default: "plotly"
- `width`: Chart width in pixels (100-2000, default: 800)
- `height`: Chart height in pixels (100-2000, default: 600)

### create_scatter_plot
Specialized scatter plot creation.

**Parameters:**

- `x_data` (required): X-axis data points
- `y_data` (required): Y-axis data points
- `labels`: Point labels
- `colors`: Color values for points
- `sizes`: Size values for points
- `title`: Plot title
- `x_title`: X-axis title
- `y_title`: Y-axis title
- `output_format`: Output format - default: "html"
- `output_file`: Path for output file

### create_bar_chart
Bar chart for categorical data.

**Parameters:**

- `categories` (required): Category names
- `values` (required): Values for each category
- `orientation`: Bar orientation ("vertical" or "horizontal") - default: "vertical"
- `title`: Chart title
- `output_format`: Output format - default: "html"
- `output_file`: Path for output file

### create_line_chart
Line chart for time series data.

**Parameters:**

- `x_data` (required): X-axis data (typically dates/times)
- `y_data` (required): Y-axis data points
- `line_name`: Name for the line series
- `title`: Chart title
- `x_title`: X-axis title
- `y_title`: Y-axis title
- `output_format`: Output format - default: "html"
- `output_file`: Path for output file

### get_supported_charts
List supported chart types and features.

**Returns:**

- Available chart types
- Supported output formats
- Theme options
- Feature capabilities

## Configuration

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

### Create Custom Scatter Plot

```json
{
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
```

### Create Advanced Scatter Plot

```json
{
  "x_data": [1.5, 2.3, 3.7, 4.1, 5.9],
  "y_data": [2.1, 4.5, 3.2, 5.8, 6.3],
  "labels": ["Point A", "Point B", "Point C", "Point D", "Point E"],
  "colors": [1, 2, 3, 4, 5],
  "sizes": [10, 15, 20, 25, 30],
  "title": "Correlation Analysis",
  "output_format": "png",
  "output_file": "scatter.png"
}
```

### Create Bar Chart

```json
{
  "categories": ["Q1", "Q2", "Q3", "Q4"],
  "values": [45.2, 38.7, 52.1, 61.4],
  "orientation": "vertical",
  "title": "Quarterly Revenue",
  "output_format": "svg"
}
```

### Create Line Chart

```json
{
  "x_data": ["2024-01", "2024-02", "2024-03", "2024-04", "2024-05"],
  "y_data": [100, 110, 105, 120, 115],
  "line_name": "Monthly Sales",
  "title": "Sales Trend",
  "output_format": "html"
}
```

### Create Pie Chart

```json
{
  "chart_type": "pie",
  "data": {
    "labels": ["Product A", "Product B", "Product C", "Product D"],
    "values": [30, 25, 20, 25]
  },
  "title": "Market Share Distribution",
  "output_format": "pdf"
}
```

### Create Heatmap

```json
{
  "chart_type": "heatmap",
  "data": {
    "z": [[1, 20, 30], [20, 1, 60], [30, 60, 1]],
    "x": ["Variable 1", "Variable 2", "Variable 3"],
    "y": ["Variable 1", "Variable 2", "Variable 3"]
  },
  "title": "Correlation Matrix",
  "output_format": "html"
}
```

## Integration

### With ContextForge

```bash
# Start the Plotly server via HTTP
make serve-http

# Register with ContextForge
curl -X POST http://localhost:8000/gateways \
  -H "Content-Type: application/json" \
  -d '{
    "name": "plotly-server",
    "url": "http://localhost:9000",
    "description": "Interactive data visualization server using Plotly"
  }'
```

### Programmatic Usage

```python
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def create_visualization():
    server_params = StdioServerParameters(
        command="python",
        args=["-m", "plotly_server.server_fastmcp"]
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Create a line chart
            result = await session.call_tool("create_line_chart", {
                "x_data": ["Jan", "Feb", "Mar", "Apr", "May"],
                "y_data": [100, 120, 110, 140, 135],
                "title": "Monthly Performance",
                "line_name": "Sales"
            })

            # Create a scatter plot
            scatter_result = await session.call_tool("create_scatter_plot", {
                "x_data": [1, 2, 3, 4, 5],
                "y_data": [2, 4, 3, 5, 6],
                "title": "Data Points"
            })

asyncio.run(create_visualization())
```

## Chart Types and Use Cases

### Scatter Plots
- **Purpose**: Correlation analysis, distribution patterns, outlier detection
- **Best for**: Continuous data relationships, regression analysis
- **Features**: Color coding, size mapping, trend lines

### Line Charts
- **Purpose**: Time series data, trends over time, comparative analysis
- **Best for**: Sequential data, performance tracking, forecasting
- **Features**: Multiple series, annotations, hover information

### Bar Charts
- **Purpose**: Categorical comparisons, ranking, distribution
- **Best for**: Discrete categories, survey results, performance metrics
- **Features**: Horizontal/vertical orientation, grouped bars, stacked bars

### Histograms
- **Purpose**: Distribution analysis, frequency patterns, data exploration
- **Best for**: Understanding data spread, identifying patterns
- **Features**: Configurable bins, overlay distributions

### Box Plots
- **Purpose**: Statistical distribution, outlier detection, comparative analysis
- **Best for**: Understanding quartiles, comparing groups
- **Features**: Quartile display, outlier identification, group comparisons

### Violin Plots
- **Purpose**: Distribution shape, density visualization
- **Best for**: Detailed distribution analysis, comparing densities
- **Features**: Kernel density estimation, quartile overlays

### Pie Charts
- **Purpose**: Part-to-whole relationships, percentage breakdowns
- **Best for**: Composition analysis, market share visualization
- **Features**: Interactive slicing, percentage labels

### Heatmaps
- **Purpose**: Correlation matrices, 2D data visualization, pattern recognition
- **Best for**: Large datasets, correlation analysis, intensity mapping
- **Features**: Color scales, annotations, hierarchical clustering

## Output Formats

### Interactive HTML
- **Features**: Full Plotly interactivity, zoom, pan, hover
- **Use cases**: Web embedding, interactive reports, data exploration
- **Benefits**: No additional software required, responsive design

### Static Images (PNG)
- **Features**: High-quality raster images
- **Use cases**: Documents, presentations, print materials
- **Requirements**: Kaleido package for export

### Vector Graphics (SVG)
- **Features**: Scalable vector format, crisp at any size
- **Use cases**: Publication-quality graphics, web graphics
- **Benefits**: Small file size, infinite scalability

### PDF Documents
- **Features**: Publication-ready format
- **Use cases**: Reports, academic papers, professional documents
- **Benefits**: Universal compatibility, print-ready

### JSON Data
- **Features**: Plotly figure specification
- **Use cases**: Data interchange, custom processing, archival
- **Benefits**: Full configuration preservation, programmatic access

## Themes and Styling

### Available Themes

- **plotly**: Default Plotly theme
- **plotly_white**: Clean white background
- **plotly_dark**: Dark mode theme
- **ggplot2**: R ggplot2-inspired theme
- **seaborn**: Seaborn-inspired theme
- **simple_white**: Minimal white theme

### Custom Styling

```json
{
  "chart_type": "scatter",
  "data": {"x": [1, 2, 3], "y": [1, 4, 9]},
  "title": "Custom Styled Chart",
  "theme": "plotly_dark",
  "width": 1200,
  "height": 800
}
```

## Advanced Features

### Multi-Series Charts

```python
# Create complex multi-series line chart
await session.call_tool("create_chart", {
    "chart_type": "line",
    "data": {
        "x": ["Jan", "Feb", "Mar", "Apr", "May"],
        "y1": [100, 120, 110, 140, 135],  # Series 1
        "y2": [80, 90, 95, 100, 105],     # Series 2
        "y3": [60, 70, 65, 80, 85]       # Series 3
    },
    "title": "Multi-Series Performance Comparison"
})
```

### Dashboard Creation

```python
# Create multiple related charts for a dashboard
charts = [
    {
        "type": "bar",
        "data": {"categories": ["A", "B", "C"], "values": [10, 20, 15]},
        "title": "Category Performance"
    },
    {
        "type": "pie",
        "data": {"labels": ["X", "Y", "Z"], "values": [30, 40, 30]},
        "title": "Distribution"
    },
    {
        "type": "line",
        "data": {"x": [1, 2, 3, 4], "y": [1, 4, 2, 5]},
        "title": "Trend Analysis"
    }
]

for i, chart_config in enumerate(charts):
    await session.call_tool("create_chart", {
        **chart_config,
        "output_file": f"dashboard_chart_{i}.html"
    })
```

### Statistical Visualizations

```python
# Create box plot for statistical analysis
await session.call_tool("create_chart", {
    "chart_type": "box",
    "data": {
        "y": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 15],  # Data with outlier
        "name": "Dataset A"
    },
    "title": "Statistical Distribution Analysis"
})

# Create violin plot for distribution comparison
await session.call_tool("create_chart", {
    "chart_type": "violin",
    "data": {
        "y": [1, 2, 2, 3, 3, 3, 4, 4, 5],
        "name": "Distribution Shape"
    },
    "title": "Distribution Density Analysis"
})
```

## Use Cases

### Business Intelligence
- Sales performance dashboards
- Financial reporting charts
- KPI tracking visualizations

### Scientific Research
- Experimental data analysis
- Statistical distributions
- Correlation studies

### Data Exploration
- Dataset profiling
- Outlier detection
- Pattern recognition

### Reporting and Presentations
- Executive summaries
- Progress reports
- Comparative analysis

### Web Applications
- Interactive dashboards
- Real-time monitoring
- User analytics

## Performance Considerations

- Plotly must be installed for chart generation
- Kaleido is required for static image export (PNG, SVG, PDF)
- HTML output includes the full Plotly library for offline viewing
- Large datasets may impact performance for complex chart types
- Interactive features work best in HTML format

## Error Handling

The server provides comprehensive error handling for:

- **Missing Dependencies**: Clear guidance for installing Plotly and Kaleido
- **Data Format Errors**: Validation of input data structures
- **Chart Type Validation**: Ensuring valid chart type and parameter combinations
- **Export Failures**: Handling issues with static image generation
- **Resource Limits**: Managing large datasets and memory constraints
