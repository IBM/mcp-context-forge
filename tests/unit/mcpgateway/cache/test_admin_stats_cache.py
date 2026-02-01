# -*- coding: utf-8 -*-
"""Tests for AdminStatsCache."""

# Standard
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import orjson
import pytest

# First-Party
from mcpgateway.cache.admin_stats_cache import AdminStatsCache, CacheEntry


@pytest.mark.asyncio
async def test_admin_stats_cache_in_memory_paths(monkeypatch):
    cache = AdminStatsCache(enabled=True)
    monkeypatch.setattr(cache, "_get_redis_client", AsyncMock(return_value=None))

    await cache.set_system_stats({"tools": 1})
    assert await cache.get_system_stats() == {"tools": 1}

    await cache.set_observability_stats({"spans": 2}, hours=12)
    assert await cache.get_observability_stats(12) == {"spans": 2}

    await cache.set_users_list(["u1"], limit=5, offset=0)
    assert await cache.get_users_list(limit=5, offset=0) == ["u1"]

    await cache.set_teams_list(["t1"], limit=5, offset=0)
    assert await cache.get_teams_list(limit=5, offset=0) == ["t1"]

    await cache.set_tags(["tag1"], entity_types_hash="hash")
    assert await cache.get_tags("hash") == ["tag1"]

    await cache.set_plugin_stats({"total": 1})
    assert await cache.get_plugin_stats() == {"total": 1}

    await cache.set_performance_history({"series": [1]}, cache_key_suffix="p1")
    assert await cache.get_performance_history("p1") == {"series": [1]}

    await cache.invalidate_system_stats()
    assert await cache.get_system_stats() is None

    await cache.invalidate_observability_stats()
    assert await cache.get_observability_stats(12) is None

    await cache.invalidate_users()
    assert await cache.get_users_list(limit=5, offset=0) is None

    await cache.invalidate_teams()
    assert await cache.get_teams_list(limit=5, offset=0) is None

    await cache.invalidate_tags()
    assert await cache.get_tags("hash") is None

    await cache.invalidate_plugins()
    assert await cache.get_plugin_stats() is None

    await cache.invalidate_performance()
    assert await cache.get_performance_history("p1") is None


@pytest.mark.asyncio
async def test_admin_stats_cache_redis_hit(monkeypatch):
    cache = AdminStatsCache(enabled=True)
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=b'{"count": 5}')
    redis.setex = AsyncMock(return_value=True)
    monkeypatch.setattr(cache, "_get_redis_client", AsyncMock(return_value=redis))

    assert await cache.get_system_stats() == {"count": 5}
    await cache.set_system_stats({"count": 6})

    stats = cache.stats()
    assert stats["redis_hit_count"] == 1


def test_admin_stats_cache_key_and_stats():
    cache = AdminStatsCache(enabled=True)
    assert cache._get_redis_key("system", "comprehensive").endswith("admin:system:comprehensive")
    stats = cache.stats()
    assert stats["enabled"] is True
    assert stats["hit_count"] == 0


@pytest.mark.asyncio
async def test_admin_stats_cache_disabled_returns_none(monkeypatch):
    cache = AdminStatsCache(enabled=False)
    monkeypatch.setattr(cache, "_get_redis_client", AsyncMock(return_value=None))
    assert await cache.get_system_stats() is None
    assert await cache.get_observability_stats(1) is None


@pytest.mark.asyncio
async def test_admin_stats_cache_redis_miss_increments(monkeypatch):
    cache = AdminStatsCache(enabled=True)
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    monkeypatch.setattr(cache, "_get_redis_client", AsyncMock(return_value=redis))

    assert await cache.get_system_stats() is None
    stats = cache.stats()
    assert stats["redis_miss_count"] == 1


@pytest.mark.asyncio
async def test_admin_stats_cache_redis_client_exception(monkeypatch):
    cache = AdminStatsCache(enabled=True)

    async def _raise():
        raise RuntimeError("redis down")

    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", _raise)
    client = await cache._get_redis_client()
    assert client is None
    assert cache._redis_checked is True


