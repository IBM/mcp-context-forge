# -*- coding: utf-8 -*-
"""Location: ./plugins/test_prompt_output_sentinel.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Test-only prompt output sentinel plugin.

This plugin appends a deterministic sentinel string to textual prompt outputs so
live MCP parity tests can prove that `prompt_post_fetch` hooks still run when
the Rust MCP public path is active.
"""

from __future__ import annotations

from copy import deepcopy

from pydantic import BaseModel, Field

from mcpgateway.plugins.framework import Plugin, PluginConfig, PluginContext, PromptPosthookPayload, PromptPosthookResult


class PromptOutputSentinelConfig(BaseModel):
    """Configuration for the prompt output sentinel plugin.

    Attributes:
        sentinel_text: Deterministic marker appended to prompt text.
        separator: Separator inserted before the sentinel.
        append_to_all_messages: When true, append to every text message.
    """

    sentinel_text: str = Field(default="[PROMPT-POST-FETCH-SENTINEL]")
    separator: str = Field(default="\n")
    append_to_all_messages: bool = Field(default=False)


def _append_sentinel(text: str, cfg: PromptOutputSentinelConfig) -> str:
    """Append the configured sentinel to a text value.

    Args:
        text: Original prompt text.
        cfg: Plugin configuration.

    Returns:
        Text with the sentinel appended once.
    """
    if cfg.sentinel_text in text:
        return text
    if not text:
        return cfg.sentinel_text
    return f"{text}{cfg.separator}{cfg.sentinel_text}"


class PromptOutputSentinelPlugin(Plugin):
    """Append a deterministic sentinel to prompt outputs for live parity tests."""

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        self._cfg = PromptOutputSentinelConfig(**(config.config or {}))

    async def prompt_post_fetch(self, payload: PromptPosthookPayload, context: PluginContext) -> PromptPosthookResult:
        """Append the sentinel to prompt message text.

        Args:
            payload: Prompt result payload after retrieval/rendering.
            context: Plugin execution context.

        Returns:
            A modified payload when a text message was updated, otherwise a
            no-op result.
        """
        del context

        result = deepcopy(payload.result)
        messages = result.get("messages") if isinstance(result, dict) else getattr(result, "messages", None)
        if not isinstance(messages, list):
            return PromptPosthookResult(continue_processing=True)

        modified = False
        for message in messages:
            content = message.get("content") if isinstance(message, dict) else getattr(message, "content", None)
            if content is None:
                continue

            if isinstance(content, dict):
                text = content.get("text")
                if not isinstance(text, str):
                    continue
                updated = _append_sentinel(text, self._cfg)
                if updated != text:
                    content["text"] = updated
                    modified = True
            else:
                text = getattr(content, "text", None)
                if not isinstance(text, str):
                    continue
                updated = _append_sentinel(text, self._cfg)
                if updated != text:
                    setattr(content, "text", updated)
                    modified = True

            if modified and not self._cfg.append_to_all_messages:
                break

        if modified:
            return PromptPosthookResult(modified_payload=PromptPosthookPayload(prompt_id=payload.prompt_id, result=result))
        return PromptPosthookResult(continue_processing=True)
