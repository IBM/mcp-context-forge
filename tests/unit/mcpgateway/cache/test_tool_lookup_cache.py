# -*- coding: utf-8 -*-
"""Tests for ToolLookupCache."""

# Third-Party
import pytest
from unittest.mock import AsyncMock

# First-Party
from mcpgateway.cache.tool_lookup_cache import ToolLookupCache


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
