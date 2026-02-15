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


# ============================================================================
# Coverage improvement tests
# ============================================================================


class TestNoRedisPartialBranches:
    """Cover all 'no Redis' partial branches where L1 misses and Redis is unavailable."""

    @pytest.mark.asyncio
    async def test_set_auth_context_no_redis(self, auth_cache):
        """set_auth_context stores only in L1 when Redis is unavailable (branch 354->365)."""
        ctx = CachedAuthContext(user={"email": "u@test.com"}, personal_team_id="t1", is_token_revoked=False)
        await auth_cache.set_auth_context("u@test.com", "jti", ctx)
        assert "u@test.com:jti" in auth_cache._context_cache

    @pytest.mark.asyncio
    async def test_invalidate_revocation_no_redis(self, auth_cache):
        """invalidate_revocation works without Redis (branch 450->exit)."""
        await auth_cache.invalidate_revocation("jti-1")
        assert "jti-1" in auth_cache._revoked_jtis

    @pytest.mark.asyncio
    async def test_get_user_role_no_redis_miss(self, auth_cache):
        """get_user_role L1 miss + no Redis = cache miss (branches 542->567, line 563)."""
        result = await auth_cache.get_user_role("u@test.com", "team-1")
        assert result is None
        assert auth_cache._miss_count > 0

    @pytest.mark.asyncio
    async def test_set_user_role_no_redis(self, auth_cache):
        """set_user_role stores only in L1 when Redis is unavailable (branch 592->600)."""
        await auth_cache.set_user_role("u@test.com", "team-1", "admin")
        assert "u@test.com:team-1" in auth_cache._role_cache

    @pytest.mark.asyncio
    async def test_invalidate_user_role_no_redis(self, auth_cache):
        """invalidate_user_role works without Redis (branch 630->exit)."""
        auth_cache._role_cache["u@test.com:team-1"] = CacheEntry(value="admin", expiry=time.time() + 10)
        await auth_cache.invalidate_user_role("u@test.com", "team-1")
        assert "u@test.com:team-1" not in auth_cache._role_cache

    @pytest.mark.asyncio
    async def test_invalidate_team_roles_no_redis_with_entries(self, auth_cache):
        """invalidate_team_roles clears matching entries without Redis (branch 661->exit, line 657)."""
        auth_cache._role_cache["u@test.com:team-1"] = CacheEntry(value="admin", expiry=time.time() + 10)
        auth_cache._role_cache["other@test.com:team-1"] = CacheEntry(value="viewer", expiry=time.time() + 10)
        auth_cache._role_cache["u@test.com:team-2"] = CacheEntry(value="dev", expiry=time.time() + 10)
        await auth_cache.invalidate_team_roles("team-1")
        assert "u@test.com:team-1" not in auth_cache._role_cache
        assert "other@test.com:team-1" not in auth_cache._role_cache
        assert "u@test.com:team-2" in auth_cache._role_cache

    @pytest.mark.asyncio
    async def test_get_user_teams_no_redis_miss(self, auth_cache):
        """get_user_teams L1 miss + no Redis = cache miss (branches 704->728, line 724)."""
        auth_cache._teams_list_enabled = True
        result = await auth_cache.get_user_teams("u@test.com:True")
        assert result is None
        assert auth_cache._miss_count > 0

    @pytest.mark.asyncio
    async def test_set_user_teams_no_redis(self, auth_cache):
        """set_user_teams stores only in L1 when Redis is unavailable (branch 748->759)."""
        auth_cache._teams_list_enabled = True
        await auth_cache.set_user_teams("u@test.com:True", ["team-1"])
        assert "u@test.com:True" in auth_cache._teams_list_cache

    @pytest.mark.asyncio
    async def test_get_team_membership_valid_no_redis_miss(self, auth_cache):
        """get_team_membership_valid L1 miss + no Redis = cache miss (branches 909->932, line 928)."""
        result = await auth_cache.get_team_membership_valid("u@test.com", ["team-1"])
        assert result is None
        assert auth_cache._miss_count > 0

    @pytest.mark.asyncio
    async def test_set_team_membership_valid_no_redis(self, auth_cache):
        """set_team_membership_valid stores only in L1 (branch 957->966)."""
        await auth_cache.set_team_membership_valid("u@test.com", ["team-1"], True)
        assert "u@test.com:team-1" in auth_cache._team_cache

    @pytest.mark.asyncio
    async def test_invalidate_team_membership_no_redis_with_entries(self, auth_cache):
        """invalidate_team_membership clears matching entries (line 992)."""
        auth_cache._team_cache["u@test.com:team-1"] = CacheEntry(value=True, expiry=time.time() + 10)
        auth_cache._team_cache["u@test.com:team-2"] = CacheEntry(value=False, expiry=time.time() + 10)
        auth_cache._team_cache["other@test.com:team-1"] = CacheEntry(value=True, expiry=time.time() + 10)
        await auth_cache.invalidate_team_membership("u@test.com")
        assert "u@test.com:team-1" not in auth_cache._team_cache
        assert "u@test.com:team-2" not in auth_cache._team_cache
        assert "other@test.com:team-1" in auth_cache._team_cache


