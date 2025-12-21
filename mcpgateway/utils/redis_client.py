# -*- coding: utf-8 -*-
"""Centralized Redis client factory for consistent configuration.

This module provides a single source of truth for Redis client creation,
ensuring all services use the same connection pool and settings.

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


async def get_redis_client() -> Optional[Any]:
    """Get or create the shared async Redis client.

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

        # Build connection kwargs
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

        # Only specify parser_class if explicitly set (not auto)
        if parser_class is not None:
            connection_kwargs["parser_class"] = parser_class

        _client = aioredis.from_url(settings.redis_url, **connection_kwargs)
        await _client.ping()
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
