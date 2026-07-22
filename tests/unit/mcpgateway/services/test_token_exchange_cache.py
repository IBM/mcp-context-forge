# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_token_exchange_cache.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Module Description.
Module documentation...
"""
# tests/unit/mcpgateway/services/test_token_exchange_cache.py
# Third-Party
import pytest

# First-Party
from mcpgateway.services.token_exchange_cache import TokenExchangeCache


@pytest.mark.asyncio
class TestTokenExchangeCache:
    async def test_miss_returns_none(self):
        c = TokenExchangeCache(redis_url=None)  # memory backend
        assert await c.get("gw1", "u@e", "aud") is None

    async def test_set_then_hit(self):
        c = TokenExchangeCache(redis_url=None)
        await c.set("gw1", "u@e", "aud", "tok-abc", expires_in=3600)
        assert await c.get("gw1", "u@e", "aud") == "tok-abc"

    async def test_user_scoped_no_cross_user_leak(self):
        c = TokenExchangeCache(redis_url=None)
        await c.set("gw1", "alice@e", "aud", "tok-alice", expires_in=3600)
        assert await c.get("gw1", "bob@e", "aud") is None

    async def test_key_does_not_collide_across_component_boundary_shift(self):
        # A bare ":"-joined key would make ("gw", "a:b", "c") collide with
        # ("gw", "a", "b:c") -- a crafted target_audience (attacker-controlled
        # per-gateway config) could shift the boundary and land on another
        # tuple's cache key, serving that principal's exchanged token instead.
        key_a = TokenExchangeCache._key("gw", "a:b", "c")
        key_b = TokenExchangeCache._key("gw", "a", "b:c")
        assert key_a != key_b

    async def test_no_cross_tuple_leak_via_crafted_audience(self):
        c = TokenExchangeCache(redis_url=None)
        await c.set("gw", "a:b", "c", "tok-victim", expires_in=3600)
        assert await c.get("gw", "a", "b:c") is None

    async def test_expiry_skew_treats_near_expiry_as_miss(self):
        c = TokenExchangeCache(redis_url=None, skew_seconds=300)
        await c.set("gw1", "u@e", "aud", "tok", expires_in=3600)
        # advance time to within the skew window of hard expiry -> miss
        # First-Party
        import mcpgateway.services.token_exchange_cache as mod

        real = mod.time.time
        try:
            mod.time.time = lambda: real() + 3500  # 100s before expiry, inside 300s skew
            assert await c.get("gw1", "u@e", "aud") is None
        finally:
            mod.time.time = real

    async def test_short_lived_token_is_still_served(self):
        # P2: a token with expires_in < skew must NOT be instantly uncacheable.
        # Effective skew is clamped to half the lifetime, so it serves for ~half.
        c = TokenExchangeCache(redis_url=None, skew_seconds=300)
        await c.set("gw1", "u@e", "aud", "short-tok", expires_in=120)
        assert await c.get("gw1", "u@e", "aud") == "short-tok"

    async def test_invalidate_removes_entry(self):
        c = TokenExchangeCache(redis_url=None)
        await c.set("gw1", "u@e", "aud", "tok", expires_in=3600)
        await c.invalidate("gw1", "u@e", "aud")
        assert await c.get("gw1", "u@e", "aud") is None

    async def test_memory_cache_is_bounded(self):
        # M2: unbounded growth is a memory-pressure DoS. Oldest entries evict.
        c = TokenExchangeCache(redis_url=None, max_entries=10)
        for i in range(50):
            await c.set("gw1", f"user{i}@e", "aud", f"tok{i}", expires_in=3600)
        assert len(c._mem) <= 10

    async def test_negative_cache_short_circuits_failures(self):
        # P4: after a recorded failure, is_failed() is True until the short TTL lapses.
        c = TokenExchangeCache(redis_url=None)
        assert await c.is_failed("gw1", "u@e", "aud") is False
        await c.set_failure("gw1", "u@e", "aud", ttl=10)
        assert await c.is_failed("gw1", "u@e", "aud") is True

    async def test_redis_hit_is_single_round_trip(self):
        # P3: a cache hit must issue exactly one Redis GET (no separate TTL call).
        # Standard
        import time as _t
        from unittest.mock import AsyncMock

        c = TokenExchangeCache(redis_url=None)
        fake = AsyncMock()
        fake.get = AsyncMock(return_value=f"{_t.time() + 3600}:tok-redis")  # serve_until:token
        c._redis = fake
        assert await c.get("gw1", "u@e", "aud") == "tok-redis"
        fake.get.assert_awaited_once()
        fake.ttl.assert_not_awaited()

    async def test_redis_set_get_invalidate_round_trip(self):
        # G9: exercise the Redis path for set/get/invalidate with a fakeredis-style store.
        try:
            # Third-Party
            import fakeredis.aioredis as fakeredis_aio  # optional dev dep
        except ImportError:
            pytest.skip("fakeredis not installed")
        c = TokenExchangeCache(redis_url=None)
        c._redis = fakeredis_aio.FakeRedis(decode_responses=True)
        await c.set("gw1", "u@e", "aud", "tok-r", expires_in=3600)
        assert await c.get("gw1", "u@e", "aud") == "tok-r"
        await c.invalidate("gw1", "u@e", "aud")
        assert await c.get("gw1", "u@e", "aud") is None

    async def test_redis_negative_cache_round_trip(self):
        # G9: is_failed/set_failure on the Redis backend.
        try:
            # Third-Party
            import fakeredis.aioredis as fakeredis_aio
        except ImportError:
            pytest.skip("fakeredis not installed")
        c = TokenExchangeCache(redis_url=None)
        c._redis = fakeredis_aio.FakeRedis(decode_responses=True)
        assert await c.is_failed("gw1", "u@e", "aud") is False
        await c.set_failure("gw1", "u@e", "aud", ttl=10)
        assert await c.is_failed("gw1", "u@e", "aud") is True

    async def test_malformed_redis_value_is_miss_not_raise(self):
        # G10: a corrupt stored value must degrade to a miss, never propagate.
        # Standard
        from unittest.mock import AsyncMock

        c = TokenExchangeCache(redis_url=None)
        fake = AsyncMock()
        fake.get = AsyncMock(return_value="not-a-valid-serve_until:tok")  # float() will fail
        c._redis = fake
        assert await c.get("gw1", "u@e", "aud") is None

    async def test_lock_registry_is_bounded(self):
        # G7: idle single-flight locks must not accumulate without bound.
        c = TokenExchangeCache(redis_url=None, max_entries=10)
        for i in range(50):
            c.lock("gw1", f"user{i}@e", "aud")  # not awaited/held -> evictable
        assert len(c._locks) <= 11  # current key is always retained

    async def test_lock_eviction_skips_held_lock(self):
        # G7: a held lock must survive eviction; idle locks are dropped first.
        c = TokenExchangeCache(redis_url=None, max_entries=2)
        held = c.lock("gw1", "held@e", "aud")
        async with held:
            for i in range(5):
                c.lock("gw1", f"user{i}@e", "aud")
            held_key = TokenExchangeCache._key("gw1", "held@e", "aud")
            assert held_key in c._locks  # held lock survives eviction
            assert len(c._locks) <= 3  # bounded (held + up to max_entries)

    async def test_lock_eviction_skips_the_current_key(self):
        # G7: when every other lock is held, the eviction loop iterates all the way to the
        # just-created current key and skips it via `continue` instead of deleting it.
        c = TokenExchangeCache(redis_url=None, max_entries=2)
        l0 = c.lock("gw1", "user0@e", "aud")
        l1 = c.lock("gw1", "user1@e", "aud")
        await l0.acquire()
        await l1.acquire()
        try:
            c.lock("gw1", "current@e", "aud")  # over budget -> eviction loop reaches current key
            current_key = TokenExchangeCache._key("gw1", "current@e", "aud")
            assert current_key in c._locks  # current key retained via the `continue` branch
            assert len(c._locks) == 3  # nothing evictable: held locks + current all survive
        finally:
            l0.release()
            l1.release()

    async def test_redis_get_empty_value_is_miss(self):
        # G10: an empty/falsy Redis value (no ":" separator) is a clean miss.
        # Standard
        from unittest.mock import AsyncMock

        c = TokenExchangeCache(redis_url=None)
        c._redis = AsyncMock()
        c._redis.get = AsyncMock(return_value="")
        assert await c.get("gw1", "u@e", "aud") is None

    async def test_redis_set_live_success_path(self):
        # P1: set() on a live Redis connection issues SET with the embedded
        # serve_until and resets the breaker on success.
        # Standard
        from unittest.mock import AsyncMock

        c = TokenExchangeCache(redis_url=None)
        c._redis = AsyncMock()
        c._redis.set = AsyncMock()
        await c.set("gw1", "u@e", "aud", "tok-live", expires_in=3600)
        c._redis.set.assert_awaited_once()
        args, kwargs = c._redis.set.call_args
        key, value = args[0], args[1]
        assert key == TokenExchangeCache._key("gw1", "u@e", "aud")
        assert value.endswith(":tok-live")
        assert kwargs["ex"] == 3600
        assert c._redis_fail_count == 0
        # in-memory store is untouched on the Redis-success path
        assert key not in c._mem

    async def test_redis_invalidate_live_path(self):
        # invalidate() on a live Redis connection issues DELETE and resets the breaker.
        # Standard
        from unittest.mock import AsyncMock

        c = TokenExchangeCache(redis_url=None)
        c._redis = AsyncMock()
        c._redis.delete = AsyncMock()
        await c.invalidate("gw1", "u@e", "aud")
        c._redis.delete.assert_awaited_once_with(TokenExchangeCache._key("gw1", "u@e", "aud"))
        assert c._redis_fail_count == 0

    async def test_redis_is_failed_live_path(self):
        # is_failed() on a live Redis connection issues GET on the ":neg" key.
        # Standard
        from unittest.mock import AsyncMock

        c = TokenExchangeCache(redis_url=None)
        c._redis = AsyncMock()
        c._redis.get = AsyncMock(return_value="1")
        assert await c.is_failed("gw1", "u@e", "aud") is True
        c._redis.get.assert_awaited_once_with(TokenExchangeCache._key("gw1", "u@e", "aud") + ":neg")
        assert c._redis_fail_count == 0

        c._redis.get = AsyncMock(return_value=None)
        assert await c.is_failed("gw1", "u@e", "aud") is False

    async def test_in_memory_negative_cache_expiry(self):
        # P4: an expired negative-cache entry is popped and reported as not-failed.
        # Standard
        import time as _t

        c = TokenExchangeCache(redis_url=None)
        key = TokenExchangeCache._key("gw1", "u@e", "aud") + ":neg"
        c._neg[key] = _t.time() - 1  # already expired
        assert await c.is_failed("gw1", "u@e", "aud") is False
        assert key not in c._neg

    async def test_redis_set_failure_live_path(self):
        # set_failure() on a live Redis connection issues SET with the failure TTL.
        # Standard
        from unittest.mock import AsyncMock

        c = TokenExchangeCache(redis_url=None)
        c._redis = AsyncMock()
        c._redis.set = AsyncMock()
        await c.set_failure("gw1", "u@e", "aud", ttl=10)
        c._redis.set.assert_awaited_once_with(TokenExchangeCache._key("gw1", "u@e", "aud") + ":neg", "1", ex=10)
        assert c._redis_fail_count == 0
        # in-memory negative cache is untouched on the Redis-success path
        assert TokenExchangeCache._key("gw1", "u@e", "aud") + ":neg" not in c._neg

    async def test_negative_cache_memory_is_bounded(self):
        # M2: unbounded negative-cache growth is the same DoS class as the token map.
        c = TokenExchangeCache(redis_url=None, max_entries=2)
        for i in range(3):
            await c.set_failure("gw1", f"user{i}@e", "aud", ttl=10)
        assert len(c._neg) <= 2

    async def test_redis_breaker_opens_and_logs_once(self, caplog):
        # L5: after threshold consecutive errors, Redis is disabled for the cooldown and
        # exactly one WARNING is emitted (no per-call flood).
        # Standard
        import logging
        from unittest.mock import AsyncMock

        c = TokenExchangeCache(redis_url=None, redis_breaker_threshold=3, redis_breaker_cooldown=30)
        boom = AsyncMock(side_effect=RuntimeError("redis down"))
        c._redis = AsyncMock()
        c._redis.get = boom
        with caplog.at_level(logging.WARNING):
            for _ in range(10):
                await c.get("gw1", "u@e", "aud")  # each falls back to memory (miss)
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "Redis disabled" in r.getMessage()]
        assert len(warnings) == 1  # logged once, not 10x
        assert c._redis_live() is False  # breaker open
