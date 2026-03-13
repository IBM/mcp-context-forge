# -*- coding: utf-8 -*-
"""Location: ./plugins/json_prune/json_prune.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti, Alexander Wiegand

JSON Prune Plugin.
Strips unnecessary JSON fields from API tool responses using a whitelist approach.
Only fields explicitly listed in dot-notation paths are retained.
"""

# Future
from __future__ import annotations

# Standard
import logging
from typing import Any

# Third-Party
import orjson

# First-Party
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
)

logger = logging.getLogger(__name__)


def _get_pruned(data: Any, whitelist: list[str], prefix: str = "") -> Any:
    """Recursively prune a JSON structure keeping only whitelisted dot-notation paths.

    Args:
        data: The JSON data to prune (dict, list, or scalar).
        whitelist: List of dot-notation paths to retain (e.g. ["name", "address.city"]).
        prefix: Current path prefix for recursion tracking.

    Returns:
        Pruned data structure with only whitelisted fields.
    """
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            current_path = f"{prefix}{key}" if not prefix else f"{prefix}.{key}"
            # Keep if this exact path is whitelisted
            if current_path in whitelist:
                result[key] = value
            # Recurse if any whitelisted path starts with this prefix
            elif any(w.startswith(current_path + ".") for w in whitelist):
                pruned = _get_pruned(value, whitelist, current_path)
                if pruned is not None:
                    result[key] = pruned
        return result
    if isinstance(data, list):
        return [_get_pruned(item, whitelist, prefix) for item in data]
    return data


class JSONPrunePlugin(Plugin):
    """Strip unnecessary JSON fields from tool outputs using a whitelist."""

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the JSON prune plugin.

        Args:
            config: Plugin configuration containing webhooks and debug settings.
        """
        super().__init__(config)
        cfg = config.config or {}
        self._webhooks: list[dict[str, Any]] = cfg.get("webhooks", [])
        self._debug: bool = cfg.get("debug", False)

    def _find_webhook(self, tool_name: str) -> dict[str, Any] | None:
        """Look up a webhook configuration by tool name.

        Args:
            tool_name: The name of the tool to find.

        Returns:
            Webhook config dict if found, None otherwise.
        """
        for wh in self._webhooks:
            if wh.get("name") == tool_name:
                return wh
        return None

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Prune JSON fields from tool results based on whitelist configuration.

        Args:
            payload: Tool invocation result payload.
            context: Plugin execution context.

        Returns:
            Result with pruned JSON if a matching webhook is configured.
        """
        webhook = self._find_webhook(payload.name)
        if webhook is None:
            return ToolPostInvokeResult(continue_processing=True)

        whitelist: list[str] = webhook.get("fields", [])

        if isinstance(payload.result, str):
            return self._prune_string(payload, whitelist)
        if isinstance(payload.result, dict):
            return self._prune_content_dict(payload, whitelist)

        return ToolPostInvokeResult(continue_processing=True)

    def _prune_string(self, payload: ToolPostInvokePayload, whitelist: list[str]) -> ToolPostInvokeResult:
        """Prune a plain JSON string result.

        Args:
            payload: Tool invocation result payload.
            whitelist: List of dot-notation paths to retain.

        Returns:
            Result with pruned JSON string.
        """
        try:
            data = orjson.loads(payload.result)
        except (orjson.JSONDecodeError, TypeError):
            if self._debug:
                logger.debug("json_prune: result for '%s' is not valid JSON, skipping", payload.name)
            return ToolPostInvokeResult(continue_processing=True)

        pruned = _get_pruned(data, whitelist)
        new_text = orjson.dumps(pruned, option=orjson.OPT_INDENT_2).decode()

        if self._debug:
            logger.debug("json_prune: pruned result for '%s'", payload.name)

        return ToolPostInvokeResult(
            modified_payload=ToolPostInvokePayload(name=payload.name, result=new_text),
            metadata={"pruned": True},
        )

    def _prune_content_dict(self, payload: ToolPostInvokePayload, whitelist: list[str]) -> ToolPostInvokeResult:
        """Prune an MCP content dict result with content[0]["text"] structure.

        Args:
            payload: Tool invocation result payload.
            whitelist: List of dot-notation paths to retain.

        Returns:
            Result with pruned JSON inside the content dict.
        """
        content = payload.result.get("content", [])
        if not content or content[0].get("type") != "text":
            return ToolPostInvokeResult(continue_processing=True)

        text = content[0].get("text", "")
        try:
            data = orjson.loads(text)
        except (orjson.JSONDecodeError, TypeError):
            if self._debug:
                logger.debug("json_prune: content text for '%s' is not valid JSON, skipping", payload.name)
            return ToolPostInvokeResult(continue_processing=True)

        pruned = _get_pruned(data, whitelist)
        new_text = orjson.dumps(pruned, option=orjson.OPT_INDENT_2).decode()

        new_content = list(content)
        new_content[0] = {**content[0], "text": new_text}
        new_result = {**payload.result, "content": new_content}

        if self._debug:
            logger.debug("json_prune: pruned content dict for '%s'", payload.name)

        return ToolPostInvokeResult(
            modified_payload=ToolPostInvokePayload(name=payload.name, result=new_result),
            metadata={"pruned": True},
        )
