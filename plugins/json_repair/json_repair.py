# -*- coding: utf-8 -*-
"""Location: ./plugins/json_repair/json_repair.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

JSON Repair Plugin.
Attempts to repair nearly-JSON string outputs into valid JSON strings.
It is conservative: only applies transformations when confidently fixable.
"""

# Future
from __future__ import annotations

# Standard
import logging
import re

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

# Try to import Rust-accelerated implemtation
try:
    from json_repair import JSONRepairPluginRust
    _RUST_AVAILABLE = True
except ImportError as e:
    _RUST_AVAILABLE = False
    JSONRepairPluginRust = None
    logger.debug("Rust json_repair implementation is not available (using Python): %s", e)
except Exception as e:
    _RUST_AVAILABLE = False
    JSONRepairPluginRust = None
    logger.warning("Unexpected error importing Rust json_repair implementation (using Python): %s", e, exc_info=True)

# Precompiled regex patterns for performance
_JSON_BRACKETS_RE = re.compile(r"^[\[{].*[\]}]$", flags=re.S)
_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")


def _try_parse(s: str) -> bool:
    """Check if string is valid JSON.

    Args:
        s: String to parse.

    Returns:
        True if string is valid JSON.
    """
    try:
        orjson.loads(s)
        return True
    except Exception:
        return False


def _repair(s: str) -> str | None:
    """Attempt to repair invalid JSON string.

    Args:
        s: Potentially invalid JSON string.

    Returns:
        Repaired JSON string or None if unrepairable.
    """
    t = s.strip()
    base = t
    # Replace single quotes with double quotes when it looks like JSON-ish
    if _JSON_BRACKETS_RE.match(t) and ("'" in t and '"' not in t):
        base = t.replace("'", '"')
        if _try_parse(base):
            return base
    # Remove trailing commas before } or ] (apply on base if changed)
    cand = _TRAILING_COMMA_RE.sub(r"\1", base)
    if cand != base and _try_parse(cand):
        return cand
    # Wrap raw object-like text missing braces
    if not t.startswith("{") and ":" in t and t.count("{") == 0 and t.count("}") == 0:
        cand = "{" + t + "}"
        if _try_parse(cand):
            return cand
    return None


class JSONRepairPlugin(Plugin):
    """Repair JSON-like string outputs, returning corrected string if fixable."""

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the JSON repair plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        self._rust_helper = None
        if _RUST_AVAILABLE and JSONRepairPluginRust is not None:
            try:
                self._rust_helper = JSONRepairPluginRust()
            except Exception as e:
                logger.warning("Failed to initialize Rust JSON repair implementation (falling back to Python): %s", e, exc_info=True)

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Repair JSON-like string results after tool invocation.

        Args:
            payload: Tool invocation result payload.
            context: Plugin execution context.

        Returns:
            Result with repaired JSON if applicable.
        """
        if isinstance(payload.result, str):
            text = payload.result
            if self._rust_helper is not None:
                try:
                    # Let Rust handle validity check + repair in one path to avoid
                    # duplicate parse checks across Python and Rust.
                    repaired = self._rust_helper.repair(text)
                except Exception as e:
                    logger.warning("Rust json_repair failed; falling back to Python repair: %s", e)
                    if _try_parse(text):
                        return ToolPostInvokeResult(continue_processing=True)
                    repaired = _repair(text)
            else:
                if _try_parse(text):
                    return ToolPostInvokeResult(continue_processing=True)
                repaired = _repair(text)
            if repaired is not None:
                return ToolPostInvokeResult(modified_payload=ToolPostInvokePayload(name=payload.name, result=repaired), metadata={"repaired": True})
        return ToolPostInvokeResult(continue_processing=True)