@pytest.mark.asyncio
async def test_admin_stats_cache_redis_available_sets_flags(monkeypatch):
    cache = AdminStatsCache(enabled=True)
    fake_redis = MagicMock()

    async def _get_client():
        return fake_redis

    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", _get_client)
    client = await cache._get_redis_client()
    assert client is fake_redis
    assert cache._redis_checked is True
    assert cache._redis_available is True


@pytest.mark.asyncio
async def test_admin_stats_cache_redis_hits(monkeypatch):
    cache = AdminStatsCache(enabled=True)

    data_map = {
        cache._get_redis_key("system", "comprehensive"): orjson.dumps({"tools": 1}),
        cache._get_redis_key("observability", "12"): orjson.dumps({"spans": 2}),
        cache._get_redis_key("users", "5:0"): orjson.dumps(["u1"]),
        cache._get_redis_key("teams", "5:0"): orjson.dumps(["t1"]),
        cache._get_redis_key("tags", "hash"): orjson.dumps(["tag1"]),
        cache._get_redis_key("plugins", "stats"): orjson.dumps({"total": 1}),
        cache._get_redis_key("performance", "p1"): orjson.dumps({"series": [1]}),
    }

    class FakeRedis:
        async def get(self, key):
            return data_map.get(key)

        async def setex(self, *_args, **_kwargs):
            return True

    monkeypatch.setattr(cache, "_get_redis_client", AsyncMock(return_value=FakeRedis()))

    assert await cache.get_system_stats() == {"tools": 1}
    assert await cache.get_observability_stats(12) == {"spans": 2}
    assert await cache.get_users_list(limit=5, offset=0) == ["u1"]
    assert await cache.get_teams_list(limit=5, offset=0) == ["t1"]
    assert await cache.get_tags("hash") == ["tag1"]
    assert await cache.get_plugin_stats() == {"total": 1}
    assert await cache.get_performance_history("p1") == {"series": [1]}


@pytest.mark.asyncio
async def test_admin_stats_cache_redis_errors_fallback_to_memory(monkeypatch):
    cache = AdminStatsCache(enabled=True)
    cache_key = cache._get_redis_key("system", "comprehensive")
    cache._cache[cache_key] = CacheEntry(value={"tools": 9}, expiry=9999999999)

    class FakeRedis:
        async def get(self, _key):
            raise RuntimeError("boom")

    monkeypatch.setattr(cache, "_get_redis_client", AsyncMock(return_value=FakeRedis()))

    assert await cache.get_system_stats() == {"tools": 9}


