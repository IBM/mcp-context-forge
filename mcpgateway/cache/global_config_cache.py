# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/cache/global_config_cache.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

GlobalConfig In-Memory Cache.

This module implements a thread-safe in-memory cache for GlobalConfig with TTL expiration.
GlobalConfig is a singleton configuration table that stores passthrough headers settings.
Since this data rarely changes (admin configuration), caching it in memory eliminates
thousands of redundant database queries under load.

Performance Impact:
    - Before: 42,000+ DB queries per load test for 0-1 row table
    - After: 1 DB query per TTL period (default 60 seconds)

Security Considerations:
    - Stale config window: Changes take up to TTL to propagate
    - Mitigation: Admin UI should call invalidate() after config changes
    - Cache poisoning: Not applicable (populated from DB only)
    - Information leakage: Not applicable (stores header names only, not values)

Examples:
    >>> from unittest.mock import Mock, patch
    >>> from mcpgateway.cache.global_config_cache import GlobalConfigCache

    >>> # Test cache miss and hit
    >>> cache = GlobalConfigCache(ttl_seconds=60)
    >>> mock_db = Mock()
    >>> mock_config = Mock()
    >>> mock_config.passthrough_headers = ["Authorization", "X-Request-ID"]
    >>> mock_db.query.return_value.first.return_value = mock_config

    >>> # First call - cache miss, queries DB
    >>> result = cache.get(mock_db)
    >>> result.passthrough_headers
    ['Authorization', 'X-Request-ID']
    >>> mock_db.query.return_value.first.call_count
    1

    >>> # Second call - cache hit, no DB query
    >>> result = cache.get(mock_db)
    >>> mock_db.query.return_value.first.call_count
    1

    >>> # After invalidation - queries DB again
    >>> cache.invalidate()
    >>> result = cache.get(mock_db)
    >>> mock_db.query.return_value.first.call_count
    2
