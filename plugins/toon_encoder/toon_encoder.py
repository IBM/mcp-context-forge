# -*- coding: utf-8 -*-
"""Location: ./plugins/toon_encoder/toon_encoder.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

TOON Encoder Plugin for MCP Gateway.

This plugin converts JSON tool results to TOON (Token-Oriented Object Notation)
format to reduce token consumption when sending responses to LLM agents/GPUs.

The plugin operates on the `tool_post_invoke` hook, intercepting tool results
after execution and converting JSON content to the more compact TOON format.

Configuration Options:
    min_size_bytes: Minimum JSON size to trigger conversion (default: 100)
    max_size_bytes: Maximum JSON size to convert (default: 1MB, prevents OOM)
    exclude_tools: List of tool names to skip conversion
    include_tools: Whitelist of tools (if set, only these are converted)
    add_format_marker: Add annotation marking content as TOON (default: True)
    skip_on_error: Continue with JSON if TOON conversion fails (default: True)

Example config.yaml entry:
    - name: "ToonEncoder"
      kind: "plugins.toon_encoder.toon_encoder.ToonEncoderPlugin"
      hooks: ["tool_post_invoke"]
      mode: "enforce"
      priority: 900
      config:
        min_size_bytes: 100
        max_size_bytes: 1048576
        exclude_tools: ["get_binary_file"]
        add_format_marker: true
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import orjson

from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
)

from .toon import encode as toon_encode

logger = logging.getLogger(__name__)


class ToonEncoderPlugin(Plugin):
    """Convert tool results from JSON to TOON format for token efficiency.

    This plugin intercepts tool invocation results and converts JSON content
    to TOON format, which typically reduces token count by 30-70% depending
    on the structure of the data.

    The plugin is designed to be safe and non-blocking:
    - Only converts content that is valid JSON
    - Only uses TOON if it's actually smaller than JSON
    - Gracefully handles errors without blocking tool execution
    - Adds format markers so downstream consumers know it's TOON

    Attributes:
        _min_size_bytes: Minimum JSON size to trigger conversion.
        _max_size_bytes: Maximum JSON size to convert.
        _exclude_tools: Tool names to skip.
        _include_tools: Whitelist of tools (optional).
        _add_format_marker: Whether to add format annotation.
        _skip_on_error: Whether to continue on conversion errors.

    Examples:
        >>> from mcpgateway.plugins.framework import PluginConfig, HookType
        >>> config = PluginConfig(
        ...     name="ToonEncoder",
        ...     kind="plugins.toon_encoder.toon_encoder.ToonEncoderPlugin",
        ...     hooks=[HookType.TOOL_POST_INVOKE],
        ...     priority=900,
        ...     config={"min_size_bytes": 50}
        ... )
        >>> plugin = ToonEncoderPlugin(config)
        >>> plugin._min_size_bytes
        50
    """

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the TOON encoder plugin.

        Args:
            config: Plugin configuration containing encoding options.
        """
        super().__init__(config)

        # Extract configuration with defaults
        plugin_config = config.config or {}
        self._min_size_bytes: int = plugin_config.get("min_size_bytes", 100)
        self._max_size_bytes: int = plugin_config.get("max_size_bytes", 1024 * 1024)  # 1MB
        self._exclude_tools: List[str] = plugin_config.get("exclude_tools", [])
        self._include_tools: Optional[List[str]] = plugin_config.get("include_tools")
        self._add_format_marker: bool = plugin_config.get("add_format_marker", True)
        self._skip_on_error: bool = plugin_config.get("skip_on_error", True)

        # Metrics for observability
        # Tool-level stats (per tool invocation)
        self._tools_processed: int = 0  # Number of tool results processed
        self._tools_converted: int = 0  # Number of tool results with at least one item converted
        # Item-level stats (per content item within tool results)
        self._items_attempted: int = 0  # Content items that met size criteria and were valid JSON
        self._items_converted: int = 0  # Content items successfully converted to TOON
        self._total_bytes_saved: int = 0

        logger.info(
            f"ToonEncoderPlugin initialized: min_size={self._min_size_bytes}, "
            f"max_size={self._max_size_bytes}, exclude={self._exclude_tools}"
        )

    async def tool_post_invoke(
        self, payload: ToolPostInvokePayload, context: PluginContext
    ) -> ToolPostInvokeResult:
        """Convert tool result to TOON format after invocation.

        This method is called after a tool has been invoked. It examines the
        result content and converts any JSON text content to TOON format if
        it would result in token savings.

        Args:
            payload: Tool invocation result containing name and result dict.
            context: Plugin execution context with request metadata.

        Returns:
            ToolPostInvokeResult with either:
            - Modified payload containing TOON-encoded content
            - continue_processing=True if no conversion needed/possible

        Examples:
            >>> import asyncio
            >>> from mcpgateway.plugins.framework import PluginConfig, PluginContext, GlobalContext, HookType
            >>> config = PluginConfig(
            ...     name="test", kind="test", hooks=[HookType.TOOL_POST_INVOKE], priority=1
            ... )
            >>> plugin = ToonEncoderPlugin(config)
            >>> payload = ToolPostInvokePayload(
            ...     name="test_tool",
            ...     result={"content": [{"type": "text", "text": '{"key": "value"}'}]}
            ... )
            >>> ctx = PluginContext(global_context=GlobalContext(request_id="test-1"))
            >>> # Result would be TOON-encoded if JSON is large enough
        """
        start_time = time.monotonic()
        tool_name = payload.name

        # Check tool filtering
        if not self._should_process_tool(tool_name):
            logger.debug(f"ToonEncoder: Skipping tool '{tool_name}' (filtered)")
            return ToolPostInvokeResult(continue_processing=True)

        result = payload.result
        if not isinstance(result, dict):
            logger.debug(f"ToonEncoder: Skipping tool '{tool_name}' (result not dict)")
            return ToolPostInvokeResult(continue_processing=True)

        # Get content from result
        content = result.get("content", [])
        if not content or not isinstance(content, list):
            return ToolPostInvokeResult(continue_processing=True)

        # Process each content item
        modified = False
        new_content = []
        total_original_size = 0
        total_new_size = 0
        items_converted_this_call = 0

        self._tools_processed += 1

        for item in content:
            processed_item, was_modified, orig_size, new_size = self._process_content_item(
                item, tool_name
            )
            new_content.append(processed_item)
            if was_modified:
                modified = True
                items_converted_this_call += 1
                self._items_converted += 1
                total_original_size += orig_size
                total_new_size += new_size

        # Return modified result if any content was converted
        if modified:
            self._tools_converted += 1
            bytes_saved = total_original_size - total_new_size
            self._total_bytes_saved += bytes_saved

            duration_ms = (time.monotonic() - start_time) * 1000
            savings_pct = (bytes_saved / total_original_size * 100) if total_original_size > 0 else 0

            logger.info(
                f"ToonEncoder: Converted tool '{tool_name}' result, "
                f"saved {bytes_saved} bytes ({savings_pct:.1f}%), "
                f"took {duration_ms:.2f}ms"
            )

            new_result = {**result, "content": new_content}
            return ToolPostInvokeResult(
                modified_payload=ToolPostInvokePayload(name=tool_name, result=new_result),
                metadata={
                    "toon_encoded": True,
                    "bytes_saved": bytes_saved,
                    "savings_percent": round(savings_pct, 2),
                    "conversion_time_ms": round(duration_ms, 2),
                },
            )

        return ToolPostInvokeResult(continue_processing=True)

    def _should_process_tool(self, tool_name: str) -> bool:
        """Check if tool should be processed based on filters.

        Args:
            tool_name: Name of the tool.

        Returns:
            True if tool should be processed.
        """
        # Check whitelist first
        if self._include_tools is not None:
            return tool_name in self._include_tools

        # Check blacklist
        return tool_name not in self._exclude_tools

    def _process_content_item(
        self, item: Any, tool_name: str
    ) -> tuple[Any, bool, int, int]:
        """Process a single content item, converting JSON to TOON if applicable.

        Args:
            item: Content item (typically a dict with 'type' and 'text').
            tool_name: Name of the tool (for logging).

        Returns:
            Tuple of (processed_item, was_modified, original_size, new_size).
        """
        if not isinstance(item, dict):
            return (item, False, 0, 0)

        item_type = item.get("type")
        text = item.get("text", "")

        # Only process text content
        if item_type != "text" or not isinstance(text, str):
            return (item, False, 0, 0)

        # Use byte length for size thresholds (per TOON spec)
        original_size = len(text.encode("utf-8"))

        # Check size thresholds
        if original_size < self._min_size_bytes:
            logger.debug(
                f"ToonEncoder: Skipping '{tool_name}' content "
                f"(size {original_size} < min {self._min_size_bytes})"
            )
            return (item, False, 0, 0)

        if original_size > self._max_size_bytes:
            logger.debug(
                f"ToonEncoder: Skipping '{tool_name}' content "
                f"(size {original_size} > max {self._max_size_bytes})"
            )
            return (item, False, 0, 0)

        # Try to parse as JSON and convert to TOON
        self._items_attempted += 1

        try:
            parsed = orjson.loads(text)
        except (orjson.JSONDecodeError, TypeError):
            # Not JSON, keep original
            logger.debug(f"ToonEncoder: Content in '{tool_name}' is not valid JSON")
            return (item, False, 0, 0)

        try:
            toon_text = toon_encode(parsed)
        except Exception as e:
            if self._skip_on_error:
                logger.warning(f"ToonEncoder: Failed to encode '{tool_name}' to TOON: {e}")
                return (item, False, 0, 0)
            raise

        new_size = len(toon_text.encode("utf-8"))

        # Only use TOON if it's actually smaller
        if new_size >= original_size:
            logger.debug(
                f"ToonEncoder: TOON not smaller for '{tool_name}' "
                f"({new_size} >= {original_size}), keeping JSON"
            )
            return (item, False, 0, 0)

        # Build new content item with TOON
        new_item: Dict[str, Any] = {
            "type": "text",
            "text": toon_text,
        }

        # Always preserve existing annotations
        existing_annotations = item.get("annotations", {})
        if isinstance(existing_annotations, dict) and existing_annotations:
            new_item["annotations"] = {**existing_annotations}
        elif existing_annotations:
            # Non-dict annotations (unlikely but handle gracefully)
            new_item["annotations"] = existing_annotations

        # Add format marker if enabled
        if self._add_format_marker:
            if "annotations" not in new_item:
                new_item["annotations"] = {}
            if isinstance(new_item["annotations"], dict):
                new_item["annotations"]["format"] = "toon"

        return (new_item, True, original_size, new_size)

    def get_stats(self) -> Dict[str, Any]:
        """Get plugin statistics for monitoring.

        Returns:
            Dictionary with conversion statistics.

        Examples:
            >>> from mcpgateway.plugins.framework import PluginConfig, HookType
            >>> config = PluginConfig(
            ...     name="test", kind="test", hooks=[HookType.TOOL_POST_INVOKE], priority=1
            ... )
            >>> plugin = ToonEncoderPlugin(config)
            >>> stats = plugin.get_stats()
            >>> "tools_processed" in stats
            True
        """
        return {
            # Tool-level stats
            "tools_processed": self._tools_processed,
            "tools_converted": self._tools_converted,
            "tool_conversion_rate": (
                self._tools_converted / self._tools_processed * 100
                if self._tools_processed > 0
                else 0.0
            ),
            # Item-level stats
            "items_attempted": self._items_attempted,
            "items_converted": self._items_converted,
            "item_conversion_rate": (
                self._items_converted / self._items_attempted * 100
                if self._items_attempted > 0
                else 0.0
            ),
            # Size stats
            "total_bytes_saved": self._total_bytes_saved,
        }
