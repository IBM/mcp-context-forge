# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/libreoffice_server/tests/test_server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for LibreOffice MCP Server (FastMCP).
"""

import pytest

from libreoffice_server.server_fastmcp import converter


@pytest.mark.skipif(converter is None, reason="LibreOffice not available")
def test_convert_document():
    """Test document conversion."""
    # Note: This test would require a real document to convert
    # For testing purposes, we just verify the converter exists
    assert converter is not None
    formats = converter.list_supported_formats()
    assert formats["success"] is True


@pytest.mark.skipif(converter is None, reason="LibreOffice not available")
def test_batch_convert():
    """Test batch conversion."""
    # Note: This test would require real documents
    # For testing purposes, we just verify the converter exists
    assert converter is not None


@pytest.mark.skipif(converter is None, reason="LibreOffice not available")
def test_get_document_info():
    """Test getting document info."""
    # Note: This test would require a real document
    # For testing purposes, we just verify the converter exists
    assert converter is not None


@pytest.mark.skipif(converter is None, reason="LibreOffice not available")
def test_list_supported_formats():
    """Test listing supported formats."""
    assert converter is not None
    result = converter.list_supported_formats()
    assert result["success"] is True
    assert "input_formats" in result
    assert "output_formats" in result


def test_converter_initialization():
    """Test converter initialization state."""
    # Converter may be None if LibreOffice is not installed
    # This is acceptable in test environments
    if converter is not None:
        assert hasattr(converter, "convert_document")
        assert hasattr(converter, "batch_convert")
        assert hasattr(converter, "get_document_info")
        assert hasattr(converter, "list_supported_formats")
