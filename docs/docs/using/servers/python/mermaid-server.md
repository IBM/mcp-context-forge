# Mermaid Server

## Overview

The Mermaid MCP Server provides comprehensive capabilities for creating, editing, and rendering Mermaid diagrams. It supports multiple diagram types including flowcharts, sequence diagrams, Gantt charts, and class diagrams, with structured input options and template systems. The server is powered by FastMCP for enhanced type safety and automatic validation.

### Key Features

- **Multiple Diagram Types**: Flowcharts, sequence diagrams, Gantt charts, class diagrams
- **Structured Input**: Create diagrams from data structures
- **Template System**: Built-in templates for common diagram types
- **Validation**: Syntax validation for Mermaid code
- **Multiple Output Formats**: SVG, PNG, PDF export
- **FastMCP Implementation**: Modern decorator-based tools with automatic validation

## Quick Start

### Prerequisites

**Mermaid CLI must be installed:**

```bash
npm install -g @mermaid-js/mermaid-cli
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
python -m mermaid_server.server_fastmcp

# HTTP bridge for REST API access
make serve-http
```

## Available Tools

### create_diagram
Create and render Mermaid diagrams.

**Parameters:**

- `diagram_type` (required): Type of diagram ("flowchart", "sequence", "gantt", "class", etc.)
- `mermaid_code` (required): Mermaid syntax code
- `title`: Diagram title
- `output_format`: Output format ("svg", "png", "pdf") - default: "svg"
- `output_file`: Path for output file
- `theme`: Mermaid theme ("default", "dark", "forest", "neutral")
- `width`: Output width in pixels (100-5000, default: 800)
- `height`: Output height in pixels (100-5000, default: 600)

### create_flowchart
Create flowcharts from structured data.

**Parameters:**

- `nodes` (required): List of node definitions with id, label, and shape
- `connections` (required): List of connections between nodes
- `direction`: Flow direction ("TD", "TB", "BT", "LR", "RL") - default: "TD"
- `title`: Flowchart title
- `output_format`: Output format - default: "svg"
- `output_file`: Path for output file

### create_sequence_diagram
Create sequence diagrams.

**Parameters:**

- `participants` (required): List of participant names
- `messages` (required): List of message definitions
- `title`: Sequence diagram title
- `output_format`: Output format - default: "svg"
- `output_file`: Path for output file

### create_gantt_chart
Create Gantt charts from task data.

**Parameters:**

- `title` (required): Chart title
- `tasks` (required): List of task definitions with name, start, duration/end
- `output_format`: Output format - default: "svg"
- `output_file`: Path for output file

### validate_mermaid
Validate Mermaid syntax.

**Parameters:**

- `mermaid_code` (required): Mermaid code to validate

### get_templates
Get diagram templates.

**Parameters:**

- `diagram_type`: Specific diagram type to get templates for

## Configuration

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

### Create Flowchart from Structure

```json
{
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
  "title": "Sample Workflow",
  "output_format": "png"
}
```

### Create Sequence Diagram

```json
{
  "participants": ["Client", "Server", "Database"],
  "messages": [
    {"from": "Client", "to": "Server", "message": "Request Data"},
    {"from": "Server", "to": "Database", "message": "Query"},
    {"from": "Database", "to": "Server", "message": "Results", "arrow": "-->"},
    {"from": "Server", "to": "Client", "message": "Response Data", "arrow": "->>"}
  ],
  "title": "API Request Flow",
  "output_format": "svg"
}
```

### Create Gantt Chart

```json
{
  "title": "Project Timeline",
  "tasks": [
    {"name": "Research", "start": "2024-01-01", "duration": "10d"},
    {"name": "Design", "start": "2024-01-11", "duration": "5d"},
    {"name": "Development", "start": "2024-01-16", "end": "2024-02-01"},
    {"name": "Testing", "start": "2024-02-01", "duration": "7d"}
  ],
  "output_format": "pdf"
}
```

### Create Custom Diagram

```json
{
  "diagram_type": "flowchart",
  "mermaid_code": "flowchart TD\n    A[Start] --> B{Decision}\n    B -->|Yes| C[Action 1]\n    B -->|No| D[Action 2]\n    C --> E[End]\n    D --> E",
  "title": "Decision Process",
  "theme": "dark",
  "output_format": "png",
  "width": 1200,
  "height": 800
}
```

### Validate Mermaid Code

```json
{
  "mermaid_code": "flowchart TD\n    A[Start] --> B[End]"
}
```

**Response:**
```json
{
  "success": true,
  "valid": true,
  "message": "Mermaid code is valid",
  "diagram_type": "flowchart",
  "complexity": "simple"
}
```

## Integration

### With MCP Gateway

```bash
# Start the Mermaid server via HTTP
make serve-http

# Register with MCP Gateway
curl -X POST http://localhost:8000/gateways \
  -H "Content-Type: application/json" \
  -d '{
    "name": "mermaid-server",
    "url": "http://localhost:9000",
    "description": "Mermaid diagram creation and rendering server"
  }'
```

### Programmatic Usage

```python
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def create_mermaid_diagram():
    server_params = StdioServerParameters(
        command="python",
        args=["-m", "mermaid_server.server_fastmcp"]
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Create a flowchart
            result = await session.call_tool("create_flowchart", {
                "nodes": [
                    {"id": "start", "label": "Begin", "shape": "circle"},
                    {"id": "process", "label": "Process", "shape": "rect"},
                    {"id": "end", "label": "Finish", "shape": "circle"}
                ],
                "connections": [
                    {"from": "start", "to": "process"},
                    {"from": "process", "to": "end"}
                ],
                "title": "Simple Process"
            })

asyncio.run(create_mermaid_diagram())
```