@pytest.mark.asyncio
async def test_admin_stats_cache_redis_set_failure_still_caches(monkeypatch):
    cache = AdminStatsCache(enabled=True)

    class FakeRedis:
        async def setex(self, *_args, **_kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr(cache, "_get_redis_client", AsyncMock(return_value=FakeRedis()))

    await cache.set_system_stats({"tools": 3})
    key = cache._get_redis_key("system", "comprehensive")
    assert key in cache._cache

    await cache.set_users_list(["u1"], limit=5, offset=0)
    users_key = cache._get_redis_key("users", "5:0")
    assert users_key in cache._cache


def test_admin_stats_cache_import_error_defaults(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "mcpgateway.config":
            raise ImportError("boom")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    cache = AdminStatsCache()
    assert cache._cache_prefix == "mcpgw:"
    assert cache._enabled is True


@pytest.mark.asyncio
async def test_admin_stats_cache_disabled_noops():
    cache = AdminStatsCache(enabled=False)

    assert await cache.get_system_stats() is None
    assert await cache.get_observability_stats(12) is None
    assert await cache.get_users_list(limit=5, offset=0) is None
    assert await cache.get_teams_list(limit=5, offset=0) is None
    assert await cache.get_tags("hash") is None
    assert await cache.get_plugin_stats() is None
    assert await cache.get_performance_history("p1") is None

    await cache.set_system_stats({"tools": 1})
    await cache.set_observability_stats({"spans": 2}, hours=12)
    await cache.set_users_list(["u1"], limit=5, offset=0)
    await cache.set_teams_list(["t1"], limit=5, offset=0)
    await cache.set_tags(["tag1"], entity_types_hash="hash")
    await cache.set_plugin_stats({"total": 1})
    await cache.set_performance_history({"series": [1]}, cache_key_suffix="p1")

    assert cache._cache == {}


@pytest.mark.asyncio
async def test_admin_stats_cache_redis_miss_per_method(monkeypatch):
    cache = AdminStatsCache(enabled=True)
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    monkeypatch.setattr(cache, "_get_redis_client", AsyncMock(return_value=redis))

    methods = [
        ("get_system_stats", ()),
        ("get_observability_stats", (12,)),
        ("get_users_list", (5, 0)),
        ("get_teams_list", (5, 0)),
        ("get_tags", ("hash",)),
        ("get_plugin_stats", ()),
        ("get_performance_history", ("p1",)),
    ]

    for name, args in methods:
        result = await getattr(cache, name)(*args)
        assert result is None

    assert cache.stats()["redis_miss_count"] == len(methods)


@pytest.mark.asyncio
async def test_admin_stats_cache_redis_get_exceptions(monkeypatch):
    cache = AdminStatsCache(enabled=True)

    class FakeRedis:
        async def get(self, _key):
            raise RuntimeError("boom")

    monkeypatch.setattr(cache, "_get_redis_client", AsyncMock(return_value=FakeRedis()))

    assert await cache.get_observability_stats(12) is None
    assert await cache.get_users_list(limit=5, offset=0) is None
    assert await cache.get_teams_list(limit=5, offset=0) is None
    assert await cache.get_tags("hash") is None
    assert await cache.get_plugin_stats() is None
    assert await cache.get_performance_history("p1") is None


@pytest.mark.asyncio
async def test_admin_stats_cache_redis_set_exceptions(monkeypatch):
    cache = AdminStatsCache(enabled=True)

    class FakeRedis:
        async def setex(self, *_args, **_kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr(cache, "_get_redis_client", AsyncMock(return_value=FakeRedis()))

    await cache.set_observability_stats({"spans": 2}, hours=12)
    await cache.set_teams_list(["t1"], limit=5, offset=0)
    await cache.set_tags(["tag1"], entity_types_hash="hash")
    await cache.set_plugin_stats({"total": 1})
    await cache.set_performance_history({"series": [1]}, cache_key_suffix="p1")


@pytest.mark.asyncio
async def test_admin_stats_cache_invalidate_prefix_redis_paths(monkeypatch):
    cache = AdminStatsCache(enabled=True)
    cache_key = cache._get_redis_key("system", "comprehensive")
    cache._cache[cache_key] = CacheEntry(value={"tools": 1}, expiry=9999999999)

    class FakeRedis:
        async def scan_iter(self, *_args, **_kwargs):
            for key in [b"mcpgw:admin:system:one"]:
                yield key

        async def delete(self, *_args, **_kwargs):
            return 1

        async def publish(self, *_args, **_kwargs):
            return 1

    monkeypatch.setattr(cache, "_get_redis_client", AsyncMock(return_value=FakeRedis()))
    await cache.invalidate_system_stats()


@pytest.mark.asyncio
async def test_admin_stats_cache_invalidate_prefix_redis_error(monkeypatch):
    cache = AdminStatsCache(enabled=True)

    class FakeRedis:
        async def scan_iter(self, *_args, **_kwargs):
            raise RuntimeError("boom")
            if False:
                yield None

    monkeypatch.setattr(cache, "_get_redis_client", AsyncMock(return_value=FakeRedis()))
    await cache.invalidate_observability_stats()
