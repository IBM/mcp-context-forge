# -*- coding: utf-8 -*-
"""Tests for CacheInvalidationSubscriber.

This module tests the cross-worker cache invalidation via Redis pubsub.
The CacheInvalidationSubscriber listens for invalidation messages published
by other workers and clears local in-memory caches accordingly.

Regression test for: REST /tools list endpoint returns stale visibility data
after tool update in multi-worker deployments.
"""

# Standard
import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.cache.registry_cache import (
    CacheInvalidationSubscriber,
    get_cache_invalidation_subscriber,
)


@pytest.fixture
def cache_subscriber():
    """Create a fresh CacheInvalidationSubscriber instance."""
    subscriber = CacheInvalidationSubscriber()
    return subscriber


def create_mock_registry_cache(cache_data: dict) -> MagicMock:
    """Create a properly configured mock registry cache.

    Args:
        cache_data: Initial cache data dictionary

    Returns:
        MagicMock configured to behave like RegistryCache
    """
    mock = MagicMock()
    mock._cache = cache_data.copy()
    mock._lock = threading.Lock()
    # Configure _get_redis_key to return proper prefixes
    mock._get_redis_key = lambda key_type: f"{key_type}:"
    return mock


class TestCacheInvalidationSubscriber:
    """Tests for CacheInvalidationSubscriber."""

    def test_subscriber_initialization(self, cache_subscriber):
        """Test that subscriber initializes with correct defaults."""
        assert cache_subscriber._task is None
        assert cache_subscriber._stop_event is None
        assert cache_subscriber._pubsub is None
        assert cache_subscriber._channel == "mcpgw:cache:invalidate"
        assert cache_subscriber._started is False

    @pytest.mark.asyncio
    async def test_process_registry_tools_invalidation(self, cache_subscriber):
        """Test processing of registry:tools invalidation message."""
        mock_registry_cache = create_mock_registry_cache({
            "tools:hash1": {"data": "cached"},
            "prompts:hash2": {"data": "cached"},
        })

        with patch("mcpgateway.cache.registry_cache.get_registry_cache", return_value=mock_registry_cache):
            await cache_subscriber._process_invalidation("registry:tools")

            # Tools cache should be cleared, prompts should remain
            assert "tools:hash1" not in mock_registry_cache._cache
            assert "prompts:hash2" in mock_registry_cache._cache

    @pytest.mark.asyncio
    async def test_process_registry_prompts_invalidation(self, cache_subscriber):
        """Test processing of registry:prompts invalidation message."""
        mock_registry_cache = create_mock_registry_cache({
            "tools:hash1": {"data": "cached"},
            "prompts:hash2": {"data": "cached"},
        })

        with patch("mcpgateway.cache.registry_cache.get_registry_cache", return_value=mock_registry_cache):
            await cache_subscriber._process_invalidation("registry:prompts")

            # Prompts cache should be cleared, tools should remain
            assert "tools:hash1" in mock_registry_cache._cache
            assert "prompts:hash2" not in mock_registry_cache._cache

    @pytest.mark.asyncio
    async def test_process_registry_resources_invalidation(self, cache_subscriber):
        """Test processing of registry:resources invalidation message."""
        mock_registry_cache = create_mock_registry_cache({
            "resources:hash1": {"data": "cached"},
            "tools:hash2": {"data": "cached"},
        })

        with patch("mcpgateway.cache.registry_cache.get_registry_cache", return_value=mock_registry_cache):
            await cache_subscriber._process_invalidation("registry:resources")

            assert "resources:hash1" not in mock_registry_cache._cache
            assert "tools:hash2" in mock_registry_cache._cache

    @pytest.mark.asyncio
    async def test_process_tool_lookup_name_invalidation(self, cache_subscriber):
        """Test processing of tool_lookup:name invalidation message."""
        mock_tool_lookup = MagicMock()
        mock_tool_lookup._cache = {
            "tool-a": MagicMock(value={"status": "active"}),
            "tool-b": MagicMock(value={"status": "active"}),
        }
        mock_tool_lookup._lock = threading.Lock()

        with patch.dict("sys.modules", {"mcpgateway.cache.tool_lookup_cache": MagicMock(tool_lookup_cache=mock_tool_lookup)}):
            with patch("mcpgateway.cache.registry_cache.get_registry_cache"):
                await cache_subscriber._process_invalidation("tool_lookup:tool-a")

                # Specific tool should be cleared
                assert "tool-a" not in mock_tool_lookup._cache
                assert "tool-b" in mock_tool_lookup._cache

    @pytest.mark.asyncio
    async def test_process_tool_lookup_gateway_invalidation(self, cache_subscriber):
        """Test processing of tool_lookup:gateway:id invalidation message."""
        mock_tool_lookup = MagicMock()
        mock_tool_lookup._cache = {
            "tool-a": MagicMock(value={"status": "active", "tool": {"gateway_id": "gw-123"}}),
            "tool-b": MagicMock(value={"status": "active", "tool": {"gateway_id": "gw-456"}}),
        }
        mock_tool_lookup._lock = threading.Lock()

        with patch.dict("sys.modules", {"mcpgateway.cache.tool_lookup_cache": MagicMock(tool_lookup_cache=mock_tool_lookup)}):
            with patch("mcpgateway.cache.registry_cache.get_registry_cache"):
                await cache_subscriber._process_invalidation("tool_lookup:gateway:gw-123")

                # Tool with matching gateway should be cleared
                assert "tool-a" not in mock_tool_lookup._cache
                assert "tool-b" in mock_tool_lookup._cache

    @pytest.mark.asyncio
    async def test_process_admin_invalidation(self, cache_subscriber):
        """Test processing of admin:prefix invalidation message."""
        mock_admin_cache = MagicMock()
        mock_admin_cache._cache = {
            "admin:users:list": {"data": "cached"},
            "admin:teams:list": {"data": "cached"},
        }
        mock_admin_cache._lock = threading.Lock()
        mock_admin_cache._get_redis_key = lambda prefix: f"admin:{prefix}:"

        with patch.dict("sys.modules", {"mcpgateway.cache.admin_stats_cache": MagicMock(admin_stats_cache=mock_admin_cache)}):
            await cache_subscriber._process_invalidation("admin:users")

            # Admin users cache should be cleared
            assert "admin:users:list" not in mock_admin_cache._cache
            assert "admin:teams:list" in mock_admin_cache._cache

    @pytest.mark.asyncio
    async def test_process_unknown_message_format(self, cache_subscriber):
        """Test that unknown message formats are handled gracefully."""
        # Should not raise an exception
        await cache_subscriber._process_invalidation("unknown:format")
        await cache_subscriber._process_invalidation("")
        await cache_subscriber._process_invalidation("no-colon")

    @pytest.mark.asyncio
    async def test_start_without_redis(self, cache_subscriber):
        """Test that start handles missing Redis gracefully."""
        with patch("mcpgateway.utils.redis_client.get_redis_client", new=AsyncMock(return_value=None)):
            await cache_subscriber.start()
            # Should not crash, just log warning
            assert cache_subscriber._started is False

    @pytest.mark.asyncio
    async def test_stop_without_start(self, cache_subscriber):
        """Test that stop is safe to call without start."""
        await cache_subscriber.stop()
        # Should not raise an exception
        assert cache_subscriber._started is False

    def test_singleton_getter(self):
        """Test that get_cache_invalidation_subscriber returns singleton."""
        sub1 = get_cache_invalidation_subscriber()
        sub2 = get_cache_invalidation_subscriber()
        assert sub1 is sub2


