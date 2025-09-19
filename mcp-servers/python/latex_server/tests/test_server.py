# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/latex_server/tests/test_server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for LaTeX MCP Server.
"""

import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from latex_server.server import handle_call_tool, handle_list_tools


@pytest.mark.asyncio
async def test_list_tools():
    """Test that tools are listed correctly."""
    tools = await handle_list_tools()

    tool_names = [tool.name for tool in tools]
    expected_tools = [
        "create_document",
        "compile_document",
        "add_content",
        "add_section",
        "add_table",
        "add_figure",
        "analyze_document",
        "create_from_template"
    ]

    for expected in expected_tools:
        assert expected in tool_names


@pytest.mark.asyncio
async def test_create_document():
    """Test creating a LaTeX document."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.tex")

        result = await handle_call_tool(
            "create_document",
            {
                "file_path": file_path,
                "document_class": "article",
                "title": "Test Document",
                "author": "Test Author"
            }
        )

        result_data = json.loads(result[0].text)
        assert result_data["success"] is True
        assert Path(file_path).exists()

        # Check content
        with open(file_path, 'r') as f:
            content = f.read()
            assert "\\documentclass{article}" in content
            assert "\\title{Test Document}" in content
            assert "\\author{Test Author}" in content


@pytest.mark.asyncio
async def test_add_content():
    """Test adding content to a LaTeX document."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.tex")

        # Create document first
        await handle_call_tool(
            "create_document",
            {"file_path": file_path, "document_class": "article"}
        )

        # Add content
        result = await handle_call_tool(
            "add_content",
            {
                "file_path": file_path,
                "content": "This is additional content.",
                "position": "end"
            }
        )

        result_data = json.loads(result[0].text)
        assert result_data["success"] is True

        # Check content was added
        with open(file_path, 'r') as f:
            content = f.read()
            assert "This is additional content." in content


@pytest.mark.asyncio
async def test_add_section():
    """Test adding a section to a LaTeX document."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.tex")

        # Create document first
        await handle_call_tool(
            "create_document",
            {"file_path": file_path}
        )

        # Add section
        result = await handle_call_tool(
            "add_section",
            {
                "file_path": file_path,
                "title": "Introduction",
                "level": "section",
                "content": "This is the introduction section."
            }
        )

        result_data = json.loads(result[0].text)
        assert result_data["success"] is True

        # Check section was added
        with open(file_path, 'r') as f:
            content = f.read()
            assert "\\section{Introduction}" in content
            assert "This is the introduction section." in content


@pytest.mark.asyncio
async def test_add_table():
    """Test adding a table to a LaTeX document."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.tex")

        # Create document first
        await handle_call_tool(
            "create_document",
            {"file_path": file_path}
        )

        # Add table
        result = await handle_call_tool(
            "add_table",
            {
                "file_path": file_path,
                "data": [["A", "B"], ["1", "2"], ["3", "4"]],
                "headers": ["Column 1", "Column 2"],
                "caption": "Test Table",
                "label": "tab:test"
            }
        )

        result_data = json.loads(result[0].text)
        assert result_data["success"] is True

        # Check table was added
        with open(file_path, 'r') as f:
            content = f.read()
            assert "\\begin{table}" in content
            assert "\\caption{Test Table}" in content
            assert "\\label{tab:test}" in content
            assert "Column 1 & Column 2" in content


@pytest.mark.asyncio
async def test_analyze_document():
    """Test analyzing a LaTeX document."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.tex")

        # Create a document with content
        latex_content = '''\\documentclass{article}
\\usepackage{amsmath}
\\usepackage{graphicx}
\\title{Test Document}
\\author{Test Author}
\\begin{document}
\\maketitle
\\section{Introduction}
This is the introduction.
\\subsection{Subsection}
Content here.
\\begin{equation}
x = y + z
\\end{equation}
\\end{document}'''

        with open(file_path, 'w') as f:
            f.write(latex_content)

        result = await handle_call_tool(
            "analyze_document",
            {"file_path": file_path}
        )

        result_data = json.loads(result[0].text)
        assert result_data["success"] is True
        assert result_data["document_class"] == "article"
        assert "amsmath" in result_data["packages"]
        assert result_data["structure"]["sections"] == 1
        assert result_data["structure"]["subsections"] == 1
        assert result_data["structure"]["equations"] == 1
        assert result_data["metadata"]["title"] == "Test Document"


@pytest.mark.asyncio
async def test_create_from_template():
    """Test creating a document from template."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "article.tex")

        result = await handle_call_tool(
            "create_from_template",
            {
                "template_type": "article",
                "file_path": file_path,
                "variables": {
                    "title": "My Article",
                    "author": "John Doe",
                    "abstract": "This is the abstract.",
                    "introduction": "This is the introduction.",
                    "conclusion": "This is the conclusion."
                }
            }
        )

        result_data = json.loads(result[0].text)
        assert result_data["success"] is True
        assert Path(file_path).exists()

        # Check template variables were substituted
        with open(file_path, 'r') as f:
            content = f.read()
            assert "My Article" in content
            assert "John Doe" in content
            assert "This is the abstract." in content


@pytest.mark.asyncio
@patch('latex_server.server.subprocess.run')
@patch('latex_server.server.shutil.which')
async def test_compile_document_success(mock_which, mock_subprocess):
    """Test successful document compilation."""
    mock_which.return_value = '/usr/bin/pdflatex'

    # Mock successful subprocess call
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "compilation successful"
    mock_result.stderr = ""
    mock_subprocess.return_value = mock_result

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a LaTeX file
        file_path = str(Path(tmpdir) / "test.tex")
        with open(file_path, 'w') as f:
            f.write("\\documentclass{article}\\begin{document}Hello\\end{document}")

        # Create expected output file
        output_file = Path(tmpdir) / "test.pdf"
        output_file.write_bytes(b"fake pdf content")

        result = await handle_call_tool(
            "compile_document",
            {
                "file_path": file_path,
                "output_format": "pdf",
                "output_dir": tmpdir
            }
        )

        result_data = json.loads(result[0].text)
        assert result_data["success"] is True
        assert result_data["output_format"] == "pdf"


@pytest.mark.asyncio
async def test_compile_document_missing_file():
    """Test compilation with missing LaTeX file."""
    result = await handle_call_tool(
        "compile_document",
        {
            "file_path": "/nonexistent/file.tex",
            "output_format": "pdf"
        }
    )

    result_data = json.loads(result[0].text)
    assert result_data["success"] is False
    assert "not found" in result_data["error"]


@pytest.mark.asyncio
async def test_add_figure_missing_image():
    """Test adding figure with missing image file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = str(Path(tmpdir) / "test.tex")

        # Create document first
        await handle_call_tool(
            "create_document",
            {"file_path": file_path}
        )

        # Try to add figure with non-existent image
        result = await handle_call_tool(
            "add_figure",
            {
                "file_path": file_path,
                "image_path": "/nonexistent/image.png",
                "caption": "Test Figure"
            }
        )

        result_data = json.loads(result[0].text)
        assert result_data["success"] is False
        assert "not found" in result_data["error"]
