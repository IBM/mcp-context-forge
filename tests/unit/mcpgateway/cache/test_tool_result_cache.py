# -*- coding: utf-8 -*-
"""Tests for the opt-in tool invocation result cache."""

# Standard
import asyncio
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import orjson
import pytest

# First-Party
from mcpgateway.cache.tool_result_cache import (
    build_result_cache_key,
    RESULT_CACHE_META_KEY,
    resolve_result_cache_policy,
    ToolResultCache,
    with_result_cache_metadata,
)
from mcpgateway.common.models import TextContent, ToolResult


def _enabled_policy(**overrides):
    params = {
        "globally_enabled": True,
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "x-contextforge-result-cache": {"enabled": True, "ttlSeconds": 30},
        },
        "integration_type": "gRPC",
        "request_type": "SSE",
        "source_operation": None,
        "meta_data": None,
        "has_tool_plugins": False,
        "default_ttl_seconds": 60,
        "max_ttl_seconds": 3600,
    }
    params.update(overrides)
    return resolve_result_cache_policy(**params)


def _new_cache(*, max_entries: int = 10, max_l1_bytes: int = 67_108_864, max_entry_bytes: int = 1_048_576) -> ToolResultCache:
    cache = ToolResultCache()
    cache._enabled = True  # pylint: disable=protected-access
    cache._l2_enabled = False  # pylint: disable=protected-access
    cache._l1_max_entries = max_entries  # pylint: disable=protected-access
    cache._l1_max_bytes = max_l1_bytes  # pylint: disable=protected-access
    cache._max_entry_bytes = max_entry_bytes  # pylint: disable=protected-access
    cache.invalidate_all_local()
    cache.reset_stats()
    return cache


def test_policy_requires_explicit_safe_opt_in():
    assert _enabled_policy().enabled is True
    assert _enabled_policy(globally_enabled=False).reason == "globally-disabled"
    assert _enabled_policy(annotations={"readOnlyHint": True}).reason == "not-opted-in"
    assert _enabled_policy(annotations={"x-contextforge-result-cache": {"enabled": True}}).reason == "not-read-only"
    assert _enabled_policy(has_tool_plugins=True).reason == "tool-plugins-active"
    assert _enabled_policy(annotations={"readOnlyHint": True, "x-contextforge-result-cache": {"enabled": True, "ttlSeconds": 9999}}, max_ttl_seconds=120).ttl_seconds == 120
    assert _enabled_policy(annotations={"readOnlyHint": True, "x-contextforge-result-cache": {"enabled": True, "ttlSeconds": 0}}).reason == "invalid-ttl"


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"integration_type": "REST", "request_type": "POST"}, "rest-write"),
        ({"integration_type": "SQL", "source_operation": "update"}, "sql-write"),
        ({"annotations": {"readOnlyHint": True, "x-contextforge-result-cache": {"enabled": True}, "x-grpc-server-streaming": True}}, "streaming"),
        ({"meta_data": {"grpc_stream_callback": lambda _item: None}}, "streaming"),
    ],
)
def test_policy_rejects_write_and_streaming_calls(overrides, reason):
    assert _enabled_policy(**overrides).reason == reason


def test_key_is_stable_but_principal_and_semantic_headers_are_isolated():
    base = {
        "tool_id": "tool-1",
        "tool_version": 2,
        "arguments": {"b": 2, "a": 1},
        "app_user_email": None,
        "user_email": "alice@example.com",
        "token_teams": ["team-2", "team-1"],
        "server_id": "server-1",
        "request_headers": {"Accept-Language": "en", "X-Correlation-ID": "one"},
        "meta_data": {"traceparent": "one"},
        "runtime_config": {"target": "grpc://service"},
    }
    reordered = {**base, "arguments": {"a": 1, "b": 2}, "request_headers": {"x-correlation-id": "two", "accept-language": "en"}, "meta_data": {"traceparent": "two"}}
    assert build_result_cache_key(**base) == build_result_cache_key(**reordered)
    assert build_result_cache_key(**base) == build_result_cache_key(**{**base, "token_teams": ["team-1", "team-2"]})
    assert build_result_cache_key(**base) != build_result_cache_key(**{**base, "user_email": "bob@example.com"})
    assert build_result_cache_key(**{**base, "token_teams": None}) != build_result_cache_key(**{**base, "token_teams": []})
    assert build_result_cache_key(**base) != build_result_cache_key(**{**base, "request_headers": {"Accept-Language": "fr"}})
    assert build_result_cache_key(**base) != build_result_cache_key(**{**base, "meta_data": {"capture_grpc_call_metadata": True}})
    assert build_result_cache_key(**{**base, "arguments": {"bad": object()}}) is None