class TestCrossWorkerCacheInvalidation:
    """Integration-style tests for cross-worker cache invalidation scenario.

    These tests verify the end-to-end behavior that when a tool's visibility
    is updated, the cache invalidation message is properly processed and
    local caches are cleared.
    """

    @pytest.mark.asyncio
    async def test_tool_visibility_update_clears_registry_cache(self):
        """Test that tool visibility update triggers registry cache invalidation.

        This is the main regression test for the bug where REST /tools list
        returned stale visibility data after tool update.
        """
        subscriber = CacheInvalidationSubscriber()

        mock_registry_cache = create_mock_registry_cache({
            "tools:default": [{"name": "my-tool", "visibility": "public"}],
            "tools:filtered": [{"name": "my-tool", "visibility": "public"}],
        })

        with patch("mcpgateway.cache.registry_cache.get_registry_cache", return_value=mock_registry_cache):
            # Simulate receiving invalidation message (as would happen from another worker)
            await subscriber._process_invalidation("registry:tools")

            # All tools caches should be cleared
            assert "tools:default" not in mock_registry_cache._cache
            assert "tools:filtered" not in mock_registry_cache._cache

    @pytest.mark.asyncio
    async def test_multiple_invalidation_messages(self):
        """Test handling of multiple rapid invalidation messages."""
        subscriber = CacheInvalidationSubscriber()

        mock_registry_cache = create_mock_registry_cache({
            "tools:h1": {"data": "1"},
            "tools:h2": {"data": "2"},
            "prompts:h1": {"data": "1"},
            "resources:h1": {"data": "1"},
        })

        with patch("mcpgateway.cache.registry_cache.get_registry_cache", return_value=mock_registry_cache):
            # Rapid-fire invalidations
            await asyncio.gather(
                subscriber._process_invalidation("registry:tools"),
                subscriber._process_invalidation("registry:prompts"),
                subscriber._process_invalidation("registry:resources"),
            )

            # All should be cleared
            assert len(mock_registry_cache._cache) == 0

    @pytest.mark.asyncio
    async def test_invalidation_message_parsing(self):
        """Test that different message formats are parsed correctly."""
        subscriber = CacheInvalidationSubscriber()

        mock_registry_cache = create_mock_registry_cache({})

        with patch("mcpgateway.cache.registry_cache.get_registry_cache", return_value=mock_registry_cache):
            # These should not raise exceptions
            await subscriber._process_invalidation("registry:tools")
            await subscriber._process_invalidation("registry:prompts")
            await subscriber._process_invalidation("registry:resources")
            await subscriber._process_invalidation("registry:agents")
            await subscriber._process_invalidation("tool_lookup:my-tool")
            await subscriber._process_invalidation("tool_lookup:gateway:gw-123")
            await subscriber._process_invalidation("admin:users")
            await subscriber._process_invalidation("admin:teams")
            # Unknown formats should be handled gracefully
            await subscriber._process_invalidation("unknown:type")
            await subscriber._process_invalidation("malformed")
            await subscriber._process_invalidation("")