"""

# Standard
import logging
import threading
import time

# Use standard logging to avoid circular imports with services
logger = logging.getLogger(__name__)


class GlobalConfigCache:
    """
    Thread-safe in-memory cache for GlobalConfig with TTL.

    This cache stores the GlobalConfig singleton to avoid repeated database queries.
    GlobalConfig contains passthrough headers configuration that rarely changes.

    Attributes:
        ttl_seconds: Time-to-live in seconds before cache refresh
        _cache: Cached GlobalConfig object (or None)
        _expiry: Timestamp when cache expires
        _lock: Threading lock for thread-safe operations

    Examples:
        >>> from unittest.mock import Mock
        >>> cache = GlobalConfigCache(ttl_seconds=60)
        >>> mock_db = Mock()
        >>> mock_db.query.return_value.first.return_value = None

        >>> # Returns None when no GlobalConfig exists
        >>> cache.get(mock_db) is None
        True

        >>> # get_passthrough_headers returns default when no config
        >>> cache.get_passthrough_headers(mock_db, ["Default-Header"])
        ['Default-Header']
    """

    # Sentinel value to distinguish "not cached" from "cached None"
    _NOT_CACHED = object()

    def __init__(self, ttl_seconds: int = 60):
        """
        Initialize the GlobalConfig cache.

        Args:
            ttl_seconds: Time-to-live in seconds (default: 60).
                        After this duration, the cache will refresh from DB.

        Examples:
            >>> cache = GlobalConfigCache(ttl_seconds=30)
            >>> cache.ttl_seconds
            30
        """
        self.ttl_seconds = ttl_seconds
        self._cache = self._NOT_CACHED  # Use sentinel to distinguish from cached None
        self._expiry: float = 0
        self._lock = threading.Lock()
        self._hit_count = 0
        self._miss_count = 0

    def get(self, db):
        """
        Get GlobalConfig from cache or database.

        Uses a double-checked locking pattern for thread safety with minimal
        lock contention on the hot path (cache hit).

        Args:
            db: SQLAlchemy database session

        Returns:
            GlobalConfig object or None if not configured

        Examples:
            >>> from unittest.mock import Mock
            >>> cache = GlobalConfigCache(ttl_seconds=60)
            >>> mock_db = Mock()
            >>> mock_config = Mock()
            >>> mock_db.query.return_value.first.return_value = mock_config
            >>> cache.get(mock_db) is mock_config
            True
        """
        now = time.time()

        # Fast path: cache hit (no lock needed for read)
        # Use sentinel check to properly cache None (empty GlobalConfig table)
        if now < self._expiry and self._cache is not self._NOT_CACHED:
            self._hit_count += 1
            return self._cache

        # Slow path: cache miss or expired - acquire lock
        with self._lock:
            # Double-check after acquiring lock (another thread may have refreshed)
            if now < self._expiry and self._cache is not self._NOT_CACHED:
                self._hit_count += 1
                return self._cache

            # Import here to avoid circular imports
            # First-Party
            from mcpgateway.db import GlobalConfig  # pylint: disable=import-outside-toplevel

            # Refresh from database
            self._cache = db.query(GlobalConfig).first()
            self._expiry = now + self.ttl_seconds
            self._miss_count += 1

            if self._cache:
                logger.debug(f"GlobalConfig cache refreshed (TTL: {self.ttl_seconds}s)")
            else:
                logger.debug("GlobalConfig not found in database, using defaults")

            return self._cache

    def get_passthrough_headers(self, db, default: list[str]) -> list[str]:
        """
        Get passthrough headers based on PASSTHROUGH_HEADERS_SOURCE setting.

        Supports three modes:
        - "env": Environment variable always wins (ignore database)
        - "db": Database wins if configured, fallback to env (default, backward compatible)
        - "merge": Union of env and database headers (DB overrides for duplicates)

        Args:
            db: SQLAlchemy database session
            default: Default headers from environment variable (settings.default_passthrough_headers)

        Returns:
            List of allowed passthrough header names

        Examples:
            >>> from unittest.mock import Mock, patch
            >>> cache = GlobalConfigCache(ttl_seconds=60)
            >>> mock_db = Mock()

            >>> # "db" mode (default): When no config exists, returns default
            >>> mock_db.query.return_value.first.return_value = None
            >>> cache.invalidate()  # Clear any cached value
            >>> with patch("mcpgateway.config.settings") as mock_settings:
            ...     mock_settings.passthrough_headers_source = "db"
            ...     cache.get_passthrough_headers(mock_db, ["X-Default"])
            ['X-Default']

            >>> # "env" mode: Always returns default, ignores database
            >>> mock_config = Mock()
            >>> mock_config.passthrough_headers = ["Authorization"]
            >>> mock_db.query.return_value.first.return_value = mock_config
            >>> cache.invalidate()
            >>> with patch("mcpgateway.config.settings") as mock_settings:
            ...     mock_settings.passthrough_headers_source = "env"
            ...     cache.get_passthrough_headers(mock_db, ["X-Default"])
            ['X-Default']

            >>> # "merge" mode: Combines both sources
            >>> cache.invalidate()
            >>> with patch("mcpgateway.config.settings") as mock_settings:
            ...     mock_settings.passthrough_headers_source = "merge"
            ...     result = cache.get_passthrough_headers(mock_db, ["X-Default"])
            ...     "X-Default" in result and "Authorization" in result
            True
        """
        # Import here to avoid circular imports
        # First-Party
        from mcpgateway.config import settings  # pylint: disable=import-outside-toplevel

        source = settings.passthrough_headers_source

        if source == "env":
            # Environment always wins - don't query database at all
            logger.debug("Passthrough headers source=env: using environment variable only")
            return default if default else []

        config = self.get(db)

        if source == "merge":
            # Union of both sources, preserving original casing
            # Use lowercase keys for deduplication, original casing for values
            env_headers = {h.lower(): h for h in (default or [])}
            db_headers = {h.lower(): h for h in (config.passthrough_headers or [])} if config else {}
            # DB values override env for same header (handles case differences)
            merged = {**env_headers, **db_headers}
            result = list(merged.values())
            logger.debug(f"Passthrough headers source=merge: combined {len(result)} headers from env and db")
            return result

        # Default "db" mode - current behavior for backward compatibility
        if config and config.passthrough_headers:
            logger.debug("Passthrough headers source=db: using database configuration")
            return config.passthrough_headers
        logger.debug("Passthrough headers source=db: no database config, using environment default")
        return default

    def invalidate(self) -> None:
        """
        Invalidate the cache, forcing a refresh on next access.

        Call this method after updating GlobalConfig in the database
        to ensure changes propagate immediately.

        Examples:
            >>> cache = GlobalConfigCache(ttl_seconds=60)
            >>> cache._expiry = time.time() + 1000  # Set future expiry
            >>> cache.invalidate()
            >>> cache._expiry
            0
        """
        with self._lock:
            self._cache = self._NOT_CACHED
            self._expiry = 0
            logger.info("GlobalConfig cache invalidated")

    def stats(self) -> dict:
        """
        Get cache statistics.

        Returns:
            Dictionary with hit_count, miss_count, and hit_rate

        Examples:
            >>> cache = GlobalConfigCache(ttl_seconds=60)
            >>> cache._hit_count = 90
            >>> cache._miss_count = 10
            >>> stats = cache.stats()
            >>> stats["hit_rate"]
            0.9
        """
        total = self._hit_count + self._miss_count
        return {
            "hit_count": self._hit_count,
            "miss_count": self._miss_count,
            "hit_rate": self._hit_count / total if total > 0 else 0.0,
            "ttl_seconds": self.ttl_seconds,
            "is_cached": self._cache is not self._NOT_CACHED and time.time() < self._expiry,
        }


# Global singleton instance
# This is the primary interface for accessing cached GlobalConfig
global_config_cache = GlobalConfigCache()
