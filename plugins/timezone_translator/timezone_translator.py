# -*- coding: utf-8 -*-
"""Location: ./plugins/timezone_translator/timezone_translator.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Timezone Translator Plugin.

Converts detected ISO-like timestamps between server and user timezones.

Hooks: tool_pre_invoke (args), tool_post_invoke (result)
"""

# Future
from __future__ import annotations

# Standard
from datetime import datetime
import re
from typing import Any
from zoneinfo import ZoneInfo

# Third-Party
from pydantic import BaseModel

# First-Party
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
)

ISO_CANDIDATE = re.compile(r"\b(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?(?:[+-]\d{2}:?\d{2}|Z)?)\b")


class TzConfig(BaseModel):
    """Configuration for timezone translation.

    Attributes:
        user_tz: User timezone name (e.g., 'America/New_York').
        server_tz: Server timezone name (e.g., 'UTC').
        direction: Translation direction ('to_user' or 'to_server').
        fields: Argument fields to translate (None = all).
    """

    user_tz: str = "UTC"
    server_tz: str = "UTC"
    direction: str = "to_user"  # to_user | to_server
    fields: list[str] | None = None  # restrict to certain arg keys when pre-invoke


def _convert(ts: str, source: ZoneInfo, target: ZoneInfo) -> str:
    """Convert timestamp between timezones.

    Args:
        ts: ISO timestamp string to convert.
        source: Source timezone.
        target: Target timezone.

    Returns:
        Converted timestamp string.
    """
    # Try datetime.fromisoformat first; fallback to naive parse without tz
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return ts
    if not dt.tzinfo:
        dt = dt.replace(tzinfo=source)
    try:
        return dt.astimezone(target).isoformat()
    except Exception:
        return ts


def _translate_text(text: str, source: ZoneInfo, target: ZoneInfo) -> str:
    """Translate timestamps in text between timezones.

    Args:
        text: Text containing timestamps to translate.
        source: Source timezone.
        target: Target timezone.

    Returns:
        Text with translated timestamps.
    """

    def repl(m: re.Match[str]) -> str:
        """Replace matched timestamp with converted version.

        Args:
            m: Regex match object.

        Returns:
            Converted timestamp string.
        """
        return _convert(m.group(1), source, target)

    return ISO_CANDIDATE.sub(repl, text)


def _walk_and_translate(value: Any, source: ZoneInfo, target: ZoneInfo, fields: list[str] | None, in_args: bool) -> Any:
    """Recursively translate timestamps in nested data structure.

    Args:
        value: Value to translate (can be str, dict, list, or other).
        source: Source timezone.
        target: Target timezone.
        fields: Fields to translate (None = all).
        in_args: Whether translating arguments (affects field filtering).

    Returns:
        Value with translated timestamps.
    """
    if isinstance(value, str):
        return _translate_text(value, source, target)
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if in_args and fields and k not in fields:
                out[k] = v
            else:
                out[k] = _walk_and_translate(v, source, target, fields, in_args)
        return out
    if isinstance(value, list):
        return [_walk_and_translate(v, source, target, fields, in_args) for v in value]
    return value


class TimezoneTranslatorPlugin(Plugin):
    """Converts detected ISO timestamps between server and user timezones."""

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the timezone translator plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        self._cfg = TzConfig(**(config.config or {}))

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        """Translate timestamps in tool arguments from user to server timezone.

        Args:
            payload: Tool invocation payload.
            context: Plugin execution context.

        Returns:
            Result with potentially modified arguments.
        """
        if self._cfg.direction != "to_server":
            return ToolPreInvokeResult(continue_processing=True)
        src = ZoneInfo(self._cfg.user_tz)
        dst = ZoneInfo(self._cfg.server_tz)
        new_args = _walk_and_translate(payload.args or {}, src, dst, self._cfg.fields or None, True)
        if new_args != (payload.args or {}):
            return ToolPreInvokeResult(modified_payload=ToolPreInvokePayload(name=payload.name, args=new_args))
        return ToolPreInvokeResult(continue_processing=True)

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Translate timestamps in tool results from server to user timezone.

        Args:
            payload: Tool result payload.
            context: Plugin execution context.

        Returns:
            Result with potentially modified result.
        """
        if self._cfg.direction != "to_user":
            return ToolPostInvokeResult(continue_processing=True)
        src = ZoneInfo(self._cfg.server_tz)
        dst = ZoneInfo(self._cfg.user_tz)
        new_result = _walk_and_translate(payload.result, src, dst, None, False)
        if new_result != payload.result:
            return ToolPostInvokeResult(modified_payload=ToolPostInvokePayload(name=payload.name, result=new_result))
        return ToolPostInvokeResult(continue_processing=True)