@pytest.mark.asyncio
async def test_set_get_expiry_and_metadata(monkeypatch):
    cache = _new_cache()
    now = 1000.0
    monkeypatch.setattr("mcpgateway.cache.tool_result_cache.time.time", lambda: now)
    result = ToolResult(content=[TextContent(type="text", text="answer")])

    assert await cache.set("key", result, ttl_seconds=10, tool_id="tool-1") is True
    hit = await cache.get("key")
    assert hit is not None
    assert hit.result.content[0].text == "answer"

    decorated = with_result_cache_metadata(hit.result, hit=True, source=hit.source, age_seconds=hit.age_seconds, ttl_seconds=10)
    assert decorated.meta[RESULT_CACHE_META_KEY]["hit"] is True
    assert result.meta is None

    now = 1011.0
    assert await cache.get("key") is None
    assert cache.stats()["l1_bytes"] == 0


@pytest.mark.asyncio
async def test_lru_bound_oversize_and_sql_table_invalidation():
    cache = _new_cache(max_entries=1, max_entry_bytes=256)
    small = ToolResult(content=[TextContent(type="text", text="ok")])
    large = ToolResult(content=[TextContent(type="text", text="x" * 1000)])

    await cache.set("one", small, ttl_seconds=30, tool_id="tool-1", sql_table_id="table-1")
    await cache.set("two", small, ttl_seconds=30, tool_id="tool-2", sql_table_id="table-2")
    assert await cache.get("one") is None
    assert await cache.get("two") is not None
    assert await cache.set("large", large, ttl_seconds=30, tool_id="tool-3") is False

    await cache.invalidate_sql_table("table-2")
    assert await cache.get("two") is None
    assert cache.stats()["evictions"] == 1
    assert cache.stats()["oversize_skips"] == 1


@pytest.mark.asyncio
async def test_l1_byte_limit_evicts_multiple_keys_until_payloads_fit():
    result = ToolResult(content=[TextContent(type="text", text="x" * 200)])
    payload_bytes = len(orjson.dumps(result.model_dump(by_alias=True, mode="json")))
    cache = _new_cache(max_entries=10, max_l1_bytes=payload_bytes * 2)

    await cache.set("one", result, ttl_seconds=30, tool_id="tool-1")
    await cache.set("two", result, ttl_seconds=30, tool_id="tool-2")
    await cache.set("three", result, ttl_seconds=30, tool_id="tool-3")

    assert await cache.get("one") is None
    assert await cache.get("two") is not None
    assert await cache.get("three") is not None
    stats = cache.stats()
    assert stats["l1_size"] == 2
    assert stats["l1_bytes"] == payload_bytes * 2
    assert stats["l1_max_bytes"] == payload_bytes * 2
    assert stats["evictions"] == 1


@pytest.mark.asyncio
async def test_l1_replacement_and_invalidation_keep_byte_accounting_exact():
    original = ToolResult(content=[TextContent(type="text", text="old")])
    replacement = ToolResult(content=[TextContent(type="text", text="replacement" * 20)])
    original_bytes = len(orjson.dumps(original.model_dump(by_alias=True, mode="json")))
    replacement_bytes = len(orjson.dumps(replacement.model_dump(by_alias=True, mode="json")))
    cache = _new_cache()

    await cache.set("same", original, ttl_seconds=30, tool_id="tool-1")
    await cache.set("same", replacement, ttl_seconds=30, tool_id="tool-1")
    await cache.set("other", original, ttl_seconds=30, tool_id="tool-1")

    stats = cache.stats()
    assert stats["l1_size"] == 2
    assert stats["l1_bytes"] == replacement_bytes + original_bytes
    assert stats["evictions"] == 0

    await cache.invalidate_tool("tool-1")
    stats = cache.stats()
    assert stats["l1_size"] == 0
    assert stats["l1_bytes"] == 0
    assert stats["invalidations"] == 2