class TestTeamMembershipSyncMissAndSet:
    """Cover get_team_membership_valid_sync miss and set_team_membership_valid_sync."""

    def test_sync_cache_miss(self):
        """get_team_membership_valid_sync returns None on miss (lines 844-845)."""
        cache = AuthCache(enabled=True)
        result = cache.get_team_membership_valid_sync("u@test.com", ["team-1"])
        assert result is None
        assert cache._miss_count > 0

    def test_sync_set_and_get(self):
        """set_team_membership_valid_sync stores value (lines 863-868)."""
        cache = AuthCache(enabled=True)
        cache.set_team_membership_valid_sync("u@test.com", ["team-1"], True)
        result = cache.get_team_membership_valid_sync("u@test.com", ["team-1"])
        assert result is True


class TestIsTokenRevokedRedisError:
    """Cover is_token_revoked Redis error path (lines 1063-1066)."""

    @pytest.mark.asyncio
    async def test_redis_error_returns_none(self):
        cache = AuthCache(enabled=True)
        redis = AsyncMock()
        redis.sismember = AsyncMock(side_effect=RuntimeError("boom"))

        with patch.object(cache, "_get_redis_client", return_value=redis):
            result = await cache.is_token_revoked("jti-1")
        assert result is None


class TestSyncRevokedTokensEdgeCases:
    """Cover sync_revoked_tokens edge cases."""

    @pytest.mark.asyncio
    async def test_sync_disabled(self):
        """sync_revoked_tokens returns early when disabled (line 1080)."""
        cache = AuthCache(enabled=False)
        await cache.sync_revoked_tokens()  # Should not raise

    @pytest.mark.asyncio
    async def test_sync_redis_sadd_fails(self, monkeypatch):
        """sync_revoked_tokens handles Redis sadd failure (lines 1109-1110)."""
        cache = AuthCache(enabled=True)
        redis = AsyncMock()
        redis.sadd = AsyncMock(side_effect=RuntimeError("boom"))

        async def _to_thread(_func):
            return {"jti-a"}

        monkeypatch.setattr("mcpgateway.cache.auth_cache.asyncio.to_thread", _to_thread)
        monkeypatch.setattr(cache, "_get_redis_client", AsyncMock(return_value=redis))

        await cache.sync_revoked_tokens()
        assert "jti-a" in cache._revoked_jtis

    @pytest.mark.asyncio
    async def test_sync_db_load_fails(self, monkeypatch):
        """sync_revoked_tokens handles DB load failure (lines 1114-1115)."""
        cache = AuthCache(enabled=True)

        async def _to_thread(_func):
            raise RuntimeError("DB error")

        monkeypatch.setattr("mcpgateway.cache.auth_cache.asyncio.to_thread", _to_thread)

        await cache.sync_revoked_tokens()  # Should not raise

    @pytest.mark.asyncio
    async def test_sync_no_redis_no_jtis(self, monkeypatch):
        """sync_revoked_tokens with no Redis and empty jtis (branch 1106->1112)."""
        cache = AuthCache(enabled=True)
        cache._redis_checked = True
        cache._redis_available = False

        async def _to_thread(_func):
            return set()

        monkeypatch.setattr("mcpgateway.cache.auth_cache.asyncio.to_thread", _to_thread)

        await cache.sync_revoked_tokens()


