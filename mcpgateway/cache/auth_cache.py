# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/cache/auth_cache.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Authentication Data Cache.

This module implements a thread-safe two-tier cache for authentication data.
L1 (in-memory) is checked first for lowest latency, with L2 (Redis) as a
shared distributed cache. It caches user data, team memberships, and token
revocation status to reduce database queries during authentication.

Performance Impact:
    - Before: 3-4 DB queries per authenticated request
    - After: 0-1 DB queries (cache hit) per TTL period

Security Considerations:
    - Short TTLs for revocation data (30s default) to limit exposure window
    - Cache invalidation on token revocation, user update, team change
    - JWT payloads are NOT cached (security risk)
    - Graceful fallback to DB on cache failure

Examples:
    >>> from mcpgateway.cache.auth_cache import auth_cache
    >>> # Cache is used automatically by get_current_user()
    >>> # Manual invalidation after user update:
    >>> import asyncio
    >>> # asyncio.run(auth_cache.invalidate_user("user@example.com"))
"""

# Standard
import asyncio
from dataclasses import dataclass
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Sentinel value to represent "user is not a member" in Redis cache
# This allows distinguishing between "not a member" (cached) and "cache miss"
_NOT_A_MEMBER_SENTINEL = "__NOT_A_MEMBER__"


@dataclass
class CachedAuthContext:
    """Cached authentication context from batched DB query.

    This dataclass holds user data, team membership, and revocation status
    retrieved from a single database roundtrip.

    Attributes:
        user: User data dict (email, is_admin, is_active, etc.) or None
        personal_team_id: User's personal team ID or None
        is_token_revoked: Whether the JWT is revoked

    Examples:
        >>> ctx = CachedAuthContext(
        ...     user={"email": "test@example.com", "is_admin": False},
        ...     personal_team_id="team-123",
        ...     is_token_revoked=False
        ... )
        >>> ctx.is_token_revoked
        False
    """

    user: Optional[Dict[str, Any]] = None
    personal_team_id: Optional[str] = None
    is_token_revoked: bool = False


@dataclass
class CacheEntry:
    """Cache entry with value and expiry timestamp.

    Examples:
        >>> import time
        >>> entry = CacheEntry(value={"key": "value"}, expiry=time.time() + 60)
        >>> entry.is_expired()
        False
    """

    value: Any
    expiry: float

    def is_expired(self) -> bool:
        """Check if this cache entry has expired.

        Returns:
            bool: True if the entry has expired, False otherwise.
        """
        return time.time() >= self.expiry


class AuthCache:
    """Thread-safe two-tier authentication cache (L1 in-memory + L2 Redis).

    This cache reduces database load during authentication by caching:
    - User data (email, is_admin, is_active, etc.)
    - Personal team ID for the user
    - Token revocation status

    Cache lookup checks L1 (in-memory) first for lowest latency, then L2
    (Redis) for distributed consistency. Redis hits are written through
    to L1 for subsequent requests.

    Attributes:
        user_ttl: TTL in seconds for user data cache (default: 60)
        revocation_ttl: TTL in seconds for revocation cache (default: 30)
        team_ttl: TTL in seconds for team cache (default: 60)

    Examples:
        >>> cache = AuthCache(user_ttl=60, revocation_ttl=30)
        >>> cache.stats()["hit_count"]
        0
    """

    _NOT_CACHED = object()

    def __init__(
        self,
        user_ttl: Optional[int] = None,
        revocation_ttl: Optional[int] = None,
        team_ttl: Optional[int] = None,
        role_ttl: Optional[int] = None,
        enabled: Optional[bool] = None,
    ):
        """Initialize the auth cache.

        Args:
            user_ttl: TTL for user data cache in seconds (default: from settings or 60)
            revocation_ttl: TTL for revocation cache in seconds (default: from settings or 30)
            team_ttl: TTL for team cache in seconds (default: from settings or 60)
            role_ttl: TTL for role cache in seconds (default: from settings or 60)
            enabled: Whether caching is enabled (default: from settings or True)

        Examples:
            >>> cache = AuthCache(user_ttl=120, revocation_ttl=30)
            >>> cache._user_ttl
            120
        """
        # Import settings lazily to avoid circular imports
        try:
            # First-Party
            from mcpgateway.config import settings  # pylint: disable=import-outside-toplevel

            self._user_ttl = user_ttl or getattr(settings, "auth_cache_user_ttl", 60)
            self._revocation_ttl = revocation_ttl or getattr(settings, "auth_cache_revocation_ttl", 30)
            self._team_ttl = team_ttl or getattr(settings, "auth_cache_team_ttl", 60)
            self._role_ttl = role_ttl or getattr(settings, "auth_cache_role_ttl", 60)
            self._teams_list_ttl = getattr(settings, "auth_cache_teams_ttl", 60)
            self._teams_list_enabled = getattr(settings, "auth_cache_teams_enabled", True)
            self._enabled = enabled if enabled is not None else getattr(settings, "auth_cache_enabled", True)
            self._cache_prefix = getattr(settings, "cache_prefix", "mcpgw:")
        except ImportError:
            self._user_ttl = user_ttl or 60
            self._revocation_ttl = revocation_ttl or 30
            self._team_ttl = team_ttl or 60
            self._role_ttl = role_ttl or 60
            self._teams_list_ttl = 60
            self._teams_list_enabled = True
            self._enabled = enabled if enabled is not None else True
            self._cache_prefix = "mcpgw:"

        # In-memory cache (fallback when Redis unavailable)
        self._user_cache: Dict[str, CacheEntry] = {}
        self._team_cache: Dict[str, CacheEntry] = {}
        self._revocation_cache: Dict[str, CacheEntry] = {}
        self._context_cache: Dict[str, CacheEntry] = {}
        self._role_cache: Dict[str, CacheEntry] = {}
        self._teams_list_cache: Dict[str, CacheEntry] = {}

        # Known revoked tokens (fast local lookup)
        self._revoked_jtis: Set[str] = set()

        # Thread safety
        self._lock = threading.Lock()

        # Redis availability (None = not checked yet)
        self._redis_checked = False
        self._redis_available = False

        # Statistics
        self._hit_count = 0
        self._miss_count = 0
        self._redis_hit_count = 0
        self._redis_miss_count = 0

        logger.info(
            f"AuthCache initialized: enabled={self._enabled}, "
            f"user_ttl={self._user_ttl}s, revocation_ttl={self._revocation_ttl}s, "
            f"team_ttl={self._team_ttl}s, role_ttl={self._role_ttl}s, "
            f"teams_list_enabled={self._teams_list_enabled}, teams_list_ttl={self._teams_list_ttl}s"
        )

    def _get_redis_key(self, key_type: str, identifier: str) -> str:
        """Generate Redis key with proper prefix.

        Args:
            key_type: Type of cache entry (user, team, revoke, ctx)
            identifier: Unique identifier (email, jti, etc.)

        Returns:
            Full Redis key with prefix

        Examples:
            >>> cache = AuthCache()
            >>> cache._get_redis_key("user", "test@example.com")
            'mcpgw:auth:user:test@example.com'
        """
        return f"{self._cache_prefix}auth:{key_type}:{identifier}"

    async def _get_redis_client(self):
        """Get Redis client if available.

        Returns:
            Redis client or None if unavailable
        """
        try:
            # First-Party
            from mcpgateway.utils.redis_client import get_redis_client  # pylint: disable=import-outside-toplevel

            client = await get_redis_client()
            if client and not self._redis_checked:
                self._redis_checked = True
                self._redis_available = True
                logger.debug("AuthCache: Redis client available")
            return client
        except Exception as e:
            if not self._redis_checked:
                self._redis_checked = True
                self._redis_available = False
                logger.debug(f"AuthCache: Redis unavailable, using in-memory cache: {e}")
            return None

    async def get_auth_context(
        self,
        email: str,
        jti: Optional[str] = None,
    ) -> Optional[CachedAuthContext]:
        """Get cached authentication context.

        Checks cache for user data, team membership, and revocation status.
        Returns None on cache miss.

        Args:
            email: User email address
            jti: JWT ID for revocation check (optional)

        Returns:
            CachedAuthContext if found in cache, None otherwise

        Examples:
            >>> import asyncio
            >>> cache = AuthCache()
            >>> result = asyncio.run(cache.get_auth_context("test@example.com"))
            >>> result is None  # Cache miss on fresh cache
            True
        """
        if not self._enabled:
            return None

        # Check for known revoked token first (fast local check)
        if jti and jti in self._revoked_jtis:
            self._hit_count += 1
            return CachedAuthContext(is_token_revoked=True)

        cache_key = f"{email}:{jti or 'no-jti'}"

        # Check L1 in-memory cache first (no network I/O)
        entry = self._context_cache.get(cache_key)
        if entry and not entry.is_expired():
            self._hit_count += 1
            return entry.value

        # Check L2 Redis cache
        redis = await self._get_redis_client()
        if redis:
            try:
                redis_key = self._get_redis_key("ctx", cache_key)
                data = await redis.get(redis_key)
                if data:
                    # Third-Party
                    import orjson  # pylint: disable=import-outside-toplevel

                    cached = orjson.loads(data)
                    result = CachedAuthContext(
                        user=cached.get("user"),
                        personal_team_id=cached.get("personal_team_id"),
                        is_token_revoked=cached.get("is_token_revoked", False),
                    )
                    self._hit_count += 1
                    self._redis_hit_count += 1

                    # Write-through: populate L1 from Redis hit
                    ttl = min(self._user_ttl, self._revocation_ttl, self._team_ttl)
                    with self._lock:
                        self._context_cache[cache_key] = CacheEntry(
                            value=result,
                            expiry=time.time() + ttl,
                        )

                    return result
                self._redis_miss_count += 1
            except Exception as e:
                logger.warning(f"AuthCache Redis get failed: {e}")

        self._miss_count += 1
        return None

    async def set_auth_context(
        self,
        email: str,
        jti: Optional[str],
        context: CachedAuthContext,
    ) -> None:
        """Store authentication context in cache.

        Stores in both Redis (if available) and in-memory cache.

        Args:
            email: User email address
            jti: JWT ID (optional)
            context: Authentication context to cache

        Examples:
            >>> import asyncio
            >>> cache = AuthCache()
            >>> ctx = CachedAuthContext(
            ...     user={"email": "test@example.com"},
            ...     personal_team_id="team-1",
            ...     is_token_revoked=False
            ... )
            >>> asyncio.run(cache.set_auth_context("test@example.com", "jti-123", ctx))
        """
        if not self._enabled:
            return

        cache_key = f"{email}:{jti or 'no-jti'}"

        # Use shortest TTL for combined context
        ttl = min(self._user_ttl, self._revocation_ttl, self._team_ttl)

        # Prepare data for serialization
        data = {
            "user": context.user,
            "personal_team_id": context.personal_team_id,
            "is_token_revoked": context.is_token_revoked,
        }

        # Store in Redis
        redis = await self._get_redis_client()
        if redis:
            try:
                # Third-Party
                import orjson  # pylint: disable=import-outside-toplevel

                redis_key = self._get_redis_key("ctx", cache_key)
                await redis.setex(redis_key, ttl, orjson.dumps(data))
            except Exception as e:
                logger.warning(f"AuthCache Redis set failed: {e}")

        # Store in in-memory cache
        with self._lock:
            self._context_cache[cache_key] = CacheEntry(
                value=context,
                expiry=time.time() + ttl,
            )

    async def invalidate_user(self, email: str) -> None:
        """Invalidate cached data for a user.

        Call this when user data changes (password, profile, etc.).

        Args:
            email: User email to invalidate

        Examples:
            >>> import asyncio
            >>> cache = AuthCache()
            >>> asyncio.run(cache.invalidate_user("test@example.com"))
        """
        logger.debug(f"AuthCache: Invalidating user cache for {email}")

        # Clear in-memory caches
        with self._lock:
            # Clear any context cache entries for this user
            keys_to_remove = [k for k in self._context_cache if k.startswith(f"{email}:")]
            for key in keys_to_remove:
                self._context_cache.pop(key, None)

            self._user_cache.pop(email, None)

            # Clear team membership cache entries (keys are email:team_ids)
            team_keys_to_remove = [k for k in self._team_cache if k.startswith(f"{email}:")]
            for key in team_keys_to_remove:
                self._team_cache.pop(key, None)

        # Clear Redis
        redis = await self._get_redis_client()
        if redis:
            try:
                # Delete user-specific keys
                await redis.delete(
                    self._get_redis_key("user", email),
                    self._get_redis_key("team", email),
                )
                # Delete context keys (pattern match)
                pattern = self._get_redis_key("ctx", f"{email}:*")
                async for key in redis.scan_iter(match=pattern):
                    await redis.delete(key)
                # Delete membership keys (pattern match)
                membership_pattern = self._get_redis_key("membership", f"{email}:*")
                async for key in redis.scan_iter(match=membership_pattern):
                    await redis.delete(key)

                # Publish invalidation for other workers
                await redis.publish("mcpgw:auth:invalidate", f"user:{email}")
            except Exception as e:
                logger.warning(f"AuthCache Redis invalidate_user failed: {e}")

    async def invalidate_revocation(self, jti: str) -> None:
        """Invalidate cache for a revoked token.

        Call this when a token is revoked.

        Args:
            jti: JWT ID of revoked token

        Examples:
            >>> import asyncio
            >>> cache = AuthCache()
            >>> asyncio.run(cache.invalidate_revocation("jti-123"))
        """
        logger.debug(f"AuthCache: Invalidating revocation cache for jti={jti[:8]}...")

        # Add to local revoked set for fast lookup
        with self._lock:
            self._revoked_jtis.add(jti)
            self._revocation_cache.pop(jti, None)

            # Clear any context cache entries with this JTI
            keys_to_remove = [k for k in self._context_cache if k.endswith(f":{jti}")]
            for key in keys_to_remove:
                self._context_cache.pop(key, None)

        # Update Redis
        redis = await self._get_redis_client()
        if redis:
            try:
                # Mark as revoked in Redis
                await redis.setex(
                    self._get_redis_key("revoke", jti),
                    86400,  # 24 hour expiry for revocation markers
                    "1",
                )
                # Add to revoked tokens set
                await redis.sadd("mcpgw:auth:revoked_tokens", jti)

                # Delete any cached contexts with this JTI
                pattern = self._get_redis_key("ctx", f"*:{jti}")
                async for key in redis.scan_iter(match=pattern):
                    await redis.delete(key)

                # Publish invalidation for other workers
                await redis.publish("mcpgw:auth:invalidate", f"revoke:{jti}")
            except Exception as e:
                logger.warning(f"AuthCache Redis invalidate_revocation failed: {e}")

    async def invalidate_team(self, email: str) -> None:
        """Invalidate team cache for a user.

        Call this when team membership changes.

        Args:
            email: User email whose team changed

        Examples:
            >>> import asyncio
            >>> cache = AuthCache()
            >>> asyncio.run(cache.invalidate_team("test@example.com"))
        """
        logger.debug(f"AuthCache: Invalidating team cache for {email}")

        # Clear in-memory caches
        with self._lock:
            self._team_cache.pop(email, None)
            # Clear context cache entries for this user
            keys_to_remove = [k for k in self._context_cache if k.startswith(f"{email}:")]
            for key in keys_to_remove:
                self._context_cache.pop(key, None)

        # Clear Redis
        redis = await self._get_redis_client()
        if redis:
            try:
                await redis.delete(self._get_redis_key("team", email))
                # Delete context keys
                pattern = self._get_redis_key("ctx", f"{email}:*")
                async for key in redis.scan_iter(match=pattern):
                    await redis.delete(key)

                # Publish invalidation
                await redis.publish("mcpgw:auth:invalidate", f"team:{email}")
            except Exception as e:
                logger.warning(f"AuthCache Redis invalidate_team failed: {e}")

    async def get_user_role(self, email: str, team_id: str) -> Optional[str]:
        """Get cached user role in a team.

        Returns:
            - None: Cache miss (caller should check DB)
            - "": User is not a member of the team (cached negative result)
            - Role string: User's role in the team (cached)

        Args:
            email: User email
            team_id: Team ID

        Examples:
            >>> import asyncio
            >>> cache = AuthCache()
            >>> result = asyncio.run(cache.get_user_role("test@example.com", "team-123"))
            >>> result is None  # Cache miss
            True
        """
        if not self._enabled:
            return None

        cache_key = f"{email}:{team_id}"

        # Check L1 in-memory cache first (no network I/O)
        entry = self._role_cache.get(cache_key)
        if entry and not entry.is_expired():
            self._hit_count += 1
            # Return empty string for None (not a member) to distinguish from cache miss
            return "" if entry.value is None else entry.value

        # Check L2 Redis cache
        redis = await self._get_redis_client()
        if redis:
            try:
                redis_key = self._get_redis_key("role", cache_key)
                data = await redis.get(redis_key)
                if data is not None:
                    self._hit_count += 1
                    self._redis_hit_count += 1
                    # Role is stored as plain string, decode it
                    decoded = data.decode() if isinstance(data, bytes) else data
                    # Convert sentinel to empty string (user is not a member)
                    role_value = "" if decoded == _NOT_A_MEMBER_SENTINEL else decoded

                    # Write-through: populate L1 from Redis hit
                    # Store as None for not-a-member to match existing L1 storage format
                    with self._lock:
                        self._role_cache[cache_key] = CacheEntry(
                            value=None if role_value == "" else role_value,
                            expiry=time.time() + self._role_ttl,
                        )

                    return role_value
                self._redis_miss_count += 1
            except Exception as e:
                logger.warning(f"AuthCache Redis get_user_role failed: {e}")

        self._miss_count += 1
        return None

    async def set_user_role(self, email: str, team_id: str, role: Optional[str]) -> None:
        """Store user role in cache.

        Args:
            email: User email
            team_id: Team ID
            role: User's role in the team (or None if not a member)

        Examples:
            >>> import asyncio
            >>> cache = AuthCache()
            >>> asyncio.run(cache.set_user_role("test@example.com", "team-123", "admin"))
        """
        if not self._enabled:
            return

        cache_key = f"{email}:{team_id}"
        # Store None as sentinel value to distinguish "not a member" from cache miss
        role_value = role if role is not None else _NOT_A_MEMBER_SENTINEL

        # Store in Redis
        redis = await self._get_redis_client()
        if redis:
            try:
                redis_key = self._get_redis_key("role", cache_key)
                await redis.setex(redis_key, self._role_ttl, role_value)
            except Exception as e:
                logger.warning(f"AuthCache Redis set_user_role failed: {e}")

        # Store in in-memory cache
        with self._lock:
            self._role_cache[cache_key] = CacheEntry(
                value=role,
                expiry=time.time() + self._role_ttl,
            )

    async def invalidate_user_role(self, email: str, team_id: str) -> None:
        """Invalidate cached role for a user in a team.

        Call this when a user's role changes in a team.

        Args:
            email: User email
            team_id: Team ID

        Examples:
            >>> import asyncio
            >>> cache = AuthCache()
            >>> asyncio.run(cache.invalidate_user_role("test@example.com", "team-123"))
        """
        logger.debug(f"AuthCache: Invalidating role cache for {email} in team {team_id}")

        cache_key = f"{email}:{team_id}"

        # Clear in-memory cache
        with self._lock:
            self._role_cache.pop(cache_key, None)

        # Clear Redis
        redis = await self._get_redis_client()
        if redis:
            try:
                await redis.delete(self._get_redis_key("role", cache_key))
                # Publish invalidation for other workers
                await redis.publish("mcpgw:auth:invalidate", f"role:{email}:{team_id}")
            except Exception as e:
                logger.warning(f"AuthCache Redis invalidate_user_role failed: {e}")

    async def invalidate_team_roles(self, team_id: str) -> None:
        """Invalidate all cached roles for a team.

        Call this when team membership changes significantly (e.g., team deletion).

        Args:
            team_id: Team ID

        Examples:
            >>> import asyncio
            >>> cache = AuthCache()
            >>> asyncio.run(cache.invalidate_team_roles("team-123"))
        """
        logger.debug(f"AuthCache: Invalidating all role caches for team {team_id}")

        # Clear in-memory cache entries for this team
        with self._lock:
            keys_to_remove = [k for k in self._role_cache if k.endswith(f":{team_id}")]
            for key in keys_to_remove:
                self._role_cache.pop(key, None)

        # Clear Redis
        redis = await self._get_redis_client()
        if redis:
            try:
                # Pattern match all role keys for this team
                pattern = self._get_redis_key("role", f"*:{team_id}")
                async for key in redis.scan_iter(match=pattern):
                    await redis.delete(key)
                # Publish invalidation
                await redis.publish("mcpgw:auth:invalidate", f"team_roles:{team_id}")
            except Exception as e:
                logger.warning(f"AuthCache Redis invalidate_team_roles failed: {e}")

    async def get_user_teams(self, cache_key: str) -> Optional[List[str]]:
        """Get cached team IDs for a user.

        The cache_key should be in the format "email:include_personal" to
        distinguish between calls with different include_personal flags.

        Returns:
            - None: Cache miss (caller should query DB)
            - Empty list: User has no teams (cached result)
            - List of team IDs: Cached team IDs

        Args:
            cache_key: Cache key in format "email:include_personal"

        Examples:
            >>> import asyncio
            >>> cache = AuthCache()
            >>> result = asyncio.run(cache.get_user_teams("test@example.com:True"))
            >>> result is None  # Cache miss
            True
        """
        if not self._enabled or not self._teams_list_enabled:
            return None

        # Check L1 in-memory cache first (no network I/O)
        entry = self._teams_list_cache.get(cache_key)
        if entry and not entry.is_expired():
            self._hit_count += 1
            return entry.value

        # Check L2 Redis cache
        redis = await self._get_redis_client()
        if redis:
            try:
                redis_key = self._get_redis_key("teams", cache_key)
                data = await redis.get(redis_key)
                if data is not None:
                    self._hit_count += 1
                    self._redis_hit_count += 1
                    # Third-Party
                    import orjson  # pylint: disable=import-outside-toplevel

                    team_ids = orjson.loads(data)

                    # Write-through: populate L1 from Redis hit
                    with self._lock:
                        self._teams_list_cache[cache_key] = CacheEntry(
                            value=team_ids,
                            expiry=time.time() + self._teams_list_ttl,
                        )

                    return team_ids
                self._redis_miss_count += 1
            except Exception as e:
                logger.warning(f"AuthCache Redis get_user_teams failed: {e}")

        self._miss_count += 1
        return None

    async def set_user_teams(self, cache_key: str, team_ids: List[str]) -> None:
        """Store team IDs for a user in cache.

        Args:
            cache_key: Cache key in format "email:include_personal"
            team_ids: List of team IDs the user belongs to

        Examples:
            >>> import asyncio
            >>> cache = AuthCache()
            >>> asyncio.run(cache.set_user_teams("test@example.com:True", ["team-1", "team-2"]))
        """
        if not self._enabled or not self._teams_list_enabled:
            return

        # Store in Redis
        redis = await self._get_redis_client()
        if redis:
            try:
                # Third-Party
                import orjson  # pylint: disable=import-outside-toplevel

                redis_key = self._get_redis_key("teams", cache_key)
                await redis.setex(redis_key, self._teams_list_ttl, orjson.dumps(team_ids))
            except Exception as e:
                logger.warning(f"AuthCache Redis set_user_teams failed: {e}")

        # Store in in-memory cache
        with self._lock:
            self._teams_list_cache[cache_key] = CacheEntry(
                value=team_ids,
                expiry=time.time() + self._teams_list_ttl,
            )

    async def invalidate_user_teams(self, email: str) -> None:
        """Invalidate cached teams list for a user.

        Call this when a user's team membership changes (add/remove member,
        delete team, approve join request).

        This invalidates both include_personal=True and include_personal=False
        cache entries for the user.

        Args:
            email: User email whose teams cache should be invalidated

        Examples:
            >>> import asyncio
            >>> cache = AuthCache()
            >>> asyncio.run(cache.invalidate_user_teams("test@example.com"))
        """
        logger.debug(f"AuthCache: Invalidating teams list cache for {email}")

        # Clear in-memory cache entries for this user (both True and False variants)
        with self._lock:
            keys_to_remove = [k for k in self._teams_list_cache if k.startswith(f"{email}:")]
            for key in keys_to_remove:
                self._teams_list_cache.pop(key, None)

        # Clear Redis
        redis = await self._get_redis_client()
        if redis:
            try:
                # Delete both variants
                await redis.delete(
                    self._get_redis_key("teams", f"{email}:True"),
                    self._get_redis_key("teams", f"{email}:False"),
                )
                # Publish invalidation for other workers
                await redis.publish("mcpgw:auth:invalidate", f"teams:{email}")
            except Exception as e:
                logger.warning(f"AuthCache Redis invalidate_user_teams failed: {e}")

    # =========================================================================
    # Team Membership Validation Cache
    # =========================================================================
    # Used by TokenScopingMiddleware to cache email_team_members lookups.
    # This prevents repeated DB queries for the same user+teams combination.

    def get_team_membership_valid_sync(self, user_email: str, team_ids: List[str]) -> Optional[bool]:
        """Get cached team membership validation result (synchronous).

        This is the synchronous version used by token_scoping middleware.
        Returns None on cache miss (caller should check DB).

        Args:
            user_email: User email
            team_ids: List of team IDs to validate membership for

        Returns:
            - None: Cache miss (caller should query DB)
            - True: User is valid member of all teams (cached)
            - False: User is NOT a valid member of all teams (cached)

        Examples:
            >>> cache = AuthCache()
            >>> result = cache.get_team_membership_valid_sync("test@example.com", ["team-1"])
            >>> result is None  # Cache miss
            True
        """
        if not self._enabled or not team_ids:
            return None

        # Create cache key from user + sorted team IDs
        sorted_teams = ":".join(sorted(team_ids))
        cache_key = f"{user_email}:{sorted_teams}"

        # Check in-memory cache only (sync version)
        entry = self._team_cache.get(cache_key)
        if entry and not entry.is_expired():
            self._hit_count += 1
            return entry.value

        self._miss_count += 1
        return None

    def set_team_membership_valid_sync(self, user_email: str, team_ids: List[str], valid: bool) -> None:
        """Store team membership validation result in cache (synchronous).

        Args:
            user_email: User email
            team_ids: List of team IDs that were validated
            valid: Whether user is a valid member of all teams

        Examples:
            >>> cache = AuthCache()
            >>> cache.set_team_membership_valid_sync("test@example.com", ["team-1"], True)
        """
        if not self._enabled or not team_ids:
            return

        # Create cache key from user + sorted team IDs
        sorted_teams = ":".join(sorted(team_ids))
        cache_key = f"{user_email}:{sorted_teams}"

        # Store in in-memory cache
        with self._lock:
            self._team_cache[cache_key] = CacheEntry(
                value=valid,
                expiry=time.time() + self._team_ttl,
            )

    async def get_team_membership_valid(self, user_email: str, team_ids: List[str]) -> Optional[bool]:
        """Get cached team membership validation result (async).

        Returns None on cache miss (caller should check DB).

        Args:
            user_email: User email
            team_ids: List of team IDs to validate membership for

        Returns:
            - None: Cache miss (caller should query DB)
            - True: User is valid member of all teams (cached)
            - False: User is NOT a valid member of all teams (cached)

        Examples:
            >>> import asyncio
            >>> cache = AuthCache()
            >>> result = asyncio.run(cache.get_team_membership_valid("test@example.com", ["team-1"]))
            >>> result is None  # Cache miss
            True
        """
        if not self._enabled or not team_ids:
            return None

        # Create cache key from user + sorted team IDs
        sorted_teams = ":".join(sorted(team_ids))
        cache_key = f"{user_email}:{sorted_teams}"

        # Check L1 in-memory cache first (no network I/O)
        entry = self._team_cache.get(cache_key)
        if entry and not entry.is_expired():
            self._hit_count += 1
            return entry.value

        # Check L2 Redis cache
        redis = await self._get_redis_client()
        if redis:
            try:
                redis_key = self._get_redis_key("membership", cache_key)
                data = await redis.get(redis_key)
                if data is not None:
                    self._hit_count += 1
                    self._redis_hit_count += 1
                    # Stored as "1" for True, "0" for False
                    decoded = data.decode() if isinstance(data, bytes) else data
                    result = decoded == "1"

                    # Write-through: populate L1 from Redis hit
                    with self._lock:
                        self._team_cache[cache_key] = CacheEntry(
                            value=result,
                            expiry=time.time() + self._team_ttl,
                        )

                    return result
                self._redis_miss_count += 1
            except Exception as e:
                logger.warning(f"AuthCache Redis get_team_membership_valid failed: {e}")

        self._miss_count += 1
        return None

    async def set_team_membership_valid(self, user_email: str, team_ids: List[str], valid: bool) -> None:
        """Store team membership validation result in cache (async).

        Args:
            user_email: User email
            team_ids: List of team IDs that were validated
            valid: Whether user is a valid member of all teams

        Examples:
            >>> import asyncio
            >>> cache = AuthCache()
            >>> asyncio.run(cache.set_team_membership_valid("test@example.com", ["team-1"], True))
        """
        if not self._enabled or not team_ids:
            return

        # Create cache key from user + sorted team IDs
        sorted_teams = ":".join(sorted(team_ids))
        cache_key = f"{user_email}:{sorted_teams}"

        # Store in Redis
        redis = await self._get_redis_client()
        if redis:
            try:
                redis_key = self._get_redis_key("membership", cache_key)
                # Store as "1" for True, "0" for False
                await redis.setex(redis_key, self._team_ttl, "1" if valid else "0")
            except Exception as e:
                logger.warning(f"AuthCache Redis set_team_membership_valid failed: {e}")

        # Store in in-memory cache
        with self._lock:
            self._team_cache[cache_key] = CacheEntry(
                value=valid,
                expiry=time.time() + self._team_ttl,
            )

    async def invalidate_team_membership(self, user_email: str) -> None:
        """Invalidate team membership cache for a user.

        Call this when a user's team membership changes (add/remove member,
        role change, deactivation).

        Args:
            user_email: User email whose membership cache should be invalidated

        Examples:
            >>> import asyncio
            >>> cache = AuthCache()
            >>> asyncio.run(cache.invalidate_team_membership("test@example.com"))
        """
        logger.debug(f"AuthCache: Invalidating team membership cache for {user_email}")

        # Clear in-memory cache entries for this user
        with self._lock:
            keys_to_remove = [k for k in self._team_cache if k.startswith(f"{user_email}:")]
            for key in keys_to_remove:
                self._team_cache.pop(key, None)

        # Clear Redis
        redis = await self._get_redis_client()
        if redis:
            try:
                # Pattern match all membership keys for this user
                pattern = self._get_redis_key("membership", f"{user_email}:*")
                async for key in redis.scan_iter(match=pattern):
                    await redis.delete(key)
                # Publish invalidation for other workers
                await redis.publish("mcpgw:auth:invalidate", f"membership:{user_email}")
            except Exception as e:
                logger.warning(f"AuthCache Redis invalidate_team_membership failed: {e}")

    async def is_token_revoked(self, jti: str) -> Optional[bool]:
        """Check if a token is revoked (cached check only).

        Returns None on cache miss (caller should check DB).

        Args:
            jti: JWT ID to check

        Returns:
            True if revoked, False if not revoked, None if unknown

        Examples:
            >>> import asyncio
            >>> cache = AuthCache()
            >>> cache._revoked_jtis.add("revoked-jti")
            >>> asyncio.run(cache.is_token_revoked("revoked-jti"))
            True
        """
        if not self._enabled:
            return None

        # Fast local check
        if jti in self._revoked_jtis:
            return True

        # Check L1 in-memory revocation cache
        entry = self._revocation_cache.get(jti)
        if entry and not entry.is_expired():
            return entry.value

        # Check L2 Redis
        redis = await self._get_redis_client()
        if redis:
            try:
                # Check revoked tokens set
                if await redis.sismember("mcpgw:auth:revoked_tokens", jti):
                    # Add to local set for faster future lookups
                    with self._lock:
                        self._revoked_jtis.add(jti)
                        # Write-through: populate L1 revocation cache
                        self._revocation_cache[jti] = CacheEntry(
                            value=True,
                            expiry=time.time() + self._revocation_ttl,
                        )
                    return True

                # Check individual revocation key
                if await redis.exists(self._get_redis_key("revoke", jti)):
                    with self._lock:
                        self._revoked_jtis.add(jti)
                        # Write-through: populate L1 revocation cache
                        self._revocation_cache[jti] = CacheEntry(
                            value=True,
                            expiry=time.time() + self._revocation_ttl,
                        )
                    return True
            except Exception as e:
                logger.warning(f"AuthCache Redis is_token_revoked failed: {e}")

        return None

    async def sync_revoked_tokens(self) -> None:
        """Sync revoked tokens from database to cache on startup.

        Should be called during application startup to populate the
        revocation cache.

        Examples:
            >>> import asyncio
            >>> cache = AuthCache()
            >>> asyncio.run(cache.sync_revoked_tokens())
        """
        if not self._enabled:
            return

        try:
            # Third-Party
            from sqlalchemy import select  # pylint: disable=import-outside-toplevel

            # First-Party
            from mcpgateway.db import fresh_db_session, TokenRevocation  # pylint: disable=import-outside-toplevel

            def _load_revoked_jtis() -> Set[str]:
                """Load all revoked JTIs from database.

                Returns:
                    Set of revoked JTI strings.
                """
                with fresh_db_session() as db:
                    result = db.execute(select(TokenRevocation.jti))
                    return {row[0] for row in result}

            jtis = await asyncio.to_thread(_load_revoked_jtis)

            with self._lock:
                self._revoked_jtis.update(jtis)

            # Also sync to Redis
            redis = await self._get_redis_client()
            if redis and jtis:
                try:
                    await redis.sadd("mcpgw:auth:revoked_tokens", *jtis)
                except Exception as e:
                    logger.warning(f"AuthCache Redis sync_revoked_tokens failed: {e}")

            logger.info(f"AuthCache: Synced {len(jtis)} revoked tokens to cache")

        except Exception as e:
            logger.warning(f"AuthCache sync_revoked_tokens failed: {e}")

    def invalidate_all(self) -> None:
        """Invalidate all cached data.

        Call during testing or when major configuration changes.

        Examples:
            >>> cache = AuthCache()
            >>> cache.invalidate_all()
        """
        with self._lock:
            self._user_cache.clear()
            self._team_cache.clear()
            self._revocation_cache.clear()
            self._context_cache.clear()
            self._role_cache.clear()
            self._teams_list_cache.clear()
            # Don't clear _revoked_jtis as those are confirmed revocations

        logger.info("AuthCache: All caches invalidated")

    def stats(self) -> Dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dictionary with hit/miss counts and hit rate

        Examples:
            >>> cache = AuthCache()
            >>> stats = cache.stats()
            >>> "hit_count" in stats
            True
        """
        total = self._hit_count + self._miss_count
        redis_total = self._redis_hit_count + self._redis_miss_count

        return {
            "enabled": self._enabled,
            "hit_count": self._hit_count,
            "miss_count": self._miss_count,
            "hit_rate": self._hit_count / total if total > 0 else 0.0,
            "redis_hit_count": self._redis_hit_count,
            "redis_miss_count": self._redis_miss_count,
            "redis_hit_rate": self._redis_hit_count / redis_total if redis_total > 0 else 0.0,
            "redis_available": self._redis_available,
            "revoked_tokens_cached": len(self._revoked_jtis),
            "context_cache_size": len(self._context_cache),
            "role_cache_size": len(self._role_cache),
            "teams_list_cache_size": len(self._teams_list_cache),
            "team_membership_cache_size": len(self._team_cache),
            "user_ttl": self._user_ttl,
            "revocation_ttl": self._revocation_ttl,
            "team_ttl": self._team_ttl,
            "role_ttl": self._role_ttl,
            "teams_list_enabled": self._teams_list_enabled,
            "teams_list_ttl": self._teams_list_ttl,
        }

    def reset_stats(self) -> None:
        """Reset hit/miss counters.

        Examples:
            >>> cache = AuthCache()
            >>> cache._hit_count = 100
            >>> cache.reset_stats()
            >>> cache._hit_count
            0
        """
        self._hit_count = 0
        self._miss_count = 0
        self._redis_hit_count = 0
        self._redis_miss_count = 0


# Global singleton instance
_auth_cache: Optional[AuthCache] = None


def get_auth_cache() -> AuthCache:
    """Get or create the singleton AuthCache instance.

    Returns:
        AuthCache: The singleton auth cache instance

    Examples:
        >>> cache = get_auth_cache()
        >>> isinstance(cache, AuthCache)
        True
    """
    global _auth_cache  # pylint: disable=global-statement
    if _auth_cache is None:
        _auth_cache = AuthCache()
    return _auth_cache


# Convenience alias for direct import
auth_cache = get_auth_cache()