@pytest.mark.asyncio
async def test_sql_dependency_invalidation_covers_included_tables():
    cache = _new_cache()
    result = ToolResult(content=[TextContent(type="text", text="joined")])

    await cache.set("joined", result, ttl_seconds=30, tool_id="tool-1", sql_table_ids=["orders", "customers"])
    assert await cache.get("joined") is not None

    await cache.invalidate_sql_table("customers")
    assert await cache.get("joined") is None


@pytest.mark.asyncio
async def test_sql_generation_rejects_fill_started_before_invalidation():
    cache = _new_cache()
    result = ToolResult(content=[TextContent(type="text", text="stale")])
    generations = cache.snapshot_sql_generations(["orders"])

    await cache.invalidate_sql_table("orders")

    assert (
        await cache.set(
            "old-generation",
            result,
            ttl_seconds=30,
            tool_id="tool-1",
            sql_table_ids=["orders"],
            expected_sql_generations=generations,
        )
        is False
    )
    assert await cache.get("old-generation") is None


@pytest.mark.asyncio
async def test_sql_generation_suffix_changes_after_invalidation():
    cache = _new_cache()

    before = await cache.sql_generation_key_suffix(["orders", "customers"])
    await cache.invalidate_sql_table("customers")
    after = await cache.sql_generation_key_suffix(["customers", "orders"])

    assert before != after


@pytest.mark.asyncio
async def test_sql_generation_read_failure_bypasses_cache_and_recovers():
    cache = _new_cache()
    cache._l2_enabled = True  # pylint: disable=protected-access
    redis = AsyncMock()
    redis.mget.side_effect = [RuntimeError("redis unavailable"), ["4", "7"]]
    cache._get_redis_client = AsyncMock(return_value=redis)  # type: ignore[method-assign]  # pylint: disable=protected-access

    failed_suffix = await cache.sql_generation_key_suffix(("orders", "customers"))
    recovered_suffix = await cache.sql_generation_key_suffix(("orders", "customers"))

    assert failed_suffix is None
    assert recovered_suffix is not None
    assert recovered_suffix.startswith(":sqlgen:")
    assert redis.mget.await_count == 2


@pytest.mark.asyncio
async def test_tool_and_gateway_invalidation_are_scoped():
    cache = _new_cache()
    result = ToolResult(content=[TextContent(type="text", text="ok")])
    await cache.set("tool-one", result, ttl_seconds=30, tool_id="tool-1", gateway_id="gw-1")
    await cache.set("tool-two", result, ttl_seconds=30, tool_id="tool-2", gateway_id="gw-1")
    await cache.set("tool-three", result, ttl_seconds=30, tool_id="tool-3", gateway_id="gw-2")

    await cache.invalidate_tool("tool-1")
    assert await cache.get("tool-one") is None
    assert await cache.get("tool-two") is not None

    await cache.invalidate_gateway("gw-1")
    assert await cache.get("tool-two") is None
    assert await cache.get("tool-three") is not None


@pytest.mark.asyncio
async def test_single_flight_allows_only_one_fill():
    cache = _new_cache()
    result = ToolResult(content=[TextContent(type="text", text="shared")])
    upstream_calls = 0

    async def invoke():
        nonlocal upstream_calls
        hit = await cache.get("same")
        if hit:
            return hit.result
        async with cache.single_flight("same"):
            hit = await cache.get("same")
            if hit:
                return hit.result
            upstream_calls += 1
            await asyncio.sleep(0)
            await cache.set("same", result, ttl_seconds=30, tool_id="tool-1")
            return result

    responses = await asyncio.gather(*(invoke() for _ in range(10)))
    assert upstream_calls == 1
    assert all(response.content[0].text == "shared" for response in responses)


@pytest.mark.asyncio
async def test_redis_l2_round_trip_and_index_invalidation():
    cache = _new_cache()
    cache._l2_enabled = True  # pylint: disable=protected-access
    redis = AsyncMock()
    cache._get_redis_client = AsyncMock(return_value=redis)  # type: ignore[method-assign]  # pylint: disable=protected-access
    result = ToolResult(content=[TextContent(type="text", text="shared")])

    assert await cache.set("redis-key", result, ttl_seconds=30, tool_id="tool-1", gateway_id="gw-1", sql_table_id="table-1") is True
    stored_envelope = redis.setex.await_args.args[2]
    assert redis.zadd.await_count == 3
    assert redis.zremrangebyscore.await_count == 3

    cache.invalidate_all_local()
    redis.get.return_value = stored_envelope
    hit = await cache.get("redis-key")
    assert hit is not None
    assert hit.source == "redis"
    assert hit.result.content[0].text == "shared"

    redis.zrangebyscore.return_value = [b"redis-key"]
    await cache.invalidate_tool("tool-1")
    redis.publish.assert_awaited_with("mcpgw:cache:invalidate", "tool_result:tool:tool-1")


