# -*- coding: utf-8 -*-
"""Unit tests for the prompt output sentinel plugin."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mcpgateway.common.models import Message, PromptResult, Role, TextContent
from mcpgateway.plugins.framework import PluginConfig, PromptPosthookPayload
from plugins.test_prompt_output_sentinel import PromptOutputSentinelPlugin


@pytest.fixture
def plugin() -> PromptOutputSentinelPlugin:
    """Create a prompt output sentinel plugin instance.

    Returns:
        Configured prompt sentinel plugin.
    """
    return PromptOutputSentinelPlugin(
        PluginConfig(
            name="prompt-sentinel",
            kind="plugins.test_prompt_output_sentinel.PromptOutputSentinelPlugin",
            hooks=["prompt_post_fetch"],
            config={"sentinel_text": "[PROMPT-POST-FETCH-SENTINEL]"},
        )
    )


@pytest.mark.asyncio
async def test_prompt_post_fetch_appends_sentinel_to_prompt_result(plugin: PromptOutputSentinelPlugin) -> None:
    """The plugin should append its sentinel to prompt text results.

    Args:
        plugin: Prompt sentinel plugin under test.
    """
    result = PromptResult(
        description="Prompt description",
        messages=[Message(role=Role.USER, content=TextContent(type="text", text="Rendered prompt body"))],
    )

    response = await plugin.prompt_post_fetch(
        PromptPosthookPayload(prompt_id="prompt-1", result=result),
        SimpleNamespace(),
    )

    updated = response.modified_payload.result
    assert updated.messages[0].content.text.endswith("[PROMPT-POST-FETCH-SENTINEL]")
    assert "Rendered prompt body" in updated.messages[0].content.text


@pytest.mark.asyncio
async def test_prompt_post_fetch_supports_dict_like_results(plugin: PromptOutputSentinelPlugin) -> None:
    """The plugin should also support dict-like prompt results.

    Args:
        plugin: Prompt sentinel plugin under test.
    """
    response = await plugin.prompt_post_fetch(
        PromptPosthookPayload(
            prompt_id="prompt-2",
            result={
                "description": "Prompt description",
                "messages": [{"role": "user", "content": {"type": "text", "text": "Rendered dict body"}}],
            },
        ),
        SimpleNamespace(),
    )

    updated = response.modified_payload.result
    assert updated.messages[0].content.text.endswith("[PROMPT-POST-FETCH-SENTINEL]")
    assert "Rendered dict body" in updated.messages[0].content.text


@pytest.mark.asyncio
async def test_prompt_post_fetch_is_idempotent(plugin: PromptOutputSentinelPlugin) -> None:
    """The plugin should not append the sentinel twice.

    Args:
        plugin: Prompt sentinel plugin under test.
    """
    payload = PromptPosthookPayload(
        prompt_id="prompt-3",
        result={
            "messages": [
                {
                    "role": "user",
                    "content": {
                        "type": "text",
                        "text": "Already tagged\n[PROMPT-POST-FETCH-SENTINEL]",
                    },
                }
            ]
        },
    )

    response = await plugin.prompt_post_fetch(payload, SimpleNamespace())

    assert response.modified_payload is None
    assert response.continue_processing is True