class TestStatsAndReset:
    """Cover stats() and reset_stats() methods."""

    def test_stats_returns_all_fields(self):
        """stats() returns complete dict (lines 1149-1152)."""
        cache = AuthCache(enabled=True)
        cache._hit_count = 5
        cache._miss_count = 3
        cache._redis_hit_count = 2
        cache._redis_miss_count = 1
        s = cache.stats()
        assert s["enabled"] is True
        assert s["hit_count"] == 5
        assert s["miss_count"] == 3
        assert s["hit_rate"] == 5.0 / 8.0
        assert s["redis_hit_count"] == 2
        assert s["redis_hit_rate"] == 2.0 / 3.0

    def test_reset_stats_clears_counters(self):
        """reset_stats() zeroes all counters (lines 1184-1187)."""
        cache = AuthCache(enabled=True)
        cache._hit_count = 10
        cache._miss_count = 5
        cache._redis_hit_count = 3
        cache._redis_miss_count = 2
        cache.reset_stats()
        assert cache._hit_count == 0
        assert cache._miss_count == 0
        assert cache._redis_hit_count == 0
        assert cache._redis_miss_count == 0


class TestGetAuthCacheSingleton:
    """Cover get_auth_cache already-initialized branch (1206->1208)."""

    def test_get_auth_cache_returns_same_instance(self):
        """get_auth_cache returns existing singleton."""
        from mcpgateway.cache.auth_cache import get_auth_cache
        c1 = get_auth_cache()
        c2 = get_auth_cache()
        assert c1 is c2


class TestGetAuthContextNoRedis:
    """Cover get_auth_context L1 miss + no Redis (branch 279->309)."""

    @pytest.mark.asyncio
    async def test_l1_miss_no_redis_returns_none(self, auth_cache):
        """get_auth_context returns None when L1 misses and Redis is unavailable."""
        result = await auth_cache.get_auth_context("u@test.com", "jti")
        assert result is None
        assert auth_cache._miss_count > 0


class TestInvalidateUserNoRedis:
    """Cover invalidate_user without Redis (branch 402->exit)."""

    @pytest.mark.asyncio
    async def test_invalidate_user_no_redis(self, auth_cache):
        """invalidate_user clears L1 when Redis is unavailable."""
        auth_cache._user_cache["u@test.com"] = CacheEntry(value={"email": "u@test.com"}, expiry=time.time() + 10)
        auth_cache._context_cache["u@test.com:jti"] = CacheEntry(
            value=CachedAuthContext(user={"email": "u@test.com"}), expiry=time.time() + 10
        )
        await auth_cache.invalidate_user("u@test.com")
        assert "u@test.com" not in auth_cache._user_cache


class TestInvalidateUserTeamsNoRedis:
    """Cover invalidate_user_teams without Redis (branch 792->exit)."""

    @pytest.mark.asyncio
    async def test_invalidate_user_teams_no_redis(self, auth_cache):
        """invalidate_user_teams clears L1 when Redis is unavailable."""
        auth_cache._teams_list_cache["u@test.com:True"] = CacheEntry(value=["t1"], expiry=time.time() + 10)
        await auth_cache.invalidate_user_teams("u@test.com")
        assert "u@test.com:True" not in auth_cache._teams_list_cache


