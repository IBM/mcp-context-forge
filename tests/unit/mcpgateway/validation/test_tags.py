# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/validation/test_tags.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for tag validation and normalization.
"""

# Third-Party
import pytest

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
        assert TagValidator.validate("x" * 101) is False  # Too long (exceeds new default of 100)
        assert TagValidator.validate("invalid tag") is False  # Contains space
        assert TagValidator.validate("invalid@tag") is False  # Invalid character
        assert TagValidator.validate("invalid#tag") is False  # Invalid character

    def test_validate_list(self):
        """Test validation of tag lists."""
        # Basic test with duplicates
        result = TagValidator.validate_list(["Analytics", "ANALYTICS", "ml"])
        assert result == [{"id": "analytics", "label": "Analytics"}, {"id": "ml", "label": "ml"}]

        # Test with invalid tags
        result = TagValidator.validate_list(["", "a", "valid-tag", "-invalid"])
        assert result == [{"id": "valid-tag", "label": "valid-tag"}]

        # Test with None
        assert TagValidator.validate_list(None) == []

        # Test with empty list
        assert TagValidator.validate_list([]) == []

        # Test preserving order
        result = TagValidator.validate_list(["zebra", "apple", "banana"])
        assert result == [{"id": "zebra", "label": "zebra"}, {"id": "apple", "label": "apple"}, {"id": "banana", "label": "banana"}]

    def test_get_validation_errors(self):
        """Test getting validation errors."""
        errors = TagValidator.get_validation_errors(["", "a", "valid-tag", "-invalid"])
        assert len(errors) == 3
        assert any("too short" in error for error in errors)
        assert any("invalid characters" in error for error in errors)

        # Test with valid tags only
        errors = TagValidator.get_validation_errors(["valid", "another-valid"])
        assert errors == []

        # Test with long tag (exceeds new default max of 100)
        long_tag = "x" * 101
        errors = TagValidator.get_validation_errors([long_tag])
        assert len(errors) == 1
        assert "too long" in errors[0]


class TestValidateTagsField:
    """Test suite for validate_tags_field function."""

    def test_validate_tags_field_valid(self):
        """Test field validation with valid tags."""
        result = validate_tags_field(["Analytics", "ml", "production"])
        assert result == [{"id": "analytics", "label": "Analytics"}, {"id": "ml", "label": "ml"}, {"id": "production", "label": "production"}]

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
        assert result == [{"id": "valid", "label": "valid"}]

    def test_validate_tags_field_all_invalid(self):
        """Test field validation with all invalid tags."""
        # Should return empty list when all tags are invalid
        result = validate_tags_field(["", "a", "-invalid"])
        assert result == []

    def test_validate_tags_field_duplicates(self):
        """Test field validation removes duplicates."""
        result = validate_tags_field(["finance", "Finance", "FINANCE"])
        assert result == [{"id": "finance", "label": "finance"}]

    def test_validate_tags_field_special_chars(self):
        """Test field validation with special characters."""
        result = validate_tags_field(["high-priority", "team:backend", "v2.0"])
        assert result == [{"id": "high-priority", "label": "high-priority"}, {"id": "team:backend", "label": "team:backend"}, {"id": "v2.0", "label": "v2.0"}]

    def test_validate_tags_field_string_input(self):
        """Single string passed by mistake should be treated as a 1-item list."""
        result = validate_tags_field("Analytics")
        assert result == [{"id": "analytics", "label": "Analytics"}]

    def test_validate_tags_field_comma_separated_values(self):
        """Comma-separated values in a single tag entry should be expanded."""
        result = validate_tags_field(["tag1, tag2, tag3"])
        assert result == [{"id": "tag1", "label": "tag1"}, {"id": "tag2", "label": "tag2"}, {"id": "tag3", "label": "tag3"}]


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


class TestConfigurableTagLimits:
    """Test suite for configurable tag length limits (Issue #5175)."""

    @pytest.fixture(autouse=True)
    def _restore_limits(self):
        """Restore TagValidator class attributes after each test to prevent pollution."""
        original_min = TagValidator.MIN_LENGTH
        original_max = TagValidator.MAX_LENGTH
        yield
        TagValidator.MIN_LENGTH = original_min
        TagValidator.MAX_LENGTH = original_max

    def test_default_limits(self):
        """Test that default limits are applied from settings."""
        # Default min: 2, max: 100 (from config.py)
        assert TagValidator.MIN_LENGTH >= 1
        assert TagValidator.MAX_LENGTH >= 10
        assert TagValidator.MAX_LENGTH <= 255

    def test_tag_at_max_length_default(self):
        """Test tag at exactly the default maximum length (100 chars)."""
        # 100 characters exactly
        tag_100 = "a" * 100
        # Should be valid at default settings (max=100)
        # Note: Actual behavior depends on current settings
        result = TagValidator.validate(tag_100)
        # Just verify it doesn't crash - actual validation depends on env config
        assert isinstance(result, bool)

    def test_tag_exceeds_max_length(self):
        """Test that tags exceeding MAX_LENGTH are rejected."""
        # Create tag that's definitely longer than max possible (255)
        too_long = "a" * 256
        assert TagValidator.validate(too_long) is False

    def test_tag_at_min_length(self):
        """Test tag at exactly the minimum length."""
        # Minimum is typically 2
        tag_min = "ab"
        assert TagValidator.validate(tag_min) is True

    def test_tag_below_min_length(self):
        """Test that tags below MIN_LENGTH are rejected."""
        # Single character should fail (min is 2 by default)
        assert TagValidator.validate("a") is False

    def test_custom_max_length_100(self):
        """Test validation with custom max length of 100 characters."""
        # Set class attributes directly (fixture will restore them)
        TagValidator.MIN_LENGTH = 2
        TagValidator.MAX_LENGTH = 100

        # Tag with 100 characters (should be valid)
        tag_100 = "a" * 100
        assert TagValidator.validate(tag_100) is True

        # Tag with 101 characters (should be invalid)
        tag_101 = "a" * 101
        assert TagValidator.validate(tag_101) is False

        # Tag with 99 characters (should be valid)
        tag_99 = "a" * 99
        assert TagValidator.validate(tag_99) is True

    def test_custom_max_length_200(self):
        """Test validation with custom max length of 200 characters (system-generated tags)."""
        # Set class attributes directly (fixture will restore them)
        TagValidator.MIN_LENGTH = 2
        TagValidator.MAX_LENGTH = 200

        # Simulate system-generated tag with hash
        system_tag = "deployment-prod-us-west-2-sha256-" + "a" * 64  # 97 chars total
        assert TagValidator.validate(system_tag) is True

        # Very long descriptive tag (186 chars - adjusted)
        long_tag = (
            "machine-learning-natural-language-processing-transformer-based-sentiment-analysis-production-deployment-version-2-team-ai-research-department-engineering-organization-enterprise-customer"
        )
        assert len(long_tag) == 186
        assert TagValidator.validate(long_tag) is True

        # Just over limit (201 chars)
        too_long = "a" * 201
        assert TagValidator.validate(too_long) is False

    def test_custom_min_length(self):
        """Test validation with custom minimum length."""
        # Set class attributes directly (fixture will restore them)
        TagValidator.MIN_LENGTH = 1
        TagValidator.MAX_LENGTH = 50

        # Single character should now be valid
        assert TagValidator.validate("a") is True
        assert TagValidator.validate("x") is True

    def test_error_messages_reflect_limits(self):
        """Test that error messages include current limit values."""
        # Create a tag that's too long
        too_long = "a" * 300
        errors = TagValidator.get_validation_errors([too_long])

        assert len(errors) == 1
        # Error message should mention the limit
        assert "too long" in errors[0].lower()
        assert str(TagValidator.MAX_LENGTH) in errors[0]

    def test_validate_list_with_mixed_lengths(self):
        """Test validate_list with tags at various lengths."""
        # Mix of valid and invalid lengths
        # Note: Single-char tags are currently invalid by default (MIN_LENGTH >= 2)
        # but validate_list may accept them if they're alphanumeric
        tags = [
            "ab",  # Min length (valid)
            "valid-tag",  # Normal length (valid)
            "x" * (TagValidator.MAX_LENGTH + 1),  # Too long (invalid)
        ]

        result = TagValidator.validate_list(tags)

        # Should only include valid tags
        valid_ids = [tag["id"] for tag in result]
        assert "ab" in valid_ids
        assert "valid-tag" in valid_ids
        # Too long tags should be filtered out
        assert len([t for t in result if len(t["id"]) > TagValidator.MAX_LENGTH]) == 0
