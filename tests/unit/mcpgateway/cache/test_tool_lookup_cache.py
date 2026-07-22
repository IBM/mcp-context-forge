# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/cache/test_tool_lookup_cache.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for ToolLookupCache.
"""

# Standard
import builtins
import time
from unittest.mock import AsyncMock, call, MagicMock

# Third-Party
import orjson
import pytest

# First-Party
from mcpgateway.cache.tool_lookup_cache import CacheEntry, ToolLookupCache


@pytest.fixture
def tool_lookup_cache_instance():
    cache = ToolLookupCache()
    cache._enabled = True
    cache._l2_enabled = False
    cache._cache.clear()
    cache._l1_maxsize = 10
    cache.reset_stats()
    return cache


@pytest.mark.asyncio
async def test_tool_lookup_cache_set_get_l1(tool_lookup_cache_instance):
    payload = {"status": "active", "tool": {"name": "tool-a"}}
    await tool_lookup_cache_instance.set("tool-a", payload)

    assert await tool_lookup_cache_instance.get("tool-a") == payload
    stats = tool_lookup_cache_instance.stats()
    assert stats["l1_hit_count"] == 1


@pytest.mark.asyncio
async def test_tool_lookup_cache_isolates_server_scopes(tool_lookup_cache_instance):
    global_payload = {"status": "active", "tool": {"name": "global-tool"}}
    server_one_payload = {"status": "active", "tool": {"name": "server-one-tool"}}
    server_two_payload = {"status": "active", "tool": {"name": "server-two-tool"}}

    await tool_lookup_cache_instance.set("shared-name", global_payload)
    await tool_lookup_cache_instance.set("shared-name", server_one_payload, gateway_id="gw-1", server_id="srv-1")
    await tool_lookup_cache_instance.set("shared-name", server_two_payload, gateway_id="gw-2", server_id="srv-2")

    assert await tool_lookup_cache_instance.get("shared-name") == global_payload
    assert await tool_lookup_cache_instance.get("shared-name", server_id="srv-1") == server_one_payload
    assert await tool_lookup_cache_instance.get("shared-name", server_id="srv-2") == server_two_payload


@pytest.mark.asyncio
async def test_tool_lookup_cache_invalidate_server(tool_lookup_cache_instance):
    global_payload = {"status": "active", "tool": {"name": "global-tool"}}
    server_one_payload = {"status": "active", "tool": {"name": "server-one-tool"}}
    server_two_payload = {"status": "active", "tool": {"name": "server-two-tool"}}

    await tool_lookup_cache_instance.set("shared-name", global_payload)
    await tool_lookup_cache_instance.set("shared-name", server_one_payload, gateway_id="gw-1", server_id="srv-1")
    await tool_lookup_cache_instance.set("shared-name", server_two_payload, gateway_id="gw-2", server_id="srv-2")

    await tool_lookup_cache_instance.invalidate_server("srv-1")

    assert await tool_lookup_cache_instance.get("shared-name") == global_payload
    assert await tool_lookup_cache_instance.get("shared-name", server_id="srv-1") is None
    assert await tool_lookup_cache_instance.get("shared-name", server_id="srv-2") == server_two_payload


@pytest.mark.asyncio
async def test_tool_lookup_cache_local_tool_invalidation_clears_scoped_entries(tool_lookup_cache_instance):
    scoped_payload = {"status": "active", "tool": {"id": "local-tool", "name": "local-tool", "gateway_id": None}}

    await tool_lookup_cache_instance.set("local-tool", scoped_payload, server_id="srv-1")
    await tool_lookup_cache_instance.set("local-alias", scoped_payload, server_id="srv-2")

    await tool_lookup_cache_instance.invalidate("local-tool")

    assert await tool_lookup_cache_instance.get("local-tool", server_id="srv-1") is None
    assert await tool_lookup_cache_instance.get("local-alias", server_id="srv-2") is None


@pytest.mark.asyncio
async def test_tool_lookup_cache_lru_eviction(tool_lookup_cache_instance):
    tool_lookup_cache_instance._l1_maxsize = 1
    payload_a = {"status": "active", "tool": {"name": "tool-a"}}
    payload_b = {"status": "active", "tool": {"name": "tool-b"}}

    await tool_lookup_cache_instance.set("tool-a", payload_a)
    await tool_lookup_cache_instance.set("tool-b", payload_b)

    assert await tool_lookup_cache_instance.get("tool-a") is None
    assert await tool_lookup_cache_instance.get("tool-b") == payload_b


@pytest.mark.asyncio
async def test_tool_lookup_cache_negative_entry(tool_lookup_cache_instance):
    await tool_lookup_cache_instance.set_negative("tool-missing", "missing")

    payload = await tool_lookup_cache_instance.get("tool-missing")
    assert payload["status"] == "missing"


@pytest.mark.asyncio
async def test_tool_lookup_cache_invalidate_gateway(tool_lookup_cache_instance):
    payload_g1 = {"status": "active", "tool": {"gateway_id": "gw-1"}}
    payload_g2 = {"status": "active", "tool": {"gateway_id": "gw-2"}}

    await tool_lookup_cache_instance.set("tool-a", payload_g1)
    await tool_lookup_cache_instance.set("tool-b", payload_g2)

    await tool_lookup_cache_instance.invalidate_gateway("gw-1")

    assert await tool_lookup_cache_instance.get("tool-a") is None
    assert await tool_lookup_cache_instance.get("tool-b") == payload_g2


@pytest.mark.asyncio
async def test_tool_lookup_cache_l2_unavailable(tool_lookup_cache_instance):
    tool_lookup_cache_instance._l2_enabled = True
    tool_lookup_cache_instance._get_redis_client = AsyncMock(return_value=None)

    assert await tool_lookup_cache_instance.get("tool-missing") is None

    payload = {"status": "active", "tool": {"name": "tool-a"}}
    await tool_lookup_cache_instance.set("tool-a", payload)
    assert await tool_lookup_cache_instance.get("tool-a") == payload


def test_tool_lookup_cache_reset_stats(tool_lookup_cache_instance):
    tool_lookup_cache_instance._l1_hit_count = 3
    tool_lookup_cache_instance._l1_miss_count = 2
    tool_lookup_cache_instance._l2_hit_count = 1
    tool_lookup_cache_instance._l2_miss_count = 4

    tool_lookup_cache_instance.reset_stats()
    stats = tool_lookup_cache_instance.stats()
    assert stats["l1_hit_count"] == 0
    assert stats["l1_miss_count"] == 0
    assert stats["l2_hit_count"] == 0
    assert stats["l2_miss_count"] == 0


@pytest.mark.asyncio
async def test_tool_lookup_cache_l2_hit(tool_lookup_cache_instance):
    tool_lookup_cache_instance._l2_enabled = True
    payload = {"status": "active", "tool": {"name": "tool-x"}}

    redis = MagicMock()
    redis.get = AsyncMock(return_value=orjson.dumps(payload))
    tool_lookup_cache_instance._get_redis_client = AsyncMock(return_value=redis)

    assert await tool_lookup_cache_instance.get("tool-x") == payload
    stats = tool_lookup_cache_instance.stats()
    assert stats["l2_hit_count"] == 1


@pytest.mark.asyncio
async def test_tool_lookup_cache_set_with_gateway_and_server_updates_redis(tool_lookup_cache_instance):
    tool_lookup_cache_instance._l2_enabled = True
    payload = {"status": "active", "tool": {"name": "tool-a"}}

    redis = MagicMock()
    redis.setex = AsyncMock()
    redis.sadd = AsyncMock()
    redis.expire = AsyncMock()
    tool_lookup_cache_instance._get_redis_client = AsyncMock(return_value=redis)

    await tool_lookup_cache_instance.set("tool-a", payload, gateway_id="gw-1", server_id="srv-1")

    redis.setex.assert_awaited_once_with("mcpgw:tool_lookup:server:srv-1:tool-a", tool_lookup_cache_instance._ttl_seconds, orjson.dumps(payload))
    assert redis.sadd.await_args_list == [
        call("mcpgw:tool_lookup:gateway:gw-1", "server:srv-1:tool-a"),
        call("mcpgw:tool_lookup:server:srv-1", "server:srv-1:tool-a"),
        call("mcpgw:tool_lookup_index:scoped", "server:srv-1:tool-a"),
    ]
    assert redis.expire.await_count == 3


@pytest.mark.asyncio
async def test_tool_lookup_cache_set_redis_exception_is_swallowed(tool_lookup_cache_instance):
    tool_lookup_cache_instance._l2_enabled = True
    redis = MagicMock()
    redis.setex = AsyncMock(side_effect=RuntimeError("boom"))
    tool_lookup_cache_instance._get_redis_client = AsyncMock(return_value=redis)

    # Exception path is intentionally swallowed and logged.
    await tool_lookup_cache_instance.set("tool-a", {"status": "active"}, gateway_id="gw-1")


@pytest.mark.asyncio
async def test_tool_lookup_cache_invalidate_redis(tool_lookup_cache_instance):
    tool_lookup_cache_instance._l2_enabled = True
    redis = MagicMock()
    redis.smembers = AsyncMock(return_value={b"tool-a", b"server:srv-1:tool-a"})
    redis.delete = AsyncMock()
    redis.publish = AsyncMock()
    tool_lookup_cache_instance._get_redis_client = AsyncMock(return_value=redis)

    await tool_lookup_cache_instance.invalidate("tool-a", gateway_id="gw-1")
    assert redis.delete.called
    assert redis.publish.called


@pytest.mark.asyncio
async def test_tool_lookup_cache_invalidate_redis_exception_is_swallowed(tool_lookup_cache_instance):
    tool_lookup_cache_instance._l2_enabled = True
    redis = MagicMock()
    redis.smembers = AsyncMock(side_effect=RuntimeError("boom"))
    tool_lookup_cache_instance._get_redis_client = AsyncMock(return_value=redis)

    # Exception path is intentionally swallowed and logged.
    await tool_lookup_cache_instance.invalidate("tool-a", gateway_id="gw-1")


@pytest.mark.asyncio
async def test_tool_lookup_cache_invalidate_gateway_redis(tool_lookup_cache_instance):
    tool_lookup_cache_instance._l2_enabled = True
    redis = MagicMock()
    redis.smembers = AsyncMock(return_value={b"tool-a", b"tool-b"})
    redis.delete = AsyncMock()
    redis.publish = AsyncMock()
    tool_lookup_cache_instance._get_redis_client = AsyncMock(return_value=redis)

    await tool_lookup_cache_instance.invalidate_gateway("gw-1")
    assert redis.delete.called
    assert redis.publish.called


@pytest.mark.asyncio
async def test_tool_lookup_cache_invalidate_server_redis(tool_lookup_cache_instance):
    tool_lookup_cache_instance._l2_enabled = True
    redis = MagicMock()
    redis.smembers = AsyncMock(return_value={b"server:srv-1:tool-a", "server:srv-1:tool-b"})
    redis.delete = AsyncMock()
    redis.publish = AsyncMock()
    tool_lookup_cache_instance._get_redis_client = AsyncMock(return_value=redis)

    await tool_lookup_cache_instance.invalidate_server("srv-1")

    redis.smembers.assert_awaited_once_with("mcpgw:tool_lookup:server:srv-1")
    assert redis.delete.await_count == 2
    redis.publish.assert_awaited_once_with("mcpgw:cache:invalidate", "tool_lookup:server:srv-1")


@pytest.mark.asyncio
async def test_tool_lookup_cache_invalidate_all_scoped_redis(tool_lookup_cache_instance):
    tool_lookup_cache_instance._l2_enabled = True
    redis = MagicMock()
    redis.smembers = AsyncMock(return_value={b"server:srv-1:tool-a", "server:srv-2:tool-b"})
    redis.delete = AsyncMock()
    redis.publish = AsyncMock()
    tool_lookup_cache_instance._get_redis_client = AsyncMock(return_value=redis)

    await tool_lookup_cache_instance.invalidate_all_scoped()

    redis.smembers.assert_awaited_once_with("mcpgw:tool_lookup_index:scoped")
    assert redis.delete.await_count == 2
    redis.publish.assert_awaited_once_with("mcpgw:cache:invalidate", "tool_lookup:scoped")


def test_tool_lookup_cache_import_error_defaults(monkeypatch):
    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "mcpgateway.config":
            raise ImportError("boom")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    cache = ToolLookupCache()
    assert cache._cache_prefix == "mcpgw:"
    assert cache._l2_enabled is False


@pytest.mark.asyncio
async def test_tool_lookup_cache_l1_expired_entry(tool_lookup_cache_instance):
    payload = {"status": "active", "tool": {"name": "tool-a"}}
    tool_lookup_cache_instance._cache["tool-a"] = CacheEntry(value=payload, expiry=time.time() - 1)

    assert await tool_lookup_cache_instance.get("tool-a") is None
    assert "tool-a" not in tool_lookup_cache_instance._cache


@pytest.mark.asyncio
async def test_tool_lookup_cache_l2_miss(tool_lookup_cache_instance):
    tool_lookup_cache_instance._l2_enabled = True
    redis = MagicMock()
    redis.get = AsyncMock(return_value=None)
    tool_lookup_cache_instance._get_redis_client = AsyncMock(return_value=redis)

    assert await tool_lookup_cache_instance.get("tool-x") is None
    assert tool_lookup_cache_instance.stats()["l2_miss_count"] == 1


@pytest.mark.asyncio
async def test_tool_lookup_cache_l2_exception(tool_lookup_cache_instance):
    tool_lookup_cache_instance._l2_enabled = True
    redis = MagicMock()
    redis.get = AsyncMock(side_effect=RuntimeError("boom"))
    tool_lookup_cache_instance._get_redis_client = AsyncMock(return_value=redis)

    assert await tool_lookup_cache_instance.get("tool-x") is None


@pytest.mark.asyncio
async def test_tool_lookup_cache_get_redis_client_exception(monkeypatch):
    cache = ToolLookupCache()
    cache._l2_enabled = True

    async def _raise():
        raise RuntimeError("boom")

    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", _raise)

    assert await cache._get_redis_client() is None
    assert cache._redis_checked is True


@pytest.mark.asyncio
async def test_tool_lookup_cache_get_redis_client_available(monkeypatch):
    cache = ToolLookupCache()
    cache._l2_enabled = True
    fake_redis = AsyncMock()

    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=fake_redis))

    client = await cache._get_redis_client()
    assert client is fake_redis
    assert cache._redis_available is True


@pytest.mark.asyncio
async def test_tool_lookup_cache_disabled_noops():
    cache = ToolLookupCache()
    cache._enabled = False

    assert await cache.get("tool-x") is None
    await cache.set("tool-x", {"status": "inactive"})
    await cache.invalidate("tool-x")
    await cache.invalidate_gateway("gw-1")
    await cache.invalidate_server("srv-1")
    await cache.invalidate_all_scoped()
    assert len(cache._cache) == 0


@pytest.mark.asyncio
async def test_tool_lookup_cache_set_overwrites_existing(tool_lookup_cache_instance):
    payload = {"status": "active", "tool": {"name": "tool-a"}}
    await tool_lookup_cache_instance.set("tool-a", payload)
    await tool_lookup_cache_instance.set("tool-a", payload)

    assert await tool_lookup_cache_instance.get("tool-a") == payload


@pytest.mark.asyncio
async def test_tool_lookup_cache_invalidate_gateway_redis_error(tool_lookup_cache_instance):
    tool_lookup_cache_instance._l2_enabled = True
    redis = MagicMock()
    redis.smembers = AsyncMock(side_effect=RuntimeError("boom"))
    tool_lookup_cache_instance._get_redis_client = AsyncMock(return_value=redis)

    await tool_lookup_cache_instance.invalidate_gateway("gw-1")


@pytest.mark.asyncio
async def test_tool_lookup_cache_invalidate_server_redis_error(tool_lookup_cache_instance):
    tool_lookup_cache_instance._l2_enabled = True
    redis = MagicMock()
    redis.smembers = AsyncMock(side_effect=RuntimeError("boom"))
    tool_lookup_cache_instance._get_redis_client = AsyncMock(return_value=redis)

    await tool_lookup_cache_instance.invalidate_server("srv-1")
