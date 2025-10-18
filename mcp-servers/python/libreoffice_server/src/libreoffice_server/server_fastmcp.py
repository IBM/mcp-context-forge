#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/libreoffice_server/src/libreoffice_server/server_fastmcp.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

LibreOffice FastMCP Server

A comprehensive MCP server for document conversion using LibreOffice in headless mode.
Supports conversion between various document formats including PDF, DOCX, ODT, HTML, and more.
Powered by FastMCP for enhanced type safety and automatic validation.
"""

import logging
import shutil
import subprocess
import sys
import tempfile
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
mcp = FastMCP("libreoffice-server")


class LibreOfficeConverter:
    """Handles LibreOffice document conversion operations."""

    def __init__(self):
        self.libreoffice_cmd = self._find_libreoffice()

    def _find_libreoffice(self) -> str:
        """Find LibreOffice executable."""
        possible_commands = [
            "libreoffice",
            "libreoffice7.0",
            "libreoffice6.4",
            "/usr/bin/libreoffice",
            "/opt/libreoffice/program/soffice",
            "soffice",
        ]

        for cmd in possible_commands:
            if shutil.which(cmd):
                return cmd

        raise RuntimeError("LibreOffice not found. Please install LibreOffice.")

    def convert_document(
        self,
        input_file: str,
        output_format: str,
        output_dir: str | None = None,
        output_filename: str | None = None,
    ) -> dict[str, Any]:
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
                "--convert-to",
                output_format,
                str(input_path),
                "--outdir",
                str(output_path),
            ]

            logger.info(f"Running command: {' '.join(cmd)}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,  # 2 minute timeout
            )

            if result.returncode != 0:
                return {
                    "success": False,
                    "error": f"LibreOffice conversion failed: {result.stderr}",
                    "stdout": result.stdout,
                    "stderr": result.stderr,
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
                        "stdout": result.stdout,
                    }

            return {
                "success": True,
                "message": "Document converted successfully",
                "input_file": str(input_path),
                "output_file": str(expected_output),
                "output_format": output_format,
                "file_size": expected_output.stat().st_size,
            }

        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Conversion timed out after 2 minutes"}
        except Exception as e:
            logger.error(f"Error converting document: {e}")
            return {"success": False, "error": str(e)}

    def convert_batch(
        self, input_files: list[str], output_format: str, output_dir: str | None = None
    ) -> dict[str, Any]:
        """Convert multiple documents."""
        try:
            results = []

            for input_file in input_files:
                result = self.convert_document(input_file, output_format, output_dir)
                results.append({"input_file": input_file, "result": result})

            successful = sum(1 for r in results if r["result"]["success"])
            failed = len(results) - successful

            return {
                "success": True,
                "message": f"Batch conversion completed: {successful} successful, {failed} failed",
                "total_files": len(input_files),
                "successful": successful,
                "failed": failed,
                "results": results,
            }

        except Exception as e:
            logger.error(f"Error in batch conversion: {e}")
            return {"success": False, "error": str(e)}

    def merge_documents(
        self, input_files: list[str], output_file: str, output_format: str = "pdf"
    ) -> dict[str, Any]:
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
                    result = self.convert_document(input_file, output_format, temp_dir)
                    if result["success"]:
                        converted_files.append(result["output_file"])
                    else:
                        return {
                            "success": False,
                            "error": f"Failed to convert {input_file}: {result['error']}",
                        }

                # For now, return the list of converted files
                # True merging would require more complex LibreOffice scripting
                return {
                    "success": True,
                    "message": "Files converted to same format (manual merge required)",
                    "converted_files": converted_files,
                    "note": "LibreOffice does not support automated merging via command line. Files have been converted to the same format.",
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
                        "output_file": output_file,
                    }
                else:
                    return {"success": False, "error": f"pdftk failed: {result.stderr}"}
            except Exception as e:
                return {"success": False, "error": f"pdftk error: {str(e)}"}

        return {
            "success": False,
            "error": "PDF merging requires pdftk or similar tool to be installed",
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
                text_content = text_file.read_text(encoding="utf-8", errors="ignore")

                # Save to output file if specified
                if output_file:
                    output_path = Path(output_file)
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_text(text_content, encoding="utf-8")

                return {
                    "success": True,
                    "message": "Text extracted successfully",
                    "input_file": input_file,
                    "output_file": output_file,
                    "text_length": len(text_content),
                    "text_preview": text_content[:500] + "..."
                    if len(text_content) > 500
                    else text_content,
                    "full_text": text_content if len(text_content) <= 10000 else None,
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
                "created_time": stat.st_ctime,
            }

            # Try to get more detailed info by converting to text and analyzing
            text_result = self.extract_text(input_file)
            if text_result["success"]:
                text = text_result["full_text"] or text_result["text_preview"]
                info.update(
                    {
                        "text_length": len(text),
                        "word_count": len(text.split()) if text else 0,
                        "line_count": len(text.splitlines()) if text else 0,
                    }
                )

            return info

        except Exception as e:
            logger.error(f"Error getting document info: {e}")
            return {"success": False, "error": str(e)}

    def list_supported_formats(self) -> dict[str, Any]:
        """List supported input and output formats."""
        return {
            "success": True,
            "input_formats": [
                "doc",
                "docx",
                "odt",
                "rtf",
                "txt",
                "html",
                "htm",
                "xls",
                "xlsx",
                "ods",
                "csv",
                "ppt",
                "pptx",
                "odp",
                "pdf",
            ],
            "output_formats": [
                "pdf",
                "docx",
                "odt",
                "html",
                "txt",
                "rtf",
                "xlsx",
                "ods",
                "csv",
                "pptx",
                "odp",
                "png",
                "jpg",
                "svg",
            ],
            "merge_formats": ["pdf"],
            "note": "Actual supported formats depend on LibreOffice installation",
        }


# Initialize converter (conditionally for testing)
try:
    converter = LibreOfficeConverter()
except RuntimeError:
    # For testing when LibreOffice is not available
    converter = None


# Tool definitions using FastMCP decorators
@mcp.tool(description="Convert a document to another format using LibreOffice")
async def convert_document(
    input_file: str = Field(..., description="Path to the input file"),
    output_format: str = Field(
        ...,
        pattern="^(pdf|docx|odt|html|txt|rtf|xlsx|ods|csv|pptx|odp|png|jpg|svg)$",
        description="Target format",
    ),
    output_dir: str | None = Field(None, description="Output directory (defaults to input dir)"),
    output_filename: str | None = Field(None, description="Custom output filename"),
) -> dict[str, Any]:
    """Convert a document to another format."""
    if converter is None:
        return {"success": False, "error": "LibreOffice not available"}

    return converter.convert_document(
        input_file=input_file,
        output_format=output_format,
        output_dir=output_dir,
        output_filename=output_filename,
    )


@mcp.tool(description="Convert multiple documents to the same format")
async def convert_batch(
    input_files: list[str] = Field(..., description="List of input file paths"),
    output_format: str = Field(
        ...,
        pattern="^(pdf|docx|odt|html|txt|rtf|xlsx|ods|csv|pptx|odp|png|jpg|svg)$",
        description="Target format for all files",
    ),
    output_dir: str | None = Field(None, description="Output directory"),
) -> dict[str, Any]:
    """Convert multiple documents to the same format."""
    if converter is None:
        return {"success": False, "error": "LibreOffice not available"}

    return converter.convert_batch(
        input_files=input_files, output_format=output_format, output_dir=output_dir
    )


@mcp.tool(description="Merge multiple documents into one file")
async def merge_documents(
    input_files: list[str] = Field(..., description="List of input file paths to merge"),
    output_file: str = Field(..., description="Output file path"),
    output_format: str = Field(
        "pdf", pattern="^(pdf)$", description="Output format (pdf recommended)"
    ),
) -> dict[str, Any]:
    """Merge multiple documents into one."""
    if converter is None:
        return {"success": False, "error": "LibreOffice not available"}

    return converter.merge_documents(
        input_files=input_files, output_file=output_file, output_format=output_format
    )


@mcp.tool(description="Extract text content from a document")
async def extract_text(
    input_file: str = Field(..., description="Path to the input file"),
    output_file: str | None = Field(None, description="Output text file path (optional)"),
) -> dict[str, Any]:
    """Extract text from a document."""
    if converter is None:
        return {"success": False, "error": "LibreOffice not available"}

    return converter.extract_text(input_file=input_file, output_file=output_file)


@mcp.tool(description="Get information about a document")
async def get_document_info(
    input_file: str = Field(..., description="Path to the input file"),
) -> dict[str, Any]:
    """Get information about a document."""
    if converter is None:
        return {"success": False, "error": "LibreOffice not available"}

    return converter.get_document_info(input_file=input_file)


@mcp.tool(description="List supported input and output formats")
async def list_supported_formats() -> dict[str, Any]:
    """List supported formats."""
    if converter is None:
        return {"success": False, "error": "LibreOffice not available"}

    return converter.list_supported_formats()


def main():
    """Main entry point for the FastMCP server."""
    import argparse

    parser = argparse.ArgumentParser(description="LibreOffice FastMCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="Transport mode (stdio or http)",
    )
    parser.add_argument("--host", default="0.0.0.0", help="HTTP host")
    parser.add_argument("--port", type=int, default=9011, help="HTTP port")

    args = parser.parse_args()

    if args.transport == "http":
        logger.info(f"Starting LibreOffice FastMCP Server on HTTP at {args.host}:{args.port}")
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        logger.info("Starting LibreOffice FastMCP Server on stdio")
        mcp.run()


if __name__ == "__main__":
    main()
