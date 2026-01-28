# -*- coding: utf-8 -*-
"""Location: ./plugins/output_length_guard/output_length_guard.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Output Length Guard Plugin for MCP Gateway.
Enforces min/max output length bounds on tool results, with either
truncate or block strategies.

Behavior
- If strategy = "truncate":
  - When result is a string longer than max_chars, truncate and append ellipsis.
  - Under-length results are allowed but annotated in metadata.
- If strategy = "block":
  - Block when result length is outside [min_chars, max_chars] (when provided).

Supported result shapes
- str: operate directly
- dict with a top-level "text" (str): operate on that field
- list[str]: operate element-wise

Other result types are ignored.
"""

# Future
from __future__ import annotations

# Standard
from typing import Any, List, Optional

# Third-Party
from pydantic import BaseModel, Field

# First-Party
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PluginViolation,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
)


class OutputLengthGuardConfig(BaseModel):
    """Configuration for the Output Length Guard plugin."""

    min_chars: int = Field(default=0, ge=0, description="Minimum allowed characters. 0 disables minimum check.")
    max_chars: Optional[int] = Field(default=None, ge=1, description="Maximum allowed characters. None disables maximum check.")
    strategy: str = Field(default="truncate", description='Strategy when out of bounds: "truncate" or "block"')
    ellipsis: str = Field(default="…", description="Suffix appended on truncation. Use empty string to disable.")

    def is_blocking(self) -> bool:
        """Check if strategy is set to blocking mode.

        Returns:
            True if strategy is block.
        """
        return self.strategy.lower() == "block"


def _length(value: str) -> int:
    """Get length of string value.

    Args:
        value: String to measure.

    Returns:
        Length of string.
    """
    return len(value)


def _truncate(value: str, max_chars: int, ellipsis: str) -> str:
    """Truncate string to maximum length with ellipsis.

    Args:
        value: String to truncate.
        max_chars: Maximum number of characters.
        ellipsis: Ellipsis string to append.

    Returns:
        Truncated string.
    """
    if max_chars is None:
        return value
    if max_chars <= 0:
        return ""
    if len(value) <= max_chars:
        return value
    # Ensure final length <= max_chars considering ellipsis
    ell = ellipsis or ""
    if len(ell) >= max_chars:
        # Ellipsis doesn't fit; hard cut
        return value[:max_chars]
    cut = max_chars - len(ell)
    return value[:cut] + ell


class OutputLengthGuardPlugin(Plugin):
    """Guard tool outputs by length with block or truncate strategies."""

    def __init__(self, config: PluginConfig):
        """Initialize the output length guard plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        self._cfg = OutputLengthGuardConfig(**(config.config or {}))

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Guard tool output by length with block or truncate strategies.

        Args:
            payload: Tool invocation result payload.
            context: Plugin execution context.

        Returns:
            Result with length enforcement applied.
        """
        cfg = self._cfg

        # Helper to evaluate and possibly modify a single string
        def handle_text(text: str) -> tuple[str, dict[str, Any], Optional[PluginViolation]]:
            """Handle length guard for a single text string.

            Args:
                text: Text to check and possibly modify.

            Returns:
                Tuple of (modified_text, metadata, violation).
            """
            length = _length(text)
            meta = {"original_length": length}

            below_min = cfg.min_chars and length < cfg.min_chars
            above_max = cfg.max_chars is not None and length > cfg.max_chars

            if not (below_min or above_max):
                meta.update({"within_bounds": True})
                return text, meta, None

            # Out of bounds
            meta.update(
                {
                    "within_bounds": False,
                    "min_chars": cfg.min_chars,
                    "max_chars": cfg.max_chars,
                    "strategy": cfg.strategy,
                }
            )

            if cfg.is_blocking():
                violation = PluginViolation(
                    reason="Output length out of bounds",
                    description=f"Result length {length} not in [{cfg.min_chars}, {cfg.max_chars}]",
                    code="OUTPUT_LENGTH_VIOLATION",
                    details={"length": length, "min": cfg.min_chars, "max": cfg.max_chars, "strategy": cfg.strategy},
                )
                return text, meta, violation

            # Truncate strategy only handles over-length
            if above_max and cfg.max_chars is not None:
                new_text = _truncate(text, cfg.max_chars, cfg.ellipsis)
                meta.update({"truncated": True, "new_length": len(new_text)})
                return new_text, meta, None

            # Under min with truncate: allow through, annotate only
            meta.update({"truncated": False, "new_length": length})
            return text, meta, None

        result = payload.result

        # Case 1: String result
        if isinstance(result, str):
            new_text, meta, violation = handle_text(result)
            if violation:
                return ToolPostInvokeResult(continue_processing=False, violation=violation, metadata=meta)
            if new_text != result:
                return ToolPostInvokeResult(modified_payload=ToolPostInvokePayload(name=payload.name, result=new_text), metadata=meta)
            return ToolPostInvokeResult(metadata=meta)

        # Case 2: Dict with text field
        if isinstance(result, dict) and isinstance(result.get("text"), str):
            current = result["text"]
            new_text, meta, violation = handle_text(current)
            if violation:
                return ToolPostInvokeResult(continue_processing=False, violation=violation, metadata=meta)
            if new_text != current:
                new_res = dict(result)
                new_res["text"] = new_text
                return ToolPostInvokeResult(modified_payload=ToolPostInvokePayload(name=payload.name, result=new_res), metadata=meta)
            return ToolPostInvokeResult(metadata=meta)

        # Case 3: List of strings
        if isinstance(result, list) and all(isinstance(x, str) for x in result):
            texts: List[str] = result
            modified = False
            meta_list: List[dict[str, Any]] = []
            out: List[str] = []
            for t in texts:
                new_t, m, violation = handle_text(t)
                meta_list.append(m)
                if violation:
                    return ToolPostInvokeResult(continue_processing=False, violation=violation, metadata={"items": meta_list})
                if new_t != t:
                    modified = True
                out.append(new_t)
            if modified:
                return ToolPostInvokeResult(modified_payload=ToolPostInvokePayload(name=payload.name, result=out), metadata={"items": meta_list})
            return ToolPostInvokeResult(metadata={"items": meta_list})

        # Unhandled result types: no-op
        return ToolPostInvokeResult(continue_processing=True)
