# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/cache/test_auth_cache_l1_l2.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Unit tests for AuthCache L1/L2 optimization (Issue #1881).

Tests verify that:
1. L1 (in-memory) cache is checked before L2 (Redis)
2. Redis hits populate L1 (write-through caching)
3. Performance improvement from avoiding unnecessary Redis calls
"""

# Standard
import builtins
import time
from unittest.mock import AsyncMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.cache.auth_cache import AuthCache, CachedAuthContext, CacheEntry


@pytest.fixture
def auth_cache():
    """Fixture for AuthCache with default settings."""
    cache = AuthCache(enabled=True)
    cache._redis_checked = True
    cache._redis_available = False  # Start without Redis for L1-only tests
    return cache


@pytest.fixture
def mock_redis():
    """Fixture for mocked Redis client."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.setex = AsyncMock()
    redis.delete = AsyncMock()
    redis.sismember = AsyncMock(return_value=False)
    redis.exists = AsyncMock(return_value=False)
    return redis


class TestGetAuthContextL1L2:
    """Test get_auth_context L1/L2 behavior."""

    @pytest.mark.asyncio
    async def test_l1_hit_no_redis_call(self, auth_cache):
        """Test that L1 cache hit does not trigger Redis call."""
        # Populate L1 cache
        email = "test@example.com"
        jti = "test-jti"
        cache_key = f"{email}:{jti}"

        ctx = CachedAuthContext(
            user={"email": email, "is_admin": False},
            personal_team_id="team-1",
            is_token_revoked=False,
        )

        auth_cache._context_cache[cache_key] = CacheEntry(
            value=ctx,
            expiry=time.time() + 300,
        )

        # L1 hit - no Redis call needed
        result = await auth_cache.get_auth_context(email, jti)

        # Verify L1 hit
        assert result is not None
        assert result.user["email"] == email
        assert result.personal_team_id == "team-1"

        # Verify hit count increased
        assert auth_cache._hit_count > 0

    @pytest.mark.asyncio
    async def test_l1_miss_l2_hit_write_through(self, auth_cache, mock_redis):
        """Test that Redis hit populates L1 cache (write-through)."""
        email = "test@example.com"
        jti = "test-jti"
        cache_key = f"{email}:{jti}"

        # Mock Redis to return data
        import orjson
        redis_data = orjson.dumps({
            "user": {"email": email, "is_admin": True},
            "personal_team_id": "team-2",
            "is_token_revoked": False,
        })
        mock_redis.get = AsyncMock(return_value=redis_data)

        with patch.object(auth_cache, '_get_redis_client', return_value=mock_redis):
            result = await auth_cache.get_auth_context(email, jti)

            # Verify Redis hit
            assert result is not None
            assert result.user["email"] == email
            assert result.user["is_admin"] is True
            assert result.personal_team_id == "team-2"

            # Verify Redis was called
            mock_redis.get.assert_called_once()

            # Verify write-through: L1 cache should now contain the entry
            assert cache_key in auth_cache._context_cache
            l1_entry = auth_cache._context_cache[cache_key]
            assert not l1_entry.is_expired()
            assert l1_entry.value.user["email"] == email

    @pytest.mark.asyncio
    async def test_l1_miss_l2_miss(self, auth_cache, mock_redis):
        """Test cache miss on both L1 and L2."""
        email = "test@example.com"
        jti = "test-jti"

        mock_redis.get = AsyncMock(return_value=None)

        initial_miss_count = auth_cache._miss_count

        with patch.object(auth_cache, '_get_redis_client', return_value=mock_redis):
            result = await auth_cache.get_auth_context(email, jti)

            # Both caches miss
            assert result is None

            # Miss count should increment
            assert auth_cache._miss_count == initial_miss_count + 1

            # Redis was called
            mock_redis.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_l1_hit_after_write_through(self, auth_cache, mock_redis):
        """Test that second request hits L1 after write-through from Redis."""
        email = "test@example.com"
        jti = "test-jti"

        # First request: L1 miss, L2 hit
        import orjson
        redis_data = orjson.dumps({
            "user": {"email": email},
            "personal_team_id": "team-1",
            "is_token_revoked": False,
        })
        mock_redis.get = AsyncMock(return_value=redis_data)

        with patch.object(auth_cache, '_get_redis_client', return_value=mock_redis):
            result1 = await auth_cache.get_auth_context(email, jti)
            assert result1 is not None
            assert mock_redis.get.call_count == 1

            # Second request: Should hit L1, no Redis call
            mock_redis.get.reset_mock()
            result2 = await auth_cache.get_auth_context(email, jti)

            assert result2 is not None
            assert result2.user["email"] == email
            # Redis should NOT be called on second request (L1 hit)
            mock_redis.get.assert_not_called()


