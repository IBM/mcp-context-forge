# Python PowerPoint (PPTX) Server

## Overview

A comprehensive MCP server for creating and editing PowerPoint (.pptx) files with **39 specialized tools** for complete presentation automation. Features professional workflow tools, template support, batch operations, and modern 16:9 widescreen format by default.

**Key Features:**

- 📊 39 comprehensive PowerPoint manipulation tools
- 🎨 Modern 16:9 widescreen format by default
- 📝 Template system with placeholder replacement
- 🔄 Batch operations for multi-slide updates
- 🎯 Professional slide layouts (title, agenda, comparison, data)
- 🖼️ Image handling from files or base64 data
- 📈 Chart generation (column, bar, line, pie)
- 🔒 Secure multi-user session isolation
- 🌐 HTTP download server for generated files

## Quick Start

### Installation

```bash
# Navigate to server directory
cd mcp-servers/python/pptx_server

# Install in development mode
pip install -e ".[dev]"

# Or install just the package
pip install -e .
```

### Running the Server

#### MCP Server Mode (stdio)
```bash
# Start the MCP server
python -m pptx_server.server

# Or use make command
make dev
```

#### With HTTP Download Server
```bash
# Start combined MCP + HTTP server
make serve-combined

# Or HTTP download server only
make serve-http-only
```

### Integration with MCP Gateway

```bash
# Register with MCP Gateway
curl -X POST http://localhost:4444/servers \
  -H "Content-Type: application/json" \
  -d '{
    "name": "pptx-server",
    "transport": "stdio",
    "command": "python -m pptx_server.server",
    "description": "PowerPoint presentation automation server"
  }'
```

## Available Tools

### Presentation Management

#### create_presentation
Create a new PowerPoint presentation.

```json
{
  "tool": "create_presentation",
  "arguments": {
    "title": "Q4 Business Review",
    "slide_width": 13.333,
    "slide_height": 7.5,
    "first_slide_layout": "Title Slide"
  }
}
```

#### open_presentation
Open an existing presentation file.

```json
{
  "tool": "open_presentation",
  "arguments": {
    "file_path": "./templates/corporate_template.pptx"
  }
}
```

#### save_presentation
Save the current presentation.

```json
{
  "tool": "save_presentation",
  "arguments": {
    "file_path": "./output/q4_review.pptx",
    "create_backup": true
  }
}
```

#### create_from_template
Create a presentation from a template with placeholders.

```json
{
  "tool": "create_from_template",
  "arguments": {
    "template_path": "./templates/sales_template.pptx",
    "replacements": {
      "{{QUARTER}}": "Q4 2024",
      "{{REVENUE}}": "$2.5M",
      "{{GROWTH}}": "15%"
    }
  }
}
```

### Slide Operations

#### add_slide
Add a new slide with specified layout.

```json
{
  "tool": "add_slide",
  "arguments": {
    "layout": "Title and Content",
    "title": "Key Achievements",
    "position": 2
  }
}
```

#### duplicate_slide
Duplicate an existing slide.

```json
{
  "tool": "duplicate_slide",
  "arguments": {
    "slide_index": 3,
    "insert_after": true
  }
}
```

#### move_slide
Move a slide to a new position.

```json
{
  "tool": "move_slide",
  "arguments": {
    "from_index": 5,
    "to_index": 2
  }
}
```

#### delete_slide
Remove a slide from the presentation.

```json
{
  "tool": "delete_slide",
  "arguments": {
    "slide_index": 7
  }
}
```

### Content Management

#### set_title
Set the title of a slide.

```json
{
  "tool": "set_title",
  "arguments": {
    "slide_index": 1,
    "title": "2024 Year in Review"
  }
}
```

#### set_content
Set the body content of a slide.

```json
{
  "tool": "set_content",
  "arguments": {
    "slide_index": 2,
    "content": "• Revenue growth: 15%\n• Customer acquisition: +2000\n• Market expansion: 3 new regions"
  }
}
```

#### add_text_box
Add a text box with positioning and formatting.

```json
{
  "tool": "add_text_box",
  "arguments": {
    "slide_index": 3,
    "text": "Important Note",
    "left": 1,
    "top": 1,
    "width": 3,
    "height": 1,
    "font_size": 14,
    "font_color": "#FF0000",
    "bold": true
  }
}
```

#### add_bullet_points
Add formatted bullet points.

```json
{
  "tool": "add_bullet_points",
  "arguments": {
    "slide_index": 4,
    "points": [
      "First main point",
      "  Sub-point A",
      "  Sub-point B",
      "Second main point"
    ],
    "left": 1,
    "top": 2,
    "font_size": 12
  }
}
```

### Image Handling

#### add_image
Insert an image from file.

