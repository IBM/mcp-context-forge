# -*- coding: utf-8 -*-
"""Tests for regex_filter plugin.

Location: tests/unit/plugins/test_regex_filter.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
"""

import os
import pytest

from mcpgateway.plugins.framework import (
    GlobalContext,
    PluginConfig,
    PluginContext,
)

# Try to import Rust implementation
try:
    from regex_filter import SearchReplacePluginRust

    RUST_AVAILABLE = True
except ImportError:
    RUST_AVAILABLE = False
    SearchReplacePluginRust = None
    # Fail in CI if Rust plugins are required
    if os.environ.get("REQUIRE_RUST_PLUGINS") == "1":
        raise ImportError("Rust plugin 'regex_filter' is required in CI but not available")


@pytest.fixture
def plugin_config():
    """Create a basic plugin configuration."""
    return PluginConfig(
        name="TestSearchReplace",
        kind="plugins.regex_filter.search_replace.SearchReplacePlugin",
        version="0.1",
        hooks=["prompt_pre_fetch", "prompt_post_fetch", "tool_pre_invoke", "tool_post_invoke"],
        config={
            "words": [
                {"search": "bad", "replace": "good"},
                {"search": r"\bsecret\b", "replace": "[REDACTED]"},
                {"search": r"\d{3}-\d{2}-\d{4}", "replace": "XXX-XX-XXXX"},
            ]
        },
    )


@pytest.fixture
def context():
    """Create a basic plugin context."""
    return PluginContext(global_context=GlobalContext(request_id="test-request"))


# Parametrized tests that run with both Python and Rust implementations
@pytest.mark.parametrize(
    "use_rust",
    [
        pytest.param(False, id="python"),
        pytest.param(True, marks=pytest.mark.skipif(not RUST_AVAILABLE, reason="Rust not available"), id="rust"),
    ],
)
class TestSearchReplaceBothImplementations:
    """Test search/replace with both Python and Rust implementations.

    These tests run twice - once with use_rust=False (Python) and once with use_rust=True (Rust).
    This ensures both implementations produce correct results.
    """

    @pytest.mark.asyncio
    async def test_prompt_pre_fetch_simple_replacement(self, plugin_config, context, use_rust):
        """Test simple word replacement in prompt arguments."""
        from plugins.regex_filter.search_replace import _process_container, SearchReplaceConfig

        config = SearchReplaceConfig.model_validate(plugin_config.config)

        # Compile patterns for Python fallback
        import re

        patterns = []
        for word in config.words:
            try:
                compiled_pattern = re.compile(word.search)
                patterns.append((compiled_pattern, word.replace))
            except re.error:
                pass

        args = {"message": "This is bad"}
        modified, new_args = _process_container(args, config, patterns, use_rust=use_rust)

        assert modified
        assert new_args["message"] == "This is good"

    @pytest.mark.asyncio
    async def test_prompt_pre_fetch_regex_replacement(self, plugin_config, context, use_rust):
        """Test regex pattern replacement in prompt arguments."""
        from plugins.regex_filter.search_replace import _process_container, SearchReplaceConfig

        config = SearchReplaceConfig.model_validate(plugin_config.config)

        import re

        patterns = []
        for word in config.words:
            try:
                compiled_pattern = re.compile(word.search)
                patterns.append((compiled_pattern, word.replace))
            except re.error:
                pass

        args = {"message": "The secret password is hidden"}
        modified, new_args = _process_container(args, config, patterns, use_rust=use_rust)

        assert modified
        assert new_args["message"] == "The [REDACTED] password is hidden"

    @pytest.mark.asyncio
    async def test_prompt_pre_fetch_ssn_replacement(self, plugin_config, context, use_rust):
        """Test SSN pattern replacement."""
        from plugins.regex_filter.search_replace import _process_container, SearchReplaceConfig

        config = SearchReplaceConfig.model_validate(plugin_config.config)

        import re

        patterns = []
        for word in config.words:
            try:
                compiled_pattern = re.compile(word.search)
                patterns.append((compiled_pattern, word.replace))
            except re.error:
                pass

        args = {"message": "SSN: 123-45-6789"}
        modified, new_args = _process_container(args, config, patterns, use_rust=use_rust)

        assert modified
        assert new_args["message"] == "SSN: XXX-XX-XXXX"

    @pytest.mark.asyncio
    async def test_prompt_pre_fetch_multiple_replacements(self, plugin_config, context, use_rust):
        """Test multiple replacements in same text."""
        from plugins.regex_filter.search_replace import _process_container, SearchReplaceConfig

        config = SearchReplaceConfig.model_validate(plugin_config.config)

        import re

        patterns = []
        for word in config.words:
            try:
                compiled_pattern = re.compile(word.search)
                patterns.append((compiled_pattern, word.replace))
            except re.error:
                pass

        args = {"message": "This bad secret is bad"}
        modified, new_args = _process_container(args, config, patterns, use_rust=use_rust)

        assert modified
        # "bad" -> "good", "secret" -> "[REDACTED]"
        assert new_args["message"] == "This good [REDACTED] is good"

    @pytest.mark.asyncio
    async def test_nested_dict(self, plugin_config, context, use_rust):
        """Test replacement in nested dictionary."""
        from plugins.regex_filter.search_replace import _process_container, SearchReplaceConfig

        config = SearchReplaceConfig.model_validate(plugin_config.config)

        import re

        patterns = []
        for word in config.words:
            try:
                compiled_pattern = re.compile(word.search)
                patterns.append((compiled_pattern, word.replace))
            except re.error:
                pass

        args = {"outer": {"inner": "This is bad"}}
        modified, new_args = _process_container(args, config, patterns, use_rust=use_rust)

        assert modified
        assert new_args["outer"]["inner"] == "This is good"

    @pytest.mark.asyncio
    async def test_tool_post_invoke_list_result(self, plugin_config, context, use_rust):
        """Test replacement in tool result (list)."""
        from plugins.regex_filter.search_replace import _process_container, SearchReplaceConfig

        config = SearchReplaceConfig.model_validate(plugin_config.config)

        import re

        patterns = []
        for word in config.words:
            try:
                compiled_pattern = re.compile(word.search)
                patterns.append((compiled_pattern, word.replace))
            except re.error:
                pass

        result = ["This is bad", "Another bad thing"]
        modified, new_result = _process_container(result, config, patterns, use_rust=use_rust)

        assert modified
        assert new_result[0] == "This is good"
        assert new_result[1] == "Another good thing"

    @pytest.mark.asyncio
    async def test_chained_replacements(self, context, use_rust):
        """Test that replacements are applied in order."""
        from plugins.regex_filter.search_replace import _process_container, SearchReplaceConfig

        config = SearchReplaceConfig(
            words=[
                {"search": "foo", "replace": "bar"},
                {"search": "bar", "replace": "baz"},
            ]
        )

        import re

        patterns = []
        for word in config.words:
            try:
                compiled_pattern = re.compile(word.search)
                patterns.append((compiled_pattern, word.replace))
            except re.error:
                pass

        args = {"message": "foo"}
        modified, new_args = _process_container(args, config, patterns, use_rust=use_rust)

        # foo -> bar -> baz
        assert modified
        assert new_args["message"] == "baz"