@pytest.mark.asyncio
async def test_sql_batch_invalidation_waits_for_distributed_barrier():
    cache = _new_cache()
    result = ToolResult(content=[TextContent(type="text", text="shared")])
    await cache.set("orders-key", result, ttl_seconds=30, tool_id="tool-1", sql_table_id="orders")
    await cache.set("customers-key", result, ttl_seconds=30, tool_id="tool-2", sql_table_id="customers")

    cache._l2_enabled = True  # pylint: disable=protected-access
    redis = AsyncMock()
    redis.zrangebyscore.return_value = []
    started = asyncio.Event()
    release = asyncio.Event()
    incremented: list[str] = []

    async def blocked_increment(key: str) -> int:
        incremented.append(key)
        if len(incremented) == 2:
            started.set()
        await release.wait()
        return 1

    redis.incr.side_effect = blocked_increment
    cache._get_redis_client = AsyncMock(return_value=redis)  # type: ignore[method-assign]  # pylint: disable=protected-access

    invalidation = asyncio.create_task(cache.invalidate_sql_tables(("orders", "customers", "orders")))
    await started.wait()

    assert invalidation.done() is False
    assert not cache._cache  # pylint: disable=protected-access

    release.set()
    await invalidation

    assert set(incremented) == {
        cache._sql_generation_key("orders"),  # pylint: disable=protected-access
        cache._sql_generation_key("customers"),  # pylint: disable=protected-access
    }
    assert redis.zrangebyscore.await_count == 2
    assert redis.publish.await_count == 2


def test_sync_sql_batch_invalidation_uses_standalone_redis_barrier():
    cache = _new_cache()
    cache._l2_enabled = True  # pylint: disable=protected-access
    redis = MagicMock()
    redis.zrangebyscore.return_value = []
    cache._new_sync_redis_client = MagicMock(return_value=redis)  # type: ignore[method-assign]  # pylint: disable=protected-access

    cache.invalidate_sql_tables_sync(("orders", "customers", "orders"))

    incremented = {args.args[0] for args in redis.incr.call_args_list}
    assert incremented == {
        cache._sql_generation_key("orders"),  # pylint: disable=protected-access
        cache._sql_generation_key("customers"),  # pylint: disable=protected-access
    }
    assert redis.zrangebyscore.call_count == 2
    assert redis.publish.call_count == 2
    redis.close.assert_called_once_with()


@pytest.mark.asyncio
async def test_error_results_are_never_stored():
    cache = _new_cache()
    result = ToolResult(content=[TextContent(type="text", text="failed")], is_error=True)
    assert await cache.set("error", result, ttl_seconds=30, tool_id="tool-1") is False
    assert await cache.get("error") is None


@pytest.mark.asyncio
async def test_non_serializable_extension_metadata_bypasses_cache_without_breaking_instrumentation():
    cache = _new_cache()
    result = ToolResult(content=[TextContent(type="text", text="ok")], _meta={"extension": object()})

    assert await cache.set("unencodable", result, ttl_seconds=30, tool_id="tool-1") is False
    assert cache.stats()["encode_errors"] == 1

    decorated = with_result_cache_metadata(result, hit=False, source="upstream-not-stored")
    assert "extension" in decorated.meta
    assert decorated.meta[RESULT_CACHE_META_KEY]["hit"] is False


@pytest.mark.asyncio
async def test_cancelled_single_flight_waiter_does_not_leak_registration():
    cache = _new_cache()
    holder_entered = asyncio.Event()
    release_holder = asyncio.Event()

    async def hold_flight():
        async with cache.single_flight("same"):
            holder_entered.set()
            await release_holder.wait()

    holder = asyncio.create_task(hold_flight())
    await holder_entered.wait()

    async def wait_for_flight():
        async with cache.single_flight("same"):
            return None

    waiter = asyncio.create_task(wait_for_flight())
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter

    release_holder.set()
    await holder
    assert not cache._flights  # pylint: disable=protected-access
