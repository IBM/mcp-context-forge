# PowerPoint MCP Server

A **comprehensive and enhanced** Model Context Protocol (MCP) server for creating and editing PowerPoint (.pptx) files using the python-pptx-fix library. This server provides complete PowerPoint automation capabilities with **professional workflow tools**, **template support**, **batch operations**, and **modern 16:9 widescreen format by default** for enterprise-grade presentation automation.

## Features

### 🎯 Core Capabilities
- **Presentation Management**: Create, open, save, clone, and template-based creation
- **Slide Operations**: Add, delete, move, duplicate, and list slides with layout control
- **Text Content**: Set titles, body content, add text boxes with comprehensive formatting
- **Image Handling**: Insert images from files or base64 data, resize and position
- **Shape Management**: Create, modify, and delete various shapes (rectangles, ovals, arrows, etc.)
- **Table Operations**: Create tables, populate data, format cells and content
- **Chart Generation**: Create column, bar, line, and pie charts with data
- **Formatting**: Comprehensive text formatting (fonts, colors, sizes, alignment)
- **Utility Functions**: List shapes, get layouts, set presentation properties

### 🚀 Enhanced Professional Features
- **Modern 16:9 Format**: All presentations default to widescreen format (13.33" x 7.5")
- **Template System**: Create presentations from templates with placeholder replacement
- **Composite Workflows**: Professional slide types (title, agenda, comparison, data, section breaks)
- **Batch Operations**: Multi-slide text replacement and bulk formatting
- **Brand Theme Application**: Consistent styling across presentations
- **Auto-generated Summaries**: Intelligent content extraction for summary slides
- **Format Control**: Switch between 16:9, 4:3, or custom slide dimensions

### 🔒 Security & Enterprise Features
- **Secure Sessions**: UUID-based workspace isolation for multi-user environments
- **File Upload System**: Safe handling of images and templates with validation
- **Download Links**: Secure, expiring download tokens for presentations
- **Path Security**: Comprehensive path validation and directory restrictions
- **Resource Management**: Configurable limits and automatic cleanup
- **Environment Configuration**: Full .env support for deployment flexibility

### 📊 Supported Content Types
- **Text**: Titles, body text, text boxes, bullet points
- **Images**: PNG, JPG, GIF from files or base64 encoded data
- **Shapes**: Rectangle, oval, triangle, arrow, diamond, pentagon, hexagon, octagon, star, heart, smiley
- **Tables**: Multi-row/column tables with formatting and data population
- **Charts**: Column, bar, line, and pie charts with customizable data series
- **Layouts**: Support for all standard PowerPoint slide layouts

## Project Structure

```
pptx_server/
├── pyproject.toml           # Package configuration
├── Makefile                 # Development automation
├── Containerfile           # Container build
├── README.md               # Documentation
├── .gitignore              # Ignore generated files
├── src/
│   └── pptx_server/
│       ├── __init__.py
│       └── server.py       # MCP server (39 tools)
├── tests/
│   └── test_server.py      # Unit tests
├── examples/               # Organized output directories
│   ├── templates/          # Template presentations
│   ├── generated/          # Auto-generated presentations
│   └── demos/              # Demo presentations
├── demo.py                 # Basic demo script
└── enhanced_demo.py        # Comprehensive enterprise demo
```

## Installation

```bash
# Install in development mode
pip install -e ".[dev]"

# Or install just the package
pip install -e .
```

## Usage

### As MCP Server (stdio)
```bash
# Start the server
python -m pptx_server.server

# Or use the make command
make dev
```

### HTTP Download Server
Start the HTTP server for downloading presentations:
```bash
# Start HTTP download server
make serve-http-only

# Or start combined MCP + HTTP server
make serve-combined

# Test downloads
make test-download
```

**Download URLs include filename:**
`http://localhost:9000/download/{token}/filename.pptx`

### Integration with Claude Desktop
Add to your Claude Desktop MCP configuration:
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

## Available Tools

### Presentation Management
- `create_presentation` - Create a new presentation
- `open_presentation` - Open existing presentation
- `save_presentation` - Save presentation to file
- `get_presentation_info` - Get presentation metadata

### Slide Operations
- `add_slide` - Add new slide with specified layout
- `delete_slide` - Remove slide from presentation
- `move_slide` - Reorder slides
- `duplicate_slide` - Copy existing slide
- `list_slides` - Get information about all slides

### Content Management
- `set_slide_title` - Set slide title text
- `set_slide_content` - Set main slide content with bullet points
- `add_text_box` - Create formatted text boxes
- `format_text` - Apply formatting to existing text

