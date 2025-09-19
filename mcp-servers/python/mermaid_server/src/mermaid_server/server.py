#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/mermaid_server/src/mermaid_server/server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Mermaid MCP Server

Comprehensive server for creating, editing, and rendering Mermaid diagrams.
Supports flowcharts, sequence diagrams, Gantt charts, and more.
"""

import asyncio
import json
import logging
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
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
server = Server("mermaid-server")


class CreateDiagramRequest(BaseModel):
    """Request to create a diagram."""
    diagram_type: str = Field(..., description="Type of Mermaid diagram")
    content: str = Field(..., description="Mermaid diagram content")
    output_format: str = Field("svg", description="Output format")
    output_file: Optional[str] = Field(None, description="Output file path")
    theme: str = Field("default", description="Diagram theme")
    width: Optional[int] = Field(None, description="Output width")
    height: Optional[int] = Field(None, description="Output height")


class CreateFlowchartRequest(BaseModel):
    """Request to create flowchart."""
    nodes: List[Dict[str, str]] = Field(..., description="Flowchart nodes")
    connections: List[Dict[str, str]] = Field(..., description="Node connections")
    direction: str = Field("TD", description="Flow direction")
    title: Optional[str] = Field(None, description="Diagram title")
    output_format: str = Field("svg", description="Output format")
    output_file: Optional[str] = Field(None, description="Output file path")


class CreateSequenceRequest(BaseModel):
    """Request to create sequence diagram."""
    participants: List[str] = Field(..., description="Sequence participants")
    messages: List[Dict[str, str]] = Field(..., description="Messages between participants")
    title: Optional[str] = Field(None, description="Diagram title")
    output_format: str = Field("svg", description="Output format")
    output_file: Optional[str] = Field(None, description="Output file path")


class CreateGanttRequest(BaseModel):
    """Request to create Gantt chart."""
    title: str = Field(..., description="Gantt chart title")
    tasks: List[Dict[str, Any]] = Field(..., description="Tasks with dates and dependencies")
    output_format: str = Field("svg", description="Output format")
    output_file: Optional[str] = Field(None, description="Output file path")


class MermaidProcessor:
    """Mermaid diagram processor."""

    def __init__(self):
        """Initialize the processor."""
        self.mermaid_cli_available = self._check_mermaid_cli()

    def _check_mermaid_cli(self) -> bool:
        """Check if Mermaid CLI is available."""
        try:
            result = subprocess.run(
                ["mmdc", "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            logger.warning("Mermaid CLI not available")
            return False

    def create_flowchart(
        self,
        nodes: List[Dict[str, str]],
        connections: List[Dict[str, str]],
        direction: str = "TD",
        title: Optional[str] = None
    ) -> str:
        """Create flowchart Mermaid code."""
        lines = [f"flowchart {direction}"]

        if title:
            lines.insert(0, f"---\ntitle: {title}\n---")

        # Add nodes
        for node in nodes:
            node_id = node.get("id", "")
            node_label = node.get("label", node_id)
            node_shape = node.get("shape", "rect")

            if node_shape == "circle":
                lines.append(f"    {node_id}(({node_label}))")
            elif node_shape == "diamond":
                lines.append(f"    {node_id}{{{node_label}}}")
            elif node_shape == "rect":
                lines.append(f"    {node_id}[{node_label}]")
            elif node_shape == "round":
                lines.append(f"    {node_id}({node_label})")
            else:
                lines.append(f"    {node_id}[{node_label}]")

        # Add connections
        for conn in connections:
            from_node = conn.get("from", "")
            to_node = conn.get("to", "")
            label = conn.get("label", "")
            arrow_type = conn.get("arrow", "-->")

            if label:
                lines.append(f"    {from_node} {arrow_type}|{label}| {to_node}")
            else:
                lines.append(f"    {from_node} {arrow_type} {to_node}")

        return '\n'.join(lines)

    def create_sequence_diagram(
        self,
        participants: List[str],
        messages: List[Dict[str, str]],
        title: Optional[str] = None
    ) -> str:
        """Create sequence diagram Mermaid code."""
        lines = ["sequenceDiagram"]

        if title:
            lines.insert(0, f"---\ntitle: {title}\n---")

        # Add participants
        for participant in participants:
            lines.append(f"    participant {participant}")

        lines.append("")

        # Add messages
        for message in messages:
            from_participant = message.get("from", "")
            to_participant = message.get("to", "")
            message_text = message.get("message", "")
            arrow_type = message.get("arrow", "->")

            if arrow_type == "-->":
                lines.append(f"    {from_participant}-->{to_participant}: {message_text}")
            elif arrow_type == "->>":
                lines.append(f"    {from_participant}->>{to_participant}: {message_text}")
            else:
                lines.append(f"    {from_participant}->{to_participant}: {message_text}")

        return '\n'.join(lines)

    def create_gantt_chart(self, title: str, tasks: List[Dict[str, Any]]) -> str:
        """Create Gantt chart Mermaid code."""
        lines = [
            "gantt",
            f"    title {title}",
            "    dateFormat  YYYY-MM-DD",
            "    axisFormat  %m/%d"
        ]

        for task in tasks:
            task_name = task.get("name", "Task")
            task_id = task.get("id", task_name.lower().replace(" ", "_"))
            start_date = task.get("start", "")
            end_date = task.get("end", "")
            duration = task.get("duration", "")
            status = task.get("status", "")

            if duration:
                task_line = f"    {task_name} :{task_id}, {start_date}, {duration}"
            elif end_date:
                task_line = f"    {task_name} :{task_id}, {start_date}, {end_date}"
            else:
                task_line = f"    {task_name} :{task_id}, {start_date}, 1d"

            if status:
                task_line += f" {status}"

            lines.append(task_line)

        return '\n'.join(lines)

    def render_diagram(
        self,
        mermaid_code: str,
        output_format: str = "svg",
        output_file: Optional[str] = None,
        theme: str = "default",
        width: Optional[int] = None,
        height: Optional[int] = None
    ) -> Dict[str, Any]:
        """Render Mermaid diagram to specified format."""
        if not self.mermaid_cli_available:
            return {
                "success": False,
                "error": "Mermaid CLI not available. Install with: npm install -g @mermaid-js/mermaid-cli"
            }

        try:
            # Create temporary input file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.mmd', delete=False) as f:
                f.write(mermaid_code)
                input_file = f.name

            # Determine output file
            if output_file is None:
                output_file = f"diagram_{uuid4()}.{output_format}"

            # Build command
            cmd = ["mmdc", "-i", input_file, "-o", output_file]

            if theme != "default":
                cmd.extend(["-t", theme])

            if width:
                cmd.extend(["-w", str(width)])

            if height:
                cmd.extend(["-H", str(height)])

            # Execute rendering
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )

            # Clean up input file
            Path(input_file).unlink(missing_ok=True)

            if result.returncode != 0:
                return {
                    "success": False,
                    "error": f"Mermaid rendering failed: {result.stderr}",
                    "stdout": result.stdout
                }

            if not Path(output_file).exists():
                return {
                    "success": False,
                    "error": f"Output file not created: {output_file}"
                }

            return {
                "success": True,
                "output_file": output_file,
                "output_format": output_format,
                "file_size": Path(output_file).stat().st_size,
                "theme": theme,
                "mermaid_code": mermaid_code
            }

        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Rendering timed out after 60 seconds"}
        except Exception as e:
            logger.error(f"Error rendering diagram: {e}")
            return {"success": False, "error": str(e)}

    def validate_mermaid(self, mermaid_code: str) -> Dict[str, Any]:
        """Validate Mermaid diagram syntax."""
        try:
            # Basic validation checks
            lines = mermaid_code.strip().split('\n')
            if not lines:
                return {"valid": False, "error": "Empty diagram"}

            first_line = lines[0].strip()
            valid_diagram_types = [
                "flowchart", "graph", "sequenceDiagram", "classDiagram",
                "stateDiagram", "erDiagram", "gantt", "pie", "journey",
                "gitgraph", "C4Context", "mindmap", "timeline"
            ]

            diagram_type = None
            for dtype in valid_diagram_types:
                if first_line.startswith(dtype):
                    diagram_type = dtype
                    break

            if not diagram_type:
                return {
                    "valid": False,
                    "error": f"Unknown diagram type. Must start with one of: {', '.join(valid_diagram_types)}"
                }

            return {
                "valid": True,
                "diagram_type": diagram_type,
                "line_count": len(lines),
                "estimated_complexity": "low" if len(lines) < 10 else "medium" if len(lines) < 50 else "high"
            }

        except Exception as e:
            return {"valid": False, "error": str(e)}

    def get_diagram_templates(self) -> Dict[str, Any]:
        """Get Mermaid diagram templates."""
        return {
            "flowchart": {
                "template": """flowchart TD
    A[Start] --> B{Decision}
    B -->|Yes| C[Process 1]
    B -->|No| D[Process 2]
    C --> E[End]
    D --> E""",
                "description": "Basic flowchart template"
            },
            "sequence": {
                "template": """sequenceDiagram
    participant A as Alice
    participant B as Bob
    A->>B: Hello Bob, how are you?
    B-->>A: Great!""",
                "description": "Basic sequence diagram template"
            },
            "gantt": {
                "template": """gantt
    title Project Timeline
    dateFormat  YYYY-MM-DD
    section Planning
    Task 1 :a1, 2024-01-01, 30d
    section Development
    Task 2 :after a1, 20d""",
                "description": "Basic Gantt chart template"
            },
            "class": {
                "template": """classDiagram
    class Animal {
        +String name
        +int age
        +makeSound()
    }
    class Dog {
        +String breed
        +bark()
    }
    Animal <|-- Dog""",
                "description": "Basic class diagram template"
            }
        }


# Initialize processor (conditionally for testing)
try:
    processor = MermaidProcessor()
except Exception:
    processor = None


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    """List available Mermaid tools."""
    return [
        Tool(
            name="create_diagram",
            description="Create and optionally render a Mermaid diagram",
            inputSchema={
                "type": "object",
                "properties": {
                    "diagram_type": {
                        "type": "string",
                        "enum": ["flowchart", "sequence", "gantt", "class", "state", "er", "pie", "journey"],
                        "description": "Type of Mermaid diagram"
                    },
                    "content": {
                        "type": "string",
                        "description": "Mermaid diagram content/code"
                    },
                    "output_format": {
                        "type": "string",
                        "enum": ["svg", "png", "pdf"],
                        "description": "Output format for rendering",
                        "default": "svg"
                    },
                    "output_file": {
                        "type": "string",
                        "description": "Output file path (optional)"
                    },
                    "theme": {
                        "type": "string",
                        "enum": ["default", "dark", "forest", "neutral"],
                        "description": "Diagram theme",
                        "default": "default"
                    },
                    "width": {
                        "type": "integer",
                        "description": "Output width in pixels (optional)"
                    },
                    "height": {
                        "type": "integer",
                        "description": "Output height in pixels (optional)"
                    }
                },
                "required": ["diagram_type", "content"]
            }
        ),
        Tool(
            name="create_flowchart",
            description="Create flowchart from structured data",
            inputSchema={
                "type": "object",
                "properties": {
                    "nodes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "label": {"type": "string"},
                                "shape": {"type": "string", "enum": ["rect", "circle", "diamond", "round"]}
                            },
                            "required": ["id", "label"]
                        },
                        "description": "Flowchart nodes"
                    },
                    "connections": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "from": {"type": "string"},
                                "to": {"type": "string"},
                                "label": {"type": "string"},
                                "arrow": {"type": "string"}
                            },
                            "required": ["from", "to"]
                        },
                        "description": "Node connections"
                    },
                    "direction": {
                        "type": "string",
                        "enum": ["TD", "TB", "BT", "RL", "LR"],
                        "description": "Flow direction",
                        "default": "TD"
                    },
                    "title": {"type": "string", "description": "Diagram title (optional)"},
                    "output_format": {
                        "type": "string",
                        "enum": ["svg", "png", "pdf"],
                        "description": "Output format",
                        "default": "svg"
                    },
                    "output_file": {"type": "string", "description": "Output file path (optional)"}
                },
                "required": ["nodes", "connections"]
            }
        ),
        Tool(
            name="create_sequence_diagram",
            description="Create sequence diagram from participants and messages",
            inputSchema={
                "type": "object",
                "properties": {
                    "participants": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Sequence participants"
                    },
                    "messages": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "from": {"type": "string"},
                                "to": {"type": "string"},
                                "message": {"type": "string"},
                                "arrow": {"type": "string", "enum": ["->", "->>", "-->"]}
                            },
                            "required": ["from", "to", "message"]
                        },
                        "description": "Messages between participants"
                    },
                    "title": {"type": "string", "description": "Diagram title (optional)"},
                    "output_format": {
                        "type": "string",
                        "enum": ["svg", "png", "pdf"],
                        "description": "Output format",
                        "default": "svg"
                    },
                    "output_file": {"type": "string", "description": "Output file path (optional)"}
                },
                "required": ["participants", "messages"]
            }
        ),
        Tool(
            name="create_gantt_chart",
            description="Create Gantt chart from task data",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Gantt chart title"
                    },
                    "tasks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "id": {"type": "string"},
                                "start": {"type": "string"},
                                "end": {"type": "string"},
                                "duration": {"type": "string"},
                                "status": {"type": "string"}
                            },
                            "required": ["name", "start"]
                        },
                        "description": "Tasks with timeline information"
                    },
                    "output_format": {
                        "type": "string",
                        "enum": ["svg", "png", "pdf"],
                        "description": "Output format",
                        "default": "svg"
                    },
                    "output_file": {"type": "string", "description": "Output file path (optional)"}
                },
                "required": ["title", "tasks"]
            }
        ),
        Tool(
            name="validate_mermaid",
            description="Validate Mermaid diagram syntax",
            inputSchema={
                "type": "object",
                "properties": {
                    "mermaid_code": {
                        "type": "string",
                        "description": "Mermaid diagram code to validate"
                    }
                },
                "required": ["mermaid_code"]
            }
        ),
        Tool(
            name="get_templates",
            description="Get Mermaid diagram templates",
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
            result = {"success": False, "error": "Mermaid processor not available"}
        elif name == "create_diagram":
            request = CreateDiagramRequest(**arguments)
            # First validate the diagram
            validation = processor.validate_mermaid(request.content)
            if not validation["valid"]:
                result = {"success": False, "error": f"Invalid Mermaid syntax: {validation['error']}"}
            else:
                result = processor.render_diagram(
                    mermaid_code=request.content,
                    output_format=request.output_format,
                    output_file=request.output_file,
                    theme=request.theme,
                    width=request.width,
                    height=request.height
                )

        elif name == "create_flowchart":
            request = CreateFlowchartRequest(**arguments)
            mermaid_code = processor.create_flowchart(
                nodes=request.nodes,
                connections=request.connections,
                direction=request.direction,
                title=request.title
            )
            result = processor.render_diagram(
                mermaid_code=mermaid_code,
                output_format=request.output_format,
                output_file=request.output_file
            )
            if result["success"]:
                result["mermaid_code"] = mermaid_code

        elif name == "create_sequence_diagram":
            request = CreateSequenceRequest(**arguments)
            mermaid_code = processor.create_sequence_diagram(
                participants=request.participants,
                messages=request.messages,
                title=request.title
            )
            result = processor.render_diagram(
                mermaid_code=mermaid_code,
                output_format=request.output_format,
                output_file=request.output_file
            )
            if result["success"]:
                result["mermaid_code"] = mermaid_code

        elif name == "create_gantt_chart":
            request = CreateGanttRequest(**arguments)
            mermaid_code = processor.create_gantt_chart(
                title=request.title,
                tasks=request.tasks
            )
            result = processor.render_diagram(
                mermaid_code=mermaid_code,
                output_format=request.output_format,
                output_file=request.output_file
            )
            if result["success"]:
                result["mermaid_code"] = mermaid_code

        elif name == "validate_mermaid":
            mermaid_code = arguments.get("mermaid_code", "")
            result = processor.validate_mermaid(mermaid_code)

        elif name == "get_templates":
            result = processor.get_diagram_templates()

        else:
            result = {"success": False, "error": f"Unknown tool: {name}"}

    except Exception as e:
        logger.error(f"Error in {name}: {str(e)}")
        result = {"success": False, "error": str(e)}

    return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]


async def main():
    """Main server entry point."""
    logger.info("Starting Mermaid MCP Server...")

    from mcp.server.stdio import stdio_server

    logger.info("Waiting for MCP client connection...")
    async with stdio_server() as (read_stream, write_stream):
        logger.info("MCP client connected, starting server...")
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="mermaid-server",
                server_version="0.1.0",
                capabilities={
                    "tools": {},
                    "logging": {},
                },
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())
