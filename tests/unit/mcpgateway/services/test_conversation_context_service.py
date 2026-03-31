# -*- coding: utf-8 -*-
"""Tests for the conversation context service.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Standard
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.schemas import ToolSearchResult
from mcpgateway.services.conversation_context_service import (
    ConversationContextService,
    get_conversation_context_service,
)


@pytest.fixture
def svc():
    return ConversationContextService()


@pytest.fixture
def mock_db():
    return MagicMock()


# ---------------------------------------------------------------------------
# Singleton helper
# ---------------------------------------------------------------------------


class TestGetConversationContextService:
    def test_returns_singleton(self):
        a = get_conversation_context_service()
        b = get_conversation_context_service()
        assert a is b
        assert isinstance(a, ConversationContextService)


# ---------------------------------------------------------------------------
# extract_context — empty / no history
# ---------------------------------------------------------------------------


class TestExtractContextNoHistory:
    @pytest.mark.asyncio
    async def test_no_redis_no_history_returns_empty(self, svc, mock_db):
        """When Redis is unavailable and chat history is empty, return []."""
        with patch("mcpgateway.services.conversation_context_service.get_redis_client", new_callable=AsyncMock, return_value=None):
            with patch("mcpgateway.services.conversation_context_service.ChatHistoryManager") as MockMgr:
                MockMgr.return_value.get_history = AsyncMock(return_value=[])
                results = await svc.extract_context("user_x", mock_db)
        assert results == []

    @pytest.mark.asyncio
    async def test_history_all_empty_content_returns_empty(self, svc, mock_db):
        """Messages with no content field produce empty combined text → return []."""
        with patch("mcpgateway.services.conversation_context_service.get_redis_client", new_callable=AsyncMock, return_value=None):
            with patch("mcpgateway.services.conversation_context_service.ChatHistoryManager") as MockMgr:
                MockMgr.return_value.get_history = AsyncMock(return_value=[{}, {}])
                results = await svc.extract_context("user_x", mock_db)
        assert results == []

    @pytest.mark.asyncio
    async def test_chat_history_fetch_exception_returns_empty(self, svc, mock_db):
        """If ChatHistoryManager raises, return []."""
        with patch("mcpgateway.services.conversation_context_service.get_redis_client", new_callable=AsyncMock, return_value=None):
            with patch("mcpgateway.services.conversation_context_service.ChatHistoryManager") as MockMgr:
                MockMgr.return_value.get_history = AsyncMock(side_effect=RuntimeError("redis down"))
                results = await svc.extract_context("user_x", mock_db)
        assert results == []


# ---------------------------------------------------------------------------
# extract_context — Redis cache hit
# ---------------------------------------------------------------------------


class TestExtractContextRedisCacheHit:
    @pytest.mark.asyncio
    async def test_redis_cache_hit_returns_cached_results(self, svc, mock_db):
        """A Redis cache hit should return cached results without calling semantic search."""
        cached = [ToolSearchResult(tool_name="cached_tool", description="d", similarity_score=0.9)]
        raw_json = json.dumps([r.model_dump() for r in cached])

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=raw_json)

        with patch("mcpgateway.services.conversation_context_service.get_redis_client", new_callable=AsyncMock, return_value=mock_redis):
            with patch("mcpgateway.services.conversation_context_service.ChatHistoryManager") as MockMgr:
                with patch("mcpgateway.services.semantic_search_service.get_semantic_search_service") as mock_sss:
                    MockMgr.return_value.get_history = AsyncMock(return_value=[])
                    results = await svc.extract_context("user_y", mock_db)

        assert len(results) == 1
        assert results[0].tool_name == "cached_tool"
        mock_sss.assert_not_called()

    @pytest.mark.asyncio
    async def test_in_memory_cache_hit_skips_search(self, svc, mock_db):
        """An in-memory cache entry that has not expired should skip semantic search."""
        cached = [ToolSearchResult(tool_name="mem_tool", description="d", similarity_score=0.7)]
        cache_key = "conv_context:user_z:10:10"
        svc._memory_cache[cache_key] = (time.monotonic() + 300, cached)

        with patch("mcpgateway.services.conversation_context_service.get_redis_client", new_callable=AsyncMock, return_value=None):
            with patch("mcpgateway.services.semantic_search_service.get_semantic_search_service") as mock_sss:
                results = await svc.extract_context("user_z", mock_db)

        assert results == cached
        mock_sss.assert_not_called()

    @pytest.mark.asyncio
    async def test_expired_in_memory_cache_reruns_search(self, svc, mock_db):
        """An expired in-memory cache entry should trigger a fresh search."""
        old = [ToolSearchResult(tool_name="old_tool", description="d", similarity_score=0.5)]
        cache_key = "conv_context:user_exp:10:10"
        svc._memory_cache[cache_key] = (time.monotonic() - 1, old)

        fresh = [ToolSearchResult(tool_name="fresh_tool", description="d", similarity_score=0.8)]
        mock_search_svc = MagicMock()
        mock_search_svc.search_tools = AsyncMock(return_value=fresh)

        with patch("mcpgateway.services.conversation_context_service.get_redis_client", new_callable=AsyncMock, return_value=None):
            with patch("mcpgateway.services.conversation_context_service.ChatHistoryManager") as MockMgr:
                MockMgr.return_value.get_history = AsyncMock(return_value=[{"content": "help me search"}])
                with patch("mcpgateway.services.semantic_search_service.get_semantic_search_service", return_value=mock_search_svc):
                    results = await svc.extract_context("user_exp", mock_db)

        assert results[0].tool_name == "fresh_tool"


# ---------------------------------------------------------------------------
# extract_context — semantic search path
# ---------------------------------------------------------------------------


class TestExtractContextSemanticSearch:
    @pytest.mark.asyncio
    async def test_semantic_search_called_with_combined_text(self, svc, mock_db):
        """Combined message text is passed to semantic search."""
        history = [{"content": "list files"}, {"content": "search tool"}]
        search_results = [ToolSearchResult(tool_name="file_tool", description="d", similarity_score=0.85)]

        mock_search_svc = MagicMock()
        mock_search_svc.search_tools = AsyncMock(return_value=search_results)

        with patch("mcpgateway.services.conversation_context_service.get_redis_client", new_callable=AsyncMock, return_value=None):
            with patch("mcpgateway.services.conversation_context_service.ChatHistoryManager") as MockMgr:
                MockMgr.return_value.get_history = AsyncMock(return_value=history)
                with patch("mcpgateway.services.semantic_search_service.get_semantic_search_service", return_value=mock_search_svc):
                    results = await svc.extract_context("user_a", mock_db, limit=5)

        mock_search_svc.search_tools.assert_called_once()
        call_args = mock_search_svc.search_tools.call_args
        assert "list files" in call_args[0][0]
        assert "search tool" in call_args[0][0]
        assert results == search_results

    @pytest.mark.asyncio
    async def test_only_last_n_messages_used(self, svc, mock_db):
        """Only the last n messages (default 10) are included."""
        history = [{"content": f"msg {i}"} for i in range(20)]
        mock_search_svc = MagicMock()
        mock_search_svc.search_tools = AsyncMock(return_value=[])

        with patch("mcpgateway.services.conversation_context_service.get_redis_client", new_callable=AsyncMock, return_value=None):
            with patch("mcpgateway.services.conversation_context_service.ChatHistoryManager") as MockMgr:
                MockMgr.return_value.get_history = AsyncMock(return_value=history)
                with patch("mcpgateway.services.semantic_search_service.get_semantic_search_service", return_value=mock_search_svc):
                    await svc.extract_context("user_b", mock_db, n=3)

        combined = mock_search_svc.search_tools.call_args[0][0]
        # Should contain last 3 messages (17,18,19)
        assert "msg 19" in combined
        assert "msg 0" not in combined

    @pytest.mark.asyncio
    async def test_semantic_search_failure_returns_empty(self, svc, mock_db):
        """If semantic search raises, return []."""
        with patch("mcpgateway.services.conversation_context_service.get_redis_client", new_callable=AsyncMock, return_value=None):
            with patch("mcpgateway.services.conversation_context_service.ChatHistoryManager") as MockMgr:
                MockMgr.return_value.get_history = AsyncMock(return_value=[{"content": "find tool"}])
                with patch("mcpgateway.services.semantic_search_service.get_semantic_search_service") as mock_getter:
                    mock_getter.return_value.search_tools = AsyncMock(side_effect=Exception("embed fail"))
                    results = await svc.extract_context("user_c", mock_db)

        assert results == []

    @pytest.mark.asyncio
    async def test_results_written_to_in_memory_cache(self, svc, mock_db):
        """Successful search results are stored in the in-memory cache."""
        search_results = [ToolSearchResult(tool_name="tool_x", description="d", similarity_score=0.6)]
        mock_search_svc = MagicMock()
        mock_search_svc.search_tools = AsyncMock(return_value=search_results)

        with patch("mcpgateway.services.conversation_context_service.get_redis_client", new_callable=AsyncMock, return_value=None):
            with patch("mcpgateway.services.conversation_context_service.ChatHistoryManager") as MockMgr:
                MockMgr.return_value.get_history = AsyncMock(return_value=[{"content": "do something"}])
                with patch("mcpgateway.services.semantic_search_service.get_semantic_search_service", return_value=mock_search_svc):
                    await svc.extract_context("user_cache_write", mock_db)

        cache_key = "conv_context:user_cache_write:10:10"
        assert cache_key in svc._memory_cache
        _, cached = svc._memory_cache[cache_key]
        assert cached == search_results