class TestGetUserRoleL1L2:
    """Test get_user_role L1/L2 behavior."""

    @pytest.mark.asyncio
    async def test_l1_hit_no_redis_call(self, auth_cache):
        """Test that L1 cache hit avoids Redis call."""
        email = "test@example.com"
        team_id = "team-123"
        cache_key = f"{email}:{team_id}"

        # Populate L1 cache
        auth_cache._role_cache[cache_key] = CacheEntry(
            value="admin",
            expiry=time.time() + 300,
        )

        # L1 hit - no Redis call needed
        result = await auth_cache.get_user_role(email, team_id)

        assert result == "admin"

    @pytest.mark.asyncio
    async def test_l2_hit_write_through(self, auth_cache, mock_redis):
        """Test Redis hit populates L1 (write-through)."""
        email = "test@example.com"
        team_id = "team-123"
        cache_key = f"{email}:{team_id}"

        # Mock Redis to return role
        mock_redis.get = AsyncMock(return_value=b"member")

        with patch.object(auth_cache, '_get_redis_client', return_value=mock_redis):
            result = await auth_cache.get_user_role(email, team_id)

            assert result == "member"
            mock_redis.get.assert_called_once()

            # Verify write-through to L1
            assert cache_key in auth_cache._role_cache
            assert auth_cache._role_cache[cache_key].value == "member"

    @pytest.mark.asyncio
    async def test_not_a_member_sentinel_handling(self, auth_cache, mock_redis):
        """Test that NOT_A_MEMBER sentinel is handled correctly."""
        email = "test@example.com"
        team_id = "team-123"
        cache_key = f"{email}:{team_id}"

        # Mock Redis to return sentinel
        from mcpgateway.cache.auth_cache import _NOT_A_MEMBER_SENTINEL
        mock_redis.get = AsyncMock(return_value=_NOT_A_MEMBER_SENTINEL.encode())

        with patch.object(auth_cache, '_get_redis_client', return_value=mock_redis):
            result = await auth_cache.get_user_role(email, team_id)

            # Should return empty string (not a member)
            assert result == ""

            # Verify write-through stores None (L1 storage format)
            assert cache_key in auth_cache._role_cache
            assert auth_cache._role_cache[cache_key].value is None


class TestGetUserTeamsL1L2:
    """Test get_user_teams L1/L2 behavior."""

    @pytest.mark.asyncio
    async def test_l1_hit_no_redis_call(self, auth_cache):
        """Test that L1 cache hit avoids Redis call."""
        cache_key = "test@example.com:True"
        teams = ["team-1", "team-2"]

        # Populate L1 cache
        auth_cache._teams_list_enabled = True
        auth_cache._teams_list_cache[cache_key] = CacheEntry(
            value=teams,
            expiry=time.time() + 300,
        )

        # L1 hit - no Redis call needed
        result = await auth_cache.get_user_teams(cache_key)

        assert result == teams

    @pytest.mark.asyncio
    async def test_l2_hit_write_through(self, auth_cache, mock_redis):
        """Test Redis hit populates L1 (write-through)."""
        cache_key = "test@example.com:True"
        teams = ["team-1", "team-2", "team-3"]

        # Mock Redis to return teams
        import orjson
        mock_redis.get = AsyncMock(return_value=orjson.dumps(teams))

        auth_cache._teams_list_enabled = True

        with patch.object(auth_cache, '_get_redis_client', return_value=mock_redis):
            result = await auth_cache.get_user_teams(cache_key)

            assert result == teams
            mock_redis.get.assert_called_once()

            # Verify write-through to L1
            assert cache_key in auth_cache._teams_list_cache
            assert auth_cache._teams_list_cache[cache_key].value == teams


