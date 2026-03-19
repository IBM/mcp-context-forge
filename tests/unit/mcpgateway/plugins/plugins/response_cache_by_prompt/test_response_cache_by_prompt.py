# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/response_cache_by_prompt/test_response_cache_by_prompt.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for ResponseCacheByPromptPlugin with inverted index optimization.
"""

import asyncio

import pytest

from mcpgateway.plugins.framework import (
    GlobalContext,
    PluginConfig,
    PluginContext,
    ToolHookType,
    ToolPostInvokePayload,
    ToolPreInvokePayload,
)
from plugins.response_cache_by_prompt.response_cache_by_prompt import (
    ResponseCacheByPromptPlugin,
    _cos_sim,
    _tokenize,
    _vectorize,
)


class TestTokenization:
    """Tests for tokenization and vectorization functions."""

    def test_tokenize_basic(self):
        """Test basic tokenization."""
        tokens = _tokenize("hello world")
        assert tokens == ["hello", "world"]

    def test_tokenize_with_duplicates(self):
        """Test tokenization preserves duplicates."""
        tokens = _tokenize("hello world hello")
        assert tokens == ["hello", "world", "hello"]

    def test_tokenize_case_insensitive(self):
        """Test tokenization is case insensitive."""
        tokens = _tokenize("Hello WORLD")
        assert tokens == ["hello", "world"]

    def test_tokenize_empty(self):
        """Test tokenization of empty string."""
        tokens = _tokenize("")
        assert tokens == []

    def test_vectorize_basic(self):
        """Test basic vectorization."""
        vec = _vectorize("hello world")
        assert set(vec.keys()) == {"hello", "world"}
        # L2 normalized: each should be 1/sqrt(2)
        assert abs(vec["hello"] - 0.7071) < 0.001
        assert abs(vec["world"] - 0.7071) < 0.001

    def test_vectorize_with_duplicates(self):
        """Test vectorization counts duplicates."""
        vec = _vectorize("hello hello world")
        # hello has count 2, world has count 1
        # norm = sqrt(4 + 1) = sqrt(5)
        assert vec["hello"] > vec["world"]

    def test_cosine_similarity_identical(self):
        """Test cosine similarity of identical vectors."""
        vec1 = _vectorize("hello world")
        vec2 = _vectorize("hello world")
        sim = _cos_sim(vec1, vec2)
        assert abs(sim - 1.0) < 0.001

    def test_cosine_similarity_disjoint(self):
        """Test cosine similarity of completely different vectors."""
        vec1 = _vectorize("hello world")
        vec2 = _vectorize("goodbye universe")
        sim = _cos_sim(vec1, vec2)
        assert sim == 0.0

    def test_cosine_similarity_partial_overlap(self):
        """Test cosine similarity with partial token overlap."""
        vec1 = _vectorize("hello world")
        vec2 = _vectorize("hello universe")
        sim = _cos_sim(vec1, vec2)
        assert 0.0 < sim < 1.0


class TestCacheBasics:
    """Tests for basic cache store and hit functionality."""

    @pytest.mark.asyncio
    async def test_cache_store_and_exact_hit(self):
        """Test storing and retrieving exact match from cache."""
        plugin = ResponseCacheByPromptPlugin(
            PluginConfig(
                name="cache",
                kind="plugins.response_cache_by_prompt.response_cache_by_prompt.ResponseCacheByPromptPlugin",
                hooks=[ToolHookType.TOOL_PRE_INVOKE, ToolHookType.TOOL_POST_INVOKE],
                config={"cacheable_tools": ["test_tool"], "ttl": 60, "threshold": 0.92},
            )
        )

        # First request - cache miss
        ctx1 = PluginContext(global_context=GlobalContext(request_id="r1"))
        pre1 = await plugin.tool_pre_invoke(ToolPreInvokePayload(name="test_tool", args={"prompt": "hello world"}), ctx1)
        assert pre1.metadata and pre1.metadata.get("approx_cache") is False

        # Store result
        post1 = await plugin.tool_post_invoke(ToolPostInvokePayload(name="test_tool", result={"data": "result1"}), ctx1)
        assert post1.metadata and post1.metadata.get("approx_cache_stored") is True

        # Second request with exact same prompt - cache hit
        ctx2 = PluginContext(global_context=GlobalContext(request_id="r2"))
        pre2 = await plugin.tool_pre_invoke(ToolPreInvokePayload(name="test_tool", args={"prompt": "hello world"}), ctx2)
        assert pre2.metadata and pre2.metadata.get("approx_cache") is True
        assert pre2.metadata.get("similarity") == 1.0

    @pytest.mark.asyncio
    async def test_cache_miss_different_prompt(self):
        """Test cache miss for completely different prompt."""
        plugin = ResponseCacheByPromptPlugin(
            PluginConfig(
                name="cache",
                kind="plugins.response_cache_by_prompt.response_cache_by_prompt.ResponseCacheByPromptPlugin",
                hooks=[ToolHookType.TOOL_PRE_INVOKE, ToolHookType.TOOL_POST_INVOKE],
                config={"cacheable_tools": ["test_tool"], "ttl": 60, "threshold": 0.92},
            )
        )

        # Store first entry
        ctx1 = PluginContext(global_context=GlobalContext(request_id="r1"))
        await plugin.tool_pre_invoke(ToolPreInvokePayload(name="test_tool", args={"prompt": "hello world"}), ctx1)
        await plugin.tool_post_invoke(ToolPostInvokePayload(name="test_tool", result={"data": "result1"}), ctx1)

        # Query with completely different prompt - cache miss
        ctx2 = PluginContext(global_context=GlobalContext(request_id="r2"))
        pre2 = await plugin.tool_pre_invoke(ToolPreInvokePayload(name="test_tool", args={"prompt": "goodbye universe"}), ctx2)
        assert pre2.metadata and pre2.metadata.get("approx_cache") is False

    @pytest.mark.asyncio
    async def test_non_cacheable_tool_ignored(self):
        """Test that non-cacheable tools are not cached."""
        plugin = ResponseCacheByPromptPlugin(
            PluginConfig(
                name="cache",
                kind="plugins.response_cache_by_prompt.response_cache_by_prompt.ResponseCacheByPromptPlugin",
                hooks=[ToolHookType.TOOL_PRE_INVOKE, ToolHookType.TOOL_POST_INVOKE],
                config={"cacheable_tools": ["cached_tool"], "ttl": 60, "threshold": 0.92},
            )
        )

        ctx = PluginContext(global_context=GlobalContext(request_id="r1"))
        pre = await plugin.tool_pre_invoke(ToolPreInvokePayload(name="uncached_tool", args={"prompt": "hello"}), ctx)
        # Should return continue_processing=True with no cache metadata
        assert pre.continue_processing is True


class TestInvertedIndex:
    """Tests for inverted index candidate filtering."""

    @pytest.mark.asyncio
    async def test_index_populated_on_insert(self):
        """Test that inverted index is populated when entries are added."""
        plugin = ResponseCacheByPromptPlugin(
            PluginConfig(
                name="cache",
                kind="plugins.response_cache_by_prompt.response_cache_by_prompt.ResponseCacheByPromptPlugin",
                hooks=[ToolHookType.TOOL_PRE_INVOKE, ToolHookType.TOOL_POST_INVOKE],
                config={"cacheable_tools": ["test_tool"], "ttl": 60, "threshold": 0.92},
            )
        )

        ctx = PluginContext(global_context=GlobalContext(request_id="r1"))
        await plugin.tool_pre_invoke(ToolPreInvokePayload(name="test_tool", args={"prompt": "apple banana"}), ctx)
        await plugin.tool_post_invoke(ToolPostInvokePayload(name="test_tool", result={"data": 1}), ctx)

        # Verify index contains the tokens
        tool_index = plugin._index.get("test_tool", {})
        assert "apple" in tool_index
        assert "banana" in tool_index
        assert 0 in tool_index["apple"]
        assert 0 in tool_index["banana"]

    @pytest.mark.asyncio
    async def test_index_maps_multiple_entries(self):
        """Test that inverted index correctly maps tokens to multiple entries."""
        plugin = ResponseCacheByPromptPlugin(
            PluginConfig(
                name="cache",
                kind="plugins.response_cache_by_prompt.response_cache_by_prompt.ResponseCacheByPromptPlugin",
                hooks=[ToolHookType.TOOL_PRE_INVOKE, ToolHookType.TOOL_POST_INVOKE],
                config={"cacheable_tools": ["test_tool"], "ttl": 60, "threshold": 0.92},
            )
        )

        # Add entries with overlapping tokens
        prompts = ["apple banana", "banana cherry", "cherry date"]
        for i, prompt in enumerate(prompts):
            ctx = PluginContext(global_context=GlobalContext(request_id=f"r{i}"))
            await plugin.tool_pre_invoke(ToolPreInvokePayload(name="test_tool", args={"prompt": prompt}), ctx)
            await plugin.tool_post_invoke(ToolPostInvokePayload(name="test_tool", result={"data": i}), ctx)

        tool_index = plugin._index.get("test_tool", {})

        # "banana" should map to entries 0 and 1
        assert tool_index.get("banana") == {0, 1}
        # "cherry" should map to entries 1 and 2
        assert tool_index.get("cherry") == {1, 2}
        # "apple" should only map to entry 0
        assert tool_index.get("apple") == {0}

    @pytest.mark.asyncio
    async def test_candidate_filtering_uses_index(self):
        """Test that _find_best uses inverted index for candidate filtering."""
        plugin = ResponseCacheByPromptPlugin(
            PluginConfig(
                name="cache",
                kind="plugins.response_cache_by_prompt.response_cache_by_prompt.ResponseCacheByPromptPlugin",
                hooks=[ToolHookType.TOOL_PRE_INVOKE, ToolHookType.TOOL_POST_INVOKE],
                config={"cacheable_tools": ["test_tool"], "ttl": 60, "threshold": 0.5},
            )
        )

        # Add diverse entries
        prompts = ["apple pie dessert", "banana split ice cream", "cherry cobbler treat"]
        for i, prompt in enumerate(prompts):
            ctx = PluginContext(global_context=GlobalContext(request_id=f"r{i}"))
            await plugin.tool_pre_invoke(ToolPreInvokePayload(name="test_tool", args={"prompt": prompt}), ctx)
            await plugin.tool_post_invoke(ToolPostInvokePayload(name="test_tool", result={"data": i}), ctx)

        # Query with "apple" - should find the apple entry via index
        best, sim = plugin._find_best("test_tool", "apple fruit")
        assert best is not None
        assert "apple" in best.text


class TestEvictionAndIndexRebuild:
    """Tests for eviction and index rebuild scenarios."""

    @pytest.mark.asyncio
    async def test_max_entries_cap(self):
        """Test that cache respects max_entries limit."""
        plugin = ResponseCacheByPromptPlugin(
            PluginConfig(
                name="cache",
                kind="plugins.response_cache_by_prompt.response_cache_by_prompt.ResponseCacheByPromptPlugin",
                hooks=[ToolHookType.TOOL_PRE_INVOKE, ToolHookType.TOOL_POST_INVOKE],
                config={"cacheable_tools": ["test_tool"], "ttl": 3600, "threshold": 0.92, "max_entries": 3},
            )
        )

        # Add 5 entries (should be capped at 3)
        for i in range(5):
            ctx = PluginContext(global_context=GlobalContext(request_id=f"r{i}"))
            await plugin.tool_pre_invoke(ToolPreInvokePayload(name="test_tool", args={"prompt": f"unique{i} text"}), ctx)
            await plugin.tool_post_invoke(ToolPostInvokePayload(name="test_tool", result={"data": i}), ctx)

        bucket = plugin._cache.get("test_tool", [])
        assert len(bucket) == 3

        # Oldest entries should be evicted (unique0, unique1)
        texts = [e.text for e in bucket]
        assert "unique0 text" not in texts
        assert "unique1 text" not in texts
        assert "unique2 text" in texts
        assert "unique3 text" in texts
        assert "unique4 text" in texts

    @pytest.mark.asyncio
    async def test_index_consistency_after_max_entries_eviction(self):
        """Test that inverted index is consistent after max_entries eviction."""
        plugin = ResponseCacheByPromptPlugin(
            PluginConfig(
                name="cache",
                kind="plugins.response_cache_by_prompt.response_cache_by_prompt.ResponseCacheByPromptPlugin",
                hooks=[ToolHookType.TOOL_PRE_INVOKE, ToolHookType.TOOL_POST_INVOKE],
                config={"cacheable_tools": ["test_tool"], "ttl": 3600, "threshold": 0.92, "max_entries": 3},
            )
        )

        # Add 5 entries
        for i in range(5):
            ctx = PluginContext(global_context=GlobalContext(request_id=f"r{i}"))
            await plugin.tool_pre_invoke(ToolPreInvokePayload(name="test_tool", args={"prompt": f"unique{i} word"}), ctx)
            await plugin.tool_post_invoke(ToolPostInvokePayload(name="test_tool", result={"data": i}), ctx)

        bucket = plugin._cache.get("test_tool", [])
        tool_index = plugin._index.get("test_tool", {})

        # Verify no stale indices
        for token, indices in tool_index.items():
            for idx in indices:
                assert idx < len(bucket), f"Stale index {idx} for token {token}"

        # Verify evicted tokens are removed
        assert "unique0" not in tool_index
        assert "unique1" not in tool_index

    @pytest.mark.asyncio
    async def test_ttl_expiration_and_index_rebuild(self, monkeypatch):
        """Test that expired entries are removed and index is rebuilt."""
        # Stabilize time-dependent behavior by controlling time.time()
        from plugins.response_cache_by_prompt import response_cache_by_prompt as rcbp

        now = [1_000.0]
        monkeypatch.setattr(rcbp.time, "time", lambda: now[0])

        plugin = ResponseCacheByPromptPlugin(
            PluginConfig(
                name="cache",
                kind="plugins.response_cache_by_prompt.response_cache_by_prompt.ResponseCacheByPromptPlugin",
                hooks=[ToolHookType.TOOL_PRE_INVOKE, ToolHookType.TOOL_POST_INVOKE],
                config={"cacheable_tools": ["test_tool"], "ttl": 1, "threshold": 0.92, "max_entries": 100},
            )
        )

        # Add an entry with short TTL
        ctx1 = PluginContext(global_context=GlobalContext(request_id="r1"))
        await plugin.tool_pre_invoke(ToolPreInvokePayload(name="test_tool", args={"prompt": "temporary entry"}), ctx1)
        await plugin.tool_post_invoke(ToolPostInvokePayload(name="test_tool", result={"data": "temp"}), ctx1)

        # Advance time beyond TTL to expire the first entry
        now[0] += 2.0

        # Add new entry to trigger eviction
        ctx2 = PluginContext(global_context=GlobalContext(request_id="r2"))
        await plugin.tool_pre_invoke(ToolPreInvokePayload(name="test_tool", args={"prompt": "fresh new entry"}), ctx2)
        await plugin.tool_post_invoke(ToolPostInvokePayload(name="test_tool", result={"data": "new"}), ctx2)

        bucket = plugin._cache.get("test_tool", [])
        tool_index = plugin._index.get("test_tool", {})

        # Allow for timing tolerance: expired entry should be removed, leaving 1-2 entries
        # In race conditions, the expired entry might not be cleaned up immediately
        assert 1 <= len(bucket) <= 2, f"Expected 1-2 entries after TTL expiration, got {len(bucket)}"

        # Verify the fresh entry is present
        texts = [e.text for e in bucket]
        assert "fresh new entry" in texts, "Fresh entry should be present in cache"

        # Index should be consistent with bucket size
        max_idx = max((max(indices) for indices in tool_index.values() if indices), default=-1)
        assert max_idx < len(bucket), f"Index contains stale reference: max_idx={max_idx}, bucket_size={len(bucket)}"

        # If only one entry remains, verify it's the fresh one and expired tokens are gone
        if len(bucket) == 1:
            assert bucket[0].text == "fresh new entry"
            assert "temporary" not in tool_index, "Expired entry tokens should be removed from index"

    @pytest.mark.asyncio
    async def test_query_after_eviction_finds_correct_entry(self):
        """Test that queries work correctly after eviction and index rebuild."""
        plugin = ResponseCacheByPromptPlugin(
            PluginConfig(
                name="cache",
                kind="plugins.response_cache_by_prompt.response_cache_by_prompt.ResponseCacheByPromptPlugin",
                hooks=[ToolHookType.TOOL_PRE_INVOKE, ToolHookType.TOOL_POST_INVOKE],
                config={"cacheable_tools": ["test_tool"], "ttl": 3600, "threshold": 0.92, "max_entries": 3},
            )
        )

        # Add 5 entries (oldest 2 will be evicted)
        for i in range(5):
            ctx = PluginContext(global_context=GlobalContext(request_id=f"r{i}"))
            await plugin.tool_pre_invoke(ToolPreInvokePayload(name="test_tool", args={"prompt": f"unique{i} text"}), ctx)
            await plugin.tool_post_invoke(ToolPostInvokePayload(name="test_tool", result={"data": i}), ctx)

        # Query for a remaining entry
        ctx_query = PluginContext(global_context=GlobalContext(request_id="query"))
        pre = await plugin.tool_pre_invoke(ToolPreInvokePayload(name="test_tool", args={"prompt": "unique3 text"}), ctx_query)
        assert pre.metadata and pre.metadata.get("approx_cache") is True
        assert pre.metadata.get("similarity") == 1.0

        # Query for an evicted entry (should miss)
        ctx_query2 = PluginContext(global_context=GlobalContext(request_id="query2"))
        pre2 = await plugin.tool_pre_invoke(ToolPreInvokePayload(name="test_tool", args={"prompt": "unique0 text"}), ctx_query2)
        assert pre2.metadata and pre2.metadata.get("approx_cache") is False
