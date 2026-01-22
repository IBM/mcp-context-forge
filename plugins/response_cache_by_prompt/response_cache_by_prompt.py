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
from collections import defaultdict
from dataclasses import dataclass, field
import math
import time
from typing import Any, Dict, List, Optional, Set, Tuple

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
    """Tokenize text into lowercase words.

    Args:
        text: Input text to tokenize.

    Returns:
        List of lowercase tokens.
    """
    # Simple whitespace + lowercasing tokenizer
    return [t for t in text.lower().split() if t]


def _vectorize(text: str) -> Dict[str, float]:
    """Convert text to L2-normalized word frequency vector.

    Args:
        text: Input text.

    Returns:
        Dictionary mapping tokens to normalized frequencies.
    """
    vec: Dict[str, float] = {}
    for tok in _tokenize(text):
        vec[tok] = vec.get(tok, 0.0) + 1.0
    # L2 normalize
    norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
    for k in list(vec.keys()):
        vec[k] /= norm
    return vec


def _cos_sim(a: Dict[str, float], b: Dict[str, float]) -> float:
    """Compute cosine similarity between two vectors.

    Args:
        a: First vector (token -> frequency mapping).
        b: Second vector (token -> frequency mapping).

    Returns:
        Cosine similarity score between 0.0 and 1.0.
    """
    if not a or not b:
        return 0.0
    # Calculate dot product over intersection
    if len(a) > len(b):
        a, b = b, a
    return sum(a.get(k, 0.0) * b.get(k, 0.0) for k in a.keys())


class ResponseCacheConfig(BaseModel):
    """Configuration for response cache by prompt similarity.

    Attributes:
        cacheable_tools: List of tool names to cache.
        fields: Argument fields to extract text from for similarity matching.
        ttl: Time-to-live for cache entries in seconds.
        threshold: Minimum cosine similarity threshold for cache hits.
        max_entries: Maximum number of cache entries per tool.
    """

    cacheable_tools: List[str] = Field(default_factory=list)
    fields: List[str] = Field(default_factory=lambda: ["prompt", "input", "query"])  # fields to read string text from args
    ttl: int = 600
    threshold: float = 0.92  # cosine similarity threshold
    max_entries: int = 1000


@dataclass
class _Entry:
    """Cache entry storing text, vector, result, and expiration.

    Attributes:
        text: Original text that was cached.
        vec: Normalized vector representation of text.
        value: Cached result value.
        expires_at: Unix timestamp when entry expires.
        tokens: Set of tokens for fast filtering (optimization).
    """

    text: str
    vec: Dict[str, float]
    value: Any
    expires_at: float
    tokens: set[str] = field(default_factory=set)  # Pre-computed token set for quick filtering


class ResponseCacheByPromptPlugin(Plugin):
    """Approximate response cache keyed by prompt similarity with optimized lookup."""

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the response cache plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        self._cfg = ResponseCacheConfig(**(config.config or {}))
        # Per-tool list of entries
        self._cache: Dict[str, list[_Entry]] = {}
        # Inverted index: tool -> token -> set of entry indices for fast filtering
        self._index: Dict[str, Dict[str, Set[int]]] = defaultdict(lambda: defaultdict(set))

    def _gather_text(self, args: dict[str, Any] | None) -> str:
        """Extract and concatenate text from configured argument fields.

        Args:
            args: Tool arguments dictionary.

        Returns:
            Concatenated text from configured fields.
        """
        if not args:
            return ""
        chunks: list[str] = []
        for f in self._cfg.fields:
            v = args.get(f)
            if isinstance(v, str) and v.strip():
                chunks.append(v)
        return "\n".join(chunks)

    def _find_best(self, tool: str, text: str) -> Tuple[Optional[_Entry], float]:
        """Find the best matching cache entry for the given text (optimized).

        Uses inverted index to quickly filter candidates before computing
        expensive cosine similarity. Only entries sharing tokens with the
        query are considered.

        Args:
            tool: Tool name to search cache for.
            text: Query text to match against.

        Returns:
            Tuple of (best matching entry, similarity score).
        """
        bucket = self._cache.get(tool, [])
        if not bucket:
            return None, 0.0

        vec = _vectorize(text)
        query_tokens = set(vec.keys())
        
        # Fast path: use inverted index to find candidate entries
        # Only consider entries that share at least one token with query
        tool_index = self._index.get(tool, {})
        candidate_indices: Set[int] = set()
        
        for token in query_tokens:
            if token in tool_index:
                candidate_indices.update(tool_index[token])
        
        # If no candidates found via index, fall back to empty result
        if not candidate_indices:
            return None, 0.0
        
        # Compute similarity only for candidates
        best: Optional[_Entry] = None
        best_sim = 0.0
        now = time.time()
        
        for idx in candidate_indices:
            if idx >= len(bucket):
                continue
            e = bucket[idx]
            if e.expires_at <= now:
                continue
            sim = _cos_sim(vec, e.vec)
            if sim > best_sim:
                best = e
                best_sim = sim
        
        return best, best_sim

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        """Check for cache hit before tool invocation.

        Args:
            payload: Tool invocation payload.
            context: Plugin execution context.

        Returns:
            Result with metadata indicating cache hit status.
        """
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
        """Store tool result in cache after invocation.

        Args:
            payload: Tool invocation result payload.
            context: Plugin execution context.

        Returns:
            Result with metadata indicating cache storage.
        """
        tool = payload.name
        if tool not in self._cfg.cacheable_tools:
            return ToolPostInvokeResult(continue_processing=True)
        # Retrieve text captured in pre-invoke
        text = context.get_state("rcbp_last_text") if context else ""
        if not text:
            # As a fallback, do nothing
            return ToolPostInvokeResult(continue_processing=True)

        vec = _vectorize(text)
        tokens = set(vec.keys())
        entry = _Entry(text=text, vec=vec, value=payload.result, expires_at=time.time() + max(1, int(self._cfg.ttl)), tokens=tokens)
        
        bucket = self._cache.setdefault(tool, [])
        entry_idx = len(bucket)
        bucket.append(entry)
        
        # Update inverted index for new entry
        tool_index = self._index[tool]
        for token in tokens:
            tool_index[token].add(entry_idx)
        
        # Evict expired entries and rebuild index
        now = time.time()
        # Filter out expired entries
        valid_entries = [e for e in bucket if e.expires_at > now]
        
        # Cap size if needed
        if len(valid_entries) > self._cfg.max_entries:
            valid_entries = valid_entries[-self._cfg.max_entries:]
        
        # Rebuild bucket and index if we removed or modified entries
        if len(valid_entries) != len(bucket):
            bucket.clear()
            bucket.extend(valid_entries)
            
            # Rebuild inverted index for this tool
            self._index[tool].clear()
            for new_idx, entry in enumerate(bucket):
                for token in entry.tokens:
                    self._index[tool][token].add(new_idx)
        
        return ToolPostInvokeResult(metadata={"approx_cache_stored": True})
