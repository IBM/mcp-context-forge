# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/content_moderation/test_content_moderation.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Tests for ContentModerationPlugin.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcpgateway.plugins.framework import (
    GlobalContext,
    PluginConfig,
    PluginContext,
    PluginViolation,
    PromptHookType,
    ToolHookType,
    PromptPrehookPayload,
    ToolPreInvokePayload,
    ToolPostInvokePayload,
)
from plugins.content_moderation.content_moderation import (
    ContentModerationPlugin,
    ModerationAction,
    ModerationProvider,
    ModerationCategory,
)


def _create_plugin(config_dict=None) -> ContentModerationPlugin:
    """Helper to create content moderation plugin with test config."""
    default_config = {
        "provider": "ibm_watson",
        "fallback_provider": "ibm_granite",
        "fallback_on_error": "warn",
        "ibm_watson": {
            "api_key": "test-watson-key",
            "url": "https://api.us-south.natural-language-understanding.watson.cloud.ibm.com",
            "version": "2022-04-07"
        },
        "ibm_granite": {
            "ollama_url": "http://localhost:11434",
            "model": "granite3-guardian",
            "temperature": 0.1
        },
        "categories": {
            "hate": {"threshold": 0.7, "action": "block"},
            "violence": {"threshold": 0.8, "action": "block"},
            "sexual": {"threshold": 0.6, "action": "warn"},
            "profanity": {"threshold": 0.6, "action": "redact"}
        },
        "audit_decisions": True,
        "enable_caching": True,
        "max_text_length": 10000
    }

    if config_dict:
        default_config.update(config_dict)

    return ContentModerationPlugin(
        PluginConfig(
            name="content_moderation_test",
            kind="plugins.content_moderation.content_moderation.ContentModerationPlugin",
            hooks=[PromptHookType.PROMPT_PRE_FETCH, ToolHookType.TOOL_PRE_INVOKE],
            config=default_config,
        )
    )


def _create_context(user="testuser", request_id="req-123") -> PluginContext:
    """Helper to create plugin context."""
    return PluginContext(
        global_context=GlobalContext(
            request_id=request_id,
            user=user,
            tenant_id="tenant-abc",
            server_id="server-xyz"
        )
    )


