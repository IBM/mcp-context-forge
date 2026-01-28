# Mermaid MCP Server

> Author: Mihai Criveti

Comprehensive server for creating, editing, and rendering Mermaid diagrams. Now powered by **FastMCP** for enhanced type safety and automatic validation!

## Features

- **Multiple Diagram Types**: Flowcharts, sequence diagrams, Gantt charts, class diagrams
- **Structured Input**: Create diagrams from data structures
- **Template System**: Built-in templates for common diagram types
- **Validation**: Syntax validation for Mermaid code
- **Multiple Output Formats**: SVG, PNG, PDF export
- **FastMCP Implementation**: Modern decorator-based tools with automatic validation

## Tools

- `create_diagram` - Create and render Mermaid diagrams
- `create_flowchart` - Create flowcharts from structured data
- `create_sequence_diagram` - Create sequence diagrams
- `create_gantt_chart` - Create Gantt charts from task data
- `validate_mermaid` - Validate Mermaid syntax
- `get_templates` - Get diagram templates

## Requirements

- **Mermaid CLI**: Required for rendering diagrams
  ```bash
  npm install -g @mermaid-js/mermaid-cli
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
python -m mermaid_server.server_fastmcp
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
    "mermaid-server": {
      "command": "python",
      "args": ["-m", "mermaid_server.server_fastmcp"],
      "cwd": "/path/to/mermaid_server"
    }
  }
}
```

## Examples

### Create Flowchart

```python
{
  "name": "create_flowchart",
  "arguments": {
    "nodes": [
      {"id": "A", "label": "Start", "shape": "circle"},
      {"id": "B", "label": "Process", "shape": "rect"},
      {"id": "C", "label": "Decision", "shape": "diamond"},
      {"id": "D", "label": "End", "shape": "circle"}
    ],
    "connections": [
      {"from": "A", "to": "B"},
      {"from": "B", "to": "C"},
      {"from": "C", "to": "D", "label": "Yes"},
      {"from": "C", "to": "B", "label": "No"}
    ],
    "direction": "TD",
    "title": "Sample Workflow"
  }
}
```

### Create Sequence Diagram

```python
{
  "name": "create_sequence_diagram",
  "arguments": {
    "participants": ["Client", "Server", "Database"],
    "messages": [
      {"from": "Client", "to": "Server", "message": "Request Data"},
      {"from": "Server", "to": "Database", "message": "Query"},
      {"from": "Database", "to": "Server", "message": "Results", "arrow": "-->"},
      {"from": "Server", "to": "Client", "message": "Response Data", "arrow": "->>"}
    ],
    "title": "API Request Flow"
  }
}
```

### Create Gantt Chart

```python
{
  "name": "create_gantt_chart",
  "arguments": {
    "title": "Project Timeline",
    "tasks": [
      {"name": "Research", "start": "2024-01-01", "duration": "10d"},
      {"name": "Design", "start": "2024-01-11", "duration": "5d"},
      {"name": "Development", "start": "2024-01-16", "end": "2024-02-01"},
      {"name": "Testing", "start": "2024-02-01", "duration": "7d"}
    ]
  }
}
```

### Validate Mermaid Code

```python
{
  "name": "validate_mermaid",
  "arguments": {
    "mermaid_code": "flowchart TD\n    A[Start] --> B[End]"
  }
}
```

## Diagram Types

- **flowchart**: Flow diagrams with various node shapes
- **sequence**: Sequence diagrams for interactions
- **gantt**: Project timeline charts
- **class**: UML class diagrams
- **state**: State machine diagrams
- **er**: Entity-relationship diagrams
- **pie**: Pie charts
- **journey**: User journey maps

## Node Shapes (Flowcharts)

- **rect**: Rectangle (default)
- **circle**: Circle nodes
- **diamond**: Diamond decision nodes
- **round**: Rounded rectangles

## Flow Directions

- **TD**: Top Down (default)
- **TB**: Top to Bottom (same as TD)
- **BT**: Bottom to Top
- **RL**: Right to Left
- **LR**: Left to Right

## Themes

- **default**: Standard theme
- **dark**: Dark mode theme
- **forest**: Forest green theme
- **neutral**: Neutral gray theme

## FastMCP Advantages

The FastMCP implementation provides:

1. **Type-Safe Parameters**: Automatic validation using Pydantic Field constraints
2. **Pattern Validation**: Ensures valid diagram types, formats, and directions
3. **Range Validation**: Width/height constrained with `ge=100, le=5000`
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

- Mermaid CLI must be installed for diagram rendering
- SVG format provides the best quality and scalability
- PNG/PDF formats are useful for embedding in documents
- Templates provide quick starting points for common diagram types
