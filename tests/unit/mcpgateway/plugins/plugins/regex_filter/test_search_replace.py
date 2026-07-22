# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/regex_filter/test_search_replace.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for the regex_filter plugin with nested structure support.
"""

# Standard
import re

# Third-Party
import pytest

# First-Party
from cpex.framework import (
    GlobalContext,
    PluginConfig,
    PluginContext,
    PromptHookType,
    PromptPosthookPayload,
    PromptPrehookPayload,
    ToolHookType,
    ToolPostInvokePayload,
    ToolPreInvokePayload,
)
from mcpgateway.common.models import Message, PromptResult, Role, TextContent
from plugins.regex_filter.search_replace import SearchReplace, SearchReplaceConfig, SearchReplacePlugin, _scan_and_replace_recursive


class TestScanAndReplaceRecursive:
    """Test the _scan_and_replace_recursive helper function."""

    def test_simple_string_replacement(self):
        """Test replacement in a simple string."""
        patterns = [(re.compile(r"bad"), "good")]
        result = _scan_and_replace_recursive("This is bad text", patterns)
        assert result == "This is good text"

    def test_multiple_patterns_on_string(self):
        """Test multiple patterns applied to same string."""
        patterns = [
            (re.compile(r"bad"), "good"),
            (re.compile(r"ugly"), "beautiful")
        ]
        result = _scan_and_replace_recursive("bad and ugly", patterns)
        assert result == "good and beautiful"

    def test_regex_pattern_with_groups(self):
        """Test regex pattern with capture groups."""
        patterns = [(re.compile(r"(\d{3})-(\d{3})-(\d{4})"), r"XXX-XXX-\3")]
        result = _scan_and_replace_recursive("Call 123-456-7890", patterns)
        assert result == "Call XXX-XXX-7890"

    def test_no_match_returns_original(self):
        """Test that strings without matches are returned unchanged."""
        patterns = [(re.compile(r"bad"), "good")]
        result = _scan_and_replace_recursive("This is clean text", patterns)
        assert result == "This is clean text"

    def test_nested_dict_single_level(self):
        """Test replacement in a single-level dictionary."""
        patterns = [(re.compile(r"bad"), "good")]
        data = {"field1": "clean text", "field2": "bad text"}
        result = _scan_and_replace_recursive(data, patterns)
        assert result["field1"] == "clean text"
        assert result["field2"] == "good text"

    def test_nested_dict_multiple_levels(self):
        """Test replacement in deeply nested dictionaries."""
        patterns = [(re.compile(r"bad"), "good")]
        data = {
            "level1": {
                "level2": {
                    "level3": "bad text here"
                }
            }
        }
        result = _scan_and_replace_recursive(data, patterns)
        assert result["level1"]["level2"]["level3"] == "good text here"

    def test_nested_list(self):
        """Test replacement in lists."""
        patterns = [(re.compile(r"bad"), "good")]
        data = ["clean", "bad text", "also clean"]
        result = _scan_and_replace_recursive(data, patterns)
        assert result[0] == "clean"
        assert result[1] == "good text"
        assert result[2] == "also clean"

    def test_dict_with_list_values(self):
        """Test replacement in dictionaries containing lists."""
        patterns = [(re.compile(r"bad"), "good")]
        data = {
            "items": ["clean", "bad text", "clean again"]
        }
        result = _scan_and_replace_recursive(data, patterns)
        assert result["items"][1] == "good text"

    def test_list_with_dict_items(self):
        """Test replacement in lists containing dictionaries."""
        patterns = [(re.compile(r"bad"), "good")]
        data = [
            {"name": "clean"},
            {"name": "bad text"},
            {"name": "clean"}
        ]
        result = _scan_and_replace_recursive(data, patterns)
        assert result[1]["name"] == "good text"

    def test_complex_nested_structure(self):
        """Test replacement in complex nested structures."""
        patterns = [(re.compile(r"bad"), "good")]
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
                        "bio": "bad bio",
                        "interests": ["gaming", "bad hobby"]
                    }
                }
            ]
        }
        result = _scan_and_replace_recursive(data, patterns)
        assert result["users"][1]["profile"]["bio"] == "good bio"
        assert result["users"][1]["profile"]["interests"][1] == "good hobby"

    def test_non_string_values_preserved(self):
        """Test that non-string values are preserved unchanged."""
        patterns = [(re.compile(r"bad"), "good")]
        data = {
            "number": 12345,
            "boolean": True,
            "none": None,
            "text": "bad text"
        }
        result = _scan_and_replace_recursive(data, patterns)
        assert result["number"] == 12345
        assert result["boolean"] is True
        assert result["none"] is None
        assert result["text"] == "good text"

    def test_empty_patterns_list(self):
        """Test with empty patterns list."""
        result = _scan_and_replace_recursive("any text", [])
        assert result == "any text"

    def test_empty_string(self):
        """Test with empty string."""
        patterns = [(re.compile(r"bad"), "good")]
        result = _scan_and_replace_recursive("", patterns)
        assert result == ""

    def test_case_sensitive_replacement(self):
        """Test case-sensitive replacement."""
        patterns = [(re.compile(r"bad"), "good")]
        result = _scan_and_replace_recursive("bad BAD Bad", patterns)
        assert result == "good BAD Bad"

    def test_case_insensitive_replacement(self):
        """Test case-insensitive replacement."""
        patterns = [(re.compile(r"bad", re.IGNORECASE), "good")]
        result = _scan_and_replace_recursive("bad BAD Bad", patterns)
        assert result == "good good good"


class TestSearchReplaceConfig:
    """Test the SearchReplaceConfig model."""

    def test_valid_config(self):
        """Test valid configuration."""
        config = SearchReplaceConfig(
            words=[
                SearchReplace(search=r"\d{3}-\d{3}-\d{4}", replace="XXX-XXX-XXXX"),
                SearchReplace(search=r"bad", replace="good")
            ]
        )
        assert len(config.words) == 2
        assert config.words[0].search == r"\d{3}-\d{3}-\d{4}"

    def test_empty_words_list(self):
        """Test configuration with empty words list."""
        config = SearchReplaceConfig(words=[])
        assert len(config.words) == 0


class TestSearchReplacePlugin:
    """Test the SearchReplacePlugin class."""

    @pytest.fixture
    def plugin_config(self) -> PluginConfig:
        """Create a test plugin configuration."""
        return PluginConfig(
            name="TestSearchReplace",
            description="Test Search Replace",
            author="Test",
            kind="plugins.regex_filter.search_replace.SearchReplacePlugin",
            version="1.0",
            hooks=[
                PromptHookType.PROMPT_PRE_FETCH,
                PromptHookType.PROMPT_POST_FETCH,
                ToolHookType.TOOL_PRE_INVOKE,
                ToolHookType.TOOL_POST_INVOKE
            ],
            tags=["test", "regex"],
            config={
                "words": [
                    {"search": r"\d{3}-\d{3}-\d{4}", "replace": "XXX-XXX-XXXX"},
                    {"search": r"bad", "replace": "good"},
                    {"search": r"secret", "replace": "[REDACTED]"}
                ]
            },
        )

    @pytest.fixture
    def plugin(self, plugin_config) -> SearchReplacePlugin:
        """Create a test plugin instance."""
        return SearchReplacePlugin(plugin_config)

    @pytest.fixture
    def context(self) -> PluginContext:
        """Create a test plugin context."""
        return PluginContext(global_context=GlobalContext(request_id="test-1"))

    @pytest.mark.asyncio
    async def test_prompt_pre_fetch_clean_args(self, plugin, context):
        """Test that clean arguments pass through unchanged."""
        payload = PromptPrehookPayload(
            prompt_id="test_prompt",
            args={"user_input": "This is clean text", "another_field": "Also clean"}
        )
        result = await plugin.prompt_pre_fetch(payload, context)
        assert result.modified_payload.args["user_input"] == "This is clean text"
        assert result.modified_payload.args["another_field"] == "Also clean"

    @pytest.mark.asyncio
    async def test_prompt_pre_fetch_simple_replacement(self, plugin, context):
        """Test simple replacement in arguments."""
        payload = PromptPrehookPayload(
            prompt_id="test_prompt",
            args={"user_input": "This is bad text"}
        )
        result = await plugin.prompt_pre_fetch(payload, context)
        assert result.modified_payload.args["user_input"] == "This is good text"

    @pytest.mark.asyncio
    async def test_prompt_pre_fetch_phone_number_redaction(self, plugin, context):
        """Test phone number redaction."""
        payload = PromptPrehookPayload(
            prompt_id="test_prompt",
            args={"user_input": "Call me at 123-456-7890"}
        )
        result = await plugin.prompt_pre_fetch(payload, context)
        assert result.modified_payload.args["user_input"] == "Call me at XXX-XXX-XXXX"

    @pytest.mark.asyncio
    async def test_prompt_pre_fetch_nested_dict(self, plugin, context):
        """Test replacement in nested dictionary using _scan_and_replace_recursive directly."""
        # Test the helper function directly since args must be flat strings
        patterns = [(re.compile(r"bad"), "good"), (re.compile(r"secret"), "[REDACTED]")]
        data = {
            "user": {
                "profile": {
                    "bio": "This is bad and contains secret info"
                }
            }
        }
        result = _scan_and_replace_recursive(data, patterns)
        assert result["user"]["profile"]["bio"] == "This is good and contains [REDACTED] info"

    @pytest.mark.asyncio
    async def test_prompt_pre_fetch_nested_list(self, plugin, context):
        """Test replacement in nested list using _scan_and_replace_recursive directly."""
        # Test the helper function directly since args must be flat strings
        patterns = [(re.compile(r"bad"), "good"), (re.compile(r"secret"), "[REDACTED]")]
        data = {
            "items": ["clean", "bad text", "secret data"]
        }
        result = _scan_and_replace_recursive(data, patterns)
        assert result["items"][1] == "good text"
        assert result["items"][2] == "[REDACTED] data"

    @pytest.mark.asyncio
    async def test_prompt_pre_fetch_complex_nested(self, plugin, context):
        """Test replacement in complex nested structure using _scan_and_replace_recursive directly."""
        # Test the helper function directly since args must be flat strings
        patterns = [(re.compile(r"\d{3}-\d{3}-\d{4}"), "XXX-XXX-XXXX"), (re.compile(r"bad"), "good"), (re.compile(r"secret"), "[REDACTED]")]
        data = {
            "data": {
                "users": [
                    {"name": "Alice", "phone": "123-456-7890"},
                    {"name": "Bob", "comment": "bad comment with secret"}
                ]
            }
        }
        result = _scan_and_replace_recursive(data, patterns)
        assert result["data"]["users"][0]["phone"] == "XXX-XXX-XXXX"
        assert result["data"]["users"][1]["comment"] == "good comment with [REDACTED]"

    @pytest.mark.asyncio
    async def test_prompt_pre_fetch_no_args(self, plugin, context):
        """Test handling of payload with no args."""
        payload = PromptPrehookPayload(prompt_id="test_prompt", args=None)
        result = await plugin.prompt_pre_fetch(payload, context)
        assert result.modified_payload.args is None

    @pytest.mark.asyncio
    async def test_prompt_post_fetch(self, plugin, context):
        """Test replacement in prompt post-fetch messages."""
        messages = [
            Message(role=Role.USER, content=TextContent(type="text", text="This is bad text")),
            Message(role=Role.ASSISTANT, content=TextContent(type="text", text="Call 123-456-7890 for secret info")),
        ]
        payload = PromptPosthookPayload(
            prompt_id="test_prompt",
            result=PromptResult(messages=messages)
        )
        result = await plugin.prompt_post_fetch(payload, context)
        assert result.modified_payload.result.messages[0].content.text == "This is good text"
        assert result.modified_payload.result.messages[1].content.text == "Call XXX-XXX-XXXX for [REDACTED] info"

    @pytest.mark.asyncio
    async def test_tool_pre_invoke_simple(self, plugin, context):
        """Test replacement in tool pre-invoke."""
        payload = ToolPreInvokePayload(
            name="test_tool",
            args={"input": "bad text with 123-456-7890"}
        )
        result = await plugin.tool_pre_invoke(payload, context)
        assert result.modified_payload.args["input"] == "good text with XXX-XXX-XXXX"

    @pytest.mark.asyncio
    async def test_tool_pre_invoke_nested(self, plugin, context):
        """Test replacement in nested tool arguments using _scan_and_replace_recursive directly."""
        # Test the helper function directly since args must be flat strings
        patterns = [(re.compile(r"bad"), "good"), (re.compile(r"secret"), "[REDACTED]")]
        data = {
            "config": {
                "settings": {
                    "value": "bad value with secret"
                }
            }
        }
        result = _scan_and_replace_recursive(data, patterns)
        assert result["config"]["settings"]["value"] == "good value with [REDACTED]"

    @pytest.mark.asyncio
    async def test_tool_post_invoke_dict_result(self, plugin, context):
        """Test replacement in tool post-invoke with dict result using _scan_and_replace_recursive directly."""
        # Test the helper function directly for nested dict results
        patterns = [(re.compile(r"\d{3}-\d{3}-\d{4}"), "XXX-XXX-XXXX"), (re.compile(r"bad"), "good"), (re.compile(r"secret"), "[REDACTED]")]
        data = {
            "status": "success",
            "message": "bad result with secret",
            "data": {
                "phone": "123-456-7890"
            }
        }
        result = _scan_and_replace_recursive(data, patterns)
        assert result["message"] == "good result with [REDACTED]"
        assert result["data"]["phone"] == "XXX-XXX-XXXX"

    @pytest.mark.asyncio
    async def test_tool_post_invoke_string_result(self, plugin, context):
        """Test replacement in tool post-invoke with string result."""
        payload = ToolPostInvokePayload(
            name="test_tool",
            result="This is bad text with 123-456-7890"
        )
        result = await plugin.tool_post_invoke(payload, context)
        assert result.modified_payload.result == "This is good text with XXX-XXX-XXXX"

    @pytest.mark.asyncio
    async def test_tool_post_invoke_none_result(self, plugin, context):
        """Test handling of None result."""
        payload = ToolPostInvokePayload(
            name="test_tool",
            result=None
        )
        result = await plugin.tool_post_invoke(payload, context)
        assert result.modified_payload.result is None

    def test_invalid_regex_pattern_skipped(self):
        """Test that invalid regex patterns are skipped during initialization."""
        config = PluginConfig(
            name="TestInvalidRegex",
            kind="plugins.regex_filter.search_replace.SearchReplacePlugin",
            hooks=[PromptHookType.PROMPT_PRE_FETCH],
            config={
                "words": [
                    {"search": r"[invalid(", "replace": "good"},  # Invalid regex
                    {"search": r"bad", "replace": "good"}  # Valid regex
                ]
            },
        )
        plugin = SearchReplacePlugin(config)
        # Should only have one valid pattern
        assert len(plugin._SearchReplacePlugin__patterns) == 1



class TestDeepRecursion:
    """Test deep recursion protection in regex_filter."""

    def test_recursion_depth_limit_pathological_payload(self):
        """Test that Python's native RecursionError fires on a pathologically nested payload."""
        import sys

        depth = sys.getrecursionlimit() + 100
        nested: dict = {"data": "test phone number 123-456-7890"}
        for i in range(depth):
            nested = {"level": nested}

        patterns = [(re.compile(r"\d{3}-\d{3}-\d{4}"), "XXX-XXX-XXXX")]

        with pytest.raises(RecursionError):
            _scan_and_replace_recursive(nested, patterns)

    def test_realistic_mcp_payload_depth_3(self):
        """Test standard MCP tool call structure (3-4 levels deep) with PII redaction."""
        # This is the actual structure used by OpenAI, Anthropic, LangChain
        payload = {
            "tool_call": {
                "name": "test_tool",
                "input": {
                    "params": {
                        "text": "test data with phone 123-456-7890 and badword content"
                    }
                }
            }
        }

        patterns = [
            (re.compile(r"\d{3}-\d{3}-\d{4}"), "XXX-XXX-XXXX"),
            (re.compile(r"badword"), "[REDACTED]")
        ]

        result = _scan_and_replace_recursive(payload, patterns)

        # Verify both patterns were replaced at the deepest level
        text = result["tool_call"]["input"]["params"]["text"]
        assert "XXX-XXX-XXXX" in text
        assert "[REDACTED]" in text
        assert "123-456-7890" not in text
        assert "badword" not in text

    def test_wide_payload_many_tools(self):
        """Test wide payload with many tool calls at same level (not deep)."""
        # Simulate a batch of 100 tool calls at the same level
        payload = {
            f"tool_{i}": {
                "name": f"query_{i}",
                "input": {"phone": f"123-456-{i:04d}"}
            }
            for i in range(100)
        }

        patterns = [(re.compile(r"\d{3}-\d{3}-\d{4}"), "XXX-XXX-XXXX")]

        # Should not raise - width doesn't affect recursion depth
        result = _scan_and_replace_recursive(payload, patterns)
        assert result is not None

        # Verify all phone numbers were redacted
        for i in range(100):
            assert result[f"tool_{i}"]["input"]["phone"] == "XXX-XXX-XXXX"
