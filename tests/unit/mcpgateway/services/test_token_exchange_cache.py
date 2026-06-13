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
