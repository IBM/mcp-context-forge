# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/cache/test_registry_cache.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for the registry cache module.
"""

# Standard
import asyncio
import builtins
import time
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import orjson
import pytest

# First-Party
from mcpgateway.cache.registry_cache import CacheEntry, CacheInvalidationSubscriber, RegistryCache, RegistryCacheConfig, _get_cleanup_timeout


class TestCacheEntry:
    """Tests for CacheEntry class."""

    def test_is_expired_false(self):
        """Test that entry is not expired when expiry is in the future."""
        entry = CacheEntry(value=["item1", "item2"], expiry=time.time() + 60)
        assert entry.is_expired() is False

    def test_is_expired_true(self):
        """Test that entry is expired when expiry is in the past."""
        entry = CacheEntry(value=["item"], expiry=time.time() - 1)
        assert entry.is_expired() is True

    def test_is_expired_boundary(self):
        """Test expiry at exact boundary."""
        now = time.time()
        entry = CacheEntry(value=[], expiry=now)
        # At exact boundary, time.time() >= expiry should be True
        assert entry.is_expired() is True


class TestRegistryCacheConfig:
    """Tests for RegistryCacheConfig class."""

    def test_default_values(self):
        """Test default configuration values."""
        config = RegistryCacheConfig()
        assert config.enabled is True
        assert config.tools_ttl == 20
        assert config.prompts_ttl == 15
        assert config.resources_ttl == 15
        assert config.agents_ttl == 20
        assert config.servers_ttl == 20
        assert config.gateways_ttl == 20
        assert config.catalog_ttl == 300

    def test_custom_values(self):
        """Test custom configuration values."""
        config = RegistryCacheConfig(
            enabled=False,
            tools_ttl=30,
            prompts_ttl=25,
        )
        assert config.enabled is False
        assert config.tools_ttl == 30
        assert config.prompts_ttl == 25


class TestRegistryCache:
    """Tests for RegistryCache class."""

    def test_initialization(self):
        """Test cache initialization."""
        cache = RegistryCache()
        assert cache._enabled is True
        assert cache._hit_count == 0
        assert cache._miss_count == 0

    def test_stats(self):
        """Test cache statistics."""
        cache = RegistryCache()
        stats = cache.stats()
        assert stats["hit_count"] == 0
        assert stats["miss_count"] == 0
        assert stats["hit_rate"] == 0.0

    def test_get_redis_key(self):
        """Test Redis key generation."""
        cache = RegistryCache()
        key = cache._get_redis_key("tools", "abc123")
        assert "registry:tools:abc123" in key

    def test_get_redis_key_no_hash(self):
        """Test Redis key generation without hash."""
        cache = RegistryCache()
        key = cache._get_redis_key("prompts", "")
        assert "registry:prompts" in key

    def test_hash_filters(self):
        """Test filters hash computation."""
        cache = RegistryCache()
        hash1 = cache.hash_filters(include_inactive=True, team_id="team1")
        hash2 = cache.hash_filters(include_inactive=True, team_id="team1")
        hash3 = cache.hash_filters(include_inactive=False, team_id="team1")

        assert hash1 == hash2
        assert hash1 != hash3

    def test_hash_filters_empty(self):
        """Test filters hash with no filters still returns a hash."""
        cache = RegistryCache()
        hash_empty = cache.hash_filters()
        # Empty kwargs still generates a hash (of empty dict)
        assert len(hash_empty) == 32  # MD5 hash length

    @pytest.mark.asyncio
    async def test_get_disabled(self):
        """Test get when cache is disabled."""
        cache = RegistryCache()
        cache._enabled = False
        result = await cache.get("tools")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_miss(self):
        """Test get cache miss."""
        cache = RegistryCache()
        result = await cache.get("tools")
        assert result is None
        assert cache._miss_count == 1

    @pytest.mark.asyncio
    async def test_set_and_get(self):
        """Test setting and getting from cache."""
        cache = RegistryCache()
        tools_data = [{"id": "1", "name": "tool1"}, {"id": "2", "name": "tool2"}]

        await cache.set("tools", tools_data)
        result = await cache.get("tools")

        assert result == tools_data
        assert cache._hit_count == 1

    @pytest.mark.asyncio
    async def test_get_redis_hit_and_miss(self):
        cache = RegistryCache()
        redis = MagicMock()
        redis.get = AsyncMock(return_value=orjson.dumps([{"id": "1"}]))
        cache._get_redis_client = AsyncMock(return_value=redis)

        result = await cache.get("tools")
        assert result == [{"id": "1"}]
        assert cache._redis_hit_count == 1

        redis.get = AsyncMock(return_value=None)
        result = await cache.get("tools")
        assert result is None
        assert cache._redis_miss_count == 1

    @pytest.mark.asyncio
    async def test_set_redis_failure_still_caches(self):
        cache = RegistryCache()
        redis = MagicMock()
        redis.setex = AsyncMock(side_effect=RuntimeError("boom"))
        cache._get_redis_client = AsyncMock(return_value=redis)

        data = [{"id": "1", "name": "tool1"}]
        await cache.set("tools", data)
        assert await cache.get("tools") == data

    @pytest.mark.asyncio
    async def test_invalidate_redis_scan_iter(self):
        cache = RegistryCache()
        redis = MagicMock()

        async def _scan_iter(*_args, **_kwargs):
            for key in [b"mcpgw:registry:tools:one", b"mcpgw:registry:tools:two"]:
                yield key

        redis.scan_iter = _scan_iter
        redis.delete = AsyncMock()
        redis.publish = AsyncMock()
        cache._get_redis_client = AsyncMock(return_value=redis)

        await cache.invalidate("tools")
        assert redis.delete.called
        assert redis.publish.called

    @pytest.mark.asyncio
    async def test_invalidate_tools(self):
        """Test tools cache invalidation."""
        cache = RegistryCache()
        tools_data = [{"id": "1", "name": "tool1"}]

        await cache.set("tools", tools_data)
        await cache.invalidate_tools()
        result = await cache.get("tools")

        assert result is None

    @pytest.mark.asyncio
    async def test_invalidate_prompts(self):
        """Test prompts cache invalidation."""
        cache = RegistryCache()
        prompts_data = [{"id": "1", "name": "prompt1"}]

        await cache.set("prompts", prompts_data)
        await cache.invalidate_prompts()
        result = await cache.get("prompts")

        assert result is None

    @pytest.mark.asyncio
    async def test_invalidate_resources(self):
        """Test resources cache invalidation."""
        cache = RegistryCache()
        resources_data = [{"id": "1", "name": "resource1"}]

        await cache.set("resources", resources_data)
        await cache.invalidate_resources()
        result = await cache.get("resources")

        assert result is None

    @pytest.mark.asyncio
    async def test_invalidate_agents(self):
        """Test agents cache invalidation."""
        cache = RegistryCache()
        agents_data = [{"id": "1", "name": "agent1"}]

        await cache.set("agents", agents_data)
        await cache.invalidate_agents()
        result = await cache.get("agents")

        assert result is None

    @pytest.mark.asyncio
    async def test_invalidate_servers(self):
        """Test servers cache invalidation."""
        cache = RegistryCache()
        servers_data = [{"id": "1", "name": "server1"}]

        await cache.set("servers", servers_data)
        await cache.invalidate_servers()
        result = await cache.get("servers")

        assert result is None

    @pytest.mark.asyncio
    async def test_invalidate_gateways(self):
        """Test gateways cache invalidation."""
        cache = RegistryCache()
        gateways_data = [{"id": "1", "name": "gateway1"}]

        await cache.set("gateways", gateways_data)
        await cache.invalidate_gateways()
        result = await cache.get("gateways")

        assert result is None

    @pytest.mark.asyncio
    async def test_invalidate_catalog(self):
        """Test catalog cache invalidation."""
        cache = RegistryCache()
        catalog_data = [{"id": "1", "name": "catalog1"}]

        await cache.set("catalog", catalog_data)
        await cache.invalidate_catalog()
        result = await cache.get("catalog")

        assert result is None

    def test_invalidate_all(self):
        """Test clearing all caches."""
        cache = RegistryCache()

        # Add entries directly to in-memory cache
        cache._cache["test1"] = CacheEntry(value=[1, 2, 3], expiry=time.time() + 60)
        cache._cache["test2"] = CacheEntry(value=[4, 5, 6], expiry=time.time() + 60)

        # Clear all
        cache.invalidate_all()

        # Verify all cleared
        assert len(cache._cache) == 0

    @pytest.mark.asyncio
    async def test_cache_expiry(self):
        """Test that cache entries expire correctly."""
        cache = RegistryCache()

        # Set with short TTL
        await cache.set("tools", [{"id": "1"}], ttl=1)

        # Should hit cache immediately
        result = await cache.get("tools")
        assert result == [{"id": "1"}]

        # Wait for expiry
        import asyncio

        await asyncio.sleep(1.1)

        # Should miss cache after expiry
        result = await cache.get("tools")
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_with_filters(self):
        """Test caching with different filter combinations."""
        cache = RegistryCache()

        # Set with different filter hashes
        hash1 = cache.hash_filters(include_inactive=False)
        hash2 = cache.hash_filters(include_inactive=True)

        await cache.set("tools", [{"id": "1"}], filters_hash=hash1)
        await cache.set("tools", [{"id": "1"}, {"id": "2"}], filters_hash=hash2)

        # Get with different filters
        result1 = await cache.get("tools", filters_hash=hash1)
        result2 = await cache.get("tools", filters_hash=hash2)

        assert result1 == [{"id": "1"}]
        assert result2 == [{"id": "1"}, {"id": "2"}]

    @pytest.mark.asyncio
    async def test_hit_rate_calculation(self):
        """Test hit rate calculation."""
        cache = RegistryCache()

        # Some misses
        await cache.get("tools")
        await cache.get("tools")

        # Add data and get hits
        await cache.set("tools", [{"id": "1"}])
        await cache.get("tools")
        await cache.get("tools")

        stats = cache.stats()
        assert stats["miss_count"] == 2
        assert stats["hit_count"] == 2
        assert stats["hit_rate"] == 0.5

    def test_reset_stats(self):
        """Test resetting cache statistics."""
        cache = RegistryCache()
        cache._hit_count = 10
        cache._miss_count = 5

        cache.reset_stats()

        assert cache._hit_count == 0
        assert cache._miss_count == 0

    def test_get_cleanup_timeout_import_error(self, monkeypatch):
        real_import = builtins.__import__

        def _fake_import(name, *args, **kwargs):
            if name == "mcpgateway.config":
                raise ImportError("boom")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _fake_import)

        assert _get_cleanup_timeout() == 5.0

    def test_import_error_defaults(self, monkeypatch):
        real_import = builtins.__import__

        def _fake_import(name, *args, **kwargs):
            if name == "mcpgateway.config":
                raise ImportError("boom")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _fake_import)

        config = RegistryCacheConfig(
            enabled=False,
            tools_ttl=1,
            prompts_ttl=2,
            resources_ttl=3,
            agents_ttl=4,
            servers_ttl=5,
            gateways_ttl=6,
            catalog_ttl=7,
        )
        cache = RegistryCache(config=config)
        assert cache._enabled is False
        assert cache._tools_ttl == 1
        assert cache._cache_prefix == "mcpgw:"

    @pytest.mark.asyncio
    async def test_get_redis_client_available(self, monkeypatch):
        cache = RegistryCache()
        fake_redis = MagicMock()
        monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=fake_redis))

        client = await cache._get_redis_client()
        assert client is fake_redis
        assert cache._redis_available is True

    @pytest.mark.asyncio
    async def test_get_redis_client_exception(self, monkeypatch):
        cache = RegistryCache()

        async def _raise():
            raise RuntimeError("boom")

        monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", _raise)
        client = await cache._get_redis_client()
        assert client is None
        assert cache._redis_checked is True

    @pytest.mark.asyncio
    async def test_set_disabled_noop(self):
        cache = RegistryCache()
        cache._enabled = False
        await cache.set("tools", [{"id": "1"}])
        assert cache._cache == {}

    @pytest.mark.asyncio
    async def test_invalidate_redis_error(self):
        cache = RegistryCache()
        redis = MagicMock()

        async def _scan_iter(*_args, **_kwargs):
            raise RuntimeError("boom")
            if False:
                yield None

        redis.scan_iter = _scan_iter
        cache._get_redis_client = AsyncMock(return_value=redis)

        await cache.invalidate("tools")