class TestIsTokenRevokedL1L2:
    """Test is_token_revoked L1/L2 behavior."""

    @pytest.mark.asyncio
    async def test_fast_local_check_revoked_jtis(self, auth_cache):
        """Test fast local check for known revoked tokens."""
        jti = "revoked-jti"
        auth_cache._revoked_jtis.add(jti)

        with patch.object(auth_cache, '_get_redis_client', new_callable=AsyncMock) as mock_get_redis:
            result = await auth_cache.is_token_revoked(jti)

            assert result is True
            # Redis should NOT be called for fast local check
            mock_get_redis.assert_not_called()

    @pytest.mark.asyncio
    async def test_l1_revocation_cache_hit(self, auth_cache):
        """Test L1 revocation cache hit before Redis."""
        jti = "cached-jti"

        # Populate L1 revocation cache
        auth_cache._revocation_cache[jti] = CacheEntry(
            value=True,
            expiry=time.time() + 300,
        )

        # L1 hit - no Redis call needed
        result = await auth_cache.is_token_revoked(jti)

        assert result is True

    @pytest.mark.asyncio
    async def test_l2_hit_write_through_revocation(self, auth_cache, mock_redis):
        """Test Redis revocation hit populates both local set and L1 cache."""
        jti = "revoked-in-redis"

        # Mock Redis to indicate token is revoked
        mock_redis.sismember = AsyncMock(return_value=True)

        with patch.object(auth_cache, '_get_redis_client', return_value=mock_redis):
            result = await auth_cache.is_token_revoked(jti)

            assert result is True

            # Verify write-through: JTI added to local set
            assert jti in auth_cache._revoked_jtis

            # Verify write-through: JTI added to L1 revocation cache
            assert jti in auth_cache._revocation_cache
            assert auth_cache._revocation_cache[jti].value is True

    @pytest.mark.asyncio
    async def test_l2_hit_revocation_key_exists(self, auth_cache, mock_redis):
        """Test Redis revocation key existence path."""
        jti = "revoked-key"
        mock_redis.sismember = AsyncMock(return_value=False)
        mock_redis.exists = AsyncMock(return_value=True)

        with patch.object(auth_cache, "_get_redis_client", return_value=mock_redis):
            result = await auth_cache.is_token_revoked(jti)

        assert result is True
        assert jti in auth_cache._revoked_jtis
        assert auth_cache._revocation_cache[jti].value is True