## Supported Diagram Types

### Flowcharts
- **Purpose**: Process flows, decision trees, workflows
- **Node Shapes**: rect, circle, diamond, round
- **Directions**: TD (Top Down), LR (Left Right), BT (Bottom Top), RL (Right Left)

### Sequence Diagrams
- **Purpose**: System interactions, API flows, communication patterns
- **Features**: Participants, messages, activation boxes, notes
- **Arrow Types**: ->, -->>, -x, --x

### Gantt Charts
- **Purpose**: Project timelines, task scheduling, milestone tracking
- **Features**: Tasks, dependencies, milestones, progress tracking
- **Date Formats**: YYYY-MM-DD, duration in days/weeks

### Class Diagrams
- **Purpose**: Software architecture, object relationships, UML modeling
- **Features**: Classes, inheritance, associations, methods

### State Diagrams
- **Purpose**: State machines, workflow states, system behavior
- **Features**: States, transitions, conditions, actions

### Entity Relationship Diagrams
- **Purpose**: Database design, data modeling, relationships
- **Features**: Entities, attributes, relationships, cardinality

### Pie Charts
- **Purpose**: Data distribution, percentage breakdowns
- **Features**: Segments, labels, percentages

### User Journey Maps
- **Purpose**: User experience flows, customer journeys
- **Features**: Stages, emotions, touchpoints

## Themes and Styling

### Available Themes

- **default**: Standard Mermaid theme
- **dark**: Dark mode theme
- **forest**: Forest green theme
- **neutral**: Neutral gray theme

### Flow Directions

- **TD/TB**: Top Down/Top to Bottom (default)
- **BT**: Bottom to Top
- **RL**: Right to Left
- **LR**: Left to Right

### Node Shapes (Flowcharts)

- **rect**: Rectangle (default)
- **circle**: Circle nodes
- **diamond**: Diamond decision nodes
- **round**: Rounded rectangles

## Advanced Features

### Complex Flowchart Creation

```python
# Create a complex business process flowchart
nodes = [
    {"id": "start", "label": "Start Process", "shape": "circle"},
    {"id": "input", "label": "Collect Input", "shape": "rect"},
    {"id": "validate", "label": "Validate Data", "shape": "diamond"},
    {"id": "process", "label": "Process Request", "shape": "rect"},
    {"id": "approve", "label": "Requires Approval?", "shape": "diamond"},
    {"id": "review", "label": "Manager Review", "shape": "rect"},
    {"id": "complete", "label": "Complete", "shape": "circle"},
    {"id": "reject", "label": "Reject", "shape": "circle"}
]

connections = [
    {"from": "start", "to": "input"},
    {"from": "input", "to": "validate"},
    {"from": "validate", "to": "process", "label": "Valid"},
    {"from": "validate", "to": "reject", "label": "Invalid"},
    {"from": "process", "to": "approve"},
    {"from": "approve", "to": "review", "label": "Yes"},
    {"from": "approve", "to": "complete", "label": "No"},
    {"from": "review", "to": "complete", "label": "Approved"},
    {"from": "review", "to": "reject", "label": "Denied"}
]

await session.call_tool("create_flowchart", {
    "nodes": nodes,
    "connections": connections,
    "title": "Business Process Workflow",
    "direction": "TD"
})
```

### Multi-format Output Generation

```python
# Generate the same diagram in multiple formats
diagram_code = """
flowchart TD
    A[Start] --> B{Decision}
    B -->|Yes| C[Action 1]
    B -->|No| D[Action 2]
    C --> E[End]
    D --> E
"""

formats = ["svg", "png", "pdf"]
for fmt in formats:
    await session.call_tool("create_diagram", {
        "diagram_type": "flowchart",
        "mermaid_code": diagram_code,
        "output_format": fmt,
        "output_file": f"./diagram.{fmt}"
    })
```

### Template-based Diagram Creation

```python
# Get available templates
templates = await session.call_tool("get_templates", {
    "diagram_type": "sequence"
})

# Use a template structure
await session.call_tool("create_sequence_diagram", {
    "participants": ["User", "Frontend", "Backend", "Database"],
    "messages": [
        {"from": "User", "to": "Frontend", "message": "Login Request"},
        {"from": "Frontend", "to": "Backend", "message": "Authenticate"},
        {"from": "Backend", "to": "Database", "message": "Verify Credentials"},
        {"from": "Database", "to": "Backend", "message": "User Data"},
        {"from": "Backend", "to": "Frontend", "message": "Auth Token"},
        {"from": "Frontend", "to": "User", "message": "Login Success"}
    ],
    "title": "User Authentication Flow"
})
```

## Use Cases

### Software Documentation
- System architecture diagrams
- API workflow documentation
- Database relationship diagrams

### Business Process Modeling
- Workflow documentation
- Decision trees
- Process optimization

### Project Management
- Project timelines
- Task dependencies
- Milestone tracking

### Educational Materials
- Concept explanations
- Process illustrations
- System overviews

### Technical Communication
- Code flow documentation
- System integration diagrams
- Troubleshooting guides

## Error Handling

The server provides comprehensive error handling for:

- **Mermaid CLI Installation**: Detection and installation guidance
- **Syntax Errors**: Detailed Mermaid syntax validation
- **Rendering Failures**: Output format and rendering issues
- **File Access**: Permission and directory creation errors
- **Resource Limits**: Large diagram handling and memory management

## Performance Considerations

- Mermaid CLI must be installed for diagram rendering
- SVG format provides the best quality and scalability
- PNG/PDF formats are useful for embedding in documents
- Large diagrams may require increased width/height limits
- Complex diagrams with many nodes may impact rendering performance
