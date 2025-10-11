# LaTeX Server

## Overview

The LaTeX MCP Server provides comprehensive capabilities for LaTeX document creation, editing, and compilation. It supports creating documents from templates, adding content, and compiling to various formats including PDF, DVI, and PS. The server includes built-in templates for articles, letters, beamer presentations, reports, and books.

### Key Features

- **Document Creation**: Create LaTeX documents from scratch or templates
- **Content Management**: Add sections, tables, figures, and arbitrary content
- **Compilation**: Compile LaTeX to PDF, DVI, or PS formats
- **Templates**: Built-in templates for articles, letters, beamer presentations, reports, and books
- **Document Analysis**: Analyze LaTeX document structure and content
- **Multi-format Support**: Support for pdflatex, xelatex, lualatex

## Quick Start

### Prerequisites

**TeX Distribution must be installed:**

```bash
# Ubuntu/Debian
sudo apt install texlive-full

# macOS
brew install --cask mactex

# Windows: Download from tug.org/texlive
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
# Stdio mode (for Claude Desktop, IDEs)
make dev

# HTTP mode (via MCP Gateway)
make serve-http
```

## Available Tools

### create_document
Create a new LaTeX document with specified class and packages.

**Parameters:**

- `file_path` (required): Path where the document will be saved
- `document_class`: LaTeX document class (default: "article")
- `packages`: List of LaTeX packages to include
- `title`: Document title
- `author`: Document author
- `date`: Document date (default: current date)

### compile_document
Compile LaTeX document to PDF or other formats.

**Parameters:**

- `file_path` (required): Path to LaTeX file
- `output_format`: Output format - "pdf", "dvi", or "ps" (default: "pdf")
- `compiler`: LaTeX compiler - "pdflatex", "xelatex", or "lualatex" (default: "pdflatex")
- `output_dir`: Output directory (default: same as input file)
- `clean_aux`: Remove auxiliary files after compilation (default: true)

### add_content
Add arbitrary LaTeX content to a document.

**Parameters:**

- `file_path` (required): Path to LaTeX document
- `content` (required): LaTeX content to add
- `position`: Where to add content - "end" or "before_end" (default: "before_end")

### add_section
Add structured sections, subsections, or subsubsections.

**Parameters:**

- `file_path` (required): Path to LaTeX document
- `title` (required): Section title
- `level`: Section level - "section", "subsection", or "subsubsection" (default: "section")
- `content`: Section content
- `label`: Label for cross-referencing

### add_table
Add formatted tables with optional headers and captions.

**Parameters:**

- `file_path` (required): Path to LaTeX document
- `data` (required): 2D array of table data
- `headers`: List of column headers
- `caption`: Table caption
- `label`: Label for cross-referencing
- `position`: Table position specifier (default: "h")

### add_figure
Add figures with images, captions, and labels.

**Parameters:**

- `file_path` (required): Path to LaTeX document
- `image_path` (required): Path to image file
- `caption`: Figure caption
- `label`: Label for cross-referencing
- `width`: Image width (default: "0.8\\textwidth")
- `position`: Figure position specifier (default: "h")

### analyze_document
Analyze document structure, packages, and statistics.

**Parameters:**

- `file_path` (required): Path to LaTeX document

### create_from_template
Create documents from built-in templates.

**Parameters:**

- `template_type` (required): Template type - "article", "letter", "beamer", "report", or "book"
- `file_path` (required): Path where document will be saved
- `variables`: Dictionary of template variables

## Configuration

### MCP Client Configuration

```json
{
  "mcpServers": {
    "latex-server": {
      "command": "python",
      "args": ["-m", "latex_server.server_fastmcp"],
      "cwd": "/path/to/latex_server"
    }
  }
}
```

## Examples

### Create Article from Template

```json
{
  "template_type": "article",
  "file_path": "./my_paper.tex",
  "variables": {
    "title": "Advanced Machine Learning Techniques",
    "author": "John Doe",
    "abstract": "This paper explores advanced ML techniques...",
    "introduction": "Machine learning has evolved significantly...",
    "conclusion": "These techniques show promise..."
  }
}
```

### Create Basic Document

```json
{
  "file_path": "./document.tex",
  "document_class": "article",
  "packages": ["geometry", "amsmath", "graphicx"],
  "title": "My Document",
  "author": "Author Name"
}
```

### Add Table with Headers

```json
{
  "file_path": "./my_paper.tex",
  "data": [
    ["SVM", "92.5%", "15s"],
    ["Neural Net", "94.1%", "45s"],
    ["Random Forest", "89.7%", "8s"]
  ],
  "headers": ["Algorithm", "Accuracy", "Runtime"],
  "caption": "Performance comparison of different algorithms",
  "label": "tab:performance"
}
```

### Add Figure

```json
{
  "file_path": "./my_paper.tex",
  "image_path": "./images/results_chart.png",
  "caption": "Performance results across different datasets",
  "label": "fig:results",
  "width": "0.8\\textwidth"
}
```

### Compile to PDF

```json
{
  "file_path": "./my_paper.tex",
  "output_format": "pdf",
  "output_dir": "./build",
  "clean_aux": true
}
```

### Add Section with Content

```json
{
  "file_path": "./document.tex",
  "title": "Methodology",
  "level": "section",
  "content": "Our approach consists of three main phases: data collection, analysis, and validation.",
  "label": "sec:methodology"
}
```

## Integration

### With MCP Gateway

