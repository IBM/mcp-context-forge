# Graphviz Server

## Overview

The Graphviz MCP Server provides comprehensive capabilities for creating, editing, and rendering Graphviz graphs. It supports DOT language manipulation, graph rendering with multiple layouts, and visualization analysis. The server is powered by FastMCP for enhanced type safety and automatic validation.

### Key Features

- **Graph Creation**: Create new DOT graph files with various types and attributes
- **Graph Rendering**: Render graphs to multiple formats (PNG, SVG, PDF, etc.) with different layouts
- **Graph Editing**: Add nodes, edges, and set attributes dynamically
- **Graph Analysis**: Analyze graph structure, calculate metrics, and validate syntax
- **Multiple Layouts**: Support for all Graphviz layout engines (dot, neato, fdp, sfdp, twopi, circo)
- **Format Support**: Wide range of output formats for different use cases
- **FastMCP Implementation**: Modern decorator-based tools with automatic validation

## Quick Start

### Prerequisites

**Graphviz must be installed and accessible via command line:**

```bash
# Ubuntu/Debian
sudo apt install graphviz

# macOS
brew install graphviz

# Windows: Download from graphviz.org
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
# Start the FastMCP server
make dev

# Or directly
python -m graphviz_server.server_fastmcp

# HTTP bridge for REST API access
make serve-http
```

## Available Tools

### create_graph
Create a new DOT graph file with specified type and attributes.

**Parameters:**

- `file_path` (required): Path where the graph file will be saved
- `graph_type`: "graph", "digraph", "strict graph", or "strict digraph" (default: "digraph")
- `graph_name`: Name of the graph (default: "G")
- `attributes`: Dictionary of graph attributes

### render_graph
Render DOT graph to image with layout and format options.

**Parameters:**

- `input_file` (required): Path to DOT file
- `output_file` (required): Path for output image
- `format`: Output format (default: "png")
- `layout`: Layout engine (default: "dot")
- `dpi`: Resolution in DPI (range: 72-600, default: 96)

### add_node
Add nodes to graphs with labels and attributes.

**Parameters:**

- `file_path` (required): Path to DOT file
- `node_id` (required): Unique node identifier
- `label`: Node label (default: same as node_id)
- `attributes`: Dictionary of node attributes

### add_edge
Add edges between nodes with labels and attributes.

**Parameters:**

- `file_path` (required): Path to DOT file
- `from_node` (required): Source node ID
- `to_node` (required): Target node ID
- `label`: Edge label
- `attributes`: Dictionary of edge attributes

### set_attributes
Set graph, node, or edge attributes.

**Parameters:**

- `file_path` (required): Path to DOT file
- `target_type` (required): "graph", "node", or "edge"
- `target_id`: Specific node/edge ID (use "*" for defaults)
- `attributes` (required): Dictionary of attributes to set

### analyze_graph
Analyze graph structure and calculate metrics.

**Parameters:**

- `file_path` (required): Path to DOT file
- `include_structure`: Include structural analysis (default: true)
- `include_metrics`: Include graph metrics (default: true)

### validate_graph
Validate DOT file syntax.

**Parameters:**

- `file_path` (required): Path to DOT file

### list_layouts
List available layout engines and output formats.

## Configuration

### MCP Client Configuration

```json
{
  "mcpServers": {
    "graphviz-server": {
      "command": "python",
      "args": ["-m", "graphviz_server.server_fastmcp"],
      "cwd": "/path/to/graphviz_server"
    }
  }
}
```

## Examples

### Create a Simple Directed Graph

```json
{
  "file_path": "./flowchart.dot",
  "graph_type": "digraph",
  "graph_name": "Flowchart",
  "attributes": {
    "rankdir": "TB",
    "bgcolor": "white",
    "fontname": "Arial"
  }
}
```

### Add Nodes with Styling

```json
{
  "file_path": "./flowchart.dot",
  "node_id": "start",
  "label": "Start",
  "attributes": {
    "shape": "ellipse",
    "color": "green",
    "style": "filled"
  }
}
```

```json
{
  "file_path": "./flowchart.dot",
  "node_id": "process",
  "label": "Process Data",
  "attributes": {
    "shape": "box",
    "color": "lightblue",
    "style": "filled"
  }
}
```

### Add Styled Edge

```json
{
  "file_path": "./flowchart.dot",
  "from_node": "start",
  "to_node": "process",
  "label": "begin",
  "attributes": {
    "color": "blue",
    "style": "bold"
  }
}
```

### Render Graph to Image

```json
{
  "input_file": "./flowchart.dot",
  "output_file": "./flowchart.png",
  "format": "png",
  "layout": "dot",
  "dpi": 300
}
```

### Analyze Graph Structure

```json
{
  "file_path": "./flowchart.dot",
  "include_structure": true,
  "include_metrics": true
}
```

**Response:**
```json
{
  "success": true,
  "structure": {
    "node_count": 5,
    "edge_count": 6,
    "graph_type": "digraph",
    "is_connected": true
  },
  "metrics": {
    "density": 0.3,
    "average_degree": 2.4,
    "max_degree": 4
  },
  "nodes": ["start", "process", "decision", "end"],
  "edges": [
    {"from": "start", "to": "process"},
    {"from": "process", "to": "decision"}
  ]
}
```

