#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/mermaid_server/src/mermaid_server/server_fastmcp.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Mermaid FastMCP Server

Comprehensive server for creating, editing, and rendering Mermaid diagrams.
Supports flowcharts, sequence diagrams, Gantt charts, and more.
Powered by FastMCP for enhanced type safety and automatic validation.
"""

import logging
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

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
mcp = FastMCP("mermaid-server")


class MermaidProcessor:
    """Mermaid diagram processor."""

    def __init__(self):
        """Initialize the processor."""
        self.mermaid_cli_available = self._check_mermaid_cli()

    def _check_mermaid_cli(self) -> bool:
        """Check if Mermaid CLI is available."""
        try:
            result = subprocess.run(
                ["mmdc", "--version"], capture_output=True, text=True, timeout=5
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            logger.warning("Mermaid CLI not available")
            return False

    def create_flowchart(
        self,
        nodes: list[dict[str, str]],
        connections: list[dict[str, str]],
        direction: str = "TD",
        title: str | None = None,
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

        return "\n".join(lines)

    def create_sequence_diagram(
        self, participants: list[str], messages: list[dict[str, str]], title: str | None = None
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

        return "\n".join(lines)

    def create_gantt_chart(self, title: str, tasks: list[dict[str, Any]]) -> str:
        """Create Gantt chart Mermaid code."""
        lines = [
            "gantt",
            f"    title {title}",
            "    dateFormat  YYYY-MM-DD",
            "    axisFormat  %m/%d",
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

        return "\n".join(lines)

    def render_diagram(
        self,
        mermaid_code: str,
        output_format: str = "svg",
        output_file: str | None = None,
        theme: str = "default",
        width: int | None = None,
        height: int | None = None,
    ) -> dict[str, Any]:
        """Render Mermaid diagram to specified format."""
        if not self.mermaid_cli_available:
            return {
                "success": False,
                "error": "Mermaid CLI not available. Install with: npm install -g @mermaid-js/mermaid-cli",
            }

        try:
            # Create temporary input file
            with tempfile.NamedTemporaryFile(mode="w", suffix=".mmd", delete=False) as f:
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
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            # Clean up input file
            Path(input_file).unlink(missing_ok=True)

            if result.returncode != 0:
                return {
                    "success": False,
                    "error": f"Mermaid rendering failed: {result.stderr}",
                    "stdout": result.stdout,
                }

            if not Path(output_file).exists():
                return {"success": False, "error": f"Output file not created: {output_file}"}

            return {
                "success": True,
                "output_file": output_file,
                "output_format": output_format,
                "file_size": Path(output_file).stat().st_size,
                "theme": theme,
                "mermaid_code": mermaid_code,
            }

        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Rendering timed out after 60 seconds"}
        except Exception as e:
            logger.error(f"Error rendering diagram: {e}")
            return {"success": False, "error": str(e)}

    def validate_mermaid(self, mermaid_code: str) -> dict[str, Any]:
        """Validate Mermaid diagram syntax."""
        try:
            # Basic validation checks
            lines = mermaid_code.strip().split("\n")
            if not lines:
                return {"valid": False, "error": "Empty diagram"}

            first_line = lines[0].strip()
            valid_diagram_types = [
                "flowchart",
                "graph",
                "sequenceDiagram",
                "classDiagram",
                "stateDiagram",
                "erDiagram",
                "gantt",
                "pie",
                "journey",
                "gitgraph",
                "C4Context",
                "mindmap",
                "timeline",
            ]

            diagram_type = None
            for dtype in valid_diagram_types:
                if first_line.startswith(dtype):
                    diagram_type = dtype
                    break

            if not diagram_type:
                return {
                    "valid": False,
                    "error": f"Unknown diagram type. Must start with one of: {', '.join(valid_diagram_types)}",
                }

            return {
                "valid": True,
                "diagram_type": diagram_type,
                "line_count": len(lines),
                "estimated_complexity": "low"
                if len(lines) < 10
                else "medium"
                if len(lines) < 50
                else "high",
            }

        except Exception as e:
            return {"valid": False, "error": str(e)}

    def get_diagram_templates(self) -> dict[str, Any]:
        """Get Mermaid diagram templates."""
        return {
            "flowchart": {
                "template": """flowchart TD
    A[Start] --> B{Decision}
    B -->|Yes| C[Process 1]
    B -->|No| D[Process 2]
    C --> E[End]
    D --> E""",
                "description": "Basic flowchart template",
            },
            "sequence": {
                "template": """sequenceDiagram
    participant A as Alice
    participant B as Bob
    A->>B: Hello Bob, how are you?
    B-->>A: Great!""",
                "description": "Basic sequence diagram template",
            },
            "gantt": {
                "template": """gantt
    title Project Timeline
    dateFormat  YYYY-MM-DD
    section Planning
    Task 1 :a1, 2024-01-01, 30d
    section Development
    Task 2 :after a1, 20d""",
                "description": "Basic Gantt chart template",
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
                "description": "Basic class diagram template",
            },
        }


# Initialize processor (conditionally for testing)
try:
    processor = MermaidProcessor()
except Exception:
    processor = None


# Tool definitions using FastMCP decorators
@mcp.tool(description="Create and optionally render a Mermaid diagram")
async def create_diagram(
    diagram_type: str = Field(
        ...,
        pattern="^(flowchart|sequence|gantt|class|state|er|pie|journey)$",
        description="Type of Mermaid diagram",
    ),
    content: str = Field(..., description="Mermaid diagram content/code"),
    output_format: str = Field("svg", pattern="^(svg|png|pdf)$", description="Output format"),
    output_file: str | None = Field(None, description="Output file path"),
    theme: str = Field(
        "default", pattern="^(default|dark|forest|neutral)$", description="Diagram theme"
    ),
    width: int | None = Field(None, ge=100, le=5000, description="Output width in pixels"),
    height: int | None = Field(None, ge=100, le=5000, description="Output height in pixels"),
) -> dict[str, Any]:
    """Create and render a Mermaid diagram."""
    if processor is None:
        return {"success": False, "error": "Mermaid processor not available"}

    # First validate the diagram
    validation = processor.validate_mermaid(content)
    if not validation["valid"]:
        return {"success": False, "error": f"Invalid Mermaid syntax: {validation['error']}"}

    return processor.render_diagram(
        mermaid_code=content,
        output_format=output_format,
        output_file=output_file,
        theme=theme,
        width=width,
        height=height,
    )


@mcp.tool(description="Create flowchart from structured data")
async def create_flowchart(
    nodes: list[dict[str, str]] = Field(
        ..., description="Flowchart nodes with id, label, and optional shape"
    ),
    connections: list[dict[str, str]] = Field(
        ..., description="Node connections with from, to, optional label and arrow"
    ),
    direction: str = Field("TD", pattern="^(TD|TB|BT|RL|LR)$", description="Flow direction"),
    title: str | None = Field(None, description="Diagram title"),
    output_format: str = Field("svg", pattern="^(svg|png|pdf)$", description="Output format"),
    output_file: str | None = Field(None, description="Output file path"),
) -> dict[str, Any]:
    """Create a flowchart from structured data."""
    if processor is None:
        return {"success": False, "error": "Mermaid processor not available"}

    mermaid_code = processor.create_flowchart(
        nodes=nodes, connections=connections, direction=direction, title=title
    )

    result = processor.render_diagram(
        mermaid_code=mermaid_code, output_format=output_format, output_file=output_file
    )

    if result.get("success"):
        result["mermaid_code"] = mermaid_code

    return result


@mcp.tool(description="Create sequence diagram from participants and messages")
async def create_sequence_diagram(
    participants: list[str] = Field(..., description="Sequence participants"),
    messages: list[dict[str, str]] = Field(
        ..., description="Messages with from, to, message, and optional arrow type"
    ),
    title: str | None = Field(None, description="Diagram title"),
    output_format: str = Field("svg", pattern="^(svg|png|pdf)$", description="Output format"),
    output_file: str | None = Field(None, description="Output file path"),
) -> dict[str, Any]:
    """Create a sequence diagram from participants and messages."""
    if processor is None:
        return {"success": False, "error": "Mermaid processor not available"}

    mermaid_code = processor.create_sequence_diagram(
        participants=participants, messages=messages, title=title
    )

    result = processor.render_diagram(
        mermaid_code=mermaid_code, output_format=output_format, output_file=output_file
    )

    if result.get("success"):
        result["mermaid_code"] = mermaid_code

    return result


@mcp.tool(description="Create Gantt chart from task data")
async def create_gantt_chart(
    title: str = Field(..., description="Gantt chart title"),
    tasks: list[dict[str, Any]] = Field(
        ..., description="Tasks with name, start, and optional end/duration/status"
    ),
    output_format: str = Field("svg", pattern="^(svg|png|pdf)$", description="Output format"),
    output_file: str | None = Field(None, description="Output file path"),
) -> dict[str, Any]:
    """Create a Gantt chart from task data."""
    if processor is None:
        return {"success": False, "error": "Mermaid processor not available"}

    mermaid_code = processor.create_gantt_chart(title=title, tasks=tasks)

    result = processor.render_diagram(
        mermaid_code=mermaid_code, output_format=output_format, output_file=output_file
    )

    if result.get("success"):
        result["mermaid_code"] = mermaid_code

    return result


@mcp.tool(description="Validate Mermaid diagram syntax")
async def validate_mermaid(
    mermaid_code: str = Field(..., description="Mermaid diagram code to validate"),
) -> dict[str, Any]:
    """Validate Mermaid diagram syntax."""
    if processor is None:
        return {"valid": False, "error": "Mermaid processor not available"}

    return processor.validate_mermaid(mermaid_code)


@mcp.tool(description="Get Mermaid diagram templates")
async def get_templates() -> dict[str, Any]:
    """Get Mermaid diagram templates."""
    if processor is None:
        return {"error": "Mermaid processor not available"}

    return processor.get_diagram_templates()


def main():
    """Main entry point for the FastMCP server."""
    import argparse

    parser = argparse.ArgumentParser(description="Mermaid FastMCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="Transport mode (stdio or http)",
    )
    parser.add_argument("--host", default="0.0.0.0", help="HTTP host")
    parser.add_argument("--port", type=int, default=9012, help="HTTP port")

    args = parser.parse_args()

    if args.transport == "http":
        logger.info(f"Starting Mermaid FastMCP Server on HTTP at {args.host}:{args.port}")
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        logger.info("Starting Mermaid FastMCP Server on stdio")
        mcp.run()


if __name__ == "__main__":
    main()
