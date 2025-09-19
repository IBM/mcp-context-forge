#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/graphviz_server/src/graphviz_server/server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Graphviz MCP Server

A comprehensive MCP server for creating, editing, and rendering Graphviz graphs.
Supports DOT language manipulation, graph rendering, and visualization analysis.
"""

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

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
server = Server("graphviz-server")


class CreateGraphRequest(BaseModel):
    """Request to create a new graph."""
    file_path: str = Field(..., description="Path for the DOT file")
    graph_type: str = Field("digraph", description="Graph type (graph, digraph, strict graph, strict digraph)")
    graph_name: str = Field("G", description="Graph name")
    attributes: dict[str, str] | None = Field(None, description="Graph attributes")


class RenderGraphRequest(BaseModel):
    """Request to render a graph to an image."""
    input_file: str = Field(..., description="Path to the DOT file")
    output_file: str | None = Field(None, description="Output image file path")
    format: str = Field("png", description="Output format (png, svg, pdf, ps, etc.)")
    layout: str = Field("dot", description="Layout engine (dot, neato, fdp, sfdp, twopi, circo)")
    dpi: int | None = Field(None, description="Output resolution in DPI")


class AddNodeRequest(BaseModel):
    """Request to add a node to a graph."""
    file_path: str = Field(..., description="Path to the DOT file")
    node_id: str = Field(..., description="Node identifier")
    label: str | None = Field(None, description="Node label")
    attributes: dict[str, str] | None = Field(None, description="Node attributes")


class AddEdgeRequest(BaseModel):
    """Request to add an edge to a graph."""
    file_path: str = Field(..., description="Path to the DOT file")
    from_node: str = Field(..., description="Source node identifier")
    to_node: str = Field(..., description="Target node identifier")
    label: str | None = Field(None, description="Edge label")
    attributes: dict[str, str] | None = Field(None, description="Edge attributes")


class SetAttributeRequest(BaseModel):
    """Request to set graph, node, or edge attributes."""
    file_path: str = Field(..., description="Path to the DOT file")
    target_type: str = Field(..., description="Attribute target (graph, node, edge)")
    target_id: str | None = Field(None, description="Target ID (for node/edge, None for graph)")
    attributes: dict[str, str] = Field(..., description="Attributes to set")


class AnalyzeGraphRequest(BaseModel):
    """Request to analyze a graph."""
    file_path: str = Field(..., description="Path to the DOT file")
    include_structure: bool = Field(True, description="Include structural analysis")
    include_metrics: bool = Field(True, description="Include graph metrics")


class ValidateGraphRequest(BaseModel):
    """Request to validate a DOT file."""
    file_path: str = Field(..., description="Path to the DOT file")


class ConvertGraphRequest(BaseModel):
    """Request to convert between graph formats."""
    input_file: str = Field(..., description="Path to input file")
    output_file: str = Field(..., description="Path to output file")
    input_format: str = Field("dot", description="Input format")
    output_format: str = Field("dot", description="Output format")


class GraphvizProcessor:
    """Handles Graphviz graph processing operations."""

    def __init__(self):
        self.dot_cmd = self._find_graphviz()

    def _find_graphviz(self) -> str:
        """Find Graphviz dot executable."""
        possible_commands = [
            'dot',
            '/usr/bin/dot',
            '/usr/local/bin/dot',
            '/opt/graphviz/bin/dot'
        ]

        for cmd in possible_commands:
            if shutil.which(cmd):
                return cmd

        raise RuntimeError("Graphviz not found. Please install Graphviz.")

    def create_graph(self, file_path: str, graph_type: str = "digraph", graph_name: str = "G",
                    attributes: dict[str, str] | None = None) -> dict[str, Any]:
        """Create a new DOT graph file."""
        try:
            # Create directory if it doesn't exist
            Path(file_path).parent.mkdir(parents=True, exist_ok=True)

            # Generate DOT content
            content = [f"{graph_type} {graph_name} {{"]

            # Add graph attributes
            if attributes:
                for key, value in attributes.items():
                    content.append(f"    {key}=\"{value}\";")
                content.append("")

            content.append("    // Nodes and edges go here")
            content.append("}")

            # Write to file
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(content))

            return {
                "success": True,
                "message": f"Graph created at {file_path}",
                "file_path": file_path,
                "graph_type": graph_type,
                "graph_name": graph_name
            }

        except Exception as e:
            logger.error(f"Error creating graph: {e}")
            return {"success": False, "error": str(e)}

    def render_graph(self, input_file: str, output_file: str | None = None, format: str = "png",
                    layout: str = "dot", dpi: int | None = None) -> dict[str, Any]:
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
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode != 0:
                return {
                    "success": False,
                    "error": f"Graphviz rendering failed: {result.stderr}",
                    "stdout": result.stdout,
                    "stderr": result.stderr
                }

            if not Path(output_file).exists():
                return {
                    "success": False,
                    "error": f"Output file not created: {output_file}",
                    "stdout": result.stdout
                }

            return {
                "success": True,
                "message": f"Graph rendered successfully",
                "input_file": input_file,
                "output_file": output_file,
                "format": format,
                "layout": layout,
                "file_size": Path(output_file).stat().st_size
            }

        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Rendering timed out after 60 seconds"}
        except Exception as e:
            logger.error(f"Error rendering graph: {e}")
            return {"success": False, "error": str(e)}

    def add_node(self, file_path: str, node_id: str, label: str | None = None,
                attributes: dict[str, str] | None = None) -> dict[str, Any]:
        """Add a node to a DOT graph."""
        try:
            if not Path(file_path).exists():
                return {"success": False, "error": f"Graph file not found: {file_path}"}

            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Build node definition
            node_attrs = []
            if label:
                node_attrs.append(f'label="{label}"')
            if attributes:
                for key, value in attributes.items():
                    node_attrs.append(f'{key}="{value}"')

            if node_attrs:
                node_def = f'    {node_id} [{", ".join(node_attrs)}];'
            else:
                node_def = f'    {node_id};'

            # Find insertion point (before closing brace)
            lines = content.split('\n')
            insert_index = -1
            for i in range(len(lines) - 1, -1, -1):
                if lines[i].strip() == '}':
                    insert_index = i
                    break

            if insert_index == -1:
                return {"success": False, "error": "Could not find closing brace in DOT file"}

            # Check if node already exists
            if re.search(rf'\b{re.escape(node_id)}\b', content):
                return {"success": False, "error": f"Node '{node_id}' already exists"}

            # Insert node definition
            lines.insert(insert_index, node_def)

            # Write back to file
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))

            return {
                "success": True,
                "message": f"Node '{node_id}' added to graph",
                "node_id": node_id,
                "label": label,
                "attributes": attributes
            }

        except Exception as e:
            logger.error(f"Error adding node: {e}")
            return {"success": False, "error": str(e)}

    def add_edge(self, file_path: str, from_node: str, to_node: str, label: str | None = None,
                attributes: dict[str, str] | None = None) -> dict[str, Any]:
        """Add an edge to a DOT graph."""
        try:
            if not Path(file_path).exists():
                return {"success": False, "error": f"Graph file not found: {file_path}"}

            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Determine edge operator based on graph type
            if content.strip().startswith('graph ') or content.strip().startswith('strict graph '):
                edge_op = '--'  # Undirected graph
            else:
                edge_op = '->'  # Directed graph

            # Build edge definition
            edge_attrs = []
            if label:
                edge_attrs.append(f'label="{label}"')
            if attributes:
                for key, value in attributes.items():
                    edge_attrs.append(f'{key}="{value}"')

            if edge_attrs:
                edge_def = f'    {from_node} {edge_op} {to_node} [{", ".join(edge_attrs)}];'
            else:
                edge_def = f'    {from_node} {edge_op} {to_node};'

            # Find insertion point (before closing brace)
            lines = content.split('\n')
            insert_index = -1
            for i in range(len(lines) - 1, -1, -1):
                if lines[i].strip() == '}':
                    insert_index = i
                    break

            if insert_index == -1:
                return {"success": False, "error": "Could not find closing brace in DOT file"}

            # Insert edge definition
            lines.insert(insert_index, edge_def)

            # Write back to file
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))

            return {
                "success": True,
                "message": f"Edge '{from_node}' {edge_op} '{to_node}' added to graph",
                "from_node": from_node,
                "to_node": to_node,
                "label": label,
                "attributes": attributes
            }

        except Exception as e:
            logger.error(f"Error adding edge: {e}")
            return {"success": False, "error": str(e)}

    def set_attributes(self, file_path: str, target_type: str, target_id: str | None = None,
                      attributes: dict[str, str] = None) -> dict[str, Any]:
        """Set attributes for graph, node, or edge."""
        try:
            if not Path(file_path).exists():
                return {"success": False, "error": f"Graph file not found: {file_path}"}

            if not attributes:
                return {"success": False, "error": "No attributes provided"}

            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            if target_type == "graph":
                # Add graph attributes after opening brace
                lines = content.split('\n')
                insert_index = -1
                for i, line in enumerate(lines):
                    if '{' in line:
                        insert_index = i + 1
                        break

                if insert_index == -1:
                    return {"success": False, "error": "Could not find opening brace in DOT file"}

                # Add attributes
                for key, value in attributes.items():
                    attr_line = f'    {key}="{value}";'
                    lines.insert(insert_index, attr_line)
                    insert_index += 1

                content = '\n'.join(lines)

            elif target_type == "node":
                if not target_id:
                    return {"success": False, "error": "Node ID required for node attributes"}

                # Add default node attributes or modify specific node
                lines = content.split('\n')
                insert_index = -1
                for i, line in enumerate(lines):
                    if '{' in line:
                        insert_index = i + 1
                        break

                attr_items = [f'{key}="{value}"' for key, value in attributes.items()]
                if target_id == "*":  # Default node attributes
                    attr_line = f'    node [{", ".join(attr_items)}];'
                else:
                    attr_line = f'    {target_id} [{", ".join(attr_items)}];'

                lines.insert(insert_index, attr_line)
                content = '\n'.join(lines)

            elif target_type == "edge":
                # Add default edge attributes
                lines = content.split('\n')
                insert_index = -1
                for i, line in enumerate(lines):
                    if '{' in line:
                        insert_index = i + 1
                        break

                attr_items = [f'{key}="{value}"' for key, value in attributes.items()]
                attr_line = f'    edge [{", ".join(attr_items)}];'
                lines.insert(insert_index, attr_line)
                content = '\n'.join(lines)

            else:
                return {"success": False, "error": f"Invalid target type: {target_type}"}

            # Write back to file
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)

            return {
                "success": True,
                "message": f"Attributes set for {target_type}",
                "target_type": target_type,
                "target_id": target_id,
                "attributes": attributes
            }

        except Exception as e:
            logger.error(f"Error setting attributes: {e}")
            return {"success": False, "error": str(e)}

    def analyze_graph(self, file_path: str, include_structure: bool = True,
                     include_metrics: bool = True) -> dict[str, Any]:
        """Analyze a DOT graph file."""
        try:
            if not Path(file_path).exists():
                return {"success": False, "error": f"Graph file not found: {file_path}"}

            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            analysis = {"success": True, "file_path": file_path}

            if include_structure:
                structure = self._analyze_structure(content)
                analysis["structure"] = structure

            if include_metrics:
                metrics = self._calculate_metrics(content)
                analysis["metrics"] = metrics

            # Basic graph info
            analysis["graph_info"] = {
                "file_size": len(content),
                "line_count": len(content.split('\n')),
                "is_directed": self._is_directed_graph(content),
                "graph_type": self._get_graph_type(content),
                "graph_name": self._get_graph_name(content)
            }

            return analysis

        except Exception as e:
            logger.error(f"Error analyzing graph: {e}")
            return {"success": False, "error": str(e)}

    def _analyze_structure(self, content: str) -> dict[str, Any]:
        """Analyze graph structure."""
        # Count nodes
        node_pattern = r'^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*(?:\[.*?\])?\s*;'
        nodes = set()
        for match in re.finditer(node_pattern, content, re.MULTILINE):
            nodes.add(match.group(1))

        # Count edges
        edge_patterns = [
            r'^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*->\s*([a-zA-Z_][a-zA-Z0-9_]*)',  # Directed
            r'^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*--\s*([a-zA-Z_][a-zA-Z0-9_]*)'   # Undirected
        ]

        edges = []
        edge_nodes = set()
        for pattern in edge_patterns:
            for match in re.finditer(pattern, content, re.MULTILINE):
                from_node, to_node = match.groups()
                edges.append((from_node, to_node))
                edge_nodes.add(from_node)
                edge_nodes.add(to_node)

        # Combine explicitly declared nodes with nodes found in edges
        all_nodes = nodes.union(edge_nodes)

        return {
            "total_nodes": len(all_nodes),
            "explicit_nodes": len(nodes),
            "total_edges": len(edges),
            "node_list": sorted(list(all_nodes)),
            "edge_list": edges
        }

    def _calculate_metrics(self, content: str) -> dict[str, Any]:
        """Calculate graph metrics."""
        structure = self._analyze_structure(content)

        # Basic metrics
        metrics = {
            "node_count": structure["total_nodes"],
            "edge_count": structure["total_edges"]
        }

        if structure["total_nodes"] > 0:
            metrics["edge_density"] = structure["total_edges"] / (structure["total_nodes"] * (structure["total_nodes"] - 1) / 2)
        else:
            metrics["edge_density"] = 0

        # Calculate degree information
        node_degrees = {}
        for from_node, to_node in structure["edge_list"]:
            node_degrees[from_node] = node_degrees.get(from_node, 0) + 1
            node_degrees[to_node] = node_degrees.get(to_node, 0) + 1

        if node_degrees:
            degrees = list(node_degrees.values())
            metrics["average_degree"] = sum(degrees) / len(degrees)
            metrics["max_degree"] = max(degrees)
            metrics["min_degree"] = min(degrees)
        else:
            metrics["average_degree"] = 0
            metrics["max_degree"] = 0
            metrics["min_degree"] = 0

        return metrics

    def _is_directed_graph(self, content: str) -> bool:
        """Check if graph is directed."""
        return content.strip().startswith('digraph ') or content.strip().startswith('strict digraph ')

    def _get_graph_type(self, content: str) -> str:
        """Get graph type from content."""
        first_line = content.strip().split('\n')[0].strip()
        if first_line.startswith('strict digraph '):
            return "strict digraph"
        elif first_line.startswith('digraph '):
            return "digraph"
        elif first_line.startswith('strict graph '):
            return "strict graph"
        elif first_line.startswith('graph '):
            return "graph"
        else:
            return "unknown"

    def _get_graph_name(self, content: str) -> str:
        """Get graph name from content."""
        match = re.match(r'^\s*(strict\s+)?(di)?graph\s+([a-zA-Z_][a-zA-Z0-9_]*)', content)
        if match:
            return match.group(3)
        return "unknown"

    def validate_graph(self, file_path: str) -> dict[str, Any]:
        """Validate a DOT graph file."""
        try:
            if not Path(file_path).exists():
                return {"success": False, "error": f"Graph file not found: {file_path}"}

            # Use dot to validate syntax
            cmd = [self.dot_cmd, "-Tplain", file_path]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                return {
                    "success": True,
                    "valid": True,
                    "message": "Graph is valid",
                    "file_path": file_path
                }
            else:
                return {
                    "success": True,
                    "valid": False,
                    "message": "Graph has syntax errors",
                    "errors": result.stderr,
                    "file_path": file_path
                }

        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Validation timed out after 30 seconds"}
        except Exception as e:
            logger.error(f"Error validating graph: {e}")
            return {"success": False, "error": str(e)}

    def list_layouts(self) -> dict[str, Any]:
        """List available Graphviz layout engines."""
        return {
            "success": True,
            "layouts": [
                {
                    "name": "dot",
                    "description": "Hierarchical or layered drawings of directed graphs"
                },
                {
                    "name": "neato",
                    "description": "Spring model layouts for undirected graphs"
                },
                {
                    "name": "fdp",
                    "description": "Spring model layouts for undirected graphs with reduced forces"
                },
                {
                    "name": "sfdp",
                    "description": "Multiscale version of fdp for large graphs"
                },
                {
                    "name": "twopi",
                    "description": "Radial layouts with one node as the center"
                },
                {
                    "name": "circo",
                    "description": "Circular layout suitable for cyclic structures"
                },
                {
                    "name": "osage",
                    "description": "Array-based layouts for clustered graphs"
                },
                {
                    "name": "patchwork",
                    "description": "Squarified treemap layout"
                }
            ],
            "formats": [
                "png", "svg", "pdf", "ps", "eps", "gif", "jpg", "jpeg",
                "dot", "plain", "json", "gv", "gml", "graphml"
            ]
        }


# Initialize processor (conditionally for testing)
try:
    processor = GraphvizProcessor()
except RuntimeError:
    # For testing when Graphviz is not available
    processor = None


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    """List available Graphviz tools."""
    return [
        Tool(
            name="create_graph",
            description="Create a new DOT graph file",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path for the DOT file"
                    },
                    "graph_type": {
                        "type": "string",
                        "enum": ["graph", "digraph", "strict graph", "strict digraph"],
                        "description": "Graph type",
                        "default": "digraph"
                    },
                    "graph_name": {
                        "type": "string",
                        "description": "Graph name",
                        "default": "G"
                    },
                    "attributes": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                        "description": "Graph attributes (optional)"
                    }
                },
                "required": ["file_path"]
            }
        ),
        Tool(
            name="render_graph",
            description="Render a DOT graph to an image",
            inputSchema={
                "type": "object",
                "properties": {
                    "input_file": {
                        "type": "string",
                        "description": "Path to the DOT file"
                    },
                    "output_file": {
                        "type": "string",
                        "description": "Output image file path (optional)"
                    },
                    "format": {
                        "type": "string",
                        "description": "Output format",
                        "default": "png"
                    },
                    "layout": {
                        "type": "string",
                        "enum": ["dot", "neato", "fdp", "sfdp", "twopi", "circo"],
                        "description": "Layout engine",
                        "default": "dot"
                    },
                    "dpi": {
                        "type": "integer",
                        "description": "Output resolution in DPI (optional)"
                    }
                },
                "required": ["input_file"]
            }
        ),
        Tool(
            name="add_node",
            description="Add a node to a DOT graph",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the DOT file"
                    },
                    "node_id": {
                        "type": "string",
                        "description": "Node identifier"
                    },
                    "label": {
                        "type": "string",
                        "description": "Node label (optional)"
                    },
                    "attributes": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                        "description": "Node attributes (optional)"
                    }
                },
                "required": ["file_path", "node_id"]
            }
        ),
        Tool(
            name="add_edge",
            description="Add an edge to a DOT graph",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the DOT file"
                    },
                    "from_node": {
                        "type": "string",
                        "description": "Source node identifier"
                    },
                    "to_node": {
                        "type": "string",
                        "description": "Target node identifier"
                    },
                    "label": {
                        "type": "string",
                        "description": "Edge label (optional)"
                    },
                    "attributes": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                        "description": "Edge attributes (optional)"
                    }
                },
                "required": ["file_path", "from_node", "to_node"]
            }
        ),
        Tool(
            name="set_attributes",
            description="Set attributes for graph, node, or edge",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the DOT file"
                    },
                    "target_type": {
                        "type": "string",
                        "enum": ["graph", "node", "edge"],
                        "description": "Attribute target type"
                    },
                    "target_id": {
                        "type": "string",
                        "description": "Target ID (for node, use '*' for default node attributes)"
                    },
                    "attributes": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                        "description": "Attributes to set"
                    }
                },
                "required": ["file_path", "target_type", "attributes"]
            }
        ),
        Tool(
            name="analyze_graph",
            description="Analyze a DOT graph structure and metrics",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the DOT file"
                    },
                    "include_structure": {
                        "type": "boolean",
                        "description": "Include structural analysis",
                        "default": True
                    },
                    "include_metrics": {
                        "type": "boolean",
                        "description": "Include graph metrics",
                        "default": True
                    }
                },
                "required": ["file_path"]
            }
        ),
        Tool(
            name="validate_graph",
            description="Validate a DOT graph file syntax",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the DOT file"
                    }
                },
                "required": ["file_path"]
            }
        ),
        Tool(
            name="list_layouts",
            description="List available Graphviz layout engines and formats",
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
        if processor is None:
            result = {"success": False, "error": "Graphviz not available"}
        elif name == "create_graph":
            request = CreateGraphRequest(**arguments)
            result = processor.create_graph(
                file_path=request.file_path,
                graph_type=request.graph_type,
                graph_name=request.graph_name,
                attributes=request.attributes
            )

        elif name == "render_graph":
            request = RenderGraphRequest(**arguments)
            result = processor.render_graph(
                input_file=request.input_file,
                output_file=request.output_file,
                format=request.format,
                layout=request.layout,
                dpi=request.dpi
            )

        elif name == "add_node":
            request = AddNodeRequest(**arguments)
            result = processor.add_node(
                file_path=request.file_path,
                node_id=request.node_id,
                label=request.label,
                attributes=request.attributes
            )

        elif name == "add_edge":
            request = AddEdgeRequest(**arguments)
            result = processor.add_edge(
                file_path=request.file_path,
                from_node=request.from_node,
                to_node=request.to_node,
                label=request.label,
                attributes=request.attributes
            )

        elif name == "set_attributes":
            request = SetAttributeRequest(**arguments)
            result = processor.set_attributes(
                file_path=request.file_path,
                target_type=request.target_type,
                target_id=request.target_id,
                attributes=request.attributes
            )

        elif name == "analyze_graph":
            request = AnalyzeGraphRequest(**arguments)
            result = processor.analyze_graph(
                file_path=request.file_path,
                include_structure=request.include_structure,
                include_metrics=request.include_metrics
            )

        elif name == "validate_graph":
            request = ValidateGraphRequest(**arguments)
            result = processor.validate_graph(file_path=request.file_path)

        elif name == "list_layouts":
            result = processor.list_layouts()

        else:
            result = {"success": False, "error": f"Unknown tool: {name}"}

    except Exception as e:
        logger.error(f"Error in {name}: {str(e)}")
        result = {"success": False, "error": str(e)}

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def main():
    """Main server entry point."""
    logger.info("Starting Graphviz MCP Server...")

    from mcp.server.stdio import stdio_server

    logger.info("Waiting for MCP client connection...")
    async with stdio_server() as (read_stream, write_stream):
        logger.info("MCP client connected, starting server...")
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="graphviz-server",
                server_version="0.1.0",
                capabilities={
                    "tools": {},
                    "logging": {},
                },
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())
