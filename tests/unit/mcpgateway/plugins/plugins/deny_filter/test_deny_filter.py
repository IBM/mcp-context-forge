# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/deny_filter/test_deny_filter.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Test Suite

Tests for the deny_filter plugin with nested structure support.
"""

# Third-Party
import pytest

# First-Party
from cpex.framework import GlobalContext, PluginConfig, PluginContext, PromptHookType, PromptPrehookPayload
from plugins.deny_filter.deny import DenyListConfig, DenyListPlugin, _scan_for_denied_words


class TestScanForDeniedWords:
    """Test the _scan_for_denied_words helper function."""

    def test_simple_string_match(self):
        """Test detection in a simple string."""
        violations = _scan_for_denied_words("This contains badword in text", ["badword"])
        assert len(violations) == 1
        assert "contains 'badword'" in violations[0]

    def test_case_insensitive_match(self):
        """Test case-insensitive detection."""
        violations = _scan_for_denied_words("This contains BADWORD in text", ["badword"])
        assert len(violations) == 1
        assert "contains 'badword'" in violations[0]

    def test_no_match_in_string(self):
        """Test no detection when word is not present."""
        violations = _scan_for_denied_words("This is clean text", ["badword"])
        assert len(violations) == 0

    def test_nested_dict_single_level(self):
        """Test detection in a single-level dictionary."""
        data = {"field1": "clean text", "field2": "contains badword here"}
        violations = _scan_for_denied_words(data, ["badword"])
        assert len(violations) == 1
        assert "field2" in violations[0]
        assert "contains 'badword'" in violations[0]

    def test_nested_dict_multiple_levels(self):
        """Test detection in deeply nested dictionaries."""
        data = {
            "level1": {
                "level2": {
                    "level3": "contains badword here"
                }
            }
        }
        violations = _scan_for_denied_words(data, ["badword"])
        assert len(violations) == 1
        assert "level1.level2.level3" in violations[0]
        assert "contains 'badword'" in violations[0]

    def test_nested_list(self):
        """Test detection in lists."""
        data = ["clean", "contains badword", "also clean"]
        violations = _scan_for_denied_words(data, ["badword"])
        assert len(violations) == 1
        assert "[1]" in violations[0]
        assert "contains 'badword'" in violations[0]

    def test_dict_with_list_values(self):
        """Test detection in dictionaries containing lists."""
        data = {
            "items": ["clean", "contains badword", "clean again"]
        }
        violations = _scan_for_denied_words(data, ["badword"])
        assert len(violations) == 1
        assert "items[1]" in violations[0]
        assert "contains 'badword'" in violations[0]

    def test_list_with_dict_items(self):
        """Test detection in lists containing dictionaries."""
        data = [
            {"name": "clean"},
            {"name": "contains badword"},
            {"name": "clean"}
        ]
        violations = _scan_for_denied_words(data, ["badword"])
        assert len(violations) == 1
        assert "[1].name" in violations[0]
        assert "contains 'badword'" in violations[0]

    def test_complex_nested_structure(self):
        """Test detection in complex nested structures."""
        data = {
            "users": [
                {
                    "name": "Alice",
                    "profile": {
                        "bio": "Clean bio",
                        "interests": ["reading", "coding"]
                    }
                },
                {
                    "name": "Bob",
                    "profile": {
                        "bio": "Contains badword in bio",
                        "interests": ["gaming", "contains badword"]
                    }
                }
            ]
        }
        violations = _scan_for_denied_words(data, ["badword"])
        assert len(violations) == 2
        assert any("users[1].profile.bio" in v for v in violations)
        assert any("users[1].profile.interests[1]" in v for v in violations)

    def test_multiple_denied_words(self):
        """Test detection of multiple different denied words."""
        data = {"field1": "contains badword1", "field2": "contains badword2"}
        violations = _scan_for_denied_words(data, ["badword1", "badword2"])
        assert len(violations) == 2

    def test_same_word_multiple_locations(self):
        """Test detection of same word in multiple locations."""
        data = {
            "field1": "contains badword",
            "field2": "also contains badword"
        }
        violations = _scan_for_denied_words(data, ["badword"])
        assert len(violations) == 2

    def test_non_string_values_ignored(self):
        """Test that non-string values are properly handled."""
        data = {
            "number": 12345,
            "boolean": True,
            "none": None,
            "text": "contains badword"
        }
        violations = _scan_for_denied_words(data, ["badword"])
        assert len(violations) == 1
        assert "text" in violations[0]

    def test_empty_deny_list(self):
        """Test with empty deny list."""
        violations = _scan_for_denied_words("any text here", [])
        assert len(violations) == 0

    def test_empty_value(self):
        """Test with empty string value."""
        violations = _scan_for_denied_words("", ["badword"])
        assert len(violations) == 0

    def test_partial_word_match(self):
        """Test that partial matches are detected."""
        violations = _scan_for_denied_words("embadwordded", ["badword"])
        assert len(violations) == 1


class TestDenyListConfig:
    """Test the DenyListConfig model."""

    def test_valid_config(self):
        """Test valid configuration."""
        config = DenyListConfig(words=["bad", "worse", "worst"])
        assert len(config.words) == 3
        assert "bad" in config.words

    def test_empty_words_list(self):
        """Test configuration with empty words list."""
        config = DenyListConfig(words=[])
        assert len(config.words) == 0


class TestDenyListPlugin:
    """Test the DenyListPlugin class."""

    @pytest.fixture
    def plugin_config(self) -> PluginConfig:
        """Create a test plugin configuration."""
        return PluginConfig(
            name="TestDenyFilter",
            description="Test Deny Filter",
            author="Test",
            kind="plugins.deny_filter.deny.DenyListPlugin",
            version="1.0",
            hooks=[PromptHookType.PROMPT_PRE_FETCH],
            tags=["test", "deny"],
            config={"words": ["badword", "forbidden", "blocked"]},
        )

    @pytest.fixture
    def plugin(self, plugin_config) -> DenyListPlugin:
        """Create a test plugin instance."""
        return DenyListPlugin(plugin_config)

    @pytest.fixture
    def context(self) -> PluginContext:
        """Create a test plugin context."""
        return PluginContext(global_context=GlobalContext(request_id="test-1"))

    @pytest.mark.asyncio
    async def test_prompt_pre_fetch_clean_args(self, plugin, context):
        """Test that clean arguments pass through."""
        payload = PromptPrehookPayload(
            prompt_id="test_prompt",
            args={"user_input": "This is clean text", "another_field": "Also clean"}
        )
        result = await plugin.prompt_pre_fetch(payload, context)
        assert result.continue_processing is True
        assert result.violation is None
        assert result.modified_payload == payload

    @pytest.mark.asyncio
    async def test_prompt_pre_fetch_simple_violation(self, plugin, context):
        """Test detection of denied word in simple argument."""
        payload = PromptPrehookPayload(
            prompt_id="test_prompt",
            args={"user_input": "This contains badword in text"}
        )
        result = await plugin.prompt_pre_fetch(payload, context)
        assert result.continue_processing is False
        assert result.violation is not None
        assert result.violation.code == "deny"
        assert result.violation.reason == "Prompt not allowed"
        assert "violations" in result.violation.details
        assert len(result.violation.details["violations"]) == 1

    @pytest.mark.asyncio
    async def test_prompt_pre_fetch_nested_dict_violation(self, plugin, context):
        """Test detection in nested dictionary structure using _scan_for_denied_words directly."""
        # Test the helper function directly since args must be flat strings
        data = {
            "user": {
                "profile": {
                    "bio": "Contains forbidden word here"
                }
            }
        }
        violations = _scan_for_denied_words(data, ["forbidden"])
        assert len(violations) == 1
        assert "user.profile.bio" in violations[0]

    @pytest.mark.asyncio
    async def test_prompt_pre_fetch_nested_list_violation(self, plugin, context):
        """Test detection in nested list structure using _scan_for_denied_words directly."""
        # Test the helper function directly since args must be flat strings
        data = {
            "items": ["clean", "contains blocked word", "clean"]
        }
        violations = _scan_for_denied_words(data, ["blocked"])
        assert len(violations) == 1
        assert "items[1]" in violations[0]

    @pytest.mark.asyncio
    async def test_prompt_pre_fetch_complex_nested_violation(self, plugin, context):
        """Test detection in complex nested structure using _scan_for_denied_words directly."""
        # Test the helper function directly since args must be flat strings
        data = {
            "data": {
                "users": [
                    {"name": "Alice", "comment": "Clean"},
                    {"name": "Bob", "comment": "Contains badword here"}
                ]
            }
        }
        violations = _scan_for_denied_words(data, ["badword"])
        assert len(violations) == 1
        assert "data.users[1].comment" in violations[0]

    @pytest.mark.asyncio
    async def test_prompt_pre_fetch_multiple_violations(self, plugin, context):
        """Test detection of multiple violations."""
        payload = PromptPrehookPayload(
            prompt_id="test_prompt",
            args={
                "field1": "contains badword",
                "field2": "contains forbidden",
                "field3": "contains blocked"
            }
        )
        result = await plugin.prompt_pre_fetch(payload, context)
        assert result.continue_processing is False
        assert result.violation is not None
        assert len(result.violation.details["violations"]) == 3

    @pytest.mark.asyncio
    async def test_prompt_pre_fetch_case_insensitive(self, plugin, context):
        """Test case-insensitive detection."""
        payload = PromptPrehookPayload(
            prompt_id="test_prompt",
            args={"user_input": "This contains BADWORD in uppercase"}
        )
        result = await plugin.prompt_pre_fetch(payload, context)
        assert result.continue_processing is False
        assert result.violation is not None

    @pytest.mark.asyncio
    async def test_prompt_pre_fetch_no_args(self, plugin, context):
        """Test handling of payload with no args."""
        payload = PromptPrehookPayload(prompt_id="test_prompt", args=None)
        result = await plugin.prompt_pre_fetch(payload, context)
        assert result.continue_processing is True
        assert result.violation is None

    @pytest.mark.asyncio
    async def test_prompt_pre_fetch_empty_args(self, plugin, context):
        """Test handling of payload with empty args."""
        payload = PromptPrehookPayload(prompt_id="test_prompt", args={})
        result = await plugin.prompt_pre_fetch(payload, context)
        assert result.continue_processing is True
        assert result.violation is None

    @pytest.mark.asyncio
    async def test_shutdown(self, plugin):
        """Test plugin shutdown."""
        await plugin.shutdown()
        # Should complete without error

# Made with Bob
