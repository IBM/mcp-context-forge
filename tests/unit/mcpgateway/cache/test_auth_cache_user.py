# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/cache/test_auth_cache_user.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Unit tests for AuthCache.get_user() / set_user() (Issue #3061).
"""

# Standard
import time
from unittest.mock import AsyncMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.cache.auth_cache import AuthCache, CacheEntry


@pytest.fixture
def cache():
    """AuthCache with caching enabled, Redis disabled."""
    c = AuthCache(enabled=True, user_ttl=60)
    c._redis_checked = True
    c._redis_available = False
    return c


@pytest.fixture
def mock_redis():
    r = AsyncMock()
    r.get = AsyncMock(return_value=None)
    r.setex = AsyncMock()
    r.delete = AsyncMock()
    r.scan_iter = AsyncMock(return_value=aiter([]))
    r.publish = AsyncMock()
    return r


async def aiter(items):
    for item in items:
        yield item


_USER_DICT = {
    "email": "test@example.com",
    "full_name": "Test User",
    "is_admin": False,
    "is_active": True,
    "auth_provider": "local",
    "password_hash_type": "argon2id",
    "password_change_required": False,
    "failed_login_attempts": 0,
    "locked_until": None,
    "email_verified_at": None,
    "created_at": "2025-01-01T00:00:00+00:00",
    "updated_at": "2025-01-01T00:00:00+00:00",
    "last_login": None,
    "admin_origin": None,
    "password_changed_at": None,
}


class TestGetUser:
    @pytest.mark.asyncio
    async def test_cache_miss_returns_none(self, cache):
        result = await cache.get_user("test@example.com")
        assert result is None
        assert cache._miss_count == 1

    @pytest.mark.asyncio
    async def test_set_then_get_returns_dict(self, cache):
        await cache.set_user("test@example.com", _USER_DICT)
        result = await cache.get_user("test@example.com")
        assert result is not None
        assert result["email"] == "test@example.com"
        assert result["is_admin"] is False
        assert cache._hit_count == 1

    @pytest.mark.asyncio
    async def test_expired_entry_returns_none(self, cache):
        # Insert an already-expired entry
        cache._user_cache["test@example.com"] = CacheEntry(
            value=_USER_DICT,
            expiry=time.time() - 1,  # already expired
        )
        result = await cache.get_user("test@example.com")
        assert result is None

    @pytest.mark.asyncio
    async def test_invalidate_user_clears_user_cache(self, cache):
        await cache.set_user("test@example.com", _USER_DICT)
        assert await cache.get_user("test@example.com") is not None

        await cache.invalidate_user("test@example.com")

        assert await cache.get_user("test@example.com") is None

    @pytest.mark.asyncio
    async def test_disabled_cache_get_returns_none(self):
        c = AuthCache(enabled=False)
        await c.set_user("test@example.com", _USER_DICT)
        result = await c.get_user("test@example.com")
        assert result is None

    @pytest.mark.asyncio
    async def test_redis_hit_populates_l1(self, cache, mock_redis):
        import orjson

        mock_redis.get = AsyncMock(return_value=orjson.dumps(_USER_DICT))

        with patch.object(cache, "_get_redis_client", return_value=mock_redis):
            result = await cache.get_user("test@example.com")

        assert result is not None
        assert result["email"] == "test@example.com"
        # L1 should now be populated
        assert "test@example.com" in cache._user_cache

    @pytest.mark.asyncio
    async def test_redis_miss_increments_redis_miss_count(self, cache, mock_redis):
        """Line 438: redis.get() returns None → _redis_miss_count increments."""
        mock_redis.get = AsyncMock(return_value=None)

        with patch.object(cache, "_get_redis_client", return_value=mock_redis):
            result = await cache.get_user("test@example.com")

        assert result is None
        assert cache._redis_miss_count == 1
        assert cache._miss_count == 1

    @pytest.mark.asyncio
    async def test_redis_get_error_logs_warning_and_returns_none(self, cache, mock_redis):
        """except block in get_user when redis.get() raises."""
        mock_redis.get = AsyncMock(side_effect=RuntimeError("Redis connection lost"))

        with patch.object(cache, "_get_redis_client", return_value=mock_redis):
            result = await cache.get_user("test@example.com")

        assert result is None
        assert cache._miss_count == 1

    @pytest.mark.asyncio
    async def test_set_user_with_redis_stores_in_both_tiers(self, cache, mock_redis):
        """Lines 463/466: import orjson and setex inside set_user try block."""
        with patch.object(cache, "_get_redis_client", return_value=mock_redis):
            await cache.set_user("test@example.com", _USER_DICT)

        mock_redis.setex.assert_awaited_once()
        assert "test@example.com" in cache._user_cache

    @pytest.mark.asyncio
    async def test_set_user_redis_error_still_populates_l1(self, cache, mock_redis):
        """Line 468: except block in set_user when redis.setex() raises."""
        mock_redis.setex = AsyncMock(side_effect=RuntimeError("Redis write failed"))

        with patch.object(cache, "_get_redis_client", return_value=mock_redis):
            await cache.set_user("test@example.com", _USER_DICT)

        assert "test@example.com" in cache._user_cache

    @pytest.mark.asyncio
    async def test_stats_includes_user_cache_size(self, cache):
        await cache.set_user("test@example.com", _USER_DICT)
        stats = cache.stats()
        assert "user_cache_size" in stats
        assert stats["user_cache_size"] == 1
