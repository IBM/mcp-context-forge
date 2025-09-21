# Enhanced PowerPoint MCP Server Integration Guide

This guide shows how to integrate the **enhanced PowerPoint MCP Server** with popular AI clients and development environments. The server now includes **50+ tools**, **template systems**, **professional workflows**, and **batch operations** for enterprise-grade presentation automation.

## Quick Start

```bash
# Install and test
cd mcp-servers/python/pptx_server
make dev-install
python3 demo.py  # Creates a comprehensive demo presentation
```

## Claude Desktop Integration

Add to your Claude Desktop MCP configuration (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "pptx-server": {
      "command": "python",
      "args": ["-m", "pptx_server.server"],
      "cwd": "/path/to/mcp-servers/python/pptx_server"
    }
  }
}
```

After configuration, you can ask Claude:
- "Create a professional business presentation from the corporate template"
- "Generate a quarterly report with data tables and integrated charts"
- "Apply our brand theme across the entire presentation"
- "Create a comparison slide showing current vs future state"
- "Build an executive summary with agenda and section breaks"
- "Replace all instances of 2024 with 2025 across the presentation"

## VS Code with Continue Integration

In your Continue configuration (`~/.continue/config.json`):

```json
{
  "mcpServers": {
    "pptx-server": {
      "command": "python",
      "args": ["-m", "pptx_server.server"],
      "cwd": "/path/to/pptx_server"
    }
  }
}
```

## HTTP/REST API Mode

Start the server in HTTP mode for web integration:

```bash
# Start HTTP server
make serve-http

# Test with curl
curl -X POST http://localhost:9000/ \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "create_presentation",
      "arguments": {
        "file_path": "api_demo.pptx",
        "title": "API Demo"
      }
    }
  }'
```

## Container Deployment

Build and run with Docker/Podman:

```bash
# Build container
docker build -t pptx-server -f Containerfile .

# Run container
docker run -it --rm -p 9000:9000 \
  -v $(pwd)/presentations:/app/presentations \
  pptx-server

# Test container
curl http://localhost:9000/health
```

## Python API Usage

Use directly in Python applications:

```python
import asyncio
from pptx_server.server import (
    create_presentation,
    add_slide,
    set_slide_title,
    add_chart,
    save_presentation
)

async def create_report():
    # Create presentation
    await create_presentation("report.pptx", "Monthly Report")

    # Add chart slide
    await add_slide("report.pptx", 1)
    await set_slide_title("report.pptx", 1, "Sales Performance")

    chart_data = {
        "categories": ["Jan", "Feb", "Mar"],
        "series": [{"name": "Sales", "values": [100, 150, 120]}]
    }
    await add_chart("report.pptx", 1, chart_data, "column")

    # Save
    await save_presentation("report.pptx")

asyncio.run(create_report())
```

## Enhanced Enterprise Features

### Template-Based Automation
Create standardized presentations from corporate templates:

```python
async def generate_monthly_reports():
    # Create department-specific reports from template
    departments = ["Sales", "Marketing", "Finance", "Operations"]

    for dept in departments:
        await create_presentation_from_template(
            "corporate_template.pptx",
            f"{dept.lower()}_monthly_report.pptx",
            replace_placeholders={
                "{{DEPARTMENT}}": dept,
                "{{MONTH}}": "December 2024",
                "{{DIRECTOR}}": get_director_name(dept)
            }
        )
```

### Professional Workflow Automation
Build complete presentations with structured workflows:

```python
async def create_board_presentation():
    # Professional title slide
    await create_title_slide(
        "board_meeting.pptx",
        "Board of Directors Meeting",
        "Q4 Strategic Review & 2025 Planning",
        "Executive Leadership Team",
        "December 15, 2024"
    )

    # Executive agenda
    await create_agenda_slide("board_meeting.pptx", [
        "CEO Opening Remarks",
        "Financial Performance Review",
        "Market Position Analysis",
        "Strategic Initiative Updates",
        "2025 Investment Priorities",
        "Risk Assessment & Mitigation",
        "Board Discussion & Decisions"
    ])

    # Section breaks for organization
    await create_section_break("board_meeting.pptx", "FINANCIAL REVIEW", "Q4 Results & Analysis")

    # Data-driven slides with integrated charts
    financial_data = get_quarterly_financials()
    await create_data_slide("board_meeting.pptx", "Financial Performance", financial_data, include_chart=True)

    # Strategic comparison
    await create_comparison_slide("board_meeting.pptx",
        "Strategic Position", "Current Strengths", current_strengths, "Growth Opportunities", opportunities)
