#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/latex_server/src/latex_server/server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

LaTeX MCP Server

A comprehensive MCP server for LaTeX document processing, compilation, and management.
Supports creating, editing, compiling, and analyzing LaTeX documents with various output formats.
"""

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

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
server = Server("latex-server")


class CreateDocumentRequest(BaseModel):
    """Request to create a new LaTeX document."""
    file_path: str = Field(..., description="Path for the new LaTeX file")
    document_class: str = Field("article", description="LaTeX document class")
    title: str | None = Field(None, description="Document title")
    author: str | None = Field(None, description="Document author")
    packages: list[str] | None = Field(None, description="LaTeX packages to include")


class CompileRequest(BaseModel):
    """Request to compile a LaTeX document."""
    file_path: str = Field(..., description="Path to the LaTeX file")
    output_format: str = Field("pdf", description="Output format (pdf, dvi, ps)")
    output_dir: str | None = Field(None, description="Output directory")
    clean_aux: bool = Field(True, description="Clean auxiliary files after compilation")


class AddContentRequest(BaseModel):
    """Request to add content to a LaTeX document."""
    file_path: str = Field(..., description="Path to the LaTeX file")
    content: str = Field(..., description="LaTeX content to add")
    position: str = Field("end", description="Where to add content (end, beginning, after_begin)")


class AddSectionRequest(BaseModel):
    """Request to add a section to a LaTeX document."""
    file_path: str = Field(..., description="Path to the LaTeX file")
    title: str = Field(..., description="Section title")
    level: str = Field("section", description="Section level (section, subsection, subsubsection)")
    content: str | None = Field(None, description="Section content")


class AddTableRequest(BaseModel):
    """Request to add a table to a LaTeX document."""
    file_path: str = Field(..., description="Path to the LaTeX file")
    data: list[list[str]] = Field(..., description="Table data (2D array)")
    headers: list[str] | None = Field(None, description="Column headers")
    caption: str | None = Field(None, description="Table caption")
    label: str | None = Field(None, description="Table label for referencing")


class AddFigureRequest(BaseModel):
    """Request to add a figure to a LaTeX document."""
    file_path: str = Field(..., description="Path to the LaTeX file")
    image_path: str = Field(..., description="Path to the image file")
    caption: str | None = Field(None, description="Figure caption")
    label: str | None = Field(None, description="Figure label for referencing")
    width: str | None = Field(None, description="Figure width (e.g., '0.5\\textwidth')")


class AnalyzeRequest(BaseModel):
    """Request to analyze a LaTeX document."""
    file_path: str = Field(..., description="Path to the LaTeX file")


class TemplateRequest(BaseModel):
    """Request to create a document from template."""
    template_type: str = Field(..., description="Template type (article, letter, beamer, etc.)")
    file_path: str = Field(..., description="Output file path")
    variables: dict[str, str] | None = Field(None, description="Template variables")


class LaTeXProcessor:
    """Handles LaTeX document processing operations."""

    def __init__(self):
        self.latex_cmd = self._find_latex()
        self.pdflatex_cmd = self._find_pdflatex()

    def _find_latex(self) -> str:
        """Find LaTeX executable."""
        possible_commands = ['latex', 'pdflatex', 'xelatex', 'lualatex']
        for cmd in possible_commands:
            if shutil.which(cmd):
                return cmd
        raise RuntimeError("LaTeX not found. Please install TeX Live or MiKTeX.")

    def _find_pdflatex(self) -> str:
        """Find pdflatex executable."""
        if shutil.which('pdflatex'):
            return 'pdflatex'
        elif shutil.which('xelatex'):
            return 'xelatex'
        elif shutil.which('lualatex'):
            return 'lualatex'
        return self.latex_cmd

    def create_document(self, file_path: str, document_class: str = "article",
                       title: str | None = None, author: str | None = None,
                       packages: list[str] | None = None) -> dict[str, Any]:
        """Create a new LaTeX document."""
        try:
            # Create directory if it doesn't exist
            Path(file_path).parent.mkdir(parents=True, exist_ok=True)

            # Default packages
            default_packages = ["inputenc", "fontenc", "geometry", "graphicx", "amsmath", "amsfonts"]
            if packages:
                all_packages = list(set(default_packages + packages))
            else:
                all_packages = default_packages

            # Generate LaTeX content
            content = [
                f"\\documentclass{{{document_class}}}",
                ""
            ]

            # Add packages
            for package in all_packages:
                if package == "inputenc":
                    content.append("\\usepackage[utf8]{inputenc}")
                elif package == "fontenc":
                    content.append("\\usepackage[T1]{fontenc}")
                elif package == "geometry":
                    content.append("\\usepackage[margin=1in]{geometry}")
                else:
                    content.append(f"\\usepackage{{{package}}}")

            content.extend(["", "% Document metadata"])

            if title:
                content.append(f"\\title{{{title}}}")
            if author:
                content.append(f"\\author{{{author}}}")

            content.extend([
                "\\date{\\today}",
                "",
                "\\begin{document}",
                ""
            ])

            if title:
                content.append("\\maketitle")
                content.append("")

            content.extend([
                "% Your content goes here",
                "",
                "\\end{document}"
            ])

            # Write to file
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(content))

            return {
                "success": True,
                "message": f"LaTeX document created at {file_path}",
                "file_path": file_path,
                "document_class": document_class,
                "packages": all_packages
            }

        except Exception as e:
            logger.error(f"Error creating document: {e}")
            return {"success": False, "error": str(e)}

    def compile_document(self, file_path: str, output_format: str = "pdf",
                        output_dir: str | None = None, clean_aux: bool = True) -> dict[str, Any]:
        """Compile a LaTeX document."""
        try:
            input_path = Path(file_path)
            if not input_path.exists():
                return {"success": False, "error": f"LaTeX file not found: {file_path}"}

            # Determine output directory
            if output_dir:
                output_path = Path(output_dir)
                output_path.mkdir(parents=True, exist_ok=True)
            else:
                output_path = input_path.parent

            # Choose appropriate compiler
            if output_format.lower() == "pdf":
                cmd = [self.pdflatex_cmd]
            else:
                cmd = [self.latex_cmd]

            # Add compilation options
            cmd.extend([
                "-interaction=nonstopmode",
                "-output-directory", str(output_path),
                str(input_path)
            ])

            logger.info(f"Running command: {' '.join(cmd)}")

            # Run compilation (may need multiple passes for references)
            output_files = []
            for pass_num in range(2):  # Two passes for references
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    cwd=str(input_path.parent),
                    timeout=120
                )

                if result.returncode != 0:
                    return {
                        "success": False,
                        "error": f"LaTeX compilation failed on pass {pass_num + 1}",
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                        "log_file": self._find_log_file(output_path, input_path.stem)
                    }

            # Find output file
            if output_format.lower() == "pdf":
                output_file = output_path / f"{input_path.stem}.pdf"
            elif output_format.lower() == "dvi":
                output_file = output_path / f"{input_path.stem}.dvi"
            elif output_format.lower() == "ps":
                output_file = output_path / f"{input_path.stem}.ps"
            else:
                output_file = output_path / f"{input_path.stem}.{output_format}"

            if not output_file.exists():
                return {
                    "success": False,
                    "error": f"Output file not found: {output_file}",
                    "stdout": result.stdout
                }

            # Clean auxiliary files
            if clean_aux:
                self._clean_aux_files(output_path, input_path.stem)

            return {
                "success": True,
                "message": f"LaTeX document compiled successfully",
                "input_file": str(input_path),
                "output_file": str(output_file),
                "output_format": output_format,
                "file_size": output_file.stat().st_size
            }

        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Compilation timed out after 2 minutes"}
        except Exception as e:
            logger.error(f"Error compiling document: {e}")
            return {"success": False, "error": str(e)}

    def _find_log_file(self, output_dir: Path, base_name: str) -> str | None:
        """Find and return log file content."""
        log_file = output_dir / f"{base_name}.log"
        if log_file.exists():
            try:
                return log_file.read_text(encoding='utf-8', errors='ignore')[-2000:]  # Last 2000 chars
            except Exception:
                return None
        return None

    def _clean_aux_files(self, output_dir: Path, base_name: str) -> None:
        """Clean auxiliary files after compilation."""
        aux_extensions = ['.aux', '.log', '.toc', '.lof', '.lot', '.fls', '.fdb_latexmk', '.synctex.gz']
        for ext in aux_extensions:
            aux_file = output_dir / f"{base_name}{ext}"
            if aux_file.exists():
                try:
                    aux_file.unlink()
                except Exception:
                    pass

    def add_content(self, file_path: str, content: str, position: str = "end") -> dict[str, Any]:
        """Add content to a LaTeX document."""
        try:
            if not Path(file_path).exists():
                return {"success": False, "error": f"LaTeX file not found: {file_path}"}

            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            # Find insertion point
            if position == "end":
                # Insert before \end{document}
                for i in range(len(lines) - 1, -1, -1):
                    if '\\end{document}' in lines[i]:
                        lines.insert(i, content + '\n\n')
                        break
            elif position == "beginning":
                # Insert after \begin{document}
                for i, line in enumerate(lines):
                    if '\\begin{document}' in line:
                        lines.insert(i + 1, '\n' + content + '\n')
                        break
            elif position == "after_begin":
                # Insert after \maketitle or \begin{document}
                for i, line in enumerate(lines):
                    if '\\maketitle' in line:
                        lines.insert(i + 1, '\n' + content + '\n')
                        break
                    elif '\\begin{document}' in line and i + 1 < len(lines):
                        lines.insert(i + 1, '\n' + content + '\n')
                        break

            # Write back to file
            with open(file_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)

            return {
                "success": True,
                "message": f"Content added to {file_path}",
                "position": position,
                "content_length": len(content)
            }

        except Exception as e:
            logger.error(f"Error adding content: {e}")
            return {"success": False, "error": str(e)}

    def add_section(self, file_path: str, title: str, level: str = "section",
                   content: str | None = None) -> dict[str, Any]:
        """Add a section to a LaTeX document."""
        try:
            section_cmd = f"\\{level}{{{title}}}"
            if content:
                section_content = f"{section_cmd}\n\n{content}"
            else:
                section_content = section_cmd

            return self.add_content(file_path, section_content, "end")

        except Exception as e:
            logger.error(f"Error adding section: {e}")
            return {"success": False, "error": str(e)}

    def add_table(self, file_path: str, data: list[list[str]], headers: list[str] | None = None,
                 caption: str | None = None, label: str | None = None) -> dict[str, Any]:
        """Add a table to a LaTeX document."""
        try:
            if not data:
                return {"success": False, "error": "Table data is empty"}

            # Determine number of columns
            max_cols = max(len(row) for row in data) if data else 0
            if headers and len(headers) > max_cols:
                max_cols = len(headers)

            # Create table
            table_lines = ["\\begin{table}[htbp]", "\\centering"]

            if caption:
                table_lines.append(f"\\caption{{{caption}}}")
            if label:
                table_lines.append(f"\\label{{{label}}}")

            # Table specification
            col_spec = "l" * max_cols
            table_lines.extend([
                f"\\begin{{tabular}}{{{col_spec}}}",
                "\\hline"
            ])

            # Add headers
            if headers:
                header_row = " & ".join(headers[:max_cols])
                table_lines.extend([header_row + " \\\\", "\\hline"])

            # Add data rows
            for row in data:
                # Pad row to max_cols length
                padded_row = row + [""] * (max_cols - len(row))
                data_row = " & ".join(padded_row[:max_cols])
                table_lines.append(data_row + " \\\\")

            table_lines.extend([
                "\\hline",
                "\\end{tabular}",
                "\\end{table}"
            ])

            table_content = '\n'.join(table_lines)
            return self.add_content(file_path, table_content, "end")

        except Exception as e:
            logger.error(f"Error adding table: {e}")
            return {"success": False, "error": str(e)}

    def add_figure(self, file_path: str, image_path: str, caption: str | None = None,
                  label: str | None = None, width: str | None = None) -> dict[str, Any]:
        """Add a figure to a LaTeX document."""
        try:
            if not Path(image_path).exists():
                return {"success": False, "error": f"Image file not found: {image_path}"}

            # Create figure
            figure_lines = ["\\begin{figure}[htbp]", "\\centering"]

            # Add includegraphics
            if width:
                figure_lines.append(f"\\includegraphics[width={width}]{{{image_path}}}")
            else:
                figure_lines.append(f"\\includegraphics{{{image_path}}}")

            if caption:
                figure_lines.append(f"\\caption{{{caption}}}")
            if label:
                figure_lines.append(f"\\label{{{label}}}")

            figure_lines.append("\\end{figure}")

            figure_content = '\n'.join(figure_lines)
            return self.add_content(file_path, figure_content, "end")

        except Exception as e:
            logger.error(f"Error adding figure: {e}")
            return {"success": False, "error": str(e)}

    def analyze_document(self, file_path: str) -> dict[str, Any]:
        """Analyze a LaTeX document."""
        try:
            if not Path(file_path).exists():
                return {"success": False, "error": f"LaTeX file not found: {file_path}"}

            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Extract document class
            doc_class_match = re.search(r'\\documentclass(?:\[.*?\])?\{(.*?)\}', content)
            document_class = doc_class_match.group(1) if doc_class_match else "unknown"

            # Extract packages
            packages = re.findall(r'\\usepackage(?:\[.*?\])?\{(.*?)\}', content)

            # Count sections
            sections = len(re.findall(r'\\section\{', content))
            subsections = len(re.findall(r'\\subsection\{', content))
            subsubsections = len(re.findall(r'\\subsubsection\{', content))

            # Count figures and tables
            figures = len(re.findall(r'\\begin\{figure\}', content))
            tables = len(re.findall(r'\\begin\{table\}', content))

            # Count equations
            equations = len(re.findall(r'\\begin\{equation\}', content))
            math_inline = len(re.findall(r'\$.*?\$', content))

            # Extract title and author
            title_match = re.search(r'\\title\{(.*?)\}', content)
            author_match = re.search(r'\\author\{(.*?)\}', content)

            # Basic statistics
            lines = content.split('\n')
            non_empty_lines = [line for line in lines if line.strip()]
            words = len(content.split())

            # Find potential issues
            issues = []
            if '\\usepackage{' not in content:
                issues.append("No packages imported")
            if '\\maketitle' not in content and ('\\title{' in content or '\\author{' in content):
                issues.append("Title/author defined but \\maketitle not used")

            return {
                "success": True,
                "file_path": file_path,
                "document_class": document_class,
                "packages": packages,
                "structure": {
                    "sections": sections,
                    "subsections": subsections,
                    "subsubsections": subsubsections,
                    "figures": figures,
                    "tables": tables,
                    "equations": equations,
                    "inline_math": math_inline
                },
                "metadata": {
                    "title": title_match.group(1) if title_match else None,
                    "author": author_match.group(1) if author_match else None
                },
                "statistics": {
                    "total_lines": len(lines),
                    "non_empty_lines": len(non_empty_lines),
                    "words": words,
                    "characters": len(content)
                },
                "issues": issues
            }

        except Exception as e:
            logger.error(f"Error analyzing document: {e}")
            return {"success": False, "error": str(e)}

    def create_from_template(self, template_type: str, file_path: str,
                           variables: dict[str, str] | None = None) -> dict[str, Any]:
        """Create a document from a template."""
        try:
            templates = {
                "article": self._get_article_template(),
                "letter": self._get_letter_template(),
                "beamer": self._get_beamer_template(),
                "report": self._get_report_template(),
                "book": self._get_book_template()
            }

            if template_type not in templates:
                return {
                    "success": False,
                    "error": f"Unknown template type: {template_type}",
                    "available_templates": list(templates.keys())
                }

            template_content = templates[template_type]

            # Replace variables
            if variables:
                for key, value in variables.items():
                    template_content = template_content.replace(f"{{{{{key}}}}}", value)

            # Create directory if needed
            Path(file_path).parent.mkdir(parents=True, exist_ok=True)

            # Write template to file
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(template_content)

            return {
                "success": True,
                "message": f"Document created from {template_type} template",
                "file_path": file_path,
                "template_type": template_type,
                "variables_used": list(variables.keys()) if variables else []
            }

        except Exception as e:
            logger.error(f"Error creating from template: {e}")
            return {"success": False, "error": str(e)}

    def _get_article_template(self) -> str:
        return '''\\documentclass[12pt]{article}
\\usepackage[utf8]{inputenc}
\\usepackage[T1]{fontenc}
\\usepackage[margin=1in]{geometry}
\\usepackage{graphicx}
\\usepackage{amsmath}
\\usepackage{amsfonts}
\\usepackage{amssymb}

\\title{{{title}}}
\\author{{{author}}}
\\date{\\today}

\\begin{document}

\\maketitle

\\begin{abstract}
{{abstract}}
\\end{abstract}

\\section{Introduction}
{{introduction}}

\\section{Conclusion}
{{conclusion}}

\\end{document}'''

    def _get_letter_template(self) -> str:
        return '''\\documentclass{letter}
\\usepackage[utf8]{inputenc}
\\usepackage[T1]{fontenc}

\\signature{{{sender}}}
\\address{{{sender_address}}}

\\begin{document}

\\begin{letter}{{{recipient_address}}}

\\opening{Dear {{recipient}},}

{{content}}

\\closing{Sincerely,}

\\end{letter}

\\end{document}'''

    def _get_beamer_template(self) -> str:
        return '''\\documentclass{beamer}
\\usepackage[utf8]{inputenc}
\\usepackage[T1]{fontenc}

\\title{{{title}}}
\\author{{{author}}}
\\date{\\today}

\\begin{document}

\\frame{\\titlepage}

\\begin{frame}
\\frametitle{Outline}
\\tableofcontents
\\end{frame}

\\section{Introduction}

\\begin{frame}
\\frametitle{Introduction}
{{introduction}}
\\end{frame}

\\section{Conclusion}

\\begin{frame}
\\frametitle{Conclusion}
{{conclusion}}
\\end{frame}

\\end{document}'''

    def _get_report_template(self) -> str:
        return '''\\documentclass[12pt]{report}
\\usepackage[utf8]{inputenc}
\\usepackage[T1]{fontenc}
\\usepackage[margin=1in]{geometry}
\\usepackage{graphicx}
\\usepackage{amsmath}

\\title{{{title}}}
\\author{{{author}}}
\\date{\\today}

\\begin{document}

\\maketitle
\\tableofcontents

\\chapter{Introduction}
{{introduction}}

\\chapter{Methodology}
{{methodology}}

\\chapter{Results}
{{results}}

\\chapter{Conclusion}
{{conclusion}}

\\end{document}'''

    def _get_book_template(self) -> str:
        return '''\\documentclass[12pt]{book}
\\usepackage[utf8]{inputenc}
\\usepackage[T1]{fontenc}
\\usepackage[margin=1in]{geometry}
\\usepackage{graphicx}
\\usepackage{amsmath}

\\title{{{title}}}
\\author{{{author}}}
\\date{\\today}

\\begin{document}

\\frontmatter
\\maketitle
\\tableofcontents

\\mainmatter

\\chapter{Introduction}
{{introduction}}

\\chapter{Main Content}
{{content}}

\\chapter{Conclusion}
{{conclusion}}

\\backmatter

\\end{document}'''


# Initialize processor (conditionally for testing)
try:
    processor = LaTeXProcessor()
except RuntimeError:
    # For testing when LaTeX is not available
    processor = None


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    """List available LaTeX tools."""
    return [
        Tool(
            name="create_document",
            description="Create a new LaTeX document",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path for the new LaTeX file"
                    },
                    "document_class": {
                        "type": "string",
                        "description": "LaTeX document class (article, report, book, etc.)",
                        "default": "article"
                    },
                    "title": {
                        "type": "string",
                        "description": "Document title (optional)"
                    },
                    "author": {
                        "type": "string",
                        "description": "Document author (optional)"
                    },
                    "packages": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Additional LaTeX packages to include (optional)"
                    }
                },
                "required": ["file_path"]
            }
        ),
        Tool(
            name="compile_document",
            description="Compile a LaTeX document to PDF or other formats",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the LaTeX file"
                    },
                    "output_format": {
                        "type": "string",
                        "description": "Output format (pdf, dvi, ps)",
                        "default": "pdf"
                    },
                    "output_dir": {
                        "type": "string",
                        "description": "Output directory (optional)"
                    },
                    "clean_aux": {
                        "type": "boolean",
                        "description": "Clean auxiliary files after compilation",
                        "default": True
                    }
                },
                "required": ["file_path"]
            }
        ),
        Tool(
            name="add_content",
            description="Add content to a LaTeX document",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the LaTeX file"
                    },
                    "content": {
                        "type": "string",
                        "description": "LaTeX content to add"
                    },
                    "position": {
                        "type": "string",
                        "enum": ["end", "beginning", "after_begin"],
                        "description": "Where to add content",
                        "default": "end"
                    }
                },
                "required": ["file_path", "content"]
            }
        ),
        Tool(
            name="add_section",
            description="Add a section to a LaTeX document",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the LaTeX file"
                    },
                    "title": {
                        "type": "string",
                        "description": "Section title"
                    },
                    "level": {
                        "type": "string",
                        "enum": ["section", "subsection", "subsubsection"],
                        "description": "Section level",
                        "default": "section"
                    },
                    "content": {
                        "type": "string",
                        "description": "Section content (optional)"
                    }
                },
                "required": ["file_path", "title"]
            }
        ),
        Tool(
            name="add_table",
            description="Add a table to a LaTeX document",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the LaTeX file"
                    },
                    "data": {
                        "type": "array",
                        "items": {
                            "type": "array",
                            "items": {"type": "string"}
                        },
                        "description": "Table data (2D array)"
                    },
                    "headers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Column headers (optional)"
                    },
                    "caption": {
                        "type": "string",
                        "description": "Table caption (optional)"
                    },
                    "label": {
                        "type": "string",
                        "description": "Table label for referencing (optional)"
                    }
                },
                "required": ["file_path", "data"]
            }
        ),
        Tool(
            name="add_figure",
            description="Add a figure to a LaTeX document",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the LaTeX file"
                    },
                    "image_path": {
                        "type": "string",
                        "description": "Path to the image file"
                    },
                    "caption": {
                        "type": "string",
                        "description": "Figure caption (optional)"
                    },
                    "label": {
                        "type": "string",
                        "description": "Figure label for referencing (optional)"
                    },
                    "width": {
                        "type": "string",
                        "description": "Figure width (e.g., '0.5\\\\textwidth') (optional)"
                    }
                },
                "required": ["file_path", "image_path"]
            }
        ),
        Tool(
            name="analyze_document",
            description="Analyze a LaTeX document structure and content",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the LaTeX file"
                    }
                },
                "required": ["file_path"]
            }
        ),
        Tool(
            name="create_from_template",
            description="Create a document from a template",
            inputSchema={
                "type": "object",
                "properties": {
                    "template_type": {
                        "type": "string",
                        "enum": ["article", "letter", "beamer", "report", "book"],
                        "description": "Template type"
                    },
                    "file_path": {
                        "type": "string",
                        "description": "Output file path"
                    },
                    "variables": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                        "description": "Template variables (optional)"
                    }
                },
                "required": ["template_type", "file_path"]
            }
        )
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict[str, Any]) -> Sequence[TextContent | ImageContent | EmbeddedResource]:
    """Handle tool calls."""
    try:
        if processor is None:
            result = {"success": False, "error": "LaTeX not available"}
        elif name == "create_document":
            request = CreateDocumentRequest(**arguments)
            result = processor.create_document(
                file_path=request.file_path,
                document_class=request.document_class,
                title=request.title,
                author=request.author,
                packages=request.packages
            )

        elif name == "compile_document":
            request = CompileRequest(**arguments)
            result = processor.compile_document(
                file_path=request.file_path,
                output_format=request.output_format,
                output_dir=request.output_dir,
                clean_aux=request.clean_aux
            )

        elif name == "add_content":
            request = AddContentRequest(**arguments)
            result = processor.add_content(
                file_path=request.file_path,
                content=request.content,
                position=request.position
            )

        elif name == "add_section":
            request = AddSectionRequest(**arguments)
            result = processor.add_section(
                file_path=request.file_path,
                title=request.title,
                level=request.level,
                content=request.content
            )

        elif name == "add_table":
            request = AddTableRequest(**arguments)
            result = processor.add_table(
                file_path=request.file_path,
                data=request.data,
                headers=request.headers,
                caption=request.caption,
                label=request.label
            )

        elif name == "add_figure":
            request = AddFigureRequest(**arguments)
            result = processor.add_figure(
                file_path=request.file_path,
                image_path=request.image_path,
                caption=request.caption,
                label=request.label,
                width=request.width
            )

        elif name == "analyze_document":
            request = AnalyzeRequest(**arguments)
            result = processor.analyze_document(file_path=request.file_path)

        elif name == "create_from_template":
            request = TemplateRequest(**arguments)
            result = processor.create_from_template(
                template_type=request.template_type,
                file_path=request.file_path,
                variables=request.variables
            )

        else:
            result = {"success": False, "error": f"Unknown tool: {name}"}

    except Exception as e:
        logger.error(f"Error in {name}: {str(e)}")
        result = {"success": False, "error": str(e)}

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def main():
    """Main server entry point."""
    logger.info("Starting LaTeX MCP Server...")

    from mcp.server.stdio import stdio_server

    logger.info("Waiting for MCP client connection...")
    async with stdio_server() as (read_stream, write_stream):
        logger.info("MCP client connected, starting server...")
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="latex-server",
                server_version="0.1.0",
                capabilities={
                    "tools": {},
                    "logging": {},
                },
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())