class TestContentModerationPlugin:
    """Test cases for ContentModerationPlugin."""

    @pytest.mark.asyncio
    async def test_plugin_initialization(self):
        """Test plugin initializes correctly with default config."""
        plugin = _create_plugin()
        assert plugin.name == "content_moderation_test"
        assert plugin._cfg.provider == ModerationProvider.IBM_WATSON
        assert plugin._cfg.fallback_provider == ModerationProvider.IBM_GRANITE
        assert ModerationCategory.HATE in plugin._cfg.categories

    @pytest.mark.asyncio
    async def test_cache_operations(self):
        """Test caching functionality."""
        plugin = _create_plugin()

        cache_key = await plugin._get_cache_key("test text", ModerationProvider.IBM_WATSON)
        assert isinstance(cache_key, str)
        assert "ibm_watson:" in cache_key

        # Test cache miss
        result = await plugin._get_cached_result("test text", ModerationProvider.IBM_WATSON)
        assert result is None

    @pytest.mark.asyncio
    async def test_text_extraction_from_payload(self):
        """Test text extraction from different payload types."""
        plugin = _create_plugin()

        payload = PromptPrehookPayload(
            prompt_id="test_prompt",
            args={
                "query": "This is a test query",
                "context": "Additional context",
                "metadata": "nested text"
            }
        )

        texts = await plugin._extract_text_content(payload)
        assert "This is a test query" in texts
        assert "Additional context" in texts
        assert "nested text" in texts

    @pytest.mark.asyncio
    @patch('plugins.content_moderation.content_moderation.httpx.AsyncClient')
    async def test_ibm_watson_moderation_success(self, mock_client_class):
        """Test successful IBM Watson moderation."""
        # Setup mock response
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "emotion": {
                "document": {
                    "emotion": {
                        "anger": 0.8,
                        "disgust": 0.3,
                        "fear": 0.1,
                        "sadness": 0.2
                    }
                }
            },
            "sentiment": {
                "document": {
                    "score": -0.8,
                    "label": "negative"
                }
            },
            "concepts": []
        }
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        plugin = _create_plugin()
        plugin._client = mock_client

        result = await plugin._moderate_with_ibm_watson("This is hateful content")

        assert result.provider == ModerationProvider.IBM_WATSON
        assert isinstance(result.flagged, bool)
        assert "hate" in result.categories
        assert result.categories["hate"] > 0  # Should have some hate score
        mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    @patch('plugins.content_moderation.content_moderation.httpx.AsyncClient')
    async def test_ibm_granite_moderation_success(self, mock_client_class):
        """Test successful IBM Granite Guardian moderation."""
        # Setup mock response
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "response": '{"hate": 0.9, "violence": 0.2, "sexual": 0.1, "self_harm": 0.0, "harassment": 0.3, "toxic": 0.7}'
        }
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        plugin = _create_plugin()
        plugin._client = mock_client

        result = await plugin._moderate_with_ibm_granite("This is hateful violent content")

        assert result.provider == ModerationProvider.IBM_GRANITE
        assert result.flagged is True  # Should be flagged due to high hate score
        assert result.categories["hate"] == 0.9
        assert result.categories["violence"] == 0.2
        assert result.action == ModerationAction.BLOCK  # Hate threshold is 0.7
        mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    @patch('plugins.content_moderation.content_moderation.httpx.AsyncClient')
    async def test_openai_moderation_success(self, mock_client_class):
        """Test successful OpenAI moderation."""
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [{
                "flagged": True,
                "categories": {
                    "hate": True,
                    "violence": False,
                    "sexual": False,
                    "self-harm": False,
                    "harassment": False
                },
                "category_scores": {
                    "hate": 0.85,
                    "violence": 0.1,
                    "sexual": 0.05,
                    "self-harm": 0.01,
                    "harassment": 0.2
                }
            }]
        }
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        config = {
            "provider": "openai",
            "openai": {
                "api_key": "test-openai-key",
                "api_base": "https://api.openai.com/v1"
            }
        }
        plugin = _create_plugin(config)
        plugin._client = mock_client

        result = await plugin._moderate_with_openai("This is hateful content")

        assert result.provider == ModerationProvider.OPENAI
        assert result.flagged is True
        assert result.categories["hate"] == 0.85
        assert result.action == ModerationAction.BLOCK

    @pytest.mark.asyncio
    async def test_pattern_based_moderation(self):
        """Test fallback pattern-based moderation."""
        plugin = _create_plugin()

        # Test hate speech detection
        result = await plugin._moderate_with_patterns("I hate all those racist people")
        assert result.categories["hate"] > 0

        # Test violence detection
        result = await plugin._moderate_with_patterns("I'm going to kill you")
        assert result.categories["violence"] > 0

        # Test self-harm detection
        result = await plugin._moderate_with_patterns("I want to kill myself")
        assert result.categories["self_harm"] > 0

        # Test profanity detection
        result = await plugin._moderate_with_patterns("This is fucking bullshit")
        assert result.categories["profanity"] > 0

        # Test clean content
        result = await plugin._moderate_with_patterns("This is a nice sunny day")
        assert max(result.categories.values()) < 0.1

    @pytest.mark.asyncio
    async def test_moderation_actions(self):
        """Test different moderation actions."""
        plugin = _create_plugin()

        # Test BLOCK action
        from plugins.content_moderation.content_moderation import ModerationResult
        block_result = ModerationResult(
            flagged=True,
            categories={"hate": 0.9},
            action=ModerationAction.BLOCK,
            provider=ModerationProvider.IBM_WATSON,
            confidence=0.9
        )
        modified = await plugin._apply_moderation_action("hateful content", block_result)
        assert modified == ""

        # Test REDACT action
        redact_result = ModerationResult(
            flagged=True,
            categories={"profanity": 0.8},
            action=ModerationAction.REDACT,
            provider=ModerationProvider.IBM_WATSON,
            confidence=0.8
        )
        modified = await plugin._apply_moderation_action("some content", redact_result)
        assert modified == "[CONTENT REMOVED BY MODERATION]"

        # Test WARN action (no change)
        warn_result = ModerationResult(
            flagged=False,
            categories={"toxic": 0.5},
            action=ModerationAction.WARN,
            provider=ModerationProvider.IBM_WATSON,
            confidence=0.5
        )
        modified = await plugin._apply_moderation_action("mild content", warn_result)
        assert modified == "mild content"

    @pytest.mark.asyncio
    async def test_prompt_pre_fetch_blocking(self):
        """Test prompt pre-fetch hook with blocking content."""
        plugin = _create_plugin()
        context = _create_context()

        # Mock moderation to return blocking result
        plugin._moderate_content = AsyncMock(return_value=MagicMock(
            flagged=True,
            action=ModerationAction.BLOCK,
            confidence=0.9,
            categories={"hate": 0.9},
            provider=ModerationProvider.IBM_WATSON,
            modified_content=None
        ))

        payload = PromptPrehookPayload(
            prompt_id="test_prompt",
            args={"query": "hateful content here"}
        )

        result = await plugin.prompt_pre_fetch(payload, context)

        assert result.continue_processing is False
        assert result.violation is not None
        assert result.violation.code == "CONTENT_MODERATION"
        assert "Content policy violation" in result.violation.reason

    @pytest.mark.asyncio
    async def test_prompt_pre_fetch_redaction(self):
        """Test prompt pre-fetch hook with content redaction."""
        plugin = _create_plugin()
        context = _create_context()

        # Mock moderation to return redaction result
        plugin._moderate_content = AsyncMock(return_value=MagicMock(
            flagged=True,
            action=ModerationAction.REDACT,
            confidence=0.7,
            categories={"profanity": 0.7},
            provider=ModerationProvider.IBM_WATSON,
            modified_content="[CONTENT REMOVED BY MODERATION]"
        ))

        payload = PromptPrehookPayload(
            prompt_id="test_prompt",
            args={"query": "some bad words"}
        )

        result = await plugin.prompt_pre_fetch(payload, context)

        assert result.continue_processing is True
        assert result.modified_payload is not None
        assert result.metadata["content_modified"] is True

    @pytest.mark.asyncio
    async def test_tool_pre_invoke_blocking(self):
        """Test tool pre-invoke hook with blocking content."""
        plugin = _create_plugin()
        context = _create_context()

        # Mock moderation to return blocking result
        plugin._moderate_content = AsyncMock(return_value=MagicMock(
            flagged=True,
            action=ModerationAction.BLOCK,
            confidence=0.95,
            categories={"violence": 0.95},
            provider=ModerationProvider.IBM_GRANITE,
            modified_content=None
        ))

        payload = ToolPreInvokePayload(
            name="search_tool",
            args={"query": "how to make bombs"}
        )

        result = await plugin.tool_pre_invoke(payload, context)

        assert result.continue_processing is False
        assert result.violation is not None
        assert result.violation.code == "CONTENT_MODERATION"
        assert "search_tool" in result.violation.details["tool"]

    @pytest.mark.asyncio
    async def test_tool_post_invoke_output_moderation(self):
        """Test tool post-invoke hook moderating output content."""
        plugin = _create_plugin()
        context = _create_context()

        # Mock moderation to return warning result
        plugin._moderate_content = AsyncMock(return_value=MagicMock(
            flagged=True,
            action=ModerationAction.WARN,
            confidence=0.6,
            categories={"toxic": 0.6},
            provider=ModerationProvider.IBM_WATSON,
            modified_content=None
        ))

        payload = ToolPostInvokePayload(
            name="search_tool",
            result="This is some mildly toxic content in the results"
        )

        result = await plugin.tool_post_invoke(payload, context)

        assert result.continue_processing is True
        assert result.metadata["output_checked"] is True

    @pytest.mark.asyncio
    async def test_fallback_provider_on_error(self):
        """Test fallback to secondary provider when primary fails."""
        plugin = _create_plugin()

        # Mock primary provider to fail
        plugin._moderate_with_ibm_watson = AsyncMock(side_effect=Exception("Watson API error"))

        # Mock fallback provider to succeed
        plugin._moderate_with_ibm_granite = AsyncMock(return_value=MagicMock(
            flagged=False,
            action=ModerationAction.WARN,
            confidence=0.2,
            categories={"hate": 0.1},
            provider=ModerationProvider.IBM_GRANITE
        ))

        # Mock pattern fallback
        plugin._moderate_with_patterns = AsyncMock(return_value=MagicMock(
            flagged=False,
            action=ModerationAction.WARN,
            confidence=0.1,
            categories={"hate": 0.0},
            provider=ModerationProvider.IBM_WATSON
        ))

        result = await plugin._moderate_content("test content")

        # Should have called the fallback provider
        plugin._moderate_with_ibm_granite.assert_called_once()
        assert result.confidence == 0.2

    @pytest.mark.asyncio
    async def test_moderation_error_handling(self):
        """Test error handling when moderation service fails."""
        config = {"fallback_on_error": "block"}
        plugin = _create_plugin(config)
        context = _create_context()

        # Mock all moderation methods to fail
        plugin._moderate_content = AsyncMock(side_effect=Exception("All services down"))

        payload = PromptPrehookPayload(
            prompt_id="test_prompt",
            args={"query": "test content"}
        )

        result = await plugin.prompt_pre_fetch(payload, context)

        assert result.continue_processing is False
        assert result.violation is not None
        assert result.violation.code == "MODERATION_ERROR"

    @pytest.mark.asyncio
    async def test_content_length_limiting(self):
        """Test content length limiting."""
        config = {"max_text_length": 50}
        plugin = _create_plugin(config)

        long_text = "This is a very long text " * 20  # Much longer than 50 chars

        # Mock the actual moderation call to verify truncated text length
        plugin._moderate_with_patterns = AsyncMock(return_value=MagicMock(
            flagged=False,
            action=ModerationAction.WARN,
            confidence=0.1,
            categories={},
            provider=ModerationProvider.IBM_WATSON
        ))

        await plugin._moderate_content(long_text)

        # Check that the text was truncated
        call_args = plugin._moderate_with_patterns.call_args[0]
        assert len(call_args[0]) <= 50

    @pytest.mark.asyncio
    async def test_audit_logging(self):
        """Test audit decision logging."""
        plugin = _create_plugin({"audit_decisions": True})
        context = _create_context()

        plugin._moderate_content = AsyncMock(return_value=MagicMock(
            flagged=True,
            action=ModerationAction.WARN,
            confidence=0.8,
            categories={"toxic": 0.8},
            provider=ModerationProvider.IBM_WATSON
        ))

        payload = PromptPrehookPayload(
            prompt_id="test_prompt",
            args={"query": "test content"}
        )

        with patch('plugins.content_moderation.content_moderation.logger') as mock_logger:
            await plugin.prompt_pre_fetch(payload, context)

            # Verify audit log was created
            mock_logger.info.assert_called()
            log_message = mock_logger.info.call_args[0][0]
            assert "Content moderation" in log_message
            assert "test_prompt" in log_message

    @pytest.mark.asyncio
    async def test_multiple_categories_evaluation(self):
        """Test evaluation when multiple categories are flagged."""
        plugin = _create_plugin()

        # Mock result with multiple high-scoring categories
        multi_category_result = MagicMock(
            flagged=True,
            categories={
                "hate": 0.9,      # Above threshold (0.7) - should trigger BLOCK
                "violence": 0.85, # Above threshold (0.8) - should trigger BLOCK
                "sexual": 0.5     # Below threshold (0.6) - should not trigger
            },
            action=ModerationAction.BLOCK,
            confidence=0.9,
            provider=ModerationProvider.IBM_WATSON
        )

        plugin._moderate_content = AsyncMock(return_value=multi_category_result)
        context = _create_context()

        payload = PromptPrehookPayload(
            prompt_id="test_prompt",
            args={"query": "content with multiple violations"}
        )

        result = await plugin.prompt_pre_fetch(payload, context)

        assert result.continue_processing is False
        assert result.violation.code == "CONTENT_MODERATION"