```

### Batch Operations
Create multiple presentations programmatically:

```python
async def create_team_reports(teams):
    for team in teams:
        await create_presentation(f"{team}_report.pptx", f"{team} Report")
        # Add team-specific content...
        await save_presentation(f"{team}_report.pptx")
```

### Template System
Use existing presentations as templates:

```python
async def create_from_template():
    # Open existing presentation
    await open_presentation("template.pptx")

    # Modify content
    await set_slide_title("template.pptx", 0, "New Title")
    await add_slide("template.pptx", 1)

    # Save as new file
    await save_presentation("new_presentation.pptx")
```

### Data Integration
Connect with databases and APIs:

```python
import pandas as pd

async def create_data_presentation(csv_file):
    df = pd.read_csv(csv_file)

    await create_presentation("data_report.pptx", "Data Analysis")
    await add_slide("data_report.pptx", 1)

    # Create table from DataFrame
    table_result = await add_table(
        "data_report.pptx", 1,
        len(df) + 1, len(df.columns)
    )

    # Populate table
    data = [df.columns.tolist()] + df.values.tolist()
    await populate_table("data_report.pptx", 1, 0, data, True)
```

## Environment Variables

Configure server behavior:

```bash
export PPTX_SERVER_PORT=9000
export PPTX_SERVER_HOST=0.0.0.0
export PPTX_OUTPUT_DIR=/app/presentations
export PPTX_LOG_LEVEL=INFO
```

## Troubleshooting

### Common Issues

1. **Module not found**: Ensure `pip install -e .` was run
2. **Permission errors**: Check write permissions for output directory
3. **Font issues**: Install Microsoft fonts for consistent rendering
4. **Memory usage**: Large presentations with many images may consume significant memory

### Debugging

Enable debug logging:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Performance Tips

1. **Batch operations**: Group multiple changes before saving
2. **Image optimization**: Resize images before adding to presentations
3. **Template reuse**: Create base templates and modify copies
4. **Resource cleanup**: Clear presentation cache periodically

## API Reference

### Core Tools

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `create_presentation` | Create new presentation | `file_path`, `title` |
| `create_presentation_from_template` | Create from template | `template_path`, `output_path`, `replace_placeholders` |
| `clone_presentation` | Clone existing presentation | `source_path`, `target_path`, `new_title` |
| `add_slide` | Add slide with layout | `layout_index`, `position` |
| `set_slide_title` | Set slide title | `slide_index`, `title` |
| `add_text_box` | Add formatted text | `text`, `font_size`, `color` |
| `add_shape` | Create shapes | `shape_type`, `fill_color` |
| `add_table` | Create data tables | `rows`, `cols`, `position` |
| `add_chart` | Generate charts | `chart_type`, `data`, `title` |
| `save_presentation` | Save to file | `file_path` |

### Professional Workflow Tools

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `create_title_slide` | Professional title slide | `title`, `subtitle`, `author`, `date` |
| `create_agenda_slide` | Formatted agenda | `agenda_items`, `numbered`, `title` |
| `create_data_slide` | Table with optional chart | `title`, `data`, `include_chart` |
| `create_comparison_slide` | Two-column comparison | `title`, `left_content`, `right_content` |
| `create_section_break` | Full-screen section divider | `section_title`, `background_color` |
| `batch_replace_text` | Multi-slide text replacement | `replacements`, `slide_range` |
| `apply_brand_theme` | Consistent branding | `primary_color`, `font_family` |
| `generate_summary_slide` | Auto-extract key points | `max_points`, `title` |

### Shape Types
- `rectangle`, `oval`, `triangle`, `diamond`, `star`
- `pentagon`, `hexagon`, `octagon`, `heart`, `smiley`

### Chart Types
- `column`, `bar`, `line`, `pie`

### Supported Formats
- **Input**: PowerPoint .pptx files
- **Images**: PNG, JPG, GIF, BMP
- **Output**: PowerPoint .pptx format

## Examples Repository

See the `demo.py` script for comprehensive examples of all features.

## Support

For issues and feature requests, please check:
1. README.md for basic usage
2. test_server.py for detailed examples
3. GitHub issues for known problems