class TestGetTeamMembershipValidL1L2:
    """Test get_team_membership_valid L1/L2 behavior."""

    @pytest.mark.asyncio
    async def test_l1_hit_no_redis_call(self, auth_cache):
        """Test that L1 cache hit avoids Redis call."""
        user_email = "test@example.com"
        team_ids = ["team-1", "team-2"]
        sorted_teams = ":".join(sorted(team_ids))
        cache_key = f"{user_email}:{sorted_teams}"

        # Populate L1 cache
        auth_cache._team_cache[cache_key] = CacheEntry(
            value=True,
            expiry=time.time() + 300,
        )

        # L1 hit - no Redis call needed
        result = await auth_cache.get_team_membership_valid(user_email, team_ids)

        assert result is True

    @pytest.mark.asyncio
    async def test_l2_hit_write_through(self, auth_cache, mock_redis):
        """Test Redis hit populates L1 (write-through)."""
        user_email = "test@example.com"
        team_ids = ["team-1", "team-2"]
        sorted_teams = ":".join(sorted(team_ids))
        cache_key = f"{user_email}:{sorted_teams}"

        # Mock Redis to return True (stored as "1")
        mock_redis.get = AsyncMock(return_value=b"1")

        with patch.object(auth_cache, '_get_redis_client', return_value=mock_redis):
            result = await auth_cache.get_team_membership_valid(user_email, team_ids)

            assert result is True
            mock_redis.get.assert_called_once()

            # Verify write-through to L1
            assert cache_key in auth_cache._team_cache
            assert auth_cache._team_cache[cache_key].value is True

    @pytest.mark.asyncio
    async def test_l2_hit_false_write_through(self, auth_cache, mock_redis):
        """Test Redis hit with False value populates L1 correctly."""
        user_email = "test@example.com"
        team_ids = ["team-1"]
        sorted_teams = ":".join(sorted(team_ids))
        cache_key = f"{user_email}:{sorted_teams}"

        # Mock Redis to return False (stored as "0")
        mock_redis.get = AsyncMock(return_value=b"0")

        with patch.object(auth_cache, '_get_redis_client', return_value=mock_redis):
            result = await auth_cache.get_team_membership_valid(user_email, team_ids)

            assert result is False

            # Verify write-through to L1
            assert cache_key in auth_cache._team_cache
            assert auth_cache._team_cache[cache_key].value is False

    @pytest.mark.asyncio
    async def test_l1_hit_after_write_through(self, auth_cache, mock_redis):
        """Test that second request hits L1 after write-through from Redis."""
        user_email = "test@example.com"
        team_ids = ["team-a", "team-b"]

        # First request: L1 miss, L2 hit
        mock_redis.get = AsyncMock(return_value=b"1")

        with patch.object(auth_cache, '_get_redis_client', return_value=mock_redis):
            result1 = await auth_cache.get_team_membership_valid(user_email, team_ids)
            assert result1 is True
            assert mock_redis.get.call_count == 1

            # Second request: Should hit L1, no Redis call
            mock_redis.get.reset_mock()
            result2 = await auth_cache.get_team_membership_valid(user_email, team_ids)

            assert result2 is True
            # Redis should NOT be called on second request (L1 hit)
            mock_redis.get.assert_not_called()


class TestPerformanceMetrics:
    """Test that hit/miss counts are tracked correctly."""

    @pytest.mark.asyncio
    async def test_hit_count_l1(self, auth_cache):
        """Test hit count increments on L1 cache hit."""
        cache_key = "test@example.com:jti"
        ctx = CachedAuthContext(user={"email": "test@example.com"})

        auth_cache._context_cache[cache_key] = CacheEntry(
            value=ctx,
            expiry=time.time() + 300,
        )

        initial_hit_count = auth_cache._hit_count

        result = await auth_cache.get_auth_context("test@example.com", "jti")

        assert result is not None
        assert auth_cache._hit_count == initial_hit_count + 1

    @pytest.mark.asyncio
    async def test_redis_hit_count_l2(self, auth_cache, mock_redis):
        """Test Redis hit count increments on L2 cache hit."""
        import orjson
        redis_data = orjson.dumps({
            "user": {"email": "test@example.com"},
            "personal_team_id": None,
            "is_token_revoked": False,
        })
        mock_redis.get = AsyncMock(return_value=redis_data)

        initial_redis_hit = auth_cache._redis_hit_count

        with patch.object(auth_cache, '_get_redis_client', return_value=mock_redis):
            result = await auth_cache.get_auth_context("test@example.com", "jti")

            assert result is not None
            assert auth_cache._redis_hit_count == initial_redis_hit + 1

    @pytest.mark.asyncio
    async def test_miss_count(self, auth_cache, mock_redis):
        """Test miss count increments on cache miss."""
        mock_redis.get = AsyncMock(return_value=None)

        initial_miss_count = auth_cache._miss_count

        with patch.object(auth_cache, '_get_redis_client', return_value=mock_redis):
            result = await auth_cache.get_auth_context("test@example.com", "jti")

            assert result is None
            assert auth_cache._miss_count == initial_miss_count + 1


