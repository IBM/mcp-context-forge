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
    user_tz: str = "UTC"
    server_tz: str = "UTC"
    direction: str = "to_user"  # to_user | to_server
    fields: list[str] | None = None  # restrict to certain arg keys when pre-invoke


def _convert(ts: str, source: ZoneInfo, target: ZoneInfo) -> str:
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
    def repl(m: re.Match[str]) -> str:
        return _convert(m.group(1), source, target)

    return ISO_CANDIDATE.sub(repl, text)


def _walk_and_translate(value: Any, source: ZoneInfo, target: ZoneInfo, fields: list[str] | None, in_args: bool) -> Any:
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
    def __init__(self, config: PluginConfig) -> None:
        super().__init__(config)
        self._cfg = TzConfig(**(config.config or {}))

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        if self._cfg.direction != "to_server":
            return ToolPreInvokeResult(continue_processing=True)
        src = ZoneInfo(self._cfg.user_tz)
        dst = ZoneInfo(self._cfg.server_tz)
        new_args = _walk_and_translate(payload.args or {}, src, dst, self._cfg.fields or None, True)
        if new_args != (payload.args or {}):
            return ToolPreInvokeResult(modified_payload=ToolPreInvokePayload(name=payload.name, args=new_args))
        return ToolPreInvokeResult(continue_processing=True)

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        if self._cfg.direction != "to_user":
            return ToolPostInvokeResult(continue_processing=True)
        src = ZoneInfo(self._cfg.server_tz)
        dst = ZoneInfo(self._cfg.user_tz)
        new_result = _walk_and_translate(payload.result, src, dst, None, False)
        if new_result != payload.result:
            return ToolPostInvokeResult(modified_payload=ToolPostInvokePayload(name=payload.name, result=new_result))
        return ToolPostInvokeResult(continue_processing=True)
