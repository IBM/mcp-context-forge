# PM MCP Server

> Author: Mihai Criveti

Project management-focused FastMCP server delivering planning, scheduling, risk, and reporting tools for PM workflows.

## Features
- Work breakdown and schedule generation with structured schemas
- Critical path and earned value calculations
- Risk, change, and stakeholder management utilities
- Diagram outputs via Graphviz SVG and Mermaid markdown fallbacks
- Template-driven reports (status, RAID, communications)

## Quick Start
```bash
make dev        # stdio transport
make serve-http # http://localhost:8000/mcp/
make test
```

Ensure Graphviz binaries are available when using diagram tools.