def test_rust_availability():
    """Test that Rust availability is correctly detected."""
    from plugins.regex_filter.search_replace import _RUST_AVAILABLE

    # Just verify the flag is a boolean
    assert isinstance(_RUST_AVAILABLE, bool)


class TestPatternValidation:
    """Test pattern validation and error handling."""

    def test_invalid_regex_pattern_detected(self):
        """Test that invalid regex patterns are detected."""
        from plugins.regex_filter.search_replace import SearchReplace

        word = SearchReplace(search="[invalid(", replace="valid")
        is_valid, error_msg = word.validate_pattern()

        assert not is_valid
        assert error_msg is not None
        assert "Invalid regex pattern" in error_msg
        assert "[invalid(" in error_msg

    def test_multiple_invalid_patterns_detected(self):
        """Test that multiple invalid patterns are detected."""
        from plugins.regex_filter.search_replace import SearchReplaceConfig

        config = SearchReplaceConfig(
            words=[
                {"search": "[invalid(", "replace": "valid"},
                {"search": "(?P<incomplete", "replace": "valid"},
                {"search": "valid", "replace": "valid"},
            ]
        )

        errors = config.validate_all_patterns()
        assert len(errors) >= 2  # At least 2 invalid patterns
        error_text = " ".join(errors)
        assert "[invalid(" in error_text
        assert "(?P<incomplete" in error_text

    def test_valid_patterns_no_error(self):
        """Test that valid patterns don't raise errors."""
        from plugins.regex_filter.search_replace import SearchReplaceConfig

        # Should not raise
        config = SearchReplaceConfig(
            words=[
                {"search": r"\d+", "replace": "NUM"},
                {"search": r"[a-z]+", "replace": "WORD"},
                {"search": r"(?:foo|bar)", "replace": "BAZ"},
            ]
        )
        assert len(config.words) == 3
        errors = config.validate_all_patterns()
        assert len(errors) == 0


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.mark.parametrize("use_rust", [False, pytest.param(True, marks=pytest.mark.skipif(not RUST_AVAILABLE, reason="Rust not available"))])
    def test_empty_string_input(self, use_rust):
        """Test handling of empty string."""
        from plugins.regex_filter.search_replace import _process_container, SearchReplaceConfig
        import re

        config = SearchReplaceConfig(words=[{"search": "test", "replace": "TEST"}])
        patterns = [(re.compile(w.search), w.replace) for w in config.words]

        modified, result = _process_container("", config, patterns, use_rust=use_rust)
        assert not modified
        assert result == ""

    @pytest.mark.parametrize("use_rust", [False, pytest.param(True, marks=pytest.mark.skipif(not RUST_AVAILABLE, reason="Rust not available"))])
    def test_unicode_emojis(self, use_rust):
        """Test handling of Unicode emojis."""
        from plugins.regex_filter.search_replace import _process_container, SearchReplaceConfig
        import re

        config = SearchReplaceConfig(words=[{"search": "bad", "replace": "good"}])
        patterns = [(re.compile(w.search), w.replace) for w in config.words]

        text = "This is bad 😀 very bad 🎉"
        modified, result = _process_container(text, config, patterns, use_rust=use_rust)
        assert modified
        assert result == "This is good 😀 very good 🎉"