class TestIsTokenRevokedNotFound:
    """Cover is_token_revoked Redis available but not found (branches 1039->1066, 1054->1066)."""

    @pytest.mark.asyncio
    async def test_redis_not_found_returns_none(self):
        """Token not in Redis sismember or exists → return None."""
        cache = AuthCache(enabled=True)
        redis = AsyncMock()
        redis.sismember = AsyncMock(return_value=False)
        redis.exists = AsyncMock(return_value=False)

        with patch.object(cache, "_get_redis_client", return_value=redis):
            result = await cache.is_token_revoked("unknown-jti")
        assert result is None


class TestSyncRevokedTokensLoadJtis:
    """Cover sync_revoked_tokens _load_revoked_jtis (lines 1095-1097)."""

    @pytest.mark.asyncio
    async def test_load_jtis_from_db(self, monkeypatch):
        """Actually exercise _load_revoked_jtis via asyncio.to_thread → DB mock."""
        from unittest.mock import MagicMock as _MM
        from contextlib import contextmanager

        cache = AuthCache(enabled=True)
        cache._redis_checked = True
        cache._redis_available = False

        @contextmanager
        def _mock_session():
            db = _MM()
            db.execute.return_value = [("jti-db-1",), ("jti-db-2",)]
            yield db

        # Let asyncio.to_thread actually call the function
        monkeypatch.setattr("mcpgateway.db.fresh_db_session", _mock_session)

        await cache.sync_revoked_tokens()
        assert "jti-db-1" in cache._revoked_jtis
        assert "jti-db-2" in cache._revoked_jtis


class TestIsTokenRevokedNoRedis:
    """Cover is_token_revoked with no Redis (branch 1039->1066)."""

    @pytest.mark.asyncio
    async def test_no_redis_returns_none(self, auth_cache):
        """is_token_revoked returns None when not in L1 and Redis unavailable."""
        result = await auth_cache.is_token_revoked("unknown-jti")
        assert result is None


class TestGetRedisClientSecondException:
    """Cover _get_redis_client exception when already checked (branch 231->235)."""

    @pytest.mark.asyncio
    async def test_exception_after_first_check(self, monkeypatch):
        """Second exception in _get_redis_client returns None (already checked)."""
        cache = AuthCache(enabled=True)
        cache._redis_checked = True  # Already checked
        cache._redis_available = True  # Was available before

        # Now it raises
        monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(side_effect=RuntimeError("gone")))
        result = await cache._get_redis_client()
        assert result is None


class TestRedisMissCounts:
    """Cover Redis miss count increments for role/teams/membership."""

    @pytest.mark.asyncio
    async def test_get_user_role_redis_miss(self, auth_cache, mock_redis):
        """Redis returns None for role → redis_miss_count incremented (line 563)."""
        mock_redis.get = AsyncMock(return_value=None)
        initial = auth_cache._redis_miss_count

        with patch.object(auth_cache, "_get_redis_client", return_value=mock_redis):
            result = await auth_cache.get_user_role("u@test.com", "team-1")

        assert result is None
        assert auth_cache._redis_miss_count == initial + 1

    @pytest.mark.asyncio
    async def test_get_user_teams_redis_miss(self, auth_cache, mock_redis):
        """Redis returns None for teams → redis_miss_count incremented (line 724)."""
        auth_cache._teams_list_enabled = True
        mock_redis.get = AsyncMock(return_value=None)
        initial = auth_cache._redis_miss_count

        with patch.object(auth_cache, "_get_redis_client", return_value=mock_redis):
            result = await auth_cache.get_user_teams("u@test.com:True")

        assert result is None
        assert auth_cache._redis_miss_count == initial + 1

    @pytest.mark.asyncio
    async def test_get_team_membership_redis_miss(self, auth_cache, mock_redis):
        """Redis returns None for membership → redis_miss_count incremented (line 928)."""
        mock_redis.get = AsyncMock(return_value=None)
        initial = auth_cache._redis_miss_count

        with patch.object(auth_cache, "_get_redis_client", return_value=mock_redis):
            result = await auth_cache.get_team_membership_valid("u@test.com", ["team-1"])

        assert result is None
        assert auth_cache._redis_miss_count == initial + 1
