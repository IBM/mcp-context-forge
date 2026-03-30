# -*- coding: utf-8 -*-
"""Centralized Redis client factory for consistent configuration.

This module provides a single source of truth for Redis client creation,
ensuring all services use the same connection pool and settings.

Supports both standalone Redis and Redis Cluster deployments. When
``REDIS_CLUSTER_MODE=true``, the factory creates a
``redis.asyncio.RedisCluster`` client that handles MOVED/ASK redirects
automatically. Otherwise it creates a standard ``redis.asyncio.Redis``
client via ``from_url``.

Performance: Uses hiredis C parser by default (ADR-026) for up to 83x faster
response parsing on large responses. Falls back to pure-Python parser if
hiredis is unavailable or explicitly disabled via REDIS_PARSER setting.

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
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Track which parser is being used for logging
_parser_info: Optional[str] = None

_client: Optional[Any] = None
_initialized: bool = False


def _is_hiredis_available() -> bool:
    """Check if hiredis library is available and functional.

    Returns:
        bool: True if hiredis can be used, False otherwise.
    """
    try:
        # Third-Party
        import hiredis  # noqa: F401

        return True
    except ImportError:
        return False


def _get_async_parser_class(parser_setting: str) -> tuple[Any, str]:
    """Get the appropriate async Redis parser class based on settings.

    Args:
        parser_setting: One of "auto", "hiredis", or "python"

    Returns:
        Tuple of (parser_class or None, parser_name) where parser_class is None
        for auto-detection (redis-py default behavior)

    Raises:
        ImportError: If hiredis is required but not available
    """
    if parser_setting == "python":
        # Force pure-Python async parser
        # Third-Party
        from redis._parsers import _AsyncRESP2Parser

        return _AsyncRESP2Parser, "AsyncRESP2Parser (pure-Python)"

    if parser_setting == "hiredis":
        # Require hiredis - fail if not available
        if not _is_hiredis_available():
            raise ImportError("REDIS_PARSER=hiredis requires hiredis to be installed. " "Install with: pip install 'redis[hiredis]'")
        # Don't set parser_class explicitly - let redis-py auto-detect for async
        # Setting _AsyncHiredisParser explicitly can cause issues
        return None, "AsyncHiredisParser (C extension)"

    # "auto" mode - let redis-py auto-detect (prefers hiredis if available)
    if _is_hiredis_available():
        return None, "AsyncHiredisParser (C extension, auto-detected)"
    return None, "AsyncRESP2Parser (pure-Python, auto-detected)"


def _strip_db_from_url(url: str) -> str:
    """Remove the database number from a Redis URL for cluster mode.

    Redis Cluster only supports database 0.  If the URL contains ``/0`` it is
    silently stripped.  If it contains a non-zero database (``/1``, ``/2``, …)
    a ``ValueError`` is raised so that misconfigurations fail fast instead of
    being silently ignored.

    Args:
        url: Redis connection URL, e.g. ``redis://:pass@host:6379/0``

    Returns:
        URL without the trailing database path, e.g. ``redis://:pass@host:6379``

    Raises:
        ValueError: If the URL specifies a non-zero database number.

    Examples:
        >>> _strip_db_from_url("redis://:pass@host:6379/0")
        'redis://:pass@host:6379'
        >>> _strip_db_from_url("redis://:pass@host:6379")
        'redis://:pass@host:6379'
        >>> _strip_db_from_url("redis://:pass@host:6379/1")
        Traceback (most recent call last):
            ...
        ValueError: Redis Cluster only supports database 0, but REDIS_URL specifies /1. Remove the database selector or use /0.
    """
    parsed = urlparse(url)
    if parsed.path and parsed.path not in ("", "/"):
        db_str = parsed.path.lstrip("/")
        if db_str and db_str != "0":
            raise ValueError(
                f"Redis Cluster only supports database 0, but REDIS_URL "
                f"specifies /{db_str}. Remove the database selector or use /0."
            )
        cleaned = parsed._replace(path="")
        return cleaned.geturl()
    return url


def _mask_redis_url(url: str) -> str:
    """Mask credentials in a Redis URL for safe logging.

    Replaces the password portion of the URL with ``***`` so that
    connection details can be logged without leaking secrets.

    Args:
        url: Redis connection URL, e.g. ``redis://:secret@host:6379``

    Returns:
        Masked URL, e.g. ``redis://:***@host:6379``

    Examples:
        >>> _mask_redis_url("redis://:secret@host:6379")
        'redis://:***@host:6379'
        >>> _mask_redis_url("redis://host:6379")
        'redis://host:6379'
        >>> _mask_redis_url("redis://user:pass@host:6379")
        'redis://user:***@host:6379'
    """
    parsed = urlparse(url)
    if parsed.password:
        # Replace password in netloc
        masked_netloc = parsed.netloc.replace(f":{parsed.password}@", ":***@", 1)
        return parsed._replace(netloc=masked_netloc).geturl()
    return url


async def _create_cluster_client(settings: Any, aioredis: Any, parser_class: Any) -> Any:
    """Create a ``redis.asyncio.RedisCluster`` client.

    Args:
        settings: Application settings object.
        aioredis: The ``redis.asyncio`` module.
        parser_class: Optional parser class override (or *None* for auto).

    Returns:
        An initialised ``RedisCluster`` async client.
    """
    url = _strip_db_from_url(settings.redis_url)

    # RedisCluster accepts a subset of the standalone kwargs.
    # ``max_connections`` and ``single_connection_client`` are not valid here;
    # the cluster client manages per-node connection pools internally.
    cluster_kwargs: dict[str, Any] = {
        "decode_responses": settings.redis_decode_responses,
        "socket_timeout": settings.redis_socket_timeout,
        "socket_connect_timeout": settings.redis_socket_connect_timeout,
        "retry_on_timeout": settings.redis_retry_on_timeout,
        "encoding": "utf-8",
    }

    if parser_class is not None:
        cluster_kwargs["parser_class"] = parser_class

    client = aioredis.RedisCluster.from_url(url, **cluster_kwargs)
    await client.ping()
    return client


async def _create_standalone_client(settings: Any, aioredis: Any, parser_class: Any) -> Any:
    """Create a standard ``redis.asyncio.Redis`` client.

    Args:
        settings: Application settings object.
        aioredis: The ``redis.asyncio`` module.
        parser_class: Optional parser class override (or *None* for auto).

    Returns:
        An initialised ``Redis`` async client.
    """
    connection_kwargs: dict[str, Any] = {
        "decode_responses": settings.redis_decode_responses,
        "max_connections": settings.redis_max_connections,
        "socket_timeout": settings.redis_socket_timeout,
        "socket_connect_timeout": settings.redis_socket_connect_timeout,
        "retry_on_timeout": settings.redis_retry_on_timeout,
        "health_check_interval": settings.redis_health_check_interval,
        "encoding": "utf-8",
        "single_connection_client": False,
    }

    if parser_class is not None:
        connection_kwargs["parser_class"] = parser_class

    client = aioredis.from_url(settings.redis_url, **connection_kwargs)
    await client.ping()
    return client


async def get_redis_client() -> Optional[Any]:
    """Get or create the shared async Redis client.

    When ``REDIS_CLUSTER_MODE`` is enabled the factory returns a
    ``redis.asyncio.RedisCluster`` instance that transparently handles
    MOVED/ASK redirects across cluster shards.  Otherwise a standard
    ``redis.asyncio.Redis`` client is returned.

    Uses hiredis C parser by default for up to 83x faster response parsing.
    Parser selection controlled by REDIS_PARSER setting (auto/hiredis/python).

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
    global _client, _initialized, _parser_info

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
        # Get parser configuration (ADR-026)
        parser_class, _parser_info = _get_async_parser_class(settings.redis_parser)

        cluster_mode = getattr(settings, "redis_cluster_mode", False)

        if cluster_mode:
            _client = await _create_cluster_client(settings, aioredis, parser_class)
            logger.info(
                f"Redis Cluster client initialized: parser={_parser_info}, "
                f"timeout={settings.redis_socket_timeout}s, "
                f"url={_mask_redis_url(_strip_db_from_url(settings.redis_url))}"
            )
        else:
            _client = await _create_standalone_client(settings, aioredis, parser_class)
            logger.info(
                f"Redis client initialized: parser={_parser_info}, "
                f"pool_size={settings.redis_max_connections}, "
                f"timeout={settings.redis_socket_timeout}s, "
                f"health_check={settings.redis_health_check_interval}s"
            )
    except ImportError as e:
        logger.error(f"Redis parser configuration error: {e}")
        _client = None
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


def get_redis_parser_info() -> Optional[str]:
    """Get information about which Redis parser is being used.

    Returns:
        Optional[str]: Parser description string, or None if Redis not initialized.
    """
    return _parser_info


def _reset_client() -> None:
    """Reset client state (for testing only)."""
    global _client, _initialized, _parser_info
    _client = None
    _initialized = False
    _parser_info = None