class TestDataTypes:
    """Test handling of different data types."""

    @pytest.mark.parametrize("use_rust", [False, pytest.param(True, marks=pytest.mark.skipif(not RUST_AVAILABLE, reason="Rust not available"))])
    def test_dict_with_none_values(self, use_rust):
        """Test dict with None values."""
        from plugins.regex_filter.search_replace import _process_container, SearchReplaceConfig
        import re

        config = SearchReplaceConfig(words=[{"search": "bad", "replace": "good"}])
        patterns = [(re.compile(w.search), w.replace) for w in config.words]

        data = {"key1": "bad", "key2": None}
        modified, result = _process_container(data, config, patterns, use_rust=use_rust)
        assert modified
        assert result["key1"] == "good"
        assert result["key2"] is None

    @pytest.mark.parametrize("use_rust", [False, pytest.param(True, marks=pytest.mark.skipif(not RUST_AVAILABLE, reason="Rust not available"))])
    def test_list_with_mixed_types(self, use_rust):
        """Test list with mixed types."""
        from plugins.regex_filter.search_replace import _process_container, SearchReplaceConfig
        import re

        config = SearchReplaceConfig(words=[{"search": "bad", "replace": "good"}])
        patterns = [(re.compile(w.search), w.replace) for w in config.words]

        data = ["bad", 123, None, {"nested": "bad"}]
        modified, result = _process_container(data, config, patterns, use_rust=use_rust)
        assert modified
        assert result[0] == "good"
        assert result[1] == 123
        assert result[2] is None
        assert result[3]["nested"] == "good"


class TestComplexPatterns:
    """Test complex regex patterns."""

    @pytest.mark.parametrize("use_rust", [False, pytest.param(True, marks=pytest.mark.skipif(not RUST_AVAILABLE, reason="Rust not available"))])
    def test_character_class(self, use_rust):
        """Test character class patterns."""
        from plugins.regex_filter.search_replace import _process_container, SearchReplaceConfig
        import re

        config = SearchReplaceConfig(words=[{"search": r"[0-9]+", "replace": "NUM"}])
        patterns = [(re.compile(w.search), w.replace) for w in config.words]

        text = "I have 123 apples and 456 oranges"
        modified, result = _process_container(text, config, patterns, use_rust=use_rust)
        assert modified
        assert result == "I have NUM apples and NUM oranges"

    @pytest.mark.parametrize("use_rust", [False, pytest.param(True, marks=pytest.mark.skipif(not RUST_AVAILABLE, reason="Rust not available"))])
    def test_word_boundary_pattern(self, use_rust):
        """Test word boundary patterns."""
        from plugins.regex_filter.search_replace import _process_container, SearchReplaceConfig
        import re

        config = SearchReplaceConfig(words=[{"search": r"\bcat\b", "replace": "dog"}])
        patterns = [(re.compile(w.search), w.replace) for w in config.words]

        text = "The cat and the caterpillar"
        modified, result = _process_container(text, config, patterns, use_rust=use_rust)
        assert modified
        assert result == "The dog and the caterpillar"

    @pytest.mark.parametrize("use_rust", [False, pytest.param(True, marks=pytest.mark.skipif(not RUST_AVAILABLE, reason="Rust not available"))])
    def test_case_insensitive_pattern(self, use_rust):
        """Test case-insensitive patterns."""
        from plugins.regex_filter.search_replace import _process_container, SearchReplaceConfig
        import re

        config = SearchReplaceConfig(words=[{"search": r"(?i)test", "replace": "EXAM"}])
        patterns = [(re.compile(w.search), w.replace) for w in config.words]

        text = "Test TEST test TeSt"
        modified, result = _process_container(text, config, patterns, use_rust=use_rust)
        assert modified
        assert result == "EXAM EXAM EXAM EXAM"


