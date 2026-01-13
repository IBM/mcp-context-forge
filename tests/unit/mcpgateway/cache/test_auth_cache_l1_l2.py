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