```json
{
  "tool": "add_image",
  "arguments": {
    "slide_index": 5,
    "image_path": "./images/logo.png",
    "left": 10,
    "top": 0.5,
    "width": 2,
    "height": 1
  }
}
```

#### add_image_from_base64
Insert an image from base64 data.

```json
{
  "tool": "add_image_from_base64",
  "arguments": {
    "slide_index": 6,
    "base64_data": "iVBORw0KGgoAAAANS...",
    "left": 5,
    "top": 3,
    "width": 3,
    "height": 2
  }
}
```

### Shape Management

#### add_shape
Add various shapes to slides.

```json
{
  "tool": "add_shape",
  "arguments": {
    "slide_index": 7,
    "shape_type": "ROUNDED_RECTANGLE",
    "left": 2,
    "top": 2,
    "width": 4,
    "height": 2,
    "fill_color": "#4472C4",
    "line_color": "#2F5597"
  }
}
```

Supported shapes:

- Rectangle, Rounded Rectangle
- Oval, Circle
- Triangle, Diamond
- Pentagon, Hexagon, Octagon
- Arrow (various directions)
- Star, Heart, Smiley

### Table Operations

#### add_table
Create a table with data.

```json
{
  "tool": "add_table",
  "arguments": {
    "slide_index": 8,
    "rows": 4,
    "cols": 3,
    "left": 1,
    "top": 2,
    "width": 8,
    "height": 3,
    "data": [
      ["Product", "Q3", "Q4"],
      ["Product A", "$100K", "$120K"],
      ["Product B", "$150K", "$180K"],
      ["Total", "$250K", "$300K"]
    ],
    "first_row_header": true
  }
}
```

### Chart Generation

#### add_chart
Create various types of charts.

```json
{
  "tool": "add_chart",
  "arguments": {
    "slide_index": 9,
    "chart_type": "COLUMN",
    "left": 1,
    "top": 2,
    "width": 6,
    "height": 4,
    "chart_data": {
      "categories": ["Q1", "Q2", "Q3", "Q4"],
      "series": [
        {"name": "Revenue", "values": [100, 120, 140, 160]},
        {"name": "Profit", "values": [20, 25, 30, 35]}
      ]
    },
    "chart_title": "Quarterly Performance"
  }
}
```

Chart types:

- COLUMN (vertical bars)
- BAR (horizontal bars)
- LINE (line graph)
- PIE (pie chart)

### Professional Workflows

#### create_title_slide
Create a professional title slide.

```json
{
  "tool": "create_title_slide",
  "arguments": {
    "title": "Annual Strategy Review",
    "subtitle": "Fiscal Year 2024",
    "author": "John Doe",
    "date": "December 2024",
    "add_logo": true,
    "logo_path": "./images/company_logo.png"
  }
}
```

#### create_agenda_slide
Create an agenda or table of contents.

```json
{
  "tool": "create_agenda_slide",
  "arguments": {
    "title": "Meeting Agenda",
    "items": [
      "Executive Summary",
      "Financial Performance",
      "Market Analysis",
      "Strategic Initiatives",
      "Q&A Session"
    ],
    "numbered": true
  }
}
```

#### create_comparison_slide
Create a comparison slide with columns.

```json
{
  "tool": "create_comparison_slide",
  "arguments": {
    "title": "Product Comparison",
    "items": [
      {
        "title": "Product A",
        "points": ["Feature 1", "Feature 2", "Feature 3"],
        "color": "#4472C4"
      },
      {
        "title": "Product B",
        "points": ["Feature 1", "Feature 4", "Feature 5"],
        "color": "#70AD47"
      }
    ]
  }
}
```

#### create_data_slide
Create a data-driven slide with charts and tables.

```json
{
  "tool": "create_data_slide",
  "arguments": {
    "title": "Sales Performance",
    "chart_type": "COLUMN",
    "data": {
      "categories": ["Jan", "Feb", "Mar"],
      "series": [
        {"name": "2023", "values": [100, 110, 120]},
        {"name": "2024", "values": [120, 140, 160]}
      ]
    },
    "summary_text": "20% YoY growth achieved"
  }
}
```

### Batch Operations

#### batch_replace_text
Replace text across multiple slides.

```json
{
  "tool": "batch_replace_text",
  "arguments": {
    "old_text": "2023",
    "new_text": "2024",
    "slides": [1, 3, 5, 7]
  }
}
```

#### apply_theme
Apply consistent theme across presentation.

```json
{
  "tool": "apply_theme",
  "arguments": {
    "font_name": "Arial",
    "title_color": "#1F4788",
    "body_color": "#404040",
    "background_color": "#FFFFFF",
    "accent_color": "#4472C4"
  }
}
```

### Utility Functions

#### list_slides
Get information about all slides.

