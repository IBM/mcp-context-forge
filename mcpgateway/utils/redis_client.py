# -*- coding: utf-8 -*-
"""Centralized Redis client factory for consistent configuration.

This module provides a single source of truth for Redis client creation,
ensuring all services use the same connection pool and settings.

SPDX-License-Identifier: Apache-2.0

Usage:
    from mcpgateway.utils.redis_client import get_redis_client, close_redis_client

    # In async context:
    client = await get_redis_client()
    if client:
        await client.set("key", "value")

    # On shutdown:
    await close_redis_client()
"""

# Standard
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

_client: Optional[Any] = None
_initialized: bool = False


async def get_redis_client() -> Optional[Any]:
    """Get or create the shared async Redis client.

    Returns:
        Optional[Redis]: Async Redis client, or None if Redis is disabled/unavailable.

    Examples:
        >>> import asyncio
        >>> # When Redis is disabled
        >>> async def test_disabled():
        ...     from mcpgateway.config import settings
        ...     original = settings.cache_type
        ...     settings.cache_type = "memory"
        ...     from mcpgateway.utils.redis_client import get_redis_client, _reset_client
        ...     _reset_client()
        ...     client = await get_redis_client()
        ...     settings.cache_type = original
        ...     _reset_client()
        ...     return client is None
        >>> asyncio.run(test_disabled())
        True
    """
    global _client, _initialized

    if _initialized:
        return _client

    # First-Party
    from mcpgateway.config import settings

    if settings.cache_type != "redis" or not settings.redis_url:
        logger.info("Redis disabled (cache_type != 'redis' or no redis_url)")
        _initialized = True
        return None

    try:
        # Third-Party
        import redis.asyncio as aioredis
    except ImportError:
        logger.warning("redis.asyncio not available, Redis disabled")
        _initialized = True
        return None

    try:
        _client = aioredis.from_url(
            settings.redis_url,
            decode_responses=settings.redis_decode_responses,
            max_connections=settings.redis_max_connections,
            socket_timeout=settings.redis_socket_timeout,
            socket_connect_timeout=settings.redis_socket_connect_timeout,
            retry_on_timeout=settings.redis_retry_on_timeout,
            health_check_interval=settings.redis_health_check_interval,
            encoding="utf-8",
            single_connection_client=False,
        )
        await _client.ping()
        logger.info(f"Redis client initialized: pool_size={settings.redis_max_connections}, " f"timeout={settings.redis_socket_timeout}s, health_check={settings.redis_health_check_interval}s")
    except Exception as e:
        logger.warning(f"Failed to connect to Redis: {e}")
        _client = None

    _initialized = True
    return _client


async def close_redis_client() -> None:
    """Close the shared Redis client and release connections."""
    global _client, _initialized

    if _client:
        try:
            await _client.aclose()
            logger.info("Redis client closed")
        except Exception as e:
            logger.warning(f"Error closing Redis client: {e}")

    _client = None
    _initialized = False


def get_redis_client_sync() -> Optional[Any]:
    """Get cached Redis client synchronously (returns None if not initialized).

    This is useful for non-async contexts that need to check if Redis is available,
    but should not be used to initialize the client.

    Returns:
        Optional[Redis]: The cached Redis client, or None if not initialized.
    """
    return _client


async def is_redis_available() -> bool:
    """Check if Redis is available and connected.

    Returns:
        bool: True if Redis is available and responding to ping.

    Examples:
        >>> import asyncio
        >>> async def test_unavailable():
        ...     from mcpgateway.config import settings
        ...     original = settings.cache_type
        ...     settings.cache_type = "memory"
        ...     from mcpgateway.utils.redis_client import is_redis_available, _reset_client
        ...     _reset_client()
        ...     result = await is_redis_available()
        ...     settings.cache_type = original
        ...     _reset_client()
        ...     return result
        >>> asyncio.run(test_unavailable())
        False
    """
    client = await get_redis_client()
    if not client:
        return False
    try:
        await client.ping()
        return True
    except Exception:
        return False


def _reset_client() -> None:
    """Reset client state (for testing only)."""
    global _client, _initialized
    _client = None
    _initialized = False
