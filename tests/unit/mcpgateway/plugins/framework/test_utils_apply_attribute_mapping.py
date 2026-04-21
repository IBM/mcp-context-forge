# -*- coding: utf-8 -*-
"""Unit tests for apply_attribute_mapping utility function.

Location: ./tests/unit/mcpgateway/plugins/framework/test_utils_apply_attribute_mapping.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

import pytest

from mcpgateway.plugins.framework.utils import apply_attribute_mapping


class TestApplyAttributeMapping:
    """Test cases for apply_attribute_mapping function."""

    def test_empty_mapping_returns_original(self):
        """Test that empty mapping returns original attributes unchanged."""
        attributes = {"tool.name": "weather", "tool.version": "1.0"}
        mapping = {}

        result = apply_attribute_mapping(attributes, mapping)

        assert result == attributes
        # Function returns same dict when mapping is empty (optimization)

    def test_none_mapping_returns_original(self):
        """Test that None mapping returns original attributes unchanged."""
        attributes = {"tool.name": "weather", "tool.version": "1.0"}
        mapping = None

        result = apply_attribute_mapping(attributes, mapping)

        assert result == attributes

    def test_single_attribute_mapping(self):
        """Test mapping a single attribute."""
        attributes = {"tool.name": "weather"}
        mapping = {"tool.name": "controls.artifact.name"}

        result = apply_attribute_mapping(attributes, mapping)

        assert "controls.artifact.name" in result
        assert result["controls.artifact.name"] == "weather"
        assert "tool.name" not in result

    def test_multiple_attribute_mappings(self):
        """Test mapping multiple attributes."""
        attributes = {
            "tool.name": "weather",
            "tool.version": "1.0",
            "tool.arguments": '{"key": "value"}'
        }
        mapping = {
            "tool.name": "controls.artifact.name",
            "tool.arguments": "controls.artifact.inputs"
        }

        result = apply_attribute_mapping(attributes, mapping)

        assert result["controls.artifact.name"] == "weather"
        assert result["controls.artifact.inputs"] == '{"key": "value"}'
        assert result["tool.version"] == "1.0"  # Unmapped attribute preserved
        assert "tool.name" not in result
        assert "tool.arguments" not in result

    def test_unmapped_attributes_preserved(self):
        """Test that unmapped attributes are preserved with original names."""
        attributes = {
            "tool.name": "weather",
            "tool.version": "1.0",
            "custom.field": "value"
        }
        mapping = {"tool.name": "controls.artifact.name"}

        result = apply_attribute_mapping(attributes, mapping)

        assert result["controls.artifact.name"] == "weather"
        assert result["tool.version"] == "1.0"
        assert result["custom.field"] == "value"

    def test_mapping_with_special_characters(self):
        """Test mapping with special characters in attribute names."""
        attributes = {
            "plugin.name": "TestPlugin",
            "plugin.hook.type": "tool_pre_invoke"
        }
        mapping = {
            "plugin.name": "controls.artifact.name",
            "plugin.hook.type": "controls.hook.type"
        }

        result = apply_attribute_mapping(attributes, mapping)

        assert result["controls.artifact.name"] == "TestPlugin"
        assert result["controls.hook.type"] == "tool_pre_invoke"

    def test_mapping_preserves_value_types(self):
        """Test that mapping preserves different value types."""
        attributes = {
            "string_attr": "value",
            "int_attr": 42,
            "bool_attr": True,
            "float_attr": 3.14,
            "none_attr": None,
            "list_attr": [1, 2, 3],
            "dict_attr": {"key": "value"}
        }
        mapping = {
            "string_attr": "new.string",
            "int_attr": "new.int",
            "bool_attr": "new.bool"
        }

        result = apply_attribute_mapping(attributes, mapping)

        assert result["new.string"] == "value"
        assert result["new.int"] == 42
        assert result["new.bool"] is True
        assert result["float_attr"] == 3.14
        assert result["none_attr"] is None
        assert result["list_attr"] == [1, 2, 3]
        assert result["dict_attr"] == {"key": "value"}

    def test_empty_attributes_with_mapping(self):
        """Test empty attributes dict with non-empty mapping."""
        attributes = {}
        mapping = {"tool.name": "controls.artifact.name"}

        result = apply_attribute_mapping(attributes, mapping)

        assert result == {}

    def test_mapping_to_same_name(self):
        """Test mapping an attribute to itself (no-op mapping)."""
        attributes = {"tool.name": "weather"}
        mapping = {"tool.name": "tool.name"}

        result = apply_attribute_mapping(attributes, mapping)

        assert result["tool.name"] == "weather"

    def test_multiple_attributes_to_same_target(self):
        """Test mapping multiple source attributes to same target (last wins)."""
        attributes = {
            "tool.name": "weather",
            "plugin.name": "TestPlugin"
        }
        mapping = {
            "tool.name": "controls.artifact.name",
            "plugin.name": "controls.artifact.name"
        }

        result = apply_attribute_mapping(attributes, mapping)

        # Last mapping wins
        assert result["controls.artifact.name"] == "TestPlugin"
        assert "tool.name" not in result
        assert "plugin.name" not in result

    def test_docstring_example(self):
        """Test the example from the function's docstring."""
        attrs = {"tool.name": "weather", "tool.version": "1.0"}
        mapping = {"tool.name": "controls.artifact.name"}

        result = apply_attribute_mapping(attrs, mapping)

        assert result == {'controls.artifact.name': 'weather', 'tool.version': '1.0'}
