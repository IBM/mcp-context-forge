# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/pptx_server/tests/test_server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for PowerPoint MCP Server (FastMCP).
"""

from pptx_server.server_fastmcp import manager


def test_create_presentation():
    """Test creating a presentation."""
    result = manager.create_presentation(title="Test Presentation")

    assert result["success"] is True
    assert "presentation_id" in result


def test_add_slide():
    """Test adding a slide."""
    # Create a presentation first
    pres_result = manager.create_presentation()
    presentation_id = pres_result["presentation_id"]

    result = manager.add_slide(
        presentation_id=presentation_id, layout="Title and Content", title="Test Slide"
    )

    assert result["success"] is True
    assert result["slide_number"] == 1


def test_add_text_to_slide():
    """Test adding text to a slide."""
    # Create a presentation and slide first
    pres_result = manager.create_presentation()
    presentation_id = pres_result["presentation_id"]

    slide_result = manager.add_slide(presentation_id=presentation_id, layout="Title and Content")

    result = manager.add_text_to_slide(
        presentation_id=presentation_id, slide_number=1, text="Test content", placeholder_index=1
    )

    assert result["success"] is True


def test_get_presentation_info():
    """Test getting presentation info."""
    # Create a presentation first
    pres_result = manager.create_presentation(title="Info Test")
    presentation_id = pres_result["presentation_id"]

    # Add a slide
    manager.add_slide(presentation_id=presentation_id)

    result = manager.get_presentation_info(presentation_id)

    assert result["success"] is True
    assert result["slide_count"] == 1


def test_save_presentation():
    """Test saving a presentation."""
    import os
    import tempfile

    # Create a presentation
    pres_result = manager.create_presentation()
    presentation_id = pres_result["presentation_id"]

    # Save to a temporary file
    with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as tmp:
        result = manager.save_presentation(presentation_id, tmp.name)
        assert result["success"] is True
        assert os.path.exists(tmp.name)

        # Clean up
        os.unlink(tmp.name)


def test_invalid_presentation_id():
    """Test operations with invalid presentation ID."""
    result = manager.add_slide(presentation_id="invalid_id", layout="Title Slide")

    assert result["success"] is False
    assert "error" in result


def test_manager_initialization():
    """Test manager initialization state."""
    assert manager is not None
    assert hasattr(manager, "create_presentation")
    assert hasattr(manager, "add_slide")
    assert hasattr(manager, "add_text_to_slide")
    assert hasattr(manager, "save_presentation")