### Set Default Node Attributes

```json
{
  "file_path": "./flowchart.dot",
  "target_type": "node",
  "target_id": "*",
  "attributes": {
    "fontname": "Arial",
    "fontsize": "12",
    "shape": "box"
  }
}
```

## Integration

### With ContextForge

```bash
# Start the Graphviz server via HTTP
make serve-http

# Register with ContextForge
curl -X POST http://localhost:8000/gateways \
  -H "Content-Type: application/json" \
  -d '{
    "name": "graphviz-server",
    "url": "http://localhost:9000",
    "description": "Graph visualization and rendering server"
  }'
```

### Programmatic Usage

```python
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def create_graph():
    server_params = StdioServerParameters(
        command="python",
        args=["-m", "graphviz_server.server_fastmcp"]
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Create a new graph
            await session.call_tool("create_graph", {
                "file_path": "./test.dot",
                "graph_type": "digraph"
            })

            # Add nodes
            await session.call_tool("add_node", {
                "file_path": "./test.dot",
                "node_id": "A",
                "label": "Start"
            })

            # Render graph
            await session.call_tool("render_graph", {
                "input_file": "./test.dot",
                "output_file": "./test.png",
                "format": "png"
            })

asyncio.run(create_graph())
```

## Graph Types and Layouts

### Graph Types

- **graph**: Undirected graph
- **digraph**: Directed graph (default)
- **strict graph**: Undirected graph with no multi-edges
- **strict digraph**: Directed graph with no multi-edges

### Layout Engines

- **dot**: Hierarchical layouts for directed graphs
- **neato**: Spring-model layouts for undirected graphs
- **fdp**: Spring-model with reduced forces
- **sfdp**: Multiscale version for large graphs
- **twopi**: Radial layouts with central node
- **circo**: Circular layouts for cyclic structures
- **osage**: Array-based layouts for clusters
- **patchwork**: Squarified treemap layout

### Output Formats

- **Images**: PNG, SVG, PDF, PS, EPS, GIF, JPG, JPEG
- **Data**: DOT, Plain, JSON, GV, GML, GraphML

## Styling and Attributes

### Common Node Shapes

- **box**: Rectangle (default)
- **ellipse**: Oval/ellipse
- **circle**: Circle
- **diamond**: Diamond
- **triangle**: Triangle
- **polygon**: Custom polygon
- **record**: Record-based shape
- **plaintext**: No shape, just text

### Graph Attributes

- `rankdir`: Layout direction (TB, LR, BT, RL)
- `bgcolor`: Background color
- `fontname`: Default font
- `fontsize`: Default font size
- `label`: Graph title
- `splines`: Edge routing (line, curved, ortho)

### Node Attributes

- `shape`: Node shape
- `color`: Border color
- `fillcolor`: Fill color
- `style`: Visual style (filled, dashed, bold)
- `fontcolor`: Text color
- `width`, `height`: Node dimensions

### Edge Attributes

- `color`: Edge color
- `style`: Edge style (solid, dashed, dotted, bold)
- `arrowhead`: Arrow style (normal, diamond, dot, none)
- `weight`: Edge weight for layout
- `constraint`: Whether edge affects ranking

## Use Cases

### Flowcharts and Process Diagrams
Create business process flows, decision trees, and workflow diagrams.

### Network Topology Diagrams
Visualize computer networks, system architectures, and infrastructure.

### Organizational Charts
Build company hierarchies and reporting structures.

### Data Flow Diagrams
Show data movement through systems and processes.

### State Machine Diagrams
Model system states and transitions.

### Dependency Graphs
Visualize software dependencies and build relationships.

## Advanced Features

### Complex Graph Creation

```python
# Create a complete workflow
async def create_workflow():
    # Create base graph
    await session.call_tool("create_graph", {
        "file_path": "./workflow.dot",
        "attributes": {"rankdir": "TB", "bgcolor": "lightgray"}
    })

    # Add decision nodes
    for i, step in enumerate(workflow_steps):
        await session.call_tool("add_node", {
            "file_path": "./workflow.dot",
            "node_id": f"step_{i}",
            "label": step["name"],
            "attributes": {"shape": "diamond" if step["type"] == "decision" else "box"}
        })

    # Connect nodes
    for connection in workflow_connections:
        await session.call_tool("add_edge", {
            "file_path": "./workflow.dot",
            "from_node": connection["from"],
            "to_node": connection["to"],
            "label": connection.get("condition", "")
        })
```

### Batch Rendering

```python
# Render to multiple formats
formats = ["png", "svg", "pdf"]
for fmt in formats:
    await session.call_tool("render_graph", {
        "input_file": "./graph.dot",
        "output_file": f"./graph.{fmt}",
        "format": fmt,
        "layout": "dot"
    })
```

## Error Handling

The server provides detailed error messages for:

- **Missing Graphviz Installation**: Clear instructions for installation
- **Invalid DOT Syntax**: Syntax error details with line numbers
- **Missing Files**: File not found errors
- **Rendering Failures**: Layout or format-specific issues
- **Invalid Attributes**: Unsupported attribute warnings
