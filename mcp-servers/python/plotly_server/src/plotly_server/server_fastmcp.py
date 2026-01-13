#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/plotly_server/src/plotly_server/server_fastmcp.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Plotly FastMCP Server

Advanced data visualization server using Plotly for creating interactive charts and graphs.
Supports multiple chart types, data formats, and export options.
Powered by FastMCP for enhanced type safety and automatic validation.
"""

import logging
import sys
from typing import Any

import orjson
from fastmcp import FastMCP
from pydantic import Field

# Configure logging to stderr to avoid MCP protocol interference
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger(__name__)

# Create FastMCP server instance
mcp = FastMCP("plotly-server")


class PlotlyVisualizer:
    """Plotly visualization handler."""

    def __init__(self):
        """Initialize the visualizer."""
        self.plotly_available = self._check_plotly()

    def _check_plotly(self) -> bool:
        """Check if Plotly is available."""
        try:
            import plotly.express as px
            import plotly.graph_objects as go

            return True
        except ImportError:
            logger.warning("Plotly not available")
            return False

    def create_scatter_plot(
        self,
        x_data: list[int | float],
        y_data: list[int | float],
        labels: list[str] | None = None,
        colors: list[str | int | float] | None = None,
        title: str | None = None,
        output_format: str = "html",
        output_file: str | None = None,
    ) -> dict[str, Any]:
        """Create scatter plot."""
        if not self.plotly_available:
            return {"success": False, "error": "Plotly not available"}

        try:
            import plotly.graph_objects as go

            # Create scatter plot
            scatter = go.Scatter(
                x=x_data,
                y=y_data,
                mode="markers",
                text=labels,
                marker=dict(
                    color=colors if colors else "blue",
                    size=8,
                    line=dict(width=1, color="DarkSlateGrey"),
                ),
                name="Data Points",
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
        categories: list[str],
        values: list[int | float],
        orientation: str = "vertical",
        title: str | None = None,
        output_format: str = "html",
        output_file: str | None = None,
    ) -> dict[str, Any]:
        """Create bar chart."""
        if not self.plotly_available:
            return {"success": False, "error": "Plotly not available"}

        try:
            import plotly.graph_objects as go

            if orientation == "horizontal":
                bar = go.Bar(y=categories, x=values, orientation="h")
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
        x_data: list[str | int | float],
        y_data: list[int | float],
        line_name: str | None = None,
        title: str | None = None,
        output_format: str = "html",
        output_file: str | None = None,
    ) -> dict[str, Any]:
        """Create line chart."""
        if not self.plotly_available:
            return {"success": False, "error": "Plotly not available"}

        try:
            import plotly.graph_objects as go

            line = go.Scatter(
                x=x_data,
                y=y_data,
                mode="lines+markers",
                name=line_name or "Data",
                line=dict(width=2),
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
        data: dict[str, list[str | int | float]],
        title: str | None = None,
        x_title: str | None = None,
        y_title: str | None = None,
        output_format: str = "html",
        output_file: str | None = None,
        width: int = 800,
        height: int = 600,
        theme: str = "plotly",
    ) -> dict[str, Any]:
        """Create custom chart with flexible configuration."""
        if not self.plotly_available:
            return {"success": False, "error": "Plotly not available"}

        try:
            import pandas as pd
            import plotly.express as px

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
                fig = px.imshow(df.select_dtypes(include=["number"]), title=title)
            else:
                return {"success": False, "error": f"Unsupported chart type: {chart_type}"}

            # Update layout
            fig.update_layout(
                width=width, height=height, template=theme, xaxis_title=x_title, yaxis_title=y_title
            )

            return self._export_figure(fig, output_format, output_file, chart_type)

        except Exception as e:
            logger.error(f"Error creating {chart_type} chart: {e}")
            return {"success": False, "error": str(e)}

    def _export_figure(
        self, fig, output_format: str, output_file: str | None, chart_name: str
    ) -> dict[str, Any]:
        """Export figure in specified format."""
        try:
            if output_format == "html":
                html_content = fig.to_html(include_plotlyjs=True)
                if output_file:
                    with open(output_file, "w") as f:
                        f.write(html_content)
                return {
                    "success": True,
                    "chart_type": chart_name,
                    "output_format": output_format,
                    "output_file": output_file,
                    "html_content": html_content[:5000] + "..."
                    if len(html_content) > 5000
                    else html_content,
                }

            elif output_format in ["png", "svg", "pdf"]:
                if output_file:
                    fig.write_image(output_file, format=output_format)
                    return {
                        "success": True,
                        "chart_type": chart_name,
                        "output_format": output_format,
                        "output_file": output_file,
                        "message": f"Chart exported to {output_file}",
                    }
                else:
                    # Return base64 encoded image
                    import base64

                    img_bytes = fig.to_image(format=output_format)
                    img_base64 = base64.b64encode(img_bytes).decode()

                    return {
                        "success": True,
                        "chart_type": chart_name,
                        "output_format": output_format,
                        "image_base64": img_base64,
                        "message": "Chart generated as base64 image",
                    }

            elif output_format == "json":
                chart_json = fig.to_json()
                if output_file:
                    with open(output_file, "w") as f:
                        f.write(chart_json)
                return {
                    "success": True,
                    "chart_type": chart_name,
                    "output_format": output_format,
                    "output_file": output_file,
                    "chart_json": orjson.loads(chart_json),
                }

            else:
                return {"success": False, "error": f"Unsupported output format: {output_format}"}

        except Exception as e:
            logger.error(f"Error exporting figure: {e}")
            return {"success": False, "error": f"Export failed: {str(e)}"}

    def get_supported_charts(self) -> dict[str, Any]:
        """Get list of supported chart types."""
        return {
            "chart_types": {
                "scatter": {
                    "description": "Scatter plot for correlation analysis",
                    "required_columns": 2,
                },
                "line": {"description": "Line chart for trends over time", "required_columns": 2},
                "bar": {"description": "Bar chart for categorical data", "required_columns": 2},
                "histogram": {
                    "description": "Histogram for distribution analysis",
                    "required_columns": 1,
                },
                "box": {
                    "description": "Box plot for statistical distribution",
                    "required_columns": 1,
                },
                "violin": {
                    "description": "Violin plot for distribution shape",
                    "required_columns": 1,
                },
                "pie": {
                    "description": "Pie chart for part-to-whole relationships",
                    "required_columns": 2,
                },
                "heatmap": {
                    "description": "Heatmap for correlation matrices",
                    "required_columns": "multiple",
                },
            },
            "output_formats": ["html", "png", "svg", "pdf", "json"],
            "themes": [
                "plotly",
                "plotly_white",
                "plotly_dark",
                "ggplot2",
                "seaborn",
                "simple_white",
            ],
            "features": [
                "Interactive HTML output",
                "Static image export",
                "JSON data export",
                "Customizable themes",
                "Responsive layouts",
                "Base64 image encoding",
            ],
        }


# Initialize visualizer (conditionally for testing)
try:
    visualizer = PlotlyVisualizer()
except Exception:
    visualizer = None


# Tool definitions using FastMCP decorators
@mcp.tool(description="Create a chart with flexible data input and configuration")
async def create_chart(
    chart_type: str = Field(
        ...,
        pattern="^(scatter|line|bar|histogram|box|violin|pie|heatmap)$",
        description="Type of chart to create",
    ),
    data: dict[str, list[str | int | float]] = Field(
        ..., description="Chart data as key-value pairs where keys are column names"
    ),
    title: str | None = Field(None, description="Chart title"),
    x_title: str | None = Field(None, description="X-axis title"),
    y_title: str | None = Field(None, description="Y-axis title"),
    output_format: str = Field(
        "html", pattern="^(html|png|svg|pdf|json)$", description="Output format"
    ),
    output_file: str | None = Field(None, description="Output file path"),
    width: int = Field(800, ge=100, le=2000, description="Chart width"),
    height: int = Field(600, ge=100, le=2000, description="Chart height"),
    theme: str = Field(
        "plotly",
        pattern="^(plotly|plotly_white|plotly_dark|ggplot2|seaborn|simple_white)$",
        description="Chart theme",
    ),
) -> dict[str, Any]:
    """Create a custom chart with flexible configuration."""
    if visualizer is None:
        return {"success": False, "error": "Plotly visualizer not available"}

    return visualizer.create_custom_chart(
        chart_type=chart_type,
        data=data,
        title=title,
        x_title=x_title,
        y_title=y_title,
        output_format=output_format,
        output_file=output_file,
        width=width,
        height=height,
        theme=theme,
    )


@mcp.tool(description="Create scatter plot with advanced customization")
async def create_scatter_plot(
    x_data: list[float] = Field(..., description="X-axis numeric data"),
    y_data: list[float] = Field(..., description="Y-axis numeric data"),
    labels: list[str] | None = Field(None, description="Labels for data points"),
    colors: list[str | float] | None = Field(None, description="Color data for points"),
    title: str | None = Field(None, description="Chart title"),
    output_format: str = Field("html", pattern="^(html|png|svg|pdf)$", description="Output format"),
    output_file: str | None = Field(None, description="Output file path"),
) -> dict[str, Any]:
    """Create a scatter plot."""
    if visualizer is None:
        return {"success": False, "error": "Plotly visualizer not available"}

    return visualizer.create_scatter_plot(
        x_data=x_data,
        y_data=y_data,
        labels=labels,
        colors=colors,
        title=title,
        output_format=output_format,
        output_file=output_file,
    )


@mcp.tool(description="Create bar chart for categorical data")
async def create_bar_chart(
    categories: list[str] = Field(..., description="Category names"),
    values: list[float] = Field(..., description="Values for each category"),
    orientation: str = Field(
        "vertical", pattern="^(vertical|horizontal)$", description="Bar orientation"
    ),
    title: str | None = Field(None, description="Chart title"),
    output_format: str = Field("html", pattern="^(html|png|svg|pdf)$", description="Output format"),
    output_file: str | None = Field(None, description="Output file path"),
) -> dict[str, Any]:
    """Create a bar chart."""
    if visualizer is None:
        return {"success": False, "error": "Plotly visualizer not available"}

    return visualizer.create_bar_chart(
        categories=categories,
        values=values,
        orientation=orientation,
        title=title,
        output_format=output_format,
        output_file=output_file,
    )


@mcp.tool(description="Create line chart for time series or continuous data")
async def create_line_chart(
    x_data: list[str | float] = Field(
        ..., description="X-axis data (can be dates, numbers, or categories)"
    ),
    y_data: list[float] = Field(..., description="Y-axis numeric data"),
    line_name: str | None = Field(None, description="Line series name"),
    title: str | None = Field(None, description="Chart title"),
    output_format: str = Field("html", pattern="^(html|png|svg|pdf)$", description="Output format"),
    output_file: str | None = Field(None, description="Output file path"),
) -> dict[str, Any]:
    """Create a line chart."""
    if visualizer is None:
        return {"success": False, "error": "Plotly visualizer not available"}

    return visualizer.create_line_chart(
        x_data=x_data,
        y_data=y_data,
        line_name=line_name,
        title=title,
        output_format=output_format,
        output_file=output_file,
    )


@mcp.tool(description="Get list of supported chart types and capabilities")
async def get_supported_charts() -> dict[str, Any]:
    """Get supported chart types and capabilities."""
    if visualizer is None:
        return {"error": "Plotly visualizer not available"}

    return visualizer.get_supported_charts()


def main():
    """Main entry point for the FastMCP server."""
    import argparse

    parser = argparse.ArgumentParser(description="Plotly FastMCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="Transport mode (stdio or http)",
    )
    parser.add_argument("--host", default="0.0.0.0", help="HTTP host")
    parser.add_argument("--port", type=int, default=9013, help="HTTP port")

    args = parser.parse_args()

    if args.transport == "http":
        logger.info(f"Starting Plotly FastMCP Server on HTTP at {args.host}:{args.port}")
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        logger.info("Starting Plotly FastMCP Server on stdio")
        mcp.run()


if __name__ == "__main__":
    main()