class TestAuthCacheInvalidation:
    """Cover invalidation paths for AuthCache."""

    @pytest.mark.asyncio
    async def test_invalidate_user_clears_caches_and_redis(self, auth_cache, mock_redis):
        email = "user@example.com"
        auth_cache._context_cache[f"{email}:jti"] = CacheEntry(value=CachedAuthContext(user={"email": email}), expiry=time.time() + 10)
        auth_cache._user_cache[email] = CacheEntry(value={"email": email}, expiry=time.time() + 10)
        auth_cache._team_cache[f"{email}:t1"] = CacheEntry(value=True, expiry=time.time() + 10)

        async def _scan_iter(match=None):
            for key in ["k1", "k2"]:
                yield key

        mock_redis.scan_iter = _scan_iter
        mock_redis.publish = AsyncMock(return_value=None)

        with patch.object(auth_cache, "_get_redis_client", return_value=mock_redis):
            await auth_cache.invalidate_user(email)

        assert email not in auth_cache._user_cache
        assert not any(k.startswith(f"{email}:") for k in auth_cache._context_cache)
        mock_redis.delete.assert_called()

    @pytest.mark.asyncio
    async def test_invalidate_revocation_updates_sets(self, auth_cache, mock_redis):
        jti = "revoked-jti"
        auth_cache._context_cache[f"user@example.com:{jti}"] = CacheEntry(value=CachedAuthContext(user={"email": "user@example.com"}), expiry=time.time() + 10)

        with patch.object(auth_cache, "_get_redis_client", return_value=mock_redis):
            await auth_cache.invalidate_revocation(jti)

        assert jti in auth_cache._revoked_jtis
        assert not any(k.endswith(f":{jti}") for k in auth_cache._context_cache)

    def test_invalidate_all_clears_l1(self, auth_cache):
        auth_cache._user_cache["u"] = CacheEntry(value={"email": "u"}, expiry=time.time() + 10)
        auth_cache._team_cache["u:t"] = CacheEntry(value=True, expiry=time.time() + 10)
        auth_cache.invalidate_all()
        assert auth_cache._user_cache == {}
        assert auth_cache._team_cache == {}


def test_auth_cache_import_error_defaults(monkeypatch):
    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "mcpgateway.config":
            raise ImportError("boom")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    cache = AuthCache()
    assert cache._cache_prefix == "mcpgw:"
    assert cache._enabled is True


@pytest.mark.asyncio
async def test_auth_cache_get_redis_client_flags(monkeypatch):
    cache = AuthCache(enabled=True)
    fake_redis = AsyncMock()
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=fake_redis))

    client = await cache._get_redis_client()
    assert client is fake_redis
    assert cache._redis_available is True

    cache = AuthCache(enabled=True)

    async def _raise():
        raise RuntimeError("boom")

    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", _raise)
    client = await cache._get_redis_client()
    assert client is None
    assert cache._redis_checked is True


@pytest.mark.asyncio
async def test_auth_cache_disabled_short_circuits():
    cache = AuthCache(enabled=False)
    ctx = CachedAuthContext(user={"email": "user@example.com"}, personal_team_id="team-1", is_token_revoked=False)

    assert await cache.get_auth_context("user@example.com", "jti") is None
    await cache.set_auth_context("user@example.com", "jti", ctx)
    assert await cache.get_user_role("user@example.com", "team-1") is None
    await cache.set_user_role("user@example.com", "team-1", "admin")
    assert await cache.get_user_teams("user@example.com:True") is None
    await cache.set_user_teams("user@example.com:True", ["team-1"])
    assert cache.get_team_membership_valid_sync("user@example.com", ["team-1"]) is None
    cache.set_team_membership_valid_sync("user@example.com", [], True)
    assert await cache.get_team_membership_valid("user@example.com", ["team-1"]) is None
    await cache.set_team_membership_valid("user@example.com", [], True)
    assert await cache.is_token_revoked("jti") is None


@pytest.mark.asyncio
async def test_auth_cache_revoked_jti_path():
    cache = AuthCache(enabled=True)
    cache._revoked_jtis.add("revoked-jti")
    result = await cache.get_auth_context("user@example.com", "revoked-jti")
    assert result.is_token_revoked is True


