# -*- coding: utf-8 -*-
"""Location: ./plugins/response_cache_by_prompt/response_cache_by_prompt.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Response Cache by Prompt Plugin.

Advisory approximate caching of tool results using cosine similarity over
selected string fields (e.g., "prompt", "input").

Because the plugin framework cannot short-circuit tool execution at pre-hook,
the plugin returns cache hit info via metadata in `tool_pre_invoke`, and writes
results at `tool_post_invoke` with a TTL.
"""

# Future
from __future__ import annotations

# Standard
from dataclasses import dataclass
import math
import time
from typing import Any, Dict, List, Optional, Tuple

# Third-Party
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


def _tokenize(text: str) -> list[str]:
    # Simple whitespace + lowercasing tokenizer
    return [t for t in text.lower().split() if t]


def _vectorize(text: str) -> Dict[str, float]:
    vec: Dict[str, float] = {}
    for tok in _tokenize(text):
        vec[tok] = vec.get(tok, 0.0) + 1.0
    # L2 normalize
    norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
    for k in list(vec.keys()):
        vec[k] /= norm
    return vec


def _cos_sim(a: Dict[str, float], b: Dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    # Calculate dot product over intersection
    if len(a) > len(b):
        a, b = b, a
    return sum(a.get(k, 0.0) * b.get(k, 0.0) for k in a.keys())


class ResponseCacheConfig(BaseModel):
    cacheable_tools: List[str] = Field(default_factory=list)
    fields: List[str] = Field(default_factory=lambda: ["prompt", "input", "query"])  # fields to read string text from args
    ttl: int = 600
    threshold: float = 0.92  # cosine similarity threshold
    max_entries: int = 1000


@dataclass
class _Entry:
    text: str
    vec: Dict[str, float]
    value: Any
    expires_at: float


class ResponseCacheByPromptPlugin(Plugin):
    """Approximate response cache keyed by prompt similarity."""

    def __init__(self, config: PluginConfig) -> None:
        super().__init__(config)
        self._cfg = ResponseCacheConfig(**(config.config or {}))
        # Per-tool list of entries
        self._cache: Dict[str, list[_Entry]] = {}

    def _gather_text(self, args: dict[str, Any] | None) -> str:
        if not args:
            return ""
        chunks: list[str] = []
        for f in self._cfg.fields:
            v = args.get(f)
            if isinstance(v, str) and v.strip():
                chunks.append(v)
        return "\n".join(chunks)

    def _find_best(self, tool: str, text: str) -> Tuple[Optional[_Entry], float]:
        vec = _vectorize(text)
        best: Optional[_Entry] = None
        best_sim = 0.0
        now = time.time()
        for e in list(self._cache.get(tool, [])):
            if e.expires_at <= now:
                continue
            sim = _cos_sim(vec, e.vec)
            if sim > best_sim:
                best = e
                best_sim = sim
        return best, best_sim

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        tool = payload.name
        if tool not in self._cfg.cacheable_tools:
            return ToolPreInvokeResult(continue_processing=True)
        text = self._gather_text(payload.args or {})
        if not text:
            return ToolPreInvokeResult(continue_processing=True)
        # Keep text for post-invoke storage
        context.set_state("rcbp_last_text", text)
        best, sim = self._find_best(tool, text)
        meta: dict[str, Any] = {"approx_cache": False}
        if best and sim >= self._cfg.threshold:
            meta.update(
                {
                    "approx_cache": True,
                    "similarity": round(sim, 4),
                    "cached_text_len": len(best.text),
                }
            )
            # Expose a small hint; not all callers will use it
            context.metadata["approx_cached_result_available"] = True
            context.metadata["approx_cached_similarity"] = sim
        return ToolPreInvokeResult(metadata=meta)

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        tool = payload.name
        if tool not in self._cfg.cacheable_tools:
            return ToolPostInvokeResult(continue_processing=True)
        # Retrieve text captured in pre-invoke
        text = context.get_state("rcbp_last_text") if context else ""
        if not text:
            # As a fallback, do nothing
            return ToolPostInvokeResult(continue_processing=True)

        entry = _Entry(text=text, vec=_vectorize(text), value=payload.result, expires_at=time.time() + max(1, int(self._cfg.ttl)))
        bucket = self._cache.setdefault(tool, [])
        bucket.append(entry)
        # Evict expired and cap size
        now = time.time()
        bucket[:] = [e for e in bucket if e.expires_at > now]
        if len(bucket) > self._cfg.max_entries:
            bucket[:] = bucket[-self._cfg.max_entries :]
        return ToolPostInvokeResult(metadata={"approx_cache_stored": True})