```json
{
  "tool": "list_slides"
}
```

#### get_slide_layouts
List available slide layouts.

```json
{
  "tool": "get_slide_layouts"
}
```

#### list_shapes
List all shapes on a slide.

```json
{
  "tool": "list_shapes",
  "arguments": {
    "slide_index": 2
  }
}
```

#### set_slide_notes
Add speaker notes to a slide.

```json
{
  "tool": "set_slide_notes",
  "arguments": {
    "slide_index": 1,
    "notes": "Welcome everyone. Today we'll cover Q4 results and 2025 strategy."
  }
}
```

## Configuration

### Environment Variables

```bash
# File paths
PPTX_WORKSPACE_DIR=/tmp/pptx_workspace
PPTX_TEMPLATE_DIR=./templates
PPTX_OUTPUT_DIR=./output

# Server settings
PPTX_HTTP_PORT=8080
PPTX_MAX_FILE_SIZE=50MB
PPTX_SESSION_TIMEOUT=3600

# Security
PPTX_SECURE_MODE=true
PPTX_ALLOWED_PATHS=/workspace,/templates
```

## Example Workflows

### Complete Presentation Creation

```python
# 1. Create presentation from template
{
  "tool": "create_from_template",
  "arguments": {
    "template_path": "./templates/quarterly_review.pptx",
    "replacements": {
      "{{QUARTER}}": "Q4 2024",
      "{{YEAR}}": "2024"
    }
  }
}

# 2. Add data slide
{
  "tool": "create_data_slide",
  "arguments": {
    "title": "Revenue Breakdown",
    "chart_type": "PIE",
    "data": {
      "categories": ["Product A", "Product B", "Services"],
      "series": [{"values": [45, 35, 20]}]
    }
  }
}

# 3. Add comparison slide
{
  "tool": "create_comparison_slide",
  "arguments": {
    "title": "Year-over-Year Comparison",
    "items": [
      {"title": "2023", "points": ["$2.1M Revenue", "500 Customers"]},
      {"title": "2024", "points": ["$2.5M Revenue", "750 Customers"]}
    ]
  }
}

# 4. Apply consistent theme
{
  "tool": "apply_theme",
  "arguments": {
    "font_name": "Calibri",
    "title_color": "#0070C0",
    "body_color": "#404040"
  }
}

# 5. Save presentation
{
  "tool": "save_presentation",
  "arguments": {
    "file_path": "./output/q4_review_final.pptx"
  }
}
```

### Batch Update Existing Presentation

```python
# 1. Open existing presentation
{
  "tool": "open_presentation",
  "arguments": {
    "file_path": "./existing_presentation.pptx"
  }
}

# 2. Batch replace outdated information
{
  "tool": "batch_replace_text",
  "arguments": {
    "old_text": "2023",
    "new_text": "2024",
    "slides": "all"
  }
}

# 3. Update all charts with new data
for slide_index in [3, 5, 7]:
  {
    "tool": "update_chart_data",
    "arguments": {
      "slide_index": slide_index,
      "new_data": {...}
    }
  }

# 4. Save as new version
{
  "tool": "save_presentation",
  "arguments": {
    "file_path": "./output/presentation_2024.pptx"
  }
}
```

## Advanced Features

### Template System

Templates support placeholder replacement:

- Text placeholders: `{{VARIABLE_NAME}}`
- Image placeholders: `{{IMAGE:logo}}`
- Chart placeholders: `{{CHART:sales_data}}`

### Secure File Handling

```python
# Upload file securely
{
  "tool": "upload_file",
  "arguments": {
    "file_type": "image",
    "file_data": "base64_encoded_data",
    "filename": "logo.png"
  }
}

# Get download link
{
  "tool": "get_download_link",
  "arguments": {
    "file_path": "./output/presentation.pptx",
    "expires_in": 3600
  }
}
```

## Troubleshooting

### Common Issues

**Missing python-pptx-fix:**
```bash
pip install python-pptx-fix
```

**Template not found:**
```bash
# Check template directory
ls -la ./templates/

# Set correct path
export PPTX_TEMPLATE_DIR=/path/to/templates
```

**Permission errors:**
```bash
# Ensure write permissions
chmod 755 ./output/
chmod 755 /tmp/pptx_workspace/
```

## Performance Tips

- Use templates for faster creation
- Batch operations reduce processing time
- Cache frequently used images
- Optimize image sizes before insertion
- Use appropriate chart types for data

## Related Resources

- [python-pptx Documentation](https://python-pptx.readthedocs.io/)
- [PowerPoint File Format](https://docs.microsoft.com/en-us/office/open-xml/presentation)
- [PPTX Server Source](https://github.com/IBM/mcp-context-forge/tree/main/mcp-servers/python/pptx_server)