class TestRealWorldScenarios:
    """Test real-world use cases."""

    @pytest.mark.parametrize("use_rust", [False, pytest.param(True, marks=pytest.mark.skipif(not RUST_AVAILABLE, reason="Rust not available"))])
    def test_email_redaction(self, use_rust):
        """Test email address redaction."""
        from plugins.regex_filter.search_replace import _process_container, SearchReplaceConfig
        import re

        config = SearchReplaceConfig(words=[{"search": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "replace": "[EMAIL]"}])
        patterns = [(re.compile(w.search), w.replace) for w in config.words]

        text = "Contact me at john.doe@example.com or jane@test.org"
        modified, result = _process_container(text, config, patterns, use_rust=use_rust)
        assert modified
        assert result == "Contact me at [EMAIL] or [EMAIL]"

    @pytest.mark.parametrize("use_rust", [False, pytest.param(True, marks=pytest.mark.skipif(not RUST_AVAILABLE, reason="Rust not available"))])
    def test_credit_card_redaction(self, use_rust):
        """Test credit card number redaction."""
        from plugins.regex_filter.search_replace import _process_container, SearchReplaceConfig
        import re

        config = SearchReplaceConfig(words=[{"search": r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b", "replace": "[CARD]"}])
        patterns = [(re.compile(w.search), w.replace) for w in config.words]

        text = "Card: 1234-5678-9012-3456 or 1234567890123456"
        modified, result = _process_container(text, config, patterns, use_rust=use_rust)
        assert modified
        assert result == "Card: [CARD] or [CARD]"

    @pytest.mark.parametrize("use_rust", [False, pytest.param(True, marks=pytest.mark.skipif(not RUST_AVAILABLE, reason="Rust not available"))])
    def test_ipv4_address_redaction(self, use_rust):
        """Test IPv4 address redaction."""
        from plugins.regex_filter.search_replace import _process_container, SearchReplaceConfig
        import re

        config = SearchReplaceConfig(words=[{"search": r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "replace": "[IP]"}])
        patterns = [(re.compile(w.search), w.replace) for w in config.words]

        text = "Server at 192.168.1.1 and 10.0.0.1"
        modified, result = _process_container(text, config, patterns, use_rust=use_rust)
        assert modified
        assert result == "Server at [IP] and [IP]"

    @pytest.mark.parametrize("use_rust", [False, pytest.param(True, marks=pytest.mark.skipif(not RUST_AVAILABLE, reason="Rust not available"))])
    def test_url_redaction(self, use_rust):
        """Test URL redaction."""
        from plugins.regex_filter.search_replace import _process_container, SearchReplaceConfig
        import re

        config = SearchReplaceConfig(words=[{"search": r"https?://[^\s]+", "replace": "[URL]"}])
        patterns = [(re.compile(w.search), w.replace) for w in config.words]

        text = "Visit https://example.com or http://test.org/path"
        modified, result = _process_container(text, config, patterns, use_rust=use_rust)
        assert modified
        assert result == "Visit [URL] or [URL]"


class TestErrorHandling:
    """Test error handling and edge cases."""

    def test_empty_config_no_words(self):
        """Test config with no words."""
        from plugins.regex_filter.search_replace import SearchReplaceConfig

        config = SearchReplaceConfig(words=[])
        assert len(config.words) == 0

    def test_invalid_regex_detected(self):
        """Test that invalid regex in config is detected."""
        from plugins.regex_filter.search_replace import SearchReplaceConfig

        config = SearchReplaceConfig(words=[{"search": "[invalid(", "replace": "test"}])
        errors = config.validate_all_patterns()
        assert len(errors) > 0
        assert "[invalid(" in " ".join(errors)

    def test_missing_search_field(self):
        """Test that missing search field raises error."""
        from plugins.regex_filter.search_replace import SearchReplaceConfig
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            SearchReplaceConfig(words=[{"replace": "test"}])

    def test_missing_replace_field(self):
        """Test that missing replace field raises error."""
        from plugins.regex_filter.search_replace import SearchReplaceConfig
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            SearchReplaceConfig(words=[{"search": "test"}])


# Made with Bob