### Image Handling
- `add_image` - Insert image from file path
- `add_image_from_base64` - Insert image from base64 data
- `replace_image` - Replace existing image

### Shape Management
- `add_shape` - Create various geometric shapes
- `modify_shape` - Change shape properties (size, position, colors)
- `delete_shape` - Remove shapes from slides

### Table Operations
- `add_table` - Create tables with specified dimensions
- `set_table_cell` - Set individual cell content
- `format_table_cell` - Format cell appearance
- `populate_table` - Fill entire table with 2D data array

### Chart Generation
- `add_chart` - Create charts (column, bar, line, pie)
- `update_chart_data` - Modify chart data (limited support)

### Utility Functions
- `list_shapes` - Get information about all shapes on a slide
- `get_slide_layouts` - List available slide layouts
- `set_presentation_properties` - Set document metadata
- `set_slide_size` - Configure slide dimensions (16:9, 4:3, custom)
- `get_slide_size` - Get current slide dimensions and aspect ratio
- `export_slide_as_image` - Export slide as image (requires additional setup)

### 🚀 Professional Workflow Tools
- `create_title_slide` - Complete professional title slide with subtitle, author, date
- `create_agenda_slide` - Numbered or bulleted agenda with professional formatting
- `create_data_slide` - Data table with optional integrated chart visualization
- `create_comparison_slide` - Two-column comparison layout with dividers
- `create_section_break` - Full-screen section divider with custom styling
- `batch_replace_text` - Replace text across multiple slides with case options
- `apply_brand_theme` - Apply consistent brand colors and fonts across presentation
- `generate_summary_slide` - Auto-extract key points for summary slides

### 📋 Template System
- `create_presentation_from_template` - Create from template with placeholder replacement
- `clone_presentation` - Clone and modify existing presentations

### 🔒 Security & File Management
- `create_secure_session` - Create UUID-based secure workspace
- `upload_file` - Upload files (images, templates) with validation
- `create_download_link` - Generate secure download URLs with expiration
- `list_session_files` - List files in session workspace
- `cleanup_session` - Clean up session resources
- `get_server_status` - Monitor server configuration and statistics

## Examples

### Creating a Professional Business Presentation
```python
# Create new presentation (automatically organized)
await create_presentation("business_review.pptx")  # Goes to examples/generated/

# Create professional title slide
await create_title_slide(
    "business_review.pptx",
    "Q4 Business Review 2024",
    "Performance Analysis & Strategic Outlook",
    "Executive Team",
    "December 2024"
)

# Create agenda slide
agenda_items = ["Executive Summary", "Financial Results", "Market Analysis", "Future Strategy"]
await create_agenda_slide("business_review.pptx", agenda_items)

# Create section break
await create_section_break("business_review.pptx", "FINANCIAL PERFORMANCE", "Q4 Results", "#003366")

# Create data slide with integrated chart
financial_data = [
    ["Quarter", "Revenue", "Profit"],
    ["Q1", "100K", "20K"],
    ["Q2", "150K", "35K"],
    ["Q3", "140K", "32K"],
    ["Q4", "180K", "45K"]
]
await create_data_slide("business_review.pptx", "Quarterly Results", financial_data, include_chart=True)

# Apply brand theme
await apply_brand_theme("business_review.pptx", "#003366", "#666666", "#FF6600", "Calibri")

# Save the presentation
await save_presentation("business_review.pptx")
```

### Using Templates
```python
# Create a template with placeholders (goes to examples/templates/)
await create_presentation("examples/templates/company_template.pptx", "{{COMPANY_NAME}} Report")
await add_slide("examples/templates/company_template.pptx", 1)
await set_slide_title("examples/templates/company_template.pptx", 1, "Welcome {{CLIENT_NAME}}")
await set_slide_content("examples/templates/company_template.pptx", 1, "Project: {{PROJECT_NAME}}\\nDate: {{DATE}}")

# Use template to create customized presentation (output automatically organized)
await create_presentation_from_template(
    "company_template.pptx",  # Automatically found in examples/templates/
    "client_presentation.pptx",  # Goes to examples/generated/
    "Acme Corp Quarterly Report",
    {
        "{{COMPANY_NAME}}": "Acme Corp",
        "{{CLIENT_NAME}}": "John Smith",
        "{{PROJECT_NAME}}": "Digital Transformation",
        "{{DATE}}": "Q4 2024"
    }
)
```

