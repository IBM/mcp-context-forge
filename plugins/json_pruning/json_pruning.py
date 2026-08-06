# -*- coding: utf-8 -*-
"""Location: ./plugins/json_pruning/json_pruning.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Matt Van Horn

JSON Response Pruning Plugin for ContextForge.
Reduces LLM token consumption by stripping unnecessary fields,
truncating arrays, truncating strings, and limiting nesting depth
in tool response JSON.

Supported result shapes
- str: attempt JSON parse, prune, re-serialize
- dict: prune in place
- list: prune each element recursively

Other result types pass through unchanged.
"""

# Future
from __future__ import annotations

# Standard
import json
from typing import Any, List, Optional

# Third-Party
from pydantic import BaseModel, Field

# First-Party
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
)


class JSONPruningConfig(BaseModel):
    """Configuration for the JSON Pruning plugin.

    Examples:
        >>> cfg = JSONPruningConfig()
        >>> cfg.max_depth
        10
        >>> cfg.max_array_items
        50
        >>> "_links" in cfg.strip_fields
        True
    """

    strip_fields: List[str] = Field(
        default_factory=lambda: ["_links", "_metadata", "debug", "pagination", "__typename"],
        description="Field names to strip from JSON objects at any depth.",
    )
    max_array_items: Optional[int] = Field(
        default=50,
        ge=1,
        description="Maximum number of items to keep in arrays. None disables.",
    )
    max_string_length: Optional[int] = Field(
        default=5000,
        ge=1,
        description="Maximum character length for string values. None disables.",
    )
    max_depth: Optional[int] = Field(
        default=10,
        ge=1,
        description="Maximum nesting depth. None disables.",
    )
    array_truncation_notice: str = Field(
        default="[... {remaining} more items truncated]",
        description="Notice appended when arrays are truncated. Use {remaining} placeholder.",
    )
    string_truncation_suffix: str = Field(
        default="...",
        description="Suffix appended when strings are truncated.",
    )
    depth_placeholder: str = Field(
        default="{...}",
        description="Placeholder for content beyond max depth.",
    )


def _prune(value: Any, cfg: JSONPruningConfig, depth: int = 0) -> tuple[Any, bool]:
    """Recursively prune a value according to the configuration.

    Args:
        value: The value to prune.
        cfg: Pruning configuration.
        depth: Current nesting depth.

    Returns:
        Tuple of (pruned_value, was_modified).

    Examples:
        >>> cfg = JSONPruningConfig(strip_fields=["debug"], max_depth=3, max_array_items=2, max_string_length=10)
        >>> val, mod = _prune({"a": 1, "debug": "x"}, cfg)
        >>> val
        {'a': 1}
        >>> mod
        True
        >>> val, mod = _prune("short", cfg)
        >>> mod
        False
        >>> val, mod = _prune("a very long string here", cfg)
        >>> len(val) <= 10 + len(cfg.string_truncation_suffix)
        True
    """
    modified = False

    # Depth limit check
    if cfg.max_depth is not None and depth >= cfg.max_depth:
        if isinstance(value, (dict, list)) and value:
            return cfg.depth_placeholder, True
        return value, False

    if isinstance(value, dict):
        result = {}
        for key, val in value.items():
            if key in cfg.strip_fields:
                modified = True
                continue
            pruned_val, child_modified = _prune(val, cfg, depth + 1)
            if child_modified:
                modified = True
            result[key] = pruned_val
        return result, modified

    if isinstance(value, list):
        pruned_items: list[Any] = []
        for item in value[: cfg.max_array_items]:
            pruned_item, child_modified = _prune(item, cfg, depth + 1)
            if child_modified:
                modified = True
            pruned_items.append(pruned_item)

        if cfg.max_array_items is not None and len(value) > cfg.max_array_items:
            remaining = len(value) - cfg.max_array_items
            notice = cfg.array_truncation_notice.replace("{remaining}", str(remaining))
            pruned_items.append(notice)
            modified = True

        return pruned_items, modified

    if isinstance(value, str):
        if cfg.max_string_length is not None and len(value) > cfg.max_string_length:
            suffix = cfg.string_truncation_suffix
            cut = cfg.max_string_length - len(suffix)
            if cut < 0:
                cut = 0
            return value[:cut] + suffix, True
        return value, False

    return value, False


def _try_parse_json(text: str) -> Any | None:
    """Attempt to parse a string as JSON.

    Args:
        text: String to parse.

    Returns:
        Parsed object or None if not valid JSON.

    Examples:
        >>> _try_parse_json('{"a": 1}')
        {'a': 1}
        >>> _try_parse_json('not json') is None
        True
    """
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


class JSONPruningPlugin(Plugin):
    """Prune JSON tool responses to reduce LLM token consumption.

    Examples:
        >>> import asyncio
        >>> from mcpgateway.plugins.framework import PluginConfig, PluginContext, GlobalContext
        >>> cfg = PluginConfig(
        ...     name="test_pruning",
        ...     kind="plugins.json_pruning.json_pruning.JSONPruningPlugin",
        ...     version="0.1.0",
        ...     author="test",
        ...     hooks=["tool_post_invoke"],
        ...     config={"strip_fields": ["debug"], "max_array_items": 2},
        ... )
        >>> plugin = JSONPruningPlugin(cfg)
        >>> plugin.name
        'test_pruning'
    """

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the JSON pruning plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        self._cfg = JSONPruningConfig(**(config.config or {}))

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Prune JSON content from tool results after invocation.

        Args:
            payload: Tool invocation result payload.
            context: Plugin execution context.

        Returns:
            Result with pruned JSON if applicable.
        """
        result = payload.result
        cfg = self._cfg

        # Case 1: String result - try to parse as JSON, prune, re-serialize
        if isinstance(result, str):
            parsed = _try_parse_json(result)
            if parsed is None:
                # Not JSON, apply string truncation only
                if cfg.max_string_length is not None and len(result) > cfg.max_string_length:
                    suffix = cfg.string_truncation_suffix
                    cut = cfg.max_string_length - len(suffix)
                    if cut < 0:
                        cut = 0
                    truncated = result[:cut] + suffix
                    return ToolPostInvokeResult(
                        modified_payload=ToolPostInvokePayload(name=payload.name, result=truncated),
                        metadata={"pruned": True, "original_length": len(result), "new_length": len(truncated)},
                    )
                return ToolPostInvokeResult(continue_processing=True)

            pruned, modified = _prune(parsed, cfg)
            if modified:
                new_result = json.dumps(pruned, separators=(",", ":"))
                return ToolPostInvokeResult(
                    modified_payload=ToolPostInvokePayload(name=payload.name, result=new_result),
                    metadata={"pruned": True, "result_type": "json_string"},
                )
            return ToolPostInvokeResult(continue_processing=True)

        # Case 2: Dict result
        if isinstance(result, dict):
            pruned, modified = _prune(result, cfg)
            if modified:
                return ToolPostInvokeResult(
                    modified_payload=ToolPostInvokePayload(name=payload.name, result=pruned),
                    metadata={"pruned": True, "result_type": "dict"},
                )
            return ToolPostInvokeResult(continue_processing=True)

        # Case 3: List result
        if isinstance(result, list):
            pruned, modified = _prune(result, cfg)
            if modified:
                return ToolPostInvokeResult(
                    modified_payload=ToolPostInvokePayload(name=payload.name, result=pruned),
                    metadata={"pruned": True, "result_type": "list"},
                )
            return ToolPostInvokeResult(continue_processing=True)

        # Unhandled result types: pass through
        return ToolPostInvokeResult(continue_processing=True)
