#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/plotly_server/src/plotly_server/server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Plotly MCP Server

Advanced data visualization server using Plotly for creating interactive charts and graphs.
Supports multiple chart types, data formats, and export options.
"""

import asyncio
import json
import logging
import sys
from typing import Any, Dict, List, Optional, Sequence, Union
from uuid import uuid4

from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.types import EmbeddedResource, ImageContent, TextContent, Tool
from pydantic import BaseModel, Field

# Configure logging to stderr to avoid MCP protocol interference
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger(__name__)

# Create server instance
server = Server("plotly-server")


class CreateChartRequest(BaseModel):
    """Request to create a chart."""
    chart_type: str = Field(..., description="Type of chart to create")
    data: Dict[str, List[Union[str, int, float]]] = Field(..., description="Chart data")
    title: Optional[str] = Field(None, description="Chart title")
    x_title: Optional[str] = Field(None, description="X-axis title")
    y_title: Optional[str] = Field(None, description="Y-axis title")
    output_format: str = Field("html", description="Output format (html, png, svg, pdf)")
    output_file: Optional[str] = Field(None, description="Output file path")
    width: int = Field(800, description="Chart width", ge=100, le=2000)
    height: int = Field(600, description="Chart height", ge=100, le=2000)
    theme: str = Field("plotly", description="Chart theme")


class ScatterPlotRequest(BaseModel):
    """Request to create scatter plot."""
    x_data: List[Union[int, float]] = Field(..., description="X-axis data")
    y_data: List[Union[int, float]] = Field(..., description="Y-axis data")
    labels: Optional[List[str]] = Field(None, description="Data point labels")
    colors: Optional[List[Union[str, int, float]]] = Field(None, description="Color data for points")
    title: Optional[str] = Field(None, description="Chart title")
    output_format: str = Field("html", description="Output format")
    output_file: Optional[str] = Field(None, description="Output file path")


class BarChartRequest(BaseModel):
    """Request to create bar chart."""
    categories: List[str] = Field(..., description="Category names")
    values: List[Union[int, float]] = Field(..., description="Values for each category")
    orientation: str = Field("vertical", description="Bar orientation (vertical/horizontal)")
    title: Optional[str] = Field(None, description="Chart title")
    output_format: str = Field("html", description="Output format")
    output_file: Optional[str] = Field(None, description="Output file path")


class LineChartRequest(BaseModel):
    """Request to create line chart."""
    x_data: List[Union[str, int, float]] = Field(..., description="X-axis data")
    y_data: List[Union[int, float]] = Field(..., description="Y-axis data")
    line_name: Optional[str] = Field(None, description="Line series name")
    title: Optional[str] = Field(None, description="Chart title")
    output_format: str = Field("html", description="Output format")
    output_file: Optional[str] = Field(None, description="Output file path")


class PlotlyVisualizer:
    """Plotly visualization handler."""

    def __init__(self):
        """Initialize the visualizer."""
        self.plotly_available = self._check_plotly()

    def _check_plotly(self) -> bool:
        """Check if Plotly is available."""
        try:
            import plotly.graph_objects as go
            import plotly.express as px
            return True
        except ImportError:
            logger.warning("Plotly not available")
            return False

    def create_scatter_plot(
        self,
        x_data: List[Union[int, float]],
        y_data: List[Union[int, float]],
        labels: Optional[List[str]] = None,
        colors: Optional[List[Union[str, int, float]]] = None,
        title: Optional[str] = None,
        output_format: str = "html",
        output_file: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create scatter plot."""
        if not self.plotly_available:
            return {"success": False, "error": "Plotly not available"}

        try:
            import plotly.graph_objects as go

            # Create scatter plot
            scatter = go.Scatter(
                x=x_data,
                y=y_data,
                mode='markers',
                text=labels,
                marker=dict(
                    color=colors if colors else 'blue',
                    size=8,
                    line=dict(width=1, color='DarkSlateGrey')
                ),
                name='Data Points'
            )

            fig = go.Figure(data=[scatter])

            if title:
                fig.update_layout(title=title)

            return self._export_figure(fig, output_format, output_file, "scatter_plot")

        except Exception as e:
            logger.error(f"Error creating scatter plot: {e}")
            return {"success": False, "error": str(e)}

    def create_bar_chart(
        self,
        categories: List[str],
        values: List[Union[int, float]],
        orientation: str = "vertical",
        title: Optional[str] = None,
        output_format: str = "html",
        output_file: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create bar chart."""
        if not self.plotly_available:
            return {"success": False, "error": "Plotly not available"}

        try:
            import plotly.graph_objects as go

            if orientation == "horizontal":
                bar = go.Bar(y=categories, x=values, orientation='h')
            else:
                bar = go.Bar(x=categories, y=values)

            fig = go.Figure(data=[bar])

            if title:
                fig.update_layout(title=title)

            return self._export_figure(fig, output_format, output_file, "bar_chart")

        except Exception as e:
            logger.error(f"Error creating bar chart: {e}")
            return {"success": False, "error": str(e)}

    def create_line_chart(
        self,
        x_data: List[Union[str, int, float]],
        y_data: List[Union[int, float]],
        line_name: Optional[str] = None,
        title: Optional[str] = None,
        output_format: str = "html",
        output_file: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create line chart."""
        if not self.plotly_available:
            return {"success": False, "error": "Plotly not available"}

        try:
            import plotly.graph_objects as go

            line = go.Scatter(
                x=x_data,
                y=y_data,
                mode='lines+markers',
                name=line_name or 'Data',
                line=dict(width=2)
            )

            fig = go.Figure(data=[line])

            if title:
                fig.update_layout(title=title)

            return self._export_figure(fig, output_format, output_file, "line_chart")

        except Exception as e:
            logger.error(f"Error creating line chart: {e}")
            return {"success": False, "error": str(e)}

    def create_custom_chart(
        self,
        chart_type: str,
        data: Dict[str, List[Union[str, int, float]]],
        title: Optional[str] = None,
        x_title: Optional[str] = None,
        y_title: Optional[str] = None,
        output_format: str = "html",
        output_file: Optional[str] = None,
        width: int = 800,
        height: int = 600,
        theme: str = "plotly"
    ) -> Dict[str, Any]:
        """Create custom chart with flexible configuration."""
        if not self.plotly_available:
            return {"success": False, "error": "Plotly not available"}

        try:
            import plotly.express as px
            import pandas as pd

            # Convert data to DataFrame
            df = pd.DataFrame(data)

            # Create chart based on type
            if chart_type == "scatter":
                fig = px.scatter(df, x=df.columns[0], y=df.columns[1], title=title)
            elif chart_type == "line":
                fig = px.line(df, x=df.columns[0], y=df.columns[1], title=title)
            elif chart_type == "bar":
                fig = px.bar(df, x=df.columns[0], y=df.columns[1], title=title)
            elif chart_type == "histogram":
                fig = px.histogram(df, x=df.columns[0], title=title)
            elif chart_type == "box":
                fig = px.box(df, y=df.columns[0], title=title)
            elif chart_type == "violin":
                fig = px.violin(df, y=df.columns[0], title=title)
            elif chart_type == "pie":
                fig = px.pie(df, values=df.columns[1], names=df.columns[0], title=title)
            elif chart_type == "heatmap":
                fig = px.imshow(df.select_dtypes(include=['number']), title=title)
            else:
                return {"success": False, "error": f"Unsupported chart type: {chart_type}"}

            # Update layout
            fig.update_layout(
                width=width,
                height=height,
                template=theme,
                xaxis_title=x_title,
                yaxis_title=y_title
            )

            return self._export_figure(fig, output_format, output_file, chart_type)

        except Exception as e:
            logger.error(f"Error creating {chart_type} chart: {e}")
            return {"success": False, "error": str(e)}

    def _export_figure(self, fig, output_format: str, output_file: Optional[str], chart_name: str) -> Dict[str, Any]:
        """Export figure in specified format."""
        try:
            if output_format == "html":
                html_content = fig.to_html(include_plotlyjs=True)
                if output_file:
                    with open(output_file, 'w') as f:
                        f.write(html_content)
                return {
                    "success": True,
                    "chart_type": chart_name,
                    "output_format": output_format,
                    "output_file": output_file,
                    "html_content": html_content[:5000] + "..." if len(html_content) > 5000 else html_content
                }

            elif output_format in ["png", "svg", "pdf"]:
                if output_file:
                    fig.write_image(output_file, format=output_format)
                    return {
                        "success": True,
                        "chart_type": chart_name,
                        "output_format": output_format,
                        "output_file": output_file,
                        "message": f"Chart exported to {output_file}"
                    }
                else:
                    # Return base64 encoded image
                    import io
                    import base64

                    img_bytes = fig.to_image(format=output_format)
                    img_base64 = base64.b64encode(img_bytes).decode()

                    return {
                        "success": True,
                        "chart_type": chart_name,
                        "output_format": output_format,
                        "image_base64": img_base64,
                        "message": "Chart generated as base64 image"
                    }

            elif output_format == "json":
                chart_json = fig.to_json()
                if output_file:
                    with open(output_file, 'w') as f:
                        f.write(chart_json)
                return {
                    "success": True,
                    "chart_type": chart_name,
                    "output_format": output_format,
                    "output_file": output_file,
                    "chart_json": json.loads(chart_json)
                }

            else:
                return {"success": False, "error": f"Unsupported output format: {output_format}"}

        except Exception as e:
            logger.error(f"Error exporting figure: {e}")
            return {"success": False, "error": f"Export failed: {str(e)}"}

    def get_supported_charts(self) -> Dict[str, Any]:
        """Get list of supported chart types."""
        return {
            "chart_types": {
                "scatter": {"description": "Scatter plot for correlation analysis", "required_columns": 2},
                "line": {"description": "Line chart for trends over time", "required_columns": 2},
                "bar": {"description": "Bar chart for categorical data", "required_columns": 2},
                "histogram": {"description": "Histogram for distribution analysis", "required_columns": 1},
                "box": {"description": "Box plot for statistical distribution", "required_columns": 1},
                "violin": {"description": "Violin plot for distribution shape", "required_columns": 1},
                "pie": {"description": "Pie chart for part-to-whole relationships", "required_columns": 2},
                "heatmap": {"description": "Heatmap for correlation matrices", "required_columns": "multiple"}
            },
            "output_formats": ["html", "png", "svg", "pdf", "json"],
            "themes": ["plotly", "plotly_white", "plotly_dark", "ggplot2", "seaborn", "simple_white"],
            "features": [
                "Interactive HTML output",
                "Static image export",
                "JSON data export",
                "Customizable themes",
                "Responsive layouts",
                "Base64 image encoding"
            ]
        }


# Initialize visualizer (conditionally for testing)
try:
    visualizer = PlotlyVisualizer()
except Exception:
    visualizer = None


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    """List available Plotly tools."""
    return [
        Tool(
            name="create_chart",
            description="Create a chart with flexible data input and configuration",
            inputSchema={
                "type": "object",
                "properties": {
                    "chart_type": {
                        "type": "string",
                        "enum": ["scatter", "line", "bar", "histogram", "box", "violin", "pie", "heatmap"],
                        "description": "Type of chart to create"
                    },
                    "data": {
                        "type": "object",
                        "additionalProperties": {
                            "type": "array",
                            "items": {"type": ["string", "number"]}
                        },
                        "description": "Chart data as key-value pairs where keys are column names"
                    },
                    "title": {"type": "string", "description": "Chart title (optional)"},
                    "x_title": {"type": "string", "description": "X-axis title (optional)"},
                    "y_title": {"type": "string", "description": "Y-axis title (optional)"},
                    "output_format": {
                        "type": "string",
                        "enum": ["html", "png", "svg", "pdf", "json"],
                        "description": "Output format",
                        "default": "html"
                    },
                    "output_file": {"type": "string", "description": "Output file path (optional)"},
                    "width": {"type": "integer", "description": "Chart width", "default": 800},
                    "height": {"type": "integer", "description": "Chart height", "default": 600},
                    "theme": {
                        "type": "string",
                        "enum": ["plotly", "plotly_white", "plotly_dark", "ggplot2", "seaborn", "simple_white"],
                        "description": "Chart theme",
                        "default": "plotly"
                    }
                },
                "required": ["chart_type", "data"]
            }
        ),
        Tool(
            name="create_scatter_plot",
            description="Create scatter plot with advanced customization",
            inputSchema={
                "type": "object",
                "properties": {
                    "x_data": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "X-axis numeric data"
                    },
                    "y_data": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Y-axis numeric data"
                    },
                    "labels": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Labels for data points (optional)"
                    },
                    "colors": {
                        "type": "array",
                        "items": {"type": ["string", "number"]},
                        "description": "Color data for points (optional)"
                    },
                    "title": {"type": "string", "description": "Chart title (optional)"},
                    "output_format": {
                        "type": "string",
                        "enum": ["html", "png", "svg", "pdf"],
                        "description": "Output format",
                        "default": "html"
                    },
                    "output_file": {"type": "string", "description": "Output file path (optional)"}
                },
                "required": ["x_data", "y_data"]
            }
        ),
        Tool(
            name="create_bar_chart",
            description="Create bar chart for categorical data",
            inputSchema={
                "type": "object",
                "properties": {
                    "categories": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Category names"
                    },
                    "values": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Values for each category"
                    },
                    "orientation": {
                        "type": "string",
                        "enum": ["vertical", "horizontal"],
                        "description": "Bar orientation",
                        "default": "vertical"
                    },
                    "title": {"type": "string", "description": "Chart title (optional)"},
                    "output_format": {
                        "type": "string",
                        "enum": ["html", "png", "svg", "pdf"],
                        "description": "Output format",
                        "default": "html"
                    },
                    "output_file": {"type": "string", "description": "Output file path (optional)"}
                },
                "required": ["categories", "values"]
            }
        ),
        Tool(
            name="create_line_chart",
            description="Create line chart for time series or continuous data",
            inputSchema={
                "type": "object",
                "properties": {
                    "x_data": {
                        "type": "array",
                        "items": {"type": ["string", "number"]},
                        "description": "X-axis data (can be dates, numbers, or categories)"
                    },
                    "y_data": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Y-axis numeric data"
                    },
                    "line_name": {"type": "string", "description": "Line series name (optional)"},
                    "title": {"type": "string", "description": "Chart title (optional)"},
                    "output_format": {
                        "type": "string",
                        "enum": ["html", "png", "svg", "pdf"],
                        "description": "Output format",
                        "default": "html"
                    },
                    "output_file": {"type": "string", "description": "Output file path (optional)"}
                },
                "required": ["x_data", "y_data"]
            }
        ),
        Tool(
            name="get_supported_charts",
            description="Get list of supported chart types and capabilities",
            inputSchema={
                "type": "object",
                "properties": {},
                "additionalProperties": False
            }
        )
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict[str, Any]) -> Sequence[TextContent | ImageContent | EmbeddedResource]:
    """Handle tool calls."""
    try:
        if visualizer is None:
            result = {"success": False, "error": "Plotly visualizer not available"}
        elif name == "create_chart":
            request = CreateChartRequest(**arguments)
            result = visualizer.create_custom_chart(
                chart_type=request.chart_type,
                data=request.data,
                title=request.title,
                x_title=request.x_title,
                y_title=request.y_title,
                output_format=request.output_format,
                output_file=request.output_file,
                width=request.width,
                height=request.height,
                theme=request.theme
            )

        elif name == "create_scatter_plot":
            request = ScatterPlotRequest(**arguments)
            result = visualizer.create_scatter_plot(
                x_data=request.x_data,
                y_data=request.y_data,
                labels=request.labels,
                colors=request.colors,
                title=request.title,
                output_format=request.output_format,
                output_file=request.output_file
            )

        elif name == "create_bar_chart":
            request = BarChartRequest(**arguments)
            result = visualizer.create_bar_chart(
                categories=request.categories,
                values=request.values,
                orientation=request.orientation,
                title=request.title,
                output_format=request.output_format,
                output_file=request.output_file
            )

        elif name == "create_line_chart":
            request = LineChartRequest(**arguments)
            result = visualizer.create_line_chart(
                x_data=request.x_data,
                y_data=request.y_data,
                line_name=request.line_name,
                title=request.title,
                output_format=request.output_format,
                output_file=request.output_file
            )

        elif name == "get_supported_charts":
            result = visualizer.get_supported_charts()

        else:
            result = {"success": False, "error": f"Unknown tool: {name}"}

    except Exception as e:
        logger.error(f"Error in {name}: {str(e)}")
        result = {"success": False, "error": str(e)}

    return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]


async def main():
    """Main server entry point."""
    logger.info("Starting Plotly MCP Server...")

    from mcp.server.stdio import stdio_server

    logger.info("Waiting for MCP client connection...")
    async with stdio_server() as (read_stream, write_stream):
        logger.info("MCP client connected, starting server...")
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="plotly-server",
                server_version="0.1.0",
                capabilities={
                    "tools": {},
                    "logging": {},
                },
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())
