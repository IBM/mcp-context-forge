# -*- coding: utf-8 -*-
"""Location: ./plugins/cached_tool_result/cached_tool_result.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Cached Tool Result Plugin.
Stores idempotent tool results in an in-memory cache keyed by tool name and
selected argument fields. Reads are advisory (metadata) due to framework
constraints; writes occur in tool_post_invoke.
"""

# Future
from __future__ import annotations

# Standard
from dataclasses import dataclass
import hashlib
import time
from typing import Any, Dict, List, Optional

# Third-Party
import orjson
from pydantic import BaseModel, Field

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


class CacheConfig(BaseModel):
    """Configuration for cached tool result plugin.

    Attributes:
        cacheable_tools: List of tool names that should be cached.
        ttl: Time-to-live in seconds for cached results.
        key_fields: Optional mapping of tool names to specific argument fields to use for cache keys.
    """

    cacheable_tools: List[str] = Field(default_factory=list)
    ttl: int = 300
    key_fields: Optional[Dict[str, List[str]]] = None  # {tool: [fields...]}


@dataclass
class _Entry:
    """Cache entry containing a value and expiration timestamp.

    Attributes:
        value: Cached tool result.
        expires_at: Unix timestamp when the cached value expires.
    """

    value: Any
    expires_at: float


_CACHE: Dict[str, _Entry] = {}


def _make_key(tool: str, args: dict | None, fields: Optional[List[str]]) -> str:
    """Generate a cache key hash from tool name and selected argument fields.

    Args:
        tool: Tool name.
        args: Tool arguments dictionary.
        fields: Optional list of specific argument fields to include in the key.

    Returns:
        SHA256 hex digest cache key.
    """
    base = {"tool": tool, "args": {}}
    if args:
        if fields:
            base["args"] = {k: args.get(k) for k in fields}
        else:
            base["args"] = args
    raw = orjson.dumps(base, default=str, option=orjson.OPT_SORT_KEYS)
    return hashlib.sha256(raw).hexdigest()


class CachedToolResultPlugin(Plugin):
    """Cache idempotent tool results (write-through)."""

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the cached tool result plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        self._cfg = CacheConfig(**(config.config or {}))

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        """Check cache before tool invocation and store cache key in context.

        Args:
            payload: Tool invocation payload.
            context: Plugin execution context.

        Returns:
            Result with cache hit/miss metadata.
        """
        tool = payload.name
        if tool not in self._cfg.cacheable_tools:
            return ToolPreInvokeResult(continue_processing=True)
        fields = (self._cfg.key_fields or {}).get(tool)
        key = _make_key(tool, payload.args or {}, fields)
        # Persist key for post-invoke
        context.set_state("cache_key", key)
        context.set_state("cache_tool", tool)
        ent = _CACHE.get(key)
        now = time.time()
        if ent and ent.expires_at > now:
            # Advisory metadata; actual short-circuiting is not supported here
            return ToolPreInvokeResult(metadata={"cache_hit": True, "key": key})
        return ToolPreInvokeResult(metadata={"cache_hit": False, "key": key})

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Store tool result in cache after invocation.

        Args:
            payload: Tool invocation result payload.
            context: Plugin execution context.

        Returns:
            Result with cache storage metadata.
        """
        tool = payload.name
        # Persist only for configured tools
        if tool not in self._cfg.cacheable_tools:
            return ToolPostInvokeResult(continue_processing=True)
        # Read key from context
        key = context.get_state("cache_key") if context else None
        if not key:
            # Fallback to a coarse key when args are unknown
            key = _make_key(tool, None, None)
        ttl = max(1, int(self._cfg.ttl))
        _CACHE[key] = _Entry(value=payload.result, expires_at=time.time() + ttl)
        return ToolPostInvokeResult(metadata={"cache_stored": True, "key": key, "ttl": ttl})