### Modern 16:9 Widescreen Format
```python
# All presentations default to 16:9 widescreen (13.33" x 7.5")
await create_presentation("modern_presentation.pptx", "Widescreen Demo")

# Check current format
size_info = await get_slide_size("modern_presentation.pptx")
# Returns: {"format": "16:9 widescreen", "aspect_ratio": "1.78:1", "is_widescreen": True}

# Switch to 4:3 if needed for legacy compatibility
await set_slide_size("modern_presentation.pptx", "4:3")

# Or use custom dimensions
await set_slide_size("modern_presentation.pptx", "custom", width_inches=12.0, height_inches=9.0)
```

### Batch Operations
```python
# Replace text across entire presentation
await batch_replace_text(
    "presentation.pptx",
    {
        "2024": "2025",
        "preliminary": "final",
        "draft": "approved"
    }
)

# Apply consistent branding
await apply_brand_theme(
    "presentation.pptx",
    primary_color="#0066CC",
    accent_color="#FF6600",
    font_family="Calibri"
)
```

### Adding a Chart
```python
# Prepare chart data
chart_data = {
    "categories": ["Q1", "Q2", "Q3", "Q4"],
    "series": [
        {"name": "Revenue", "values": [100, 150, 120, 200]},
        {"name": "Expenses", "values": [80, 90, 85, 95]}
    ]
}

# Add chart to slide
await add_chart(
    "presentation.pptx",
    slide_index=1,
    data=chart_data,
    chart_type="column",
    title="Quarterly Performance"
)
```

### Creating a Table
```python
# Add table
await add_table("presentation.pptx", 1, rows=3, cols=4)

# Populate with data
table_data = [
    ["Quarter", "Revenue", "Expenses", "Profit"],
    ["Q1", "100K", "80K", "20K"],
    ["Q2", "150K", "90K", "60K"]
]
await populate_table("presentation.pptx", 1, 0, table_data, header_row=True)
```

### Adding Formatted Text Box
```python
await add_text_box(
    "presentation.pptx",
    slide_index=1,
    text="Important Notice",
    left=1.0,
    top=3.0,
    width=4.0,
    height=1.0,
    font_size=24,
    font_color="#FF0000",
    bold=True
)
```

## Development

### Quick Start
```bash
# Install development dependencies
make dev-install

# Format and lint code
make format lint

# Run tests
make test

# Create demo presentation
make demo

# Validate created files
make validate
```

### Testing Tools
```bash
# List available tools
make test-tools

# Test via HTTP
make serve-http
# In another terminal:
make test-http
```

### Container Operations
```bash
# Build container
docker build -t pptx-server -f Containerfile .

# Run container
docker run -it --rm -p 9000:9000 pptx-server

# With volume for presentations
docker run -it --rm -p 9000:9000 -v $(pwd)/presentations:/app/presentations pptx-server
```

## Architecture

The server is built using:
- **python-pptx-fix**: Enhanced version of python-pptx with bug fixes and additional features
- **MCP (Model Context Protocol)**: Standard protocol for AI tool integration
- **FastAPI-style async handlers**: All operations are async-compatible
- **Comprehensive error handling**: Detailed error messages and validation

### Key Components
- `server.py`: Main MCP server implementation with all tool handlers
- `pyproject.toml`: Package configuration with dependencies
- `Makefile`: Development and deployment automation
- `Containerfile`: Container build configuration

## Limitations and Notes

1. **Slide Moving**: Complex slide reordering requires XML manipulation
2. **Image Replacement**: Currently requires delete + add pattern
3. **Chart Data Updates**: Limited support for updating existing charts
4. **Image Export**: Slide-to-image export requires additional libraries
5. **Advanced Animations**: Not supported (python-pptx limitation)

## Dependencies

- **python-pptx-fix**: Core PowerPoint manipulation library
- **Pillow**: Image processing support
- **mcp**: Model Context Protocol server framework
- **pydantic**: Data validation and serialization

## Contributing

1. Install development dependencies: `make dev-install`
2. Follow code formatting: `make format`
3. Run linting: `make lint`
4. Run tests: `make test`
5. Test with demo: `make demo && make validate`

## License

MIT License - See LICENSE file for details.

## Related Projects

- [python-pptx-fix](https://python-pptx-fix.readthedocs.io/): Enhanced python-pptx library
- [MCP](https://modelcontextprotocol.io/): Model Context Protocol specification
- [Claude Desktop](https://claude.ai/): AI assistant supporting MCP servers
