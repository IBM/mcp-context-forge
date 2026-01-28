#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/latex_server/src/latex_server/server_fastmcp.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

LaTeX MCP Server - FastMCP Implementation

A comprehensive MCP server for LaTeX document processing, compilation, and management.
Supports creating, editing, compiling, and analyzing LaTeX documents with various output formats.
"""

import logging
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

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
mcp = FastMCP("latex-server")


class LaTeXProcessor:
    """Handles LaTeX document processing operations."""

    def __init__(self):
        self.latex_cmd = self._find_latex()
        self.pdflatex_cmd = self._find_pdflatex()

    def _find_latex(self) -> str:
        """Find LaTeX executable."""
        possible_commands = ["latex", "pdflatex", "xelatex", "lualatex"]
        for cmd in possible_commands:
            if shutil.which(cmd):
                return cmd
        raise RuntimeError("LaTeX not found. Please install TeX Live or MiKTeX.")

    def _find_pdflatex(self) -> str:
        """Find pdflatex executable."""
        if shutil.which("pdflatex"):
            return "pdflatex"
        elif shutil.which("xelatex"):
            return "xelatex"
        elif shutil.which("lualatex"):
            return "lualatex"
        return self.latex_cmd

    def create_document(
        self,
        file_path: str,
        document_class: str = "article",
        title: str | None = None,
        author: str | None = None,
        packages: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a new LaTeX document."""
        try:
            # Create directory if it doesn't exist
            Path(file_path).parent.mkdir(parents=True, exist_ok=True)

            # Default packages
            default_packages = [
                "inputenc",
                "fontenc",
                "geometry",
                "graphicx",
                "amsmath",
                "amsfonts",
            ]
            if packages:
                all_packages = list(set(default_packages + packages))
            else:
                all_packages = default_packages

            # Generate LaTeX content
            content = [f"\\documentclass{{{document_class}}}", ""]

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

            content.extend(["\\date{\\today}", "", "\\begin{document}", ""])

            if title:
                content.append("\\maketitle")
                content.append("")

            content.extend(["% Your content goes here", "", "\\end{document}"])

            # Write to file
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("\n".join(content))

            return {
                "success": True,
                "message": f"LaTeX document created at {file_path}",
                "file_path": file_path,
                "document_class": document_class,
                "packages": all_packages,
            }

        except Exception as e:
            logger.error(f"Error creating document: {e}")
            return {"success": False, "error": str(e)}

    def compile_document(
        self,
        file_path: str,
        output_format: str = "pdf",
        output_dir: str | None = None,
        clean_aux: bool = True,
    ) -> dict[str, Any]:
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
            cmd.extend(
                ["-interaction=nonstopmode", "-output-directory", str(output_path), str(input_path)]
            )

            logger.info(f"Running command: {' '.join(cmd)}")

            # Run compilation (may need multiple passes for references)
            output_files = []
            for pass_num in range(2):  # Two passes for references
                result = subprocess.run(
                    cmd, capture_output=True, text=True, cwd=str(input_path.parent), timeout=120
                )

                if result.returncode != 0:
                    return {
                        "success": False,
                        "error": f"LaTeX compilation failed on pass {pass_num + 1}",
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                        "log_file": self._find_log_file(output_path, input_path.stem),
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
                    "stdout": result.stdout,
                }

            # Clean auxiliary files
            if clean_aux:
                self._clean_aux_files(output_path, input_path.stem)

            return {
                "success": True,
                "message": "LaTeX document compiled successfully",
                "input_file": str(input_path),
                "output_file": str(output_file),
                "output_format": output_format,
                "file_size": output_file.stat().st_size,
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
                return log_file.read_text(encoding="utf-8", errors="ignore")[
                    -2000:
                ]  # Last 2000 chars
            except Exception:
                return None
        return None

    def _clean_aux_files(self, output_dir: Path, base_name: str) -> None:
        """Clean auxiliary files after compilation."""
        aux_extensions = [
            ".aux",
            ".log",
            ".toc",
            ".lof",
            ".lot",
            ".fls",
            ".fdb_latexmk",
            ".synctex.gz",
        ]
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

            with open(file_path, encoding="utf-8") as f:
                lines = f.readlines()

            # Find insertion point
            if position == "end":
                # Insert before \end{document}
                for i in range(len(lines) - 1, -1, -1):
                    if "\\end{document}" in lines[i]:
                        lines.insert(i, content + "\n\n")
                        break
            elif position == "beginning":
                # Insert after \begin{document}
                for i, line in enumerate(lines):
                    if "\\begin{document}" in line:
                        lines.insert(i + 1, "\n" + content + "\n")
                        break
            elif position == "after_begin":
                # Insert after \maketitle or \begin{document}
                for i, line in enumerate(lines):
                    if "\\maketitle" in line:
                        lines.insert(i + 1, "\n" + content + "\n")
                        break
                    elif "\\begin{document}" in line and i + 1 < len(lines):
                        lines.insert(i + 1, "\n" + content + "\n")
                        break

            # Write back to file
            with open(file_path, "w", encoding="utf-8") as f:
                f.writelines(lines)

            return {
                "success": True,
                "message": f"Content added to {file_path}",
                "position": position,
                "content_length": len(content),
            }

        except Exception as e:
            logger.error(f"Error adding content: {e}")
            return {"success": False, "error": str(e)}

    def add_section(
        self, file_path: str, title: str, level: str = "section", content: str | None = None
    ) -> dict[str, Any]:
        """Add a section to a LaTeX document."""
        try:
            if level not in ["section", "subsection", "subsubsection", "chapter", "part"]:
                return {"success": False, "error": f"Invalid section level: {level}"}

            section_content = f"\\{level}{{{title}}}"
            if content:
                section_content += f"\n{content}"

            return self.add_content(file_path, section_content, "end")

        except Exception as e:
            logger.error(f"Error adding section: {e}")
            return {"success": False, "error": str(e)}

    def add_table(
        self,
        file_path: str,
        data: list[list[str]],
        headers: list[str] | None = None,
        caption: str | None = None,
        label: str | None = None,
    ) -> dict[str, Any]:
        """Add a table to a LaTeX document."""
        try:
            if not data:
                return {"success": False, "error": "Table data is empty"}

            num_cols = len(data[0]) if data else 0
            if num_cols == 0:
                return {"success": False, "error": "Table has no columns"}

            # Create table content
            table_content = ["\\begin{table}[h]", "\\centering"]

            if caption:
                table_content.append(f"\\caption{{{caption}}}")
            if label:
                table_content.append(f"\\label{{{label}}}")

            # Create tabular environment
            col_spec = "|".join(["c"] * num_cols)
            table_content.append(f"\\begin{{tabular}}{{{col_spec}}}")
            table_content.append("\\hline")

            # Add headers if provided
            if headers:
                header_row = " & ".join(headers) + " \\\\"
                table_content.append(header_row)
                table_content.append("\\hline")

            # Add data rows
            for row in data:
                row_str = " & ".join(str(cell) for cell in row) + " \\\\"
                table_content.append(row_str)

            table_content.append("\\hline")
            table_content.append("\\end{tabular}")
            table_content.append("\\end{table}")

            return self.add_content(file_path, "\n".join(table_content), "end")

        except Exception as e:
            logger.error(f"Error adding table: {e}")
            return {"success": False, "error": str(e)}

    def add_figure(
        self,
        file_path: str,
        image_path: str,
        caption: str | None = None,
        label: str | None = None,
        width: str | None = None,
    ) -> dict[str, Any]:
        """Add a figure to a LaTeX document."""
        try:
            # Check if image exists
            if not Path(image_path).exists():
                return {"success": False, "error": f"Image file not found: {image_path}"}

            # Create figure content
            figure_content = ["\\begin{figure}[h]", "\\centering"]

            # Add includegraphics
            if width:
                figure_content.append(f"\\includegraphics[width={width}]{{{image_path}}}")
            else:
                figure_content.append(f"\\includegraphics{{{image_path}}}")

            if caption:
                figure_content.append(f"\\caption{{{caption}}}")
            if label:
                figure_content.append(f"\\label{{{label}}}")

            figure_content.append("\\end{figure}")

            return self.add_content(file_path, "\n".join(figure_content), "end")

        except Exception as e:
            logger.error(f"Error adding figure: {e}")
            return {"success": False, "error": str(e)}

    def analyze_document(self, file_path: str) -> dict[str, Any]:
        """Analyze a LaTeX document."""
        try:
            if not Path(file_path).exists():
                return {"success": False, "error": f"LaTeX file not found: {file_path}"}

            with open(file_path, encoding="utf-8") as f:
                content = f.read()

            # Extract document information
            analysis = {
                "success": True,
                "file_path": file_path,
                "file_size": len(content),
                "line_count": content.count("\n") + 1,
            }

            # Find document class
            doc_class_match = re.search(r"\\documentclass(?:\[.*?\])?\{(.*?)\}", content)
            analysis["document_class"] = doc_class_match.group(1) if doc_class_match else "unknown"

            # Find packages
            packages = re.findall(r"\\usepackage(?:\[.*?\])?\{(.*?)\}", content)
            analysis["packages"] = packages

            # Count sections
            analysis["sections"] = len(re.findall(r"\\section\{", content))
            analysis["subsections"] = len(re.findall(r"\\subsection\{", content))
            analysis["subsubsections"] = len(re.findall(r"\\subsubsection\{", content))

            # Count figures and tables
            analysis["figures"] = len(re.findall(r"\\begin\{figure\}", content))
            analysis["tables"] = len(re.findall(r"\\begin\{table\}", content))

            # Extract title and author
            title_match = re.search(r"\\title\{(.*?)\}", content)
            analysis["title"] = title_match.group(1) if title_match else None

            author_match = re.search(r"\\author\{(.*?)\}", content)
            analysis["author"] = author_match.group(1) if author_match else None

            # Check for bibliography
            analysis["has_bibliography"] = bool(
                re.search(r"\\bibliography\{", content)
                or re.search(r"\\begin\{thebibliography\}", content)
            )

            return analysis

        except Exception as e:
            logger.error(f"Error analyzing document: {e}")
            return {"success": False, "error": str(e)}

    def create_from_template(
        self, template_type: str, file_path: str, variables: dict[str, str] | None = None
    ) -> dict[str, Any]:
        """Create a document from a template."""
        templates = {
            "article": self._get_article_template,
            "letter": self._get_letter_template,
            "beamer": self._get_beamer_template,
            "report": self._get_report_template,
            "book": self._get_book_template,
        }

        if template_type not in templates:
            return {"success": False, "error": f"Unknown template type: {template_type}"}

        try:
            # Get template content
            template_content = templates[template_type](variables or {})

            # Write to file
            Path(file_path).parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(template_content)

            return {
                "success": True,
                "message": f"Document created from {template_type} template",
                "file_path": file_path,
                "template_type": template_type,
            }

        except Exception as e:
            logger.error(f"Error creating from template: {e}")
            return {"success": False, "error": str(e)}

    def _get_article_template(self, variables: dict[str, str]) -> str:
        """Get article template."""
        title = variables.get("title", "Article Title")
        author = variables.get("author", "Author Name")

        return f"""\\documentclass[12pt,a4paper]{{article}}
\\usepackage[utf8]{{inputenc}}
\\usepackage[T1]{{fontenc}}
\\usepackage[margin=1in]{{geometry}}
\\usepackage{{graphicx}}
\\usepackage{{amsmath,amsfonts,amssymb}}
\\usepackage{{hyperref}}

\\title{{{title}}}
\\author{{{author}}}
\\date{{\\today}}

\\begin{{document}}

\\maketitle

\\begin{{abstract}}
Your abstract goes here.
\\end{{abstract}}

\\section{{Introduction}}
Your introduction goes here.

\\section{{Methodology}}
Describe your methodology here.

\\section{{Results}}
Present your results here.

\\section{{Conclusion}}
Your conclusion goes here.

\\end{{document}}"""

    def _get_letter_template(self, variables: dict[str, str]) -> str:
        """Get letter template."""
        return """\\documentclass{letter}
\\usepackage[utf8]{inputenc}
\\signature{Your Name}
\\address{Your Address \\\\ City, State ZIP}

\\begin{document}

\\begin{letter}{Recipient Name \\\\ Address \\\\ City, State ZIP}

\\opening{Dear Sir/Madam,}

Your letter content goes here.

\\closing{Sincerely,}

\\end{letter}

\\end{document}"""

    def _get_beamer_template(self, variables: dict[str, str]) -> str:
        """Get beamer presentation template."""
        title = variables.get("title", "Presentation Title")
        author = variables.get("author", "Author Name")

        return f"""\\documentclass{{beamer}}
\\usetheme{{Madrid}}
\\usepackage[utf8]{{inputenc}}

\\title{{{title}}}
\\author{{{author}}}
\\institute{{Institution}}
\\date{{\\today}}

\\begin{{document}}

\\frame{{\\titlepage}}

\\begin{{frame}}
\\frametitle{{Outline}}
\\tableofcontents
\\end{{frame}}

\\section{{Introduction}}
\\begin{{frame}}
\\frametitle{{Introduction}}
\\begin{{itemize}}
\\item First point
\\item Second point
\\item Third point
\\end{{itemize}}
\\end{{frame}}

\\section{{Main Content}}
\\begin{{frame}}
\\frametitle{{Main Points}}
Your content here
\\end{{frame}}

\\section{{Conclusion}}
\\begin{{frame}}
\\frametitle{{Conclusion}}
Summary of your presentation
\\end{{frame}}

\\end{{document}}"""

    def _get_report_template(self, variables: dict[str, str]) -> str:
        """Get report template."""
        return """\\documentclass[12pt,a4paper]{report}
\\usepackage[utf8]{inputenc}
\\usepackage[T1]{fontenc}
\\usepackage[margin=1in]{geometry}
\\usepackage{graphicx}

\\title{Report Title}
\\author{Author Name}
\\date{\\today}

\\begin{document}

\\maketitle
\\tableofcontents

\\chapter{Introduction}
Your introduction goes here.

\\chapter{Background}
Background information goes here.

\\chapter{Methodology}
Describe your methodology here.

\\chapter{Results and Discussion}
Present your results here.

\\chapter{Conclusion}
Your conclusion goes here.

\\end{document}"""

    def _get_book_template(self, variables: dict[str, str]) -> str:
        """Get book template."""
        return """\\documentclass[12pt,a4paper]{book}
\\usepackage[utf8]{inputenc}
\\usepackage[T1]{fontenc}
\\usepackage[margin=1in]{geometry}
\\usepackage{graphicx}

\\title{Book Title}
\\author{Author Name}
\\date{\\today}

\\begin{document}

\\frontmatter
\\maketitle
\\tableofcontents

\\mainmatter

\\chapter{First Chapter}
\\section{Introduction}
Your content goes here.

\\chapter{Second Chapter}
More content goes here.

\\backmatter
\\chapter{Appendix}
Appendix content goes here.

\\end{document}"""


# Initialize the processor
processor = LaTeXProcessor()


@mcp.tool(description="Create a new LaTeX document")
async def create_document(
    file_path: str = Field(..., description="Path for the new LaTeX file"),
    document_class: str = Field(
        "article",
        pattern="^(article|report|book|letter|beamer)$",
        description="LaTeX document class",
    ),
    title: str | None = Field(None, description="Document title"),
    author: str | None = Field(None, description="Document author"),
    packages: list[str] | None = Field(None, description="LaTeX packages to include"),
) -> dict[str, Any]:
    """Create a new LaTeX document with specified class and packages."""
    return processor.create_document(file_path, document_class, title, author, packages)


@mcp.tool(description="Compile a LaTeX document to PDF or other formats")
async def compile_document(
    file_path: str = Field(..., description="Path to the LaTeX file"),
    output_format: str = Field(
        "pdf", pattern="^(pdf|dvi|ps)$", description="Output format (pdf, dvi, ps)"
    ),
    output_dir: str | None = Field(None, description="Output directory"),
    clean_aux: bool = Field(True, description="Clean auxiliary files after compilation"),
) -> dict[str, Any]:
    """Compile a LaTeX document to the specified format."""
    return processor.compile_document(file_path, output_format, output_dir, clean_aux)


@mcp.tool(description="Add content to a LaTeX document")
async def add_content(
    file_path: str = Field(..., description="Path to the LaTeX file"),
    content: str = Field(..., description="LaTeX content to add"),
    position: str = Field(
        "end",
        pattern="^(end|beginning|after_begin)$",
        description="Where to add content (end, beginning, after_begin)",
    ),
) -> dict[str, Any]:
    """Add arbitrary LaTeX content to a document."""
    return processor.add_content(file_path, content, position)


@mcp.tool(description="Add a section to a LaTeX document")
async def add_section(
    file_path: str = Field(..., description="Path to the LaTeX file"),
    title: str = Field(..., description="Section title"),
    level: str = Field(
        "section",
        pattern="^(section|subsection|subsubsection|chapter|part)$",
        description="Section level",
    ),
    content: str | None = Field(None, description="Section content"),
) -> dict[str, Any]:
    """Add a structured section to a LaTeX document."""
    return processor.add_section(file_path, title, level, content)


@mcp.tool(description="Add a table to a LaTeX document")
async def add_table(
    file_path: str = Field(..., description="Path to the LaTeX file"),
    data: list[list[str]] = Field(..., description="Table data (2D array)"),
    headers: list[str] | None = Field(None, description="Column headers"),
    caption: str | None = Field(None, description="Table caption"),
    label: str | None = Field(None, description="Table label for referencing"),
) -> dict[str, Any]:
    """Add a formatted table to a LaTeX document."""
    return processor.add_table(file_path, data, headers, caption, label)


@mcp.tool(description="Add a figure to a LaTeX document")
async def add_figure(
    file_path: str = Field(..., description="Path to the LaTeX file"),
    image_path: str = Field(..., description="Path to the image file"),
    caption: str | None = Field(None, description="Figure caption"),
    label: str | None = Field(None, description="Figure label for referencing"),
    width: str | None = Field(None, description="Figure width (e.g., '0.5\\\\textwidth')"),
) -> dict[str, Any]:
    """Add a figure with an image to a LaTeX document."""
    return processor.add_figure(file_path, image_path, caption, label, width)


@mcp.tool(description="Analyze LaTeX document structure and content")
async def analyze_document(
    file_path: str = Field(..., description="Path to the LaTeX file"),
) -> dict[str, Any]:
    """Analyze a LaTeX document's structure, packages, and statistics."""
    return processor.analyze_document(file_path)


@mcp.tool(description="Create a LaTeX document from a template")
async def create_from_template(
    template_type: str = Field(
        ..., pattern="^(article|letter|beamer|report|book)$", description="Template type"
    ),
    file_path: str = Field(..., description="Output file path"),
    variables: dict[str, str] | None = Field(None, description="Template variables"),
) -> dict[str, Any]:
    """Create a LaTeX document from a built-in template."""
    return processor.create_from_template(template_type, file_path, variables)


def main():
    """Main entry point for the FastMCP server."""
    import argparse

    parser = argparse.ArgumentParser(description="LaTeX FastMCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="Transport mode (stdio or http)",
    )
    parser.add_argument("--host", default="0.0.0.0", help="HTTP host")
    parser.add_argument("--port", type=int, default=9010, help="HTTP port")

    args = parser.parse_args()

    if args.transport == "http":
        logger.info(f"Starting LaTeX FastMCP Server on HTTP at {args.host}:{args.port}")
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        logger.info("Starting LaTeX FastMCP Server on stdio")
        mcp.run()


if __name__ == "__main__":
    main()
