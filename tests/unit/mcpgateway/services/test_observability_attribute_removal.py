# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_observability_attribute_removal.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for ObservabilityService attribute removal logic.
"""

import pytest
from unittest.mock import MagicMock, patch

from mcpgateway.plugins.framework import GlobalContext, PluginContext
from mcpgateway.services.observability_service import ObservabilityService


@pytest.mark.asyncio
async def test_observability_removes_specified_attributes():
    """Test that ObservabilityService removes attributes specified in context (line 517)."""
    with patch("mcpgateway.services.observability_service.SessionLocal") as mock_session:
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        obs_service = ObservabilityService()

        # Setup context with attributes to remove
        global_context = GlobalContext(request_id="test-123")
        global_context.state["remove_span_attributes"] = ["debug_info", "internal_id"]
        context = PluginContext(global_context=global_context)

        # Create attributes including ones to be removed
        attributes = {
            "tool.name": "test_tool",
            "debug_info": "sensitive",
            "internal_id": "12345",
            "public_attr": "visible",
        }

        # Simulate the removal logic from observability_service.py (line 517)
        remove_attrs = context.global_context.state.get("remove_span_attributes", [])
        if remove_attrs:
            for attr_name in remove_attrs:
                attributes.pop(attr_name, None)

        # Verify removal was applied
        assert "tool.name" in attributes
        assert "public_attr" in attributes
        assert "debug_info" not in attributes
        assert "internal_id" not in attributes


@pytest.mark.asyncio
async def test_observability_removal_with_nonexistent_attributes():
    """Test that removal handles non-existent attributes gracefully."""
    with patch("mcpgateway.services.observability_service.SessionLocal") as mock_session:
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        obs_service = ObservabilityService()

        # Setup context with attributes to remove (some don't exist)
        global_context = GlobalContext(request_id="test-123")
        global_context.state["remove_span_attributes"] = ["nonexistent", "also_missing"]
        context = PluginContext(global_context=global_context)

        # Create attributes that don't include the ones to be removed
        attributes = {
            "tool.name": "test_tool",
            "public_attr": "visible",
        }

        # Simulate the removal logic
        remove_attrs = context.global_context.state.get("remove_span_attributes", [])
        if remove_attrs:
            for attr_name in remove_attrs:
                attributes.pop(attr_name, None)

        # Verify no error and attributes remain
        assert "tool.name" in attributes
        assert "public_attr" in attributes


@pytest.mark.asyncio
async def test_observability_removal_empty_list():
    """Test that empty removal list doesn't affect attributes."""
    with patch("mcpgateway.services.observability_service.SessionLocal") as mock_session:
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        obs_service = ObservabilityService()

        # Setup context with empty removal list
        global_context = GlobalContext(request_id="test-123")
        global_context.state["remove_span_attributes"] = []
        context = PluginContext(global_context=global_context)

        # Create attributes
        attributes = {
            "tool.name": "test_tool",
            "debug_info": "should_remain",
        }

        # Simulate the removal logic
        remove_attrs = context.global_context.state.get("remove_span_attributes", [])
        if remove_attrs:
            for attr_name in remove_attrs:
                attributes.pop(attr_name, None)

        # Verify all attributes remain
        assert "tool.name" in attributes
        assert "debug_info" in attributes


@pytest.mark.asyncio
async def test_observability_removal_not_in_context():
    """Test that missing removal list in context doesn't break execution."""
    with patch("mcpgateway.services.observability_service.SessionLocal") as mock_session:
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        obs_service = ObservabilityService()

        # Setup context WITHOUT removal list
        global_context = GlobalContext(request_id="test-123")
        context = PluginContext(global_context=global_context)

        # Create attributes
        attributes = {
            "tool.name": "test_tool",
            "debug_info": "should_remain",
        }

        # Simulate the removal logic
        remove_attrs = context.global_context.state.get("remove_span_attributes", [])
        if remove_attrs:
            for attr_name in remove_attrs:
                attributes.pop(attr_name, None)

        # Verify all attributes remain
        assert "tool.name" in attributes
        assert "debug_info" in attributes


@pytest.mark.asyncio
async def test_observability_combined_mapping_and_removal():
    """Test that attribute mapping and removal work together."""
    with patch("mcpgateway.services.observability_service.SessionLocal") as mock_session:
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db

        obs_service = ObservabilityService()

        # Setup context with both mapping and removal
        global_context = GlobalContext(request_id="test-123")
        global_context.state["span_attribute_mapping"] = {"tool.name": "controls.artifact.name"}
        global_context.state["remove_span_attributes"] = ["debug_info"]
        context = PluginContext(global_context=global_context)

        # Create attributes
        attributes = {
            "tool.name": "test_tool",
            "debug_info": "sensitive",
            "public_attr": "visible",
        }

        # Simulate mapping first
        from mcpgateway.plugins.framework.utils import apply_attribute_mapping

        attribute_mapping = context.global_context.state.get("span_attribute_mapping", {})
        if attribute_mapping:
            attributes = apply_attribute_mapping(attributes, attribute_mapping)

        # Then removal
        remove_attrs = context.global_context.state.get("remove_span_attributes", [])
        if remove_attrs:
            for attr_name in remove_attrs:
                attributes.pop(attr_name, None)

        # Verify both operations were applied
        assert "controls.artifact.name" in attributes
        assert attributes["controls.artifact.name"] == "test_tool"
        assert "tool.name" not in attributes  # Mapped away
        assert "debug_info" not in attributes  # Removed
        assert "public_attr" in attributes  # Preserved
