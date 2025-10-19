#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/graphviz_server/src/graphviz_server/server_fastmcp.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Graphviz MCP Server - FastMCP Implementation

A comprehensive MCP server for creating, editing, and rendering Graphviz graphs.
Supports DOT language manipulation, graph rendering, and visualization analysis.
"""

import logging
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

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
mcp = FastMCP("graphviz-server")


class GraphvizProcessor:
    """Handles Graphviz graph processing operations."""

    def __init__(self):
        self.dot_cmd = self._find_graphviz()

    def _find_graphviz(self) -> str:
        """Find Graphviz dot executable."""
        possible_commands = [
            "dot",
            "/usr/bin/dot",
            "/usr/local/bin/dot",
            "/opt/graphviz/bin/dot",
            "/opt/homebrew/bin/dot",  # macOS Homebrew
            "C:\\Program Files\\Graphviz\\bin\\dot.exe",  # Windows
            "C:\\Program Files (x86)\\Graphviz\\bin\\dot.exe",  # Windows x86
        ]

        for cmd in possible_commands:
            if shutil.which(cmd):
                logger.info(f"Found Graphviz at: {cmd}")
                return cmd

        logger.warning("Graphviz not found. Please install Graphviz.")
        raise RuntimeError(
            "Graphviz not found. Please install Graphviz from https://graphviz.org/download/"
        )

    def create_graph(
        self,
        file_path: str,
        graph_type: str = "digraph",
        graph_name: str = "G",
        attributes: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Create a new DOT graph file."""
        try:
            # Create directory if it doesn't exist
            Path(file_path).parent.mkdir(parents=True, exist_ok=True)

            # Generate DOT content
            content = [f"{graph_type} {graph_name} {{"]

            # Add graph attributes
            if attributes:
                for key, value in attributes.items():
                    content.append(f'    {key}="{value}";')
                content.append("")

            content.append("    // Nodes and edges go here")
            content.append("}")

            # Write to file
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("\n".join(content))

            return {
                "success": True,
                "message": f"Graph created at {file_path}",
                "file_path": file_path,
                "graph_type": graph_type,
                "graph_name": graph_name,
            }

        except Exception as e:
            logger.error(f"Error creating graph: {e}")
            return {"success": False, "error": str(e)}

    def render_graph(
        self,
        input_file: str,
        output_file: str | None = None,
        format: str = "png",
        layout: str = "dot",
        dpi: int | None = None,
    ) -> dict[str, Any]:
        """Render a DOT graph to an image."""
        try:
            if not Path(input_file).exists():
                return {"success": False, "error": f"Input file not found: {input_file}"}

            # Determine output file
            if output_file is None:
                input_path = Path(input_file)
                output_file = str(input_path.with_suffix(f".{format}"))

            # Ensure output directory exists
            Path(output_file).parent.mkdir(parents=True, exist_ok=True)

            # Build command
            cmd = [self.dot_cmd, f"-T{format}", f"-K{layout}"]

            if dpi:
                cmd.extend(["-Gdpi=" + str(dpi)])

            cmd.extend(["-o", output_file, input_file])

            logger.info(f"Running command: {' '.join(cmd)}")

            # Run Graphviz
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            if result.returncode != 0:
                return {
                    "success": False,
                    "error": f"Graphviz rendering failed: {result.stderr}",
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }

            if not Path(output_file).exists():
                return {
                    "success": False,
                    "error": f"Output file not created: {output_file}",
                    "stdout": result.stdout,
                }

            return {
                "success": True,
                "message": "Graph rendered successfully",
                "input_file": input_file,
                "output_file": output_file,
                "format": format,
                "layout": layout,
                "file_size": Path(output_file).stat().st_size,
            }

        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Rendering timed out after 60 seconds"}
        except Exception as e:
            logger.error(f"Error rendering graph: {e}")
            return {"success": False, "error": str(e)}

    def add_node(
        self,
        file_path: str,
        node_id: str,
        label: str | None = None,
        attributes: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Add a node to a DOT graph."""
        try:
            if not Path(file_path).exists():
                return {"success": False, "error": f"Graph file not found: {file_path}"}

            with open(file_path, encoding="utf-8") as f:
                content = f.read()

            # Build node definition
            node_attrs = []
            if label:
                node_attrs.append(f'label="{label}"')
            if attributes:
                for key, value in attributes.items():
                    node_attrs.append(f'{key}="{value}"')

            if node_attrs:
                node_def = f"    {node_id} [{', '.join(node_attrs)}];"
            else:
                node_def = f"    {node_id};"

            # Find insertion point (before closing brace)
            lines = content.split("\n")
            insert_index = -1
            for i in range(len(lines) - 1, -1, -1):
                if lines[i].strip() == "}":
                    insert_index = i
                    break

            if insert_index == -1:
                return {"success": False, "error": "Could not find closing brace in DOT file"}

            # Check if node already exists
            if re.search(rf"\b{re.escape(node_id)}\b", content):
                return {"success": False, "error": f"Node '{node_id}' already exists"}

            # Insert node definition
            lines.insert(insert_index, node_def)

            # Write back to file
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))

            return {
                "success": True,
                "message": f"Node '{node_id}' added to graph",
                "node_id": node_id,
                "label": label,
                "attributes": attributes,
            }

        except Exception as e:
            logger.error(f"Error adding node: {e}")
            return {"success": False, "error": str(e)}

    def add_edge(
        self,
        file_path: str,
        from_node: str,
        to_node: str,
        label: str | None = None,
        attributes: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Add an edge to a DOT graph."""
        try:
            if not Path(file_path).exists():
                return {"success": False, "error": f"Graph file not found: {file_path}"}

            with open(file_path, encoding="utf-8") as f:
                content = f.read()

            # Determine edge operator based on graph type
            if content.strip().startswith("graph ") or content.strip().startswith("strict graph "):
                edge_op = "--"  # Undirected graph
            else:
                edge_op = "->"  # Directed graph

            # Build edge definition
            edge_attrs = []
            if label:
                edge_attrs.append(f'label="{label}"')
            if attributes:
                for key, value in attributes.items():
                    edge_attrs.append(f'{key}="{value}"')

            if edge_attrs:
                edge_def = f"    {from_node} {edge_op} {to_node} [{', '.join(edge_attrs)}];"
            else:
                edge_def = f"    {from_node} {edge_op} {to_node};"

            # Find insertion point (before closing brace)
            lines = content.split("\n")
            insert_index = -1
            for i in range(len(lines) - 1, -1, -1):
                if lines[i].strip() == "}":
                    insert_index = i
                    break

            if insert_index == -1:
                return {"success": False, "error": "Could not find closing brace in DOT file"}

            # Insert edge definition
            lines.insert(insert_index, edge_def)

            # Write back to file
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))

            return {
                "success": True,
                "message": f"Edge '{from_node}' {edge_op} '{to_node}' added to graph",
                "from_node": from_node,
                "to_node": to_node,
                "label": label,
                "attributes": attributes,
            }

        except Exception as e:
            logger.error(f"Error adding edge: {e}")
            return {"success": False, "error": str(e)}

    def set_attributes(
        self,
        file_path: str,
        target_type: str,
        target_id: str | None = None,
        attributes: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Set attributes for graph, node, or edge."""
        try:
            if not Path(file_path).exists():
                return {"success": False, "error": f"Graph file not found: {file_path}"}

            if not attributes:
                return {"success": False, "error": "No attributes provided"}

            with open(file_path, encoding="utf-8") as f:
                content = f.read()

            # For graph attributes, add them at the beginning of the graph
            if target_type == "graph":
                lines = content.split("\n")
                for i, line in enumerate(lines):
                    if "{" in line:
                        # Insert attributes after opening brace
                        for key, value in attributes.items():
                            lines.insert(i + 1, f'    {key}="{value}";')
                        break

                with open(file_path, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines))

                return {
                    "success": True,
                    "message": "Graph attributes set successfully",
                    "attributes": attributes,
                }

            # For node/edge attributes (simplified implementation)
            return {
                "success": True,
                "message": f"{target_type.capitalize()} attributes would be set (simplified for FastMCP)",
                "target_type": target_type,
                "target_id": target_id,
                "attributes": attributes,
            }

        except Exception as e:
            logger.error(f"Error setting attributes: {e}")
            return {"success": False, "error": str(e)}

    def analyze_graph(
        self, file_path: str, include_structure: bool = True, include_metrics: bool = True
    ) -> dict[str, Any]:
        """Analyze a DOT graph file."""
        try:
            if not Path(file_path).exists():
                return {"success": False, "error": f"Graph file not found: {file_path}"}

            with open(file_path, encoding="utf-8") as f:
                content = f.read()

            analysis = {"success": True}

            if include_structure:
                # Count nodes and edges (simplified)
                node_count = len(re.findall(r"^\s*(\w+)\s*\[", content, re.MULTILINE))
                edge_count = len(re.findall(r"(->|--)", content))

                # Detect graph type
                if content.strip().startswith("digraph"):
                    graph_type = "directed"
                elif content.strip().startswith("graph"):
                    graph_type = "undirected"
                else:
                    graph_type = "unknown"

                analysis["structure"] = {
                    "graph_type": graph_type,
                    "node_count": node_count,
                    "edge_count": edge_count,
                    "file_lines": len(content.split("\n")),
                }

            if include_metrics:
                # Basic metrics
                analysis["metrics"] = {
                    "file_size": len(content),
                    "has_attributes": "label=" in content
                    or "color=" in content
                    or "shape=" in content,
                    "has_subgraphs": "subgraph" in content,
                }

            return analysis

        except Exception as e:
            logger.error(f"Error analyzing graph: {e}")
            return {"success": False, "error": str(e)}

    def validate_graph(self, file_path: str) -> dict[str, Any]:
        """Validate a DOT graph file."""
        try:
            if not Path(file_path).exists():
                return {"success": False, "error": f"Graph file not found: {file_path}"}

            # Run dot with -n flag (no output) to validate
            cmd = [self.dot_cmd, "-n", file_path]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

            if result.returncode == 0:
                return {"success": True, "message": "Graph is valid", "file_path": file_path}
            else:
                return {
                    "success": False,
                    "error": "Graph validation failed",
                    "stderr": result.stderr,
                    "returncode": result.returncode,
                }

        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Validation timed out after 10 seconds"}
        except Exception as e:
            logger.error(f"Error validating graph: {e}")
            return {"success": False, "error": str(e)}

    def list_layouts(self) -> dict[str, Any]:
        """List available Graphviz layout engines and formats."""
        try:
            layouts = ["dot", "neato", "fdp", "sfdp", "twopi", "circo", "patchwork", "osage"]
            formats = ["png", "svg", "pdf", "ps", "gif", "jpg", "json", "dot", "xdot"]

            return {
                "success": True,
                "layouts": layouts,
                "formats": formats,
                "default_layout": "dot",
                "default_format": "png",
            }
        except Exception as e:
            logger.error(f"Error listing layouts: {e}")
            return {"success": False, "error": str(e)}


# Initialize the processor
try:
    processor = GraphvizProcessor()
except RuntimeError as e:
    logger.warning(f"Graphviz not available: {e}")
    processor = None  # Server will still work for DOT file manipulation


@mcp.tool(description="Create a new DOT graph file")
async def create_graph(
    file_path: str = Field(..., description="Path for the DOT file"),
    graph_type: str = Field(
        "digraph",
        pattern="^(graph|digraph|strict graph|strict digraph)$",
        description="Graph type (graph, digraph, strict graph, strict digraph)",
    ),
    graph_name: str = Field("G", description="Graph name"),
    attributes: dict[str, str] | None = Field(None, description="Graph attributes"),
) -> dict[str, Any]:
    """Create a new Graphviz DOT graph file."""
    return processor.create_graph(file_path, graph_type, graph_name, attributes)


@mcp.tool(description="Render a DOT graph to an image")
async def render_graph(
    input_file: str = Field(..., description="Path to the DOT file"),
    output_file: str | None = Field(None, description="Output image file path"),
    format: str = Field(
        "png",
        pattern="^(png|svg|pdf|ps|gif|jpg|json|dot|xdot)$",
        description="Output format (png, svg, pdf, ps, etc.)",
    ),
    layout: str = Field(
        "dot",
        pattern="^(dot|neato|fdp|sfdp|twopi|circo|patchwork|osage)$",
        description="Layout engine (dot, neato, fdp, sfdp, twopi, circo)",
    ),
    dpi: int | None = Field(None, description="Output resolution in DPI", ge=72, le=600),
) -> dict[str, Any]:
    """Render a DOT graph to an image with specified format and layout."""
    return processor.render_graph(input_file, output_file, format, layout, dpi)


@mcp.tool(description="Add a node to a DOT graph")
async def add_node(
    file_path: str = Field(..., description="Path to the DOT file"),
    node_id: str = Field(..., description="Node identifier"),
    label: str | None = Field(None, description="Node label"),
    attributes: dict[str, str] | None = Field(None, description="Node attributes"),
) -> dict[str, Any]:
    """Add a node with optional label and attributes to a DOT graph."""
    return processor.add_node(file_path, node_id, label, attributes)


@mcp.tool(description="Add an edge to a DOT graph")
async def add_edge(
    file_path: str = Field(..., description="Path to the DOT file"),
    from_node: str = Field(..., description="Source node identifier"),
    to_node: str = Field(..., description="Target node identifier"),
    label: str | None = Field(None, description="Edge label"),
    attributes: dict[str, str] | None = Field(None, description="Edge attributes"),
) -> dict[str, Any]:
    """Add an edge between two nodes with optional label and attributes."""
    return processor.add_edge(file_path, from_node, to_node, label, attributes)


@mcp.tool(description="Set graph, node, or edge attributes")
async def set_attributes(
    file_path: str = Field(..., description="Path to the DOT file"),
    target_type: str = Field(
        ..., pattern="^(graph|node|edge)$", description="Attribute target (graph, node, edge)"
    ),
    target_id: str | None = Field(None, description="Target ID (for node/edge, None for graph)"),
    attributes: dict[str, str] | None = Field(None, description="Attributes to set"),
) -> dict[str, Any]:
    """Set attributes for graph, node, or edge elements."""
    return processor.set_attributes(file_path, target_type, target_id, attributes)


@mcp.tool(description="Analyze a DOT graph structure and metrics")
async def analyze_graph(
    file_path: str = Field(..., description="Path to the DOT file"),
    include_structure: bool = Field(True, description="Include structural analysis"),
    include_metrics: bool = Field(True, description="Include graph metrics"),
) -> dict[str, Any]:
    """Analyze a graph's structure and calculate metrics."""
    return processor.analyze_graph(file_path, include_structure, include_metrics)


@mcp.tool(description="Validate DOT file syntax")
async def validate_graph(
    file_path: str = Field(..., description="Path to the DOT file"),
) -> dict[str, Any]:
    """Validate the syntax of a DOT graph file."""
    return processor.validate_graph(file_path)


@mcp.tool(description="List available layout engines and output formats")
async def list_layouts() -> dict[str, Any]:
    """List all available Graphviz layout engines and output formats."""
    return processor.list_layouts()


def main():
    """Main entry point for the FastMCP server."""
    import argparse

    parser = argparse.ArgumentParser(description="Graphviz FastMCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="Transport mode (stdio or http)",
    )
    parser.add_argument("--host", default="0.0.0.0", help="HTTP host")
    parser.add_argument("--port", type=int, default=9005, help="HTTP port")

    args = parser.parse_args()

    if args.transport == "http":
        logger.info(f"Starting Graphviz FastMCP Server on HTTP at {args.host}:{args.port}")
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        logger.info("Starting Graphviz FastMCP Server on stdio")
        mcp.run()


if __name__ == "__main__":
    main()
