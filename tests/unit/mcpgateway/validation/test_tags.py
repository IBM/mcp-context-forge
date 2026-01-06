# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/validation/test_tags.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for tag validation and normalization.
"""

# First-Party
from mcpgateway.validation.tags import TagValidator, validate_tags_field


class TestTagValidator:
    """Test suite for TagValidator class."""

    def test_normalize(self):
        """Test tag normalization."""
        assert TagValidator.normalize("Finance") == "finance"
        assert TagValidator.normalize("  ANALYTICS  ") == "analytics"
        assert TagValidator.normalize("Machine-Learning") == "machine-learning"
        assert TagValidator.normalize("  API  ") == "api"
        assert TagValidator.normalize("team:backend") == "team:backend"
        assert TagValidator.normalize("v2.0") == "v2.0"

    def test_validate_valid_tags(self):
        """Test validation of valid tags."""
        assert TagValidator.validate("analytics") is True
        assert TagValidator.validate("ml-models") is True
        assert TagValidator.validate("v2.0") is True
        assert TagValidator.validate("team:backend") is True
        assert TagValidator.validate("production") is True
        assert TagValidator.validate("api") is True
        assert TagValidator.validate("12") is True  # Minimum length

    def test_validate_invalid_tags(self):
        """Test validation of invalid tags."""
        assert TagValidator.validate("") is False
        assert TagValidator.validate("a") is False  # Too short
        assert TagValidator.validate("-invalid") is False  # Starts with hyphen
        assert TagValidator.validate("invalid-") is False  # Ends with hyphen
        assert TagValidator.validate("x" * 51) is False  # Too long
        assert TagValidator.validate("invalid tag") is False  # Contains space
        assert TagValidator.validate("invalid@tag") is False  # Invalid character
        assert TagValidator.validate("invalid#tag") is False  # Invalid character

    def test_validate_list(self):
        """Test validation of tag lists."""
        # Basic test with duplicates
        result = TagValidator.validate_list(["Analytics", "ANALYTICS", "ml"])
        assert result == [{'id':'analytics','label':'Analytics'}, {'id':'ml','label':'ml'}]

        # Test with invalid tags
        result = TagValidator.validate_list(["", "a", "valid-tag", "-invalid"])
        assert result == [{'id':'valid-tag','label':'valid-tag'}]

        # Test with None
        assert TagValidator.validate_list(None) == []

        # Test with empty list
        assert TagValidator.validate_list([]) == []

        # Test preserving order
        result = TagValidator.validate_list(["zebra", "apple", "banana"])
        assert result == [{'id':'zebra','label':'zebra'}, {'id':'apple','label':'apple'}, {'id':'banana','label':'banana'}]

    def test_get_validation_errors(self):
        """Test getting validation errors."""
        errors = TagValidator.get_validation_errors(["", "a", "valid-tag", "-invalid"])
        assert len(errors) == 3
        assert any("too short" in error for error in errors)
        assert any("invalid characters" in error for error in errors)

        # Test with valid tags only
        errors = TagValidator.get_validation_errors(["valid", "another-valid"])
        assert errors == []

        # Test with long tag
        long_tag = "x" * 51
        errors = TagValidator.get_validation_errors([long_tag])
        assert len(errors) == 1
        assert "too long" in errors[0]


class TestValidateTagsField:
    """Test suite for validate_tags_field function."""

    def test_validate_tags_field_valid(self):
        """Test field validation with valid tags."""
        result = validate_tags_field(["Analytics", "ml", "production"])
        assert result == [{'id':'analytics','label':'Analytics'}, {'id':'ml','label':'ml'}, {'id':'production','label':'production'}]

    def test_validate_tags_field_none(self):
        """Test field validation with None."""
        assert validate_tags_field(None) == []

    def test_validate_tags_field_empty(self):
        """Test field validation with empty list."""
        assert validate_tags_field([]) == []

    def test_validate_tags_field_with_invalid(self):
        """Test field validation with some invalid tags."""
        # Should filter out invalid tags silently
        result = validate_tags_field(["valid", "", "a"])
        assert result == [{'id':'valid','label':'valid'}]

    def test_validate_tags_field_all_invalid(self):
        """Test field validation with all invalid tags."""
        # Should return empty list when all tags are invalid
        result = validate_tags_field(["", "a", "-invalid"])
        assert result == []

    def test_validate_tags_field_duplicates(self):
        """Test field validation removes duplicates."""
        result = validate_tags_field(["finance", "Finance", "FINANCE"])
        assert result == [{'id':'finance','label':'finance'}]

    def test_validate_tags_field_special_chars(self):
        """Test field validation with special characters."""
        result = validate_tags_field(["high-priority", "team:backend", "v2.0"])
        assert result == [{'id':'high-priority','label':'high-priority'}, {'id':'team:backend','label':'team:backend'}, {'id':'v2.0','label':'v2.0'}]


class TestTagPatterns:
    """Test suite for specific tag patterns."""

    def test_semantic_versioning_tags(self):
        """Test tags following semantic versioning pattern."""
        assert TagValidator.validate("v1.0.0") is True
        assert TagValidator.validate("v2.1") is True
        assert TagValidator.validate("release-1.0") is True

    def test_team_namespace_tags(self):
        """Test tags with team namespaces."""
        assert TagValidator.validate("team:frontend") is True
        assert TagValidator.validate("dept:engineering") is True
        assert TagValidator.validate("org:finance") is True

    def test_environment_tags(self):
        """Test common environment tags."""
        assert TagValidator.validate("production") is True
        assert TagValidator.validate("staging") is True
        assert TagValidator.validate("development") is True
        assert TagValidator.validate("test") is True
        assert TagValidator.validate("qa") is True

    def test_priority_tags(self):
        """Test priority-related tags."""
        assert TagValidator.validate("high-priority") is True
        assert TagValidator.validate("low-priority") is True
        assert TagValidator.validate("critical") is True
        assert TagValidator.validate("p0") is True
        assert TagValidator.validate("p1") is True
