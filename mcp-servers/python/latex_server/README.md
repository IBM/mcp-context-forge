# LaTeX MCP Server

> Author: Mihai Criveti

A comprehensive MCP server for LaTeX document creation, editing, and compilation. Supports creating documents from templates, adding content, and compiling to various formats. Now powered by **FastMCP** for enhanced type safety and automatic validation!

## Features

- **Document Creation**: Create LaTeX documents from scratch or templates
- **Content Management**: Add sections, tables, figures, and arbitrary content
- **Compilation**: Compile LaTeX to PDF, DVI, or PS formats
- **Templates**: Built-in templates for articles, letters, beamer presentations, reports, and books
- **Document Analysis**: Analyze LaTeX document structure and content
- **Multi-format Support**: Support for pdflatex, xelatex, lualatex

## Tools

- `create_document` - Create a new LaTeX document with specified class and packages
- `compile_document` - Compile LaTeX document to PDF or other formats
- `add_content` - Add arbitrary LaTeX content to a document
- `add_section` - Add structured sections, subsections, or subsubsections
- `add_table` - Add formatted tables with optional headers and captions
- `add_figure` - Add figures with images, captions, and labels
- `analyze_document` - Analyze document structure, packages, and statistics
- `create_from_template` - Create documents from built-in templates

## Requirements

- **TeX Distribution**: TeXLive, MiKTeX, or similar
  ```bash
  # Ubuntu/Debian
  sudo apt install texlive-full

  # macOS
  brew install --cask mactex

  # Windows: Download from tug.org/texlive
  ```

## Installation

```bash
# Install in development mode
make dev-install

# Or install normally
make install
```

## Usage

### Stdio Mode (for Claude Desktop, IDEs)

```bash
make dev
```

### HTTP Mode (via ContextForge)

```bash
make serve-http
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

## Examples

### Create Article from Template
```python
{
  "name": "create_from_template",
  "arguments": {
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
}
```

### Add Table
```python
{
  "name": "add_table",
  "arguments": {
    "file_path": "./my_paper.tex",
    "data": [
      ["Method", "Accuracy", "Time"],
      ["SVM", "92.5%", "15s"],
      ["Neural Net", "94.1%", "45s"],
      ["Random Forest", "89.7%", "8s"]
    ],
    "headers": ["Algorithm", "Accuracy", "Runtime"],
    "caption": "Performance comparison of different algorithms",
    "label": "tab:performance"
  }
}
```

### Add Figure
```python
{
  "name": "add_figure",
  "arguments": {
    "file_path": "./my_paper.tex",
    "image_path": "./images/results_chart.png",
    "caption": "Performance results across different datasets",
    "label": "fig:results",
    "width": "0.8\\textwidth"
  }
}
```

### Compile Document
```python
{
  "name": "compile_document",
  "arguments": {
    "file_path": "./my_paper.tex",
    "output_format": "pdf",
    "output_dir": "./build",
    "clean_aux": true
  }
}
```

### Analyze Document
```python
{
  "name": "analyze_document",
  "arguments": {
    "file_path": "./my_paper.tex"
  }
}
```

## Document Classes

Supported document classes:
- `article` - Standard article
- `report` - Multi-chapter report
- `book` - Full book format
- `letter` - Letter format
- `beamer` - Presentation slides
- `memoir` - Flexible book/article class
- `scrartcl`, `scrreprt`, `scrbook` - KOMA-Script classes

## Common Packages

Automatically included packages:
- `inputenc` - UTF-8 input encoding
- `fontenc` - Font encoding
- `geometry` - Page layout
- `graphicx` - Graphics inclusion
- `amsmath`, `amsfonts` - Math support

## Development

```bash
# Format code
make format

# Run tests
make test

# Lint code
make lint
```

## Compilation Notes

- The server automatically runs multiple compilation passes for references
- Auxiliary files (.aux, .log, etc.) are cleaned by default
- Compilation timeout is set to 2 minutes
- Error logs are captured and returned for debugging

## Supported Output Formats

- **PDF**: Via pdflatex, xelatex, or lualatex
- **DVI**: Device Independent format
- **PS**: PostScript format

## Error Handling

The server provides detailed error messages including:
- LaTeX compilation errors
- Missing file errors
- Syntax errors with line numbers
- Package-related issues
