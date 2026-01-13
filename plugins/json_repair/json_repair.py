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
    if re.match(r"^[\[{].*[\]}]$", t, flags=re.S) and ("'" in t and '"' not in t):
        base = t.replace("'", '"')
        if _try_parse(base):
            return base
    # Remove trailing commas before } or ] (apply on base if changed)
    cand = re.sub(r",(\s*[}\]])", r"\1", base)
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
            if _try_parse(text):
                return ToolPostInvokeResult(continue_processing=True)
            repaired = _repair(text)
            if repaired is not None:
                return ToolPostInvokeResult(modified_payload=ToolPostInvokePayload(name=payload.name, result=repaired), metadata={"repaired": True})
        return ToolPostInvokeResult(continue_processing=True)
