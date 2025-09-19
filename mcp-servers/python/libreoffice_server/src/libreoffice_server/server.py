#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/libreoffice_server/src/libreoffice_server/server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

LibreOffice MCP Server

A comprehensive MCP server for document conversion using LibreOffice in headless mode.
Supports conversion between various document formats including PDF, DOCX, ODT, HTML, and more.
"""

import asyncio
import json
import logging
import os
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
server = Server("libreoffice-server")


class ConvertRequest(BaseModel):
    """Request to convert a document."""
    input_file: str = Field(..., description="Path to input file")
    output_format: str = Field(..., description="Target format (pdf, docx, odt, html, txt, etc.)")
    output_dir: str | None = Field(None, description="Output directory (optional)")
    output_filename: str | None = Field(None, description="Custom output filename (optional)")


class ConvertBatchRequest(BaseModel):
    """Request to convert multiple documents."""
    input_files: list[str] = Field(..., description="List of input file paths")
    output_format: str = Field(..., description="Target format")
    output_dir: str | None = Field(None, description="Output directory (optional)")


class MergeRequest(BaseModel):
    """Request to merge documents."""
    input_files: list[str] = Field(..., description="List of input file paths to merge")
    output_file: str = Field(..., description="Output file path")
    output_format: str = Field("pdf", description="Output format")


class ExtractTextRequest(BaseModel):
    """Request to extract text from a document."""
    input_file: str = Field(..., description="Path to input file")
    output_file: str | None = Field(None, description="Output text file path (optional)")


class InfoRequest(BaseModel):
    """Request to get document information."""
    input_file: str = Field(..., description="Path to input file")


class LibreOfficeConverter:
    """Handles LibreOffice document conversion operations."""

    def __init__(self):
        self.libreoffice_cmd = self._find_libreoffice()

    def _find_libreoffice(self) -> str:
        """Find LibreOffice executable."""
        possible_commands = [
            'libreoffice',
            'libreoffice7.0',
            'libreoffice6.4',
            '/usr/bin/libreoffice',
            '/opt/libreoffice/program/soffice',
            'soffice'
        ]

        for cmd in possible_commands:
            if shutil.which(cmd):
                return cmd

        raise RuntimeError("LibreOffice not found. Please install LibreOffice.")

    def convert_document(self, input_file: str, output_format: str,
                        output_dir: str | None = None,
                        output_filename: str | None = None) -> dict[str, Any]:
        """Convert a document to the specified format."""
        try:
            input_path = Path(input_file)
            if not input_path.exists():
                return {"success": False, "error": f"Input file not found: {input_file}"}

            # Determine output directory
            if output_dir:
                output_path = Path(output_dir)
                output_path.mkdir(parents=True, exist_ok=True)
            else:
                output_path = input_path.parent

            # Run LibreOffice conversion
            cmd = [
                self.libreoffice_cmd,
                "--headless",
                "--convert-to", output_format,
                str(input_path),
                "--outdir", str(output_path)
            ]

            logger.info(f"Running command: {' '.join(cmd)}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120  # 2 minute timeout
            )

            if result.returncode != 0:
                return {
                    "success": False,
                    "error": f"LibreOffice conversion failed: {result.stderr}",
                    "stdout": result.stdout,
                    "stderr": result.stderr
                }

            # Find the output file
            expected_output = output_path / f"{input_path.stem}.{output_format}"

            # Handle custom output filename
            if output_filename:
                custom_output = output_path / output_filename
                if expected_output.exists():
                    expected_output.rename(custom_output)
                    expected_output = custom_output

            if not expected_output.exists():
                # Try to find any new file in the output directory
                possible_outputs = list(output_path.glob(f"{input_path.stem}.*"))
                if possible_outputs:
                    expected_output = possible_outputs[0]
                else:
                    return {
                        "success": False,
                        "error": f"Output file not found: {expected_output}",
                        "stdout": result.stdout
                    }

            return {
                "success": True,
                "message": f"Document converted successfully",
                "input_file": str(input_path),
                "output_file": str(expected_output),
                "output_format": output_format,
                "file_size": expected_output.stat().st_size
            }

        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Conversion timed out after 2 minutes"}
        except Exception as e:
            logger.error(f"Error converting document: {e}")
            return {"success": False, "error": str(e)}

    def convert_batch(self, input_files: list[str], output_format: str,
                     output_dir: str | None = None) -> dict[str, Any]:
        """Convert multiple documents."""
        try:
            results = []

            for input_file in input_files:
                result = self.convert_document(input_file, output_format, output_dir)
                results.append({
                    "input_file": input_file,
                    "result": result
                })

            successful = sum(1 for r in results if r["result"]["success"])
            failed = len(results) - successful

            return {
                "success": True,
                "message": f"Batch conversion completed: {successful} successful, {failed} failed",
                "total_files": len(input_files),
                "successful": successful,
                "failed": failed,
                "results": results
            }

        except Exception as e:
            logger.error(f"Error in batch conversion: {e}")
            return {"success": False, "error": str(e)}

    def merge_documents(self, input_files: list[str], output_file: str,
                       output_format: str = "pdf") -> dict[str, Any]:
        """Merge multiple documents into one."""
        try:
            if len(input_files) < 2:
                return {"success": False, "error": "At least 2 files required for merging"}

            # For PDF merging, we need a different approach
            if output_format.lower() == "pdf":
                return self._merge_pdfs(input_files, output_file)

            # For other formats, convert all to the same format first, then merge
            with tempfile.TemporaryDirectory() as temp_dir:
                converted_files = []

                # Convert all files to the target format
                for input_file in input_files:
                    result = self.convert_document(
                        input_file, output_format, temp_dir
                    )
                    if result["success"]:
                        converted_files.append(result["output_file"])
                    else:
                        return {
                            "success": False,
                            "error": f"Failed to convert {input_file}: {result['error']}"
                        }

                # For now, return the list of converted files
                # True merging would require more complex LibreOffice scripting
                return {
                    "success": True,
                    "message": "Files converted to same format (manual merge required)",
                    "converted_files": converted_files,
                    "note": "LibreOffice does not support automated merging via command line. Files have been converted to the same format."
                }

        except Exception as e:
            logger.error(f"Error merging documents: {e}")
            return {"success": False, "error": str(e)}

    def _merge_pdfs(self, input_files: list[str], output_file: str) -> dict[str, Any]:
        """Merge PDF files using external tools if available."""
        # Check if pdftk or similar tools are available
        if shutil.which("pdftk"):
            try:
                cmd = ["pdftk"] + input_files + ["cat", "output", output_file]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

                if result.returncode == 0:
                    return {
                        "success": True,
                        "message": "PDFs merged successfully using pdftk",
                        "output_file": output_file
                    }
                else:
                    return {"success": False, "error": f"pdftk failed: {result.stderr}"}
            except Exception as e:
                return {"success": False, "error": f"pdftk error: {str(e)}"}

        return {
            "success": False,
            "error": "PDF merging requires pdftk or similar tool to be installed"
        }

    def extract_text(self, input_file: str, output_file: str | None = None) -> dict[str, Any]:
        """Extract text from a document."""
        try:
            input_path = Path(input_file)
            if not input_path.exists():
                return {"success": False, "error": f"Input file not found: {input_file}"}

            # Use temporary directory for conversion
            with tempfile.TemporaryDirectory() as temp_dir:
                # Convert to text format
                result = self.convert_document(input_file, "txt", temp_dir)

                if not result["success"]:
                    return result

                # Read the extracted text
                text_file = Path(result["output_file"])
                text_content = text_file.read_text(encoding='utf-8', errors='ignore')

                # Save to output file if specified
                if output_file:
                    output_path = Path(output_file)
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_text(text_content, encoding='utf-8')

                return {
                    "success": True,
                    "message": "Text extracted successfully",
                    "input_file": input_file,
                    "output_file": output_file,
                    "text_length": len(text_content),
                    "text_preview": text_content[:500] + "..." if len(text_content) > 500 else text_content,
                    "full_text": text_content if len(text_content) <= 10000 else None
                }

        except Exception as e:
            logger.error(f"Error extracting text: {e}")
            return {"success": False, "error": str(e)}

    def get_document_info(self, input_file: str) -> dict[str, Any]:
        """Get information about a document."""
        try:
            input_path = Path(input_file)
            if not input_path.exists():
                return {"success": False, "error": f"Input file not found: {input_file}"}

            # Get basic file information
            stat = input_path.stat()

            info = {
                "success": True,
                "file_path": str(input_path),
                "file_name": input_path.name,
                "file_size": stat.st_size,
                "file_extension": input_path.suffix,
                "modified_time": stat.st_mtime,
                "created_time": stat.st_ctime
            }

            # Try to get more detailed info by converting to text and analyzing
            text_result = self.extract_text(input_file)
            if text_result["success"]:
                text = text_result["full_text"] or text_result["text_preview"]
                info.update({
                    "text_length": len(text),
                    "word_count": len(text.split()) if text else 0,
                    "line_count": len(text.splitlines()) if text else 0
                })

            return info

        except Exception as e:
            logger.error(f"Error getting document info: {e}")
            return {"success": False, "error": str(e)}

    def list_supported_formats(self) -> dict[str, Any]:
        """List supported input and output formats."""
        return {
            "success": True,
            "input_formats": [
                "doc", "docx", "odt", "rtf", "txt", "html", "htm",
                "xls", "xlsx", "ods", "csv",
                "ppt", "pptx", "odp",
                "pdf"
            ],
            "output_formats": [
                "pdf", "docx", "odt", "html", "txt", "rtf",
                "xlsx", "ods", "csv",
                "pptx", "odp",
                "png", "jpg", "svg"
            ],
            "merge_formats": ["pdf"],
            "note": "Actual supported formats depend on LibreOffice installation"
        }


# Initialize converter (conditionally for testing)
try:
    converter = LibreOfficeConverter()
except RuntimeError:
    # For testing when LibreOffice is not available
    converter = None


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    """List available LibreOffice tools."""
    return [
        Tool(
            name="convert_document",
            description="Convert a document to another format using LibreOffice",
            inputSchema={
                "type": "object",
                "properties": {
                    "input_file": {
                        "type": "string",
                        "description": "Path to the input file"
                    },
                    "output_format": {
                        "type": "string",
                        "description": "Target format (pdf, docx, odt, html, txt, etc.)"
                    },
                    "output_dir": {
                        "type": "string",
                        "description": "Output directory (optional, defaults to input file directory)"
                    },
                    "output_filename": {
                        "type": "string",
                        "description": "Custom output filename (optional)"
                    }
                },
                "required": ["input_file", "output_format"]
            }
        ),
        Tool(
            name="convert_batch",
            description="Convert multiple documents to the same format",
            inputSchema={
                "type": "object",
                "properties": {
                    "input_files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of input file paths"
                    },
                    "output_format": {
                        "type": "string",
                        "description": "Target format for all files"
                    },
                    "output_dir": {
                        "type": "string",
                        "description": "Output directory (optional)"
                    }
                },
                "required": ["input_files", "output_format"]
            }
        ),
        Tool(
            name="merge_documents",
            description="Merge multiple documents into one file",
            inputSchema={
                "type": "object",
                "properties": {
                    "input_files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of input file paths to merge"
                    },
                    "output_file": {
                        "type": "string",
                        "description": "Output file path"
                    },
                    "output_format": {
                        "type": "string",
                        "description": "Output format (pdf recommended)",
                        "default": "pdf"
                    }
                },
                "required": ["input_files", "output_file"]
            }
        ),
        Tool(
            name="extract_text",
            description="Extract text content from a document",
            inputSchema={
                "type": "object",
                "properties": {
                    "input_file": {
                        "type": "string",
                        "description": "Path to the input file"
                    },
                    "output_file": {
                        "type": "string",
                        "description": "Output text file path (optional)"
                    }
                },
                "required": ["input_file"]
            }
        ),
        Tool(
            name="get_document_info",
            description="Get information about a document",
            inputSchema={
                "type": "object",
                "properties": {
                    "input_file": {
                        "type": "string",
                        "description": "Path to the input file"
                    }
                },
                "required": ["input_file"]
            }
        ),
        Tool(
            name="list_supported_formats",
            description="List supported input and output formats",
            inputSchema={
                "type": "object",
                "properties": {},
                "additionalProperties": False
            }
        )
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict[str, Any]) -> Sequence[TextContent | ImageContent | EmbeddedResource]:
    """Handle tool calls."""
    try:
        if converter is None:
            result = {"success": False, "error": "LibreOffice not available"}
        elif name == "convert_document":
            request = ConvertRequest(**arguments)
            result = converter.convert_document(
                input_file=request.input_file,
                output_format=request.output_format,
                output_dir=request.output_dir,
                output_filename=request.output_filename
            )

        elif name == "convert_batch":
            request = ConvertBatchRequest(**arguments)
            result = converter.convert_batch(
                input_files=request.input_files,
                output_format=request.output_format,
                output_dir=request.output_dir
            )

        elif name == "merge_documents":
            request = MergeRequest(**arguments)
            result = converter.merge_documents(
                input_files=request.input_files,
                output_file=request.output_file,
                output_format=request.output_format
            )

        elif name == "extract_text":
            request = ExtractTextRequest(**arguments)
            result = converter.extract_text(
                input_file=request.input_file,
                output_file=request.output_file
            )

        elif name == "get_document_info":
            request = InfoRequest(**arguments)
            result = converter.get_document_info(input_file=request.input_file)

        elif name == "list_supported_formats":
            result = converter.list_supported_formats()

        else:
            result = {"success": False, "error": f"Unknown tool: {name}"}

    except Exception as e:
        logger.error(f"Error in {name}: {str(e)}")
        result = {"success": False, "error": str(e)}

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def main():
    """Main server entry point."""
    logger.info("Starting LibreOffice MCP Server...")

    from mcp.server.stdio import stdio_server

    logger.info("Waiting for MCP client connection...")
    async with stdio_server() as (read_stream, write_stream):
        logger.info("MCP client connected, starting server...")
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="libreoffice-server",
                server_version="0.1.0",
                capabilities={
                    "tools": {},
                    "logging": {},
                },
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())
