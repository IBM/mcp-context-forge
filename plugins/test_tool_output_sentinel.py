# -*- coding: utf-8 -*-
"""Location: ./plugins/test_tool_output_sentinel.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Test-only tool output sentinel plugin.

This plugin appends a deterministic sentinel string to textual tool outputs so
live MCP parity tests can prove that `tool_post_invoke` hooks are still applied
when the Rust MCP fast path is active.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from pydantic import BaseModel, Field

from mcpgateway.plugins.framework import Plugin, PluginConfig, PluginContext, ToolPostInvokePayload, ToolPostInvokeResult


class ToolOutputSentinelConfig(BaseModel):
    """Configuration for the tool output sentinel plugin.

    Attributes:
        sentinel_text: Deterministic marker appended to text outputs.
        separator: Separator inserted before the sentinel.
        append_to_all_text_blocks: When true, append to every text block in an
            MCP `content` array. When false, stop after the first text block.
    """

    sentinel_text: str = Field(default="[TOOL-POST-INVOKE-SENTINEL]")
    separator: str = Field(default="\n")
    append_to_all_text_blocks: bool = Field(default=False)


def _append_sentinel(text: str, cfg: ToolOutputSentinelConfig) -> str:
    """Append the configured sentinel to a text value.

    Args:
        text: Original text result.
        cfg: Plugin configuration.

    Returns:
        Text with the sentinel appended once.
    """
    if cfg.sentinel_text in text:
        return text
    if not text:
        return cfg.sentinel_text
    return f"{text}{cfg.separator}{cfg.sentinel_text}"


class ToolOutputSentinelPlugin(Plugin):
    """Append a deterministic sentinel to tool outputs for live parity tests."""

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        self._cfg = ToolOutputSentinelConfig(**(config.config or {}))

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Append the sentinel to supported textual tool outputs.

        Args:
            payload: Tool result payload after execution.
            context: Plugin execution context.

        Returns:
            A modified payload when the result shape is supported, otherwise a
            no-op result.
        """
        del context

        result = payload.result
        if isinstance(result, str):
            updated = _append_sentinel(result, self._cfg)
            if updated != result:
                return ToolPostInvokeResult(modified_payload=ToolPostInvokePayload(name=payload.name, result=updated))
            return ToolPostInvokeResult(continue_processing=True)

        if isinstance(result, dict) and isinstance(result.get("text"), str):
            updated = _append_sentinel(result["text"], self._cfg)
            if updated != result["text"]:
                new_result = dict(result)
                new_result["text"] = updated
                return ToolPostInvokeResult(modified_payload=ToolPostInvokePayload(name=payload.name, result=new_result))
            return ToolPostInvokeResult(continue_processing=True)

        if isinstance(result, dict) and isinstance(result.get("content"), list):
            new_result: dict[str, Any] = deepcopy(result)
            modified = False
            for item in new_result["content"]:
                if not isinstance(item, dict):
                    continue
                if item.get("type") != "text" or not isinstance(item.get("text"), str):
                    continue
                updated = _append_sentinel(item["text"], self._cfg)
                if updated != item["text"]:
                    item["text"] = updated
                    modified = True
                if not self._cfg.append_to_all_text_blocks:
                    break
            if modified:
                return ToolPostInvokeResult(modified_payload=ToolPostInvokePayload(name=payload.name, result=new_result))
            return ToolPostInvokeResult(continue_processing=True)

        return ToolPostInvokeResult(continue_processing=True)