```bash
# Start the LaTeX server via HTTP
make serve-http

# Register with MCP Gateway
curl -X POST http://localhost:8000/gateways \
  -H "Content-Type: application/json" \
  -d '{
    "name": "latex-server",
    "url": "http://localhost:9000",
    "description": "LaTeX document creation and compilation server"
  }'
```

### Programmatic Usage

```python
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def create_latex_doc():
    server_params = StdioServerParameters(
        command="python",
        args=["-m", "latex_server.server_fastmcp"]
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Create document from template
            await session.call_tool("create_from_template", {
                "template_type": "article",
                "file_path": "./paper.tex",
                "variables": {
                    "title": "Research Paper",
                    "author": "Researcher"
                }
            })

            # Add content
            await session.call_tool("add_section", {
                "file_path": "./paper.tex",
                "title": "Introduction",
                "content": "This paper presents..."
            })

            # Compile to PDF
            result = await session.call_tool("compile_document", {
                "file_path": "./paper.tex",
                "output_format": "pdf"
            })

asyncio.run(create_latex_doc())
```

## Templates

### Available Templates

1. **Article**: Standard academic article with abstract, sections
2. **Letter**: Business letter format
3. **Beamer**: Presentation slides
4. **Report**: Multi-chapter report with table of contents
5. **Book**: Full book with front/main/back matter

### Template Variables

Templates support variable substitution:

- `{title}` - Document title
- `{author}` - Author name
- `{abstract}` - Abstract content
- `{introduction}` - Introduction text
- `{content}` - Main content
- `{conclusion}` - Conclusion text
- `{recipient}` - Letter recipient
- `{sender}` - Letter sender

### Example Template Usage

```json
{
  "template_type": "letter",
  "file_path": "./business_letter.tex",
  "variables": {
    "sender": "John Doe\\\\123 Main St\\\\City, State",
    "recipient": "Jane Smith\\\\456 Oak Ave\\\\Another City, State",
    "content": "I am writing to follow up on our recent meeting..."
  }
}
```

## Document Classes and Packages

### Supported Document Classes

- `article` - Standard article
- `report` - Multi-chapter report
- `book` - Full book format
- `letter` - Letter format
- `beamer` - Presentation slides
- `memoir` - Flexible book/article class
- `scrartcl`, `scrreprt`, `scrbook` - KOMA-Script classes

### Common Packages

Automatically included packages:

- `inputenc` - UTF-8 input encoding
- `fontenc` - Font encoding
- `geometry` - Page layout
- `graphicx` - Graphics inclusion
- `amsmath`, `amsfonts` - Math support

### Custom Package Loading

```json
{
  "file_path": "./document.tex",
  "document_class": "article",
  "packages": [
    "babel[english]",
    "hyperref",
    "listings",
    "xcolor"
  ]
}
```

## Advanced Features

### Document Analysis

```json
{
  "file_path": "./document.tex"
}
```

**Response:**
```json
{
  "success": true,
  "structure": {
    "document_class": "article",
    "packages": ["geometry", "amsmath", "graphicx"],
    "sections": 5,
    "figures": 3,
    "tables": 2
  },
  "statistics": {
    "line_count": 245,
    "word_count": 1850,
    "character_count": 12450
  },
  "references": {
    "labels": ["sec:intro", "fig:results", "tab:data"],
    "citations": ["author2023", "smith2022"]
  }
}
```

### Multi-format Compilation

```python
# Compile to multiple formats
formats = ["pdf", "dvi", "ps"]
for fmt in formats:
    await session.call_tool("compile_document", {
        "file_path": "./document.tex",
        "output_format": fmt,
        "output_dir": f"./output/{fmt}"
    })
```

### Complex Document Creation

```python
# Create a complete research paper
async def create_research_paper():
    # Start with template
    await session.call_tool("create_from_template", {
        "template_type": "article",
        "file_path": "./paper.tex",
        "variables": {"title": "Research Title", "author": "Author"}
    })

    # Add sections
    sections = [
        {"title": "Introduction", "content": "Introduction text..."},
        {"title": "Methodology", "content": "Methodology description..."},
        {"title": "Results", "content": "Results and analysis..."},
        {"title": "Conclusion", "content": "Concluding remarks..."}
    ]

    for section in sections:
        await session.call_tool("add_section", {
            "file_path": "./paper.tex",
            "title": section["title"],
            "content": section["content"]
        })

    # Add table and figure
    await session.call_tool("add_table", {
        "file_path": "./paper.tex",
        "data": experimental_data,
        "headers": ["Parameter", "Value", "Error"],
        "caption": "Experimental results"
    })

    await session.call_tool("add_figure", {
        "file_path": "./paper.tex",
        "image_path": "./chart.png",
        "caption": "Performance comparison"
    })

    # Compile final document
    await session.call_tool("compile_document", {
        "file_path": "./paper.tex",
        "output_format": "pdf"
    })
```

## Use Cases

### Academic Writing
Create research papers, theses, and academic articles with proper formatting.

### Business Documentation
Generate reports, proposals, and professional documents.

### Presentations
Create beamer slides for academic and business presentations.

### Books and Manuals
Write technical documentation, user manuals, and books.

### Letters and Correspondence
Generate formal letters and business correspondence.

## Compilation Notes

- The server automatically runs multiple compilation passes for references
- Auxiliary files (.aux, .log, etc.) are cleaned by default
- Compilation timeout is set to 2 minutes
- Error logs are captured and returned for debugging

## Error Handling

The server provides detailed error messages including:

- LaTeX compilation errors with line numbers
- Missing file errors
- Syntax errors in LaTeX code
- Package-related issues
- Template variable errors
