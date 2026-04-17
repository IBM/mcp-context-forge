# -*- coding: utf-8 -*-
"""Gateway-side smoke tests for the cpex-content-moderation package.

These tests verify that ContentModerationPlugin can be loaded via its
published package path ``cpex_content_moderation.ContentModerationPlugin``
and that all three hooks (prompt_pre_fetch, tool_pre_invoke, tool_post_invoke)
execute without error when wired through the gateway plugin framework.
"""

# Future
from __future__ import annotations

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.plugins.framework import (
    GlobalContext,
    PluginConfig,
    PromptPrehookPayload,
    ToolPostInvokePayload,
    ToolPreInvokePayload,
)


def _make_plugin():
    """Instantiate ContentModerationPlugin via the packaged kind path."""
    # Third-Party
    from cpex_content_moderation import ContentModerationPlugin

    return ContentModerationPlugin(
        PluginConfig(
            name="ContentModeration",
            kind="cpex_content_moderation.ContentModerationPlugin",
            hooks=["prompt_pre_fetch", "tool_pre_invoke", "tool_post_invoke"],
            config={
                "provider": "ibm_watson",
                "ibm_watson": {
                    "api_key": "test-key",
                    "url": "https://example.watson.cloud.ibm.com",
                    "version": "2022-04-07",
                },
                "categories": {
                    "hate": {"threshold": 0.8, "action": "block"},
                },
                "audit_decisions": False,
                "enable_caching": False,
            },
        )
    )


@pytest.fixture
def context():
    """Return a minimal GlobalContext."""
    return GlobalContext(request_id="smoke-test-req", user="tester@example.com")


@pytest.mark.asyncio
@patch("cpex_content_moderation.content_moderation.httpx.AsyncClient")
async def test_prompt_pre_fetch_safe_content_continues(mock_client_cls, context):
    """Safe content should continue processing with no violation."""
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "emotion": {"document": {"emotion": {"anger": 0.1, "disgust": 0.1, "fear": 0.1, "sadness": 0.1}}},
        "sentiment": {"document": {"score": 0.5, "label": "positive"}},
        "concepts": [],
    }
    mock_client.post.return_value = mock_response
    mock_client_cls.return_value = mock_client

    plugin = _make_plugin()
    payload = PromptPrehookPayload(prompt_id="p1", args={"query": "What is the weather today?"})
    result = await plugin.prompt_pre_fetch(payload, context)

    assert result.continue_processing is True
    assert result.violation is None


@pytest.mark.asyncio
@patch("cpex_content_moderation.content_moderation.httpx.AsyncClient")
async def test_prompt_pre_fetch_harmful_content_blocked(mock_client_cls, context):
    """Content with high anger/disgust scores should be blocked."""
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "emotion": {"document": {"emotion": {"anger": 0.95, "disgust": 0.9, "fear": 0.1, "sadness": 0.1}}},
        "sentiment": {"document": {"score": -0.95, "label": "negative"}},
        "concepts": [],
    }
    mock_client.post.return_value = mock_response
    mock_client_cls.return_value = mock_client

    plugin = _make_plugin()
    payload = PromptPrehookPayload(prompt_id="p2", args={"query": "I hate everyone!"})
    result = await plugin.prompt_pre_fetch(payload, context)

    assert result.continue_processing is False
    assert result.violation is not None
    assert result.violation.code == "CONTENT_MODERATION"


@pytest.mark.asyncio
@patch("cpex_content_moderation.content_moderation.httpx.AsyncClient")
async def test_tool_pre_invoke_passes_clean_input(mock_client_cls, context):
    """tool_pre_invoke hook should pass through clean tool arguments."""
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "emotion": {"document": {"emotion": {"anger": 0.05, "disgust": 0.05, "fear": 0.05, "sadness": 0.05}}},
        "sentiment": {"document": {"score": 0.8, "label": "positive"}},
        "concepts": [],
    }
    mock_client.post.return_value = mock_response
    mock_client_cls.return_value = mock_client

    plugin = _make_plugin()
    payload = ToolPreInvokePayload(name="search", args={"query": "Open source AI tools"})
    result = await plugin.tool_pre_invoke(payload, context)

    assert result.continue_processing is True


@pytest.mark.asyncio
@patch("cpex_content_moderation.content_moderation.httpx.AsyncClient")
async def test_tool_post_invoke_passes_clean_output(mock_client_cls, context):
    """tool_post_invoke hook should pass through clean tool output."""
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "emotion": {"document": {"emotion": {"anger": 0.05, "disgust": 0.05, "fear": 0.05, "sadness": 0.05}}},
        "sentiment": {"document": {"score": 0.8, "label": "positive"}},
        "concepts": [],
    }
    mock_client.post.return_value = mock_response
    mock_client_cls.return_value = mock_client

    plugin = _make_plugin()
    payload = ToolPostInvokePayload(name="search", args={}, result={"output": "Here are the results."})
    result = await plugin.tool_post_invoke(payload, context)

    assert result.continue_processing is True