@pytest.mark.asyncio
async def test_auth_cache_redis_error_paths(monkeypatch):
    cache = AuthCache(enabled=True)
    cache._teams_list_enabled = True

    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=RuntimeError("boom"))
    redis.setex = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(cache, "_get_redis_client", AsyncMock(return_value=redis))

    assert await cache.get_auth_context("user@example.com", "jti") is None

    ctx = CachedAuthContext(user={"email": "user@example.com"}, personal_team_id="team-1", is_token_revoked=False)
    await cache.set_auth_context("user@example.com", "jti", ctx)

    assert await cache.get_user_role("user@example.com", "team-1") is None
    await cache.set_user_role("user@example.com", "team-1", "admin")

    assert await cache.get_user_teams("user@example.com:True") is None
    await cache.set_user_teams("user@example.com:True", ["team-1"])

    assert await cache.get_team_membership_valid("user@example.com", ["team-1"]) is None
    await cache.set_team_membership_valid("user@example.com", ["team-1"], True)


def test_auth_cache_team_membership_sync_hit():
    cache = AuthCache(enabled=True)
    cache._team_cache["user@example.com:team-1"] = CacheEntry(value=True, expiry=time.time() + 10)
    assert cache.get_team_membership_valid_sync("user@example.com", ["team-1"]) is True


@pytest.mark.asyncio
async def test_auth_cache_invalidation_redis_warning_paths(monkeypatch):
    cache = AuthCache(enabled=True)
    email = "user@example.com"
    team_id = "team-1"
    jti = "jti-123"

    cache._context_cache[f"{email}:{jti}"] = CacheEntry(value=CachedAuthContext(user={"email": email}), expiry=time.time() + 10)
    cache._user_cache[email] = CacheEntry(value={"email": email}, expiry=time.time() + 10)
    cache._team_cache[f"{email}:{team_id}"] = CacheEntry(value=True, expiry=time.time() + 10)
    cache._role_cache[f"{email}:{team_id}"] = CacheEntry(value="admin", expiry=time.time() + 10)
    cache._teams_list_cache[f"{email}:True"] = CacheEntry(value=[team_id], expiry=time.time() + 10)

    class FakeRedis:
        async def delete(self, *_args, **_kwargs):
            return 1

        async def scan_iter(self, *_args, **_kwargs):
            for key in [b"mcpgw:auth:key"]:
                yield key

        async def publish(self, *_args, **_kwargs):
            raise RuntimeError("boom")

        async def setex(self, *_args, **_kwargs):
            return 1

        async def sadd(self, *_args, **_kwargs):
            return 1

    monkeypatch.setattr(cache, "_get_redis_client", AsyncMock(return_value=FakeRedis()))

    await cache.invalidate_user(email)
    await cache.invalidate_revocation(jti)
    await cache.invalidate_team(email)
    await cache.invalidate_user_role(email, team_id)
    await cache.invalidate_team_roles(team_id)
    await cache.invalidate_user_teams(email)
    await cache.invalidate_team_membership(email)


@pytest.mark.asyncio
async def test_auth_cache_sync_revoked_tokens_updates_redis(monkeypatch):
    cache = AuthCache(enabled=True)
    fake_redis = AsyncMock()

    async def _to_thread(_func):
        return {"jti-1", "jti-2"}

    monkeypatch.setattr("mcpgateway.cache.auth_cache.asyncio.to_thread", _to_thread)
    monkeypatch.setattr(cache, "_get_redis_client", AsyncMock(return_value=fake_redis))

    await cache.sync_revoked_tokens()

    assert "jti-1" in cache._revoked_jtis
    fake_redis.sadd.assert_called()


@pytest.mark.asyncio
async def test_invalidate_team_clears_context_cache(auth_cache, mock_redis):
    email = "user@example.com"
    auth_cache._context_cache[f"{email}:jti"] = CacheEntry(value=CachedAuthContext(user={"email": email}), expiry=time.time() + 10)

    with patch.object(auth_cache, "_get_redis_client", return_value=None):
        await auth_cache.invalidate_team(email)

    assert not any(k.startswith(f"{email}:") for k in auth_cache._context_cache)
