# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/cache/test_auth_cache_user.py
Copyright contributors to the MCP-CONTEXT-FORGE project
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


@pytest.mark.asyncio
async def test_auth_context_key_uses_user_id_identity(monkeypatch):
    """get_current_user keys the auth-context cache by canonical user_id, not raw e-mail (issue #5891)."""
    # Standard
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace

    # Third-Party
    from fastapi.security import HTTPAuthorizationCredentials

    # First-Party
    from mcpgateway.auth import get_current_user
    from mcpgateway.config import settings
    from mcpgateway.db import EmailUser

    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="valid_jwt_token")  # pragma: allowlist secret
    jwt_payload = {
        "sub": "e@x.test",
        "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp(),
        "user": {"user_id": "u-1", "email": "e@x.test", "is_admin": False, "auth_provider": "local"},
    }

    mock_user = EmailUser(
        email="e@x.test",
        password_hash="hash",  # pragma: allowlist secret
        full_name="Test User",
        is_admin=False,
        is_active=True,
        email_verified_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    get_auth_context_spy = AsyncMock(return_value=None)  # cache miss: fall through to the DB path

    monkeypatch.setattr(settings, "auth_cache_enabled", True)
    monkeypatch.setattr(settings, "auth_cache_batch_queries", False)

    request = SimpleNamespace(state=SimpleNamespace())
    with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=jwt_payload)):
        with patch("mcpgateway.cache.auth_cache.auth_cache.get_auth_context", get_auth_context_spy):
            with patch("mcpgateway.auth._check_token_revoked_sync", return_value=False):
                with patch("mcpgateway.auth._is_api_token_jti_sync", return_value=True):
                    with patch("mcpgateway.auth._update_api_token_last_used_sync", return_value=None):
                        with patch("mcpgateway.auth._get_user_by_email_sync", return_value=mock_user):
                            with patch("mcpgateway.auth._get_personal_team_sync", return_value=None):
                                await get_current_user(credentials=credentials, request=request)

    get_auth_context_spy.assert_awaited_once()
    assert get_auth_context_spy.await_args.args[0] == "u-1"
