# Graphviz MCP Server

> Author: Mihai Criveti

A comprehensive MCP server for creating, editing, and rendering Graphviz graphs. Supports DOT language manipulation, graph rendering with multiple layouts, and visualization analysis. Now powered by **FastMCP** for enhanced type safety and automatic validation!

## Features

- **Graph Creation**: Create new DOT graph files with various types and attributes
- **Graph Rendering**: Render graphs to multiple formats (PNG, SVG, PDF, etc.) with different layouts
- **Graph Editing**: Add nodes, edges, and set attributes dynamically
- **Graph Analysis**: Analyze graph structure, calculate metrics, and validate syntax
- **Multiple Layouts**: Support for all Graphviz layout engines (dot, neato, fdp, sfdp, twopi, circo)
- **Format Support**: Wide range of output formats for different use cases
- **FastMCP Implementation**: Modern decorator-based tools with automatic validation

## Tools

- `create_graph` - Create a new DOT graph file with specified type and attributes
- `render_graph` - Render DOT graph to image with layout and format options
- `add_node` - Add nodes to graphs with labels and attributes
- `add_edge` - Add edges between nodes with labels and attributes
- `set_attributes` - Set graph, node, or edge attributes
- `analyze_graph` - Analyze graph structure and calculate metrics
- `validate_graph` - Validate DOT file syntax
- `list_layouts` - List available layout engines and output formats

## Requirements

- **Graphviz**: Must be installed and accessible via command line
  ```bash
  # Ubuntu/Debian
  sudo apt install graphviz

  # macOS
  brew install graphviz

  # Windows: Download from graphviz.org
  ```

## Installation

```bash
# Install in development mode
make dev-install

# Or install normally
make install
```

## Usage

### Running the FastMCP Server

```bash
# Start the server
make dev

# Or directly
python -m graphviz_server.server_fastmcp
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
    "graphviz-server": {
      "command": "python",
      "args": ["-m", "graphviz_server.server_fastmcp"],
      "cwd": "/path/to/graphviz_server"
    }
  }
}
```

## Graph Types

- **graph**: Undirected graph
- **digraph**: Directed graph (default)
- **strict graph**: Undirected graph with no multi-edges
- **strict digraph**: Directed graph with no multi-edges

## Layout Engines

- **dot**: Hierarchical layouts for directed graphs
- **neato**: Spring-model layouts for undirected graphs
- **fdp**: Spring-model with reduced forces
- **sfdp**: Multiscale version for large graphs
- **twopi**: Radial layouts with central node
- **circo**: Circular layouts for cyclic structures
- **osage**: Array-based layouts for clusters
- **patchwork**: Squarified treemap layout

## Output Formats

- **Images**: PNG, SVG, PDF, PS, EPS, GIF, JPG, JPEG
- **Data**: DOT, Plain, JSON, GV, GML, GraphML

## Examples

### Create a Simple Directed Graph
```python
{
  "name": "create_graph",
  "arguments": {
    "file_path": "./flowchart.dot",
    "graph_type": "digraph",
    "graph_name": "Flowchart",
    "attributes": {
      "rankdir": "TB",
      "bgcolor": "white",
      "fontname": "Arial"
    }
  }
}
```

### Add Nodes and Edges
```python
# Add nodes
{
  "name": "add_node",
  "arguments": {
    "file_path": "./flowchart.dot",
    "node_id": "start",
    "label": "Start",
    "attributes": {
      "shape": "ellipse",
      "color": "green",
      "style": "filled"
    }
  }
}

{
  "name": "add_node",
  "arguments": {
    "file_path": "./flowchart.dot",
    "node_id": "process",
    "label": "Process Data",
    "attributes": {
      "shape": "box",
      "color": "lightblue",
      "style": "filled"
    }
  }
}

# Add edge
{
  "name": "add_edge",
  "arguments": {
    "file_path": "./flowchart.dot",
    "from_node": "start",
    "to_node": "process",
    "label": "begin",
    "attributes": {
      "color": "blue",
      "style": "bold"
    }
  }
}
```

### Render Graph
```python
{
  "name": "render_graph",
  "arguments": {
    "input_file": "./flowchart.dot",
    "output_file": "./flowchart.png",
    "format": "png",
    "layout": "dot",
    "dpi": 300
  }
}
```

### Analyze Graph
```python
{
  "name": "analyze_graph",
  "arguments": {
    "file_path": "./flowchart.dot",
    "include_structure": true,
    "include_metrics": true
  }
}
```

### Set Default Node Attributes
```python
{
  "name": "set_attributes",
  "arguments": {
    "file_path": "./flowchart.dot",
    "target_type": "node",
    "target_id": "*",
    "attributes": {
      "fontname": "Arial",
      "fontsize": "12",
      "shape": "box"
    }
  }
}
```

## FastMCP Advantages

The FastMCP implementation provides:

1. **Type-Safe Parameters**: Automatic validation using Pydantic Field constraints
2. **Pattern Validation**: Ensures valid graph types, layouts, formats, and targets
3. **Range Validation**: DPI constrained between 72-600 with `ge=72, le=600`
4. **Cleaner Code**: Decorator-based tool definitions (`@mcp.tool`)
5. **Better Error Handling**: Built-in exception management
6. **Automatic Schema Generation**: No manual JSON schema definitions

## Common Node Shapes

- **box**: Rectangle (default)
- **ellipse**: Oval/ellipse
- **circle**: Circle
- **diamond**: Diamond
- **triangle**: Triangle
- **polygon**: Custom polygon
- **record**: Record-based shape
- **plaintext**: No shape, just text

## Common Attributes

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

## Development

```bash
# Format code
make format

# Run tests
make test

# Lint code
make lint
```

## Validation

The server includes DOT syntax validation using Graphviz itself:

```python
{
  "name": "validate_graph",
  "arguments": {
    "file_path": "./graph.dot"
  }
}
```

## Error Handling

The server provides detailed error messages for:
- Missing Graphviz installation
- Invalid DOT syntax
- Missing files
- Rendering failures
- Invalid attributes or node IDs

## Notes

- Node IDs must be valid identifiers (alphanumeric + underscore)
- Attributes are automatically quoted in DOT output
- Graph analysis includes node count, edge count, density, and degree metrics
- Large graphs may take longer to render depending on layout complexity
