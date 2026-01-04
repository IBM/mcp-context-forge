# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/http_client_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Shared HTTP Client Service.

This module provides a singleton httpx.AsyncClient that is shared across all
services in MCP Gateway. Using a shared client instead of per-request clients
provides significant performance benefits:

- Connection reuse: Avoids TCP handshake and TLS negotiation per request
- Connection pooling: Manages concurrent connections efficiently
- Configurable limits: Prevents connection exhaustion under high load

Performance benchmarks show ~20x throughput improvement vs per-request clients.

Usage:
    from mcpgateway.services.http_client_service import get_http_client

    # Get the shared client for making requests
    client = await get_http_client()
    response = await client.get("https://example.com/api")

    # For requests needing isolated TLS/auth context (rare):
    async with get_isolated_http_client(verify=custom_ssl_context) as client:
        response = await client.get("https://example.com/api")

Configuration (environment variables):
    HTTPX_MAX_CONNECTIONS: Maximum concurrent connections (default: 200)
    HTTPX_MAX_KEEPALIVE_CONNECTIONS: Idle connections to retain (default: 100)
    HTTPX_KEEPALIVE_EXPIRY: Idle connection timeout in seconds (default: 30)
    HTTPX_CONNECT_TIMEOUT: Connection timeout in seconds (default: 5)
    HTTPX_READ_TIMEOUT: Read timeout in seconds (default: 120, high for slow MCP tools)
    HTTPX_WRITE_TIMEOUT: Write timeout in seconds (default: 30)
    HTTPX_POOL_TIMEOUT: Pool wait timeout in seconds (default: 10)
    HTTPX_HTTP2_ENABLED: Enable HTTP/2 (default: false)
    HTTPX_ADMIN_READ_TIMEOUT: Read timeout for admin operations (default: 30)
"""

# Future
from __future__ import annotations

# Standard
import asyncio
from contextlib import asynccontextmanager
import logging
import ssl
from typing import AsyncIterator, Optional, TYPE_CHECKING

# Third-Party
import httpx

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class SharedHttpClient:
    """
    Singleton wrapper for a shared httpx.AsyncClient.

    All callers share the same client instance and its internal connection pool.
    This avoids the overhead of creating new clients per request while providing
    configurable connection limits.

    The client is initialized lazily on first access and shut down during
    application shutdown via the FastAPI lifespan.
    """

    _instance: Optional["SharedHttpClient"] = None
    _lock: asyncio.Lock = asyncio.Lock()

    def __init__(self) -> None:
        """Initialize the SharedHttpClient wrapper (not the actual client)."""
        self._client: Optional[httpx.AsyncClient] = None
        self._initialized: bool = False

    @classmethod
    async def get_instance(cls) -> "SharedHttpClient":
        """
        Get or create the singleton instance.

        Thread-safe initialization using asyncio.Lock.

        Returns:
            SharedHttpClient: The singleton instance with initialized client.
        """
        if cls._instance is None or not cls._instance._initialized:  # pylint: disable=protected-access
            async with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
                if not cls._instance._initialized:  # pylint: disable=protected-access
                    await cls._instance._initialize()  # pylint: disable=protected-access
        return cls._instance

    async def _initialize(self) -> None:
        """
        Initialize the HTTP client with configured limits and timeouts.

        Reads configuration from settings and creates the shared AsyncClient.
        """
        # Import here to avoid circular imports
        # First-Party
        from mcpgateway.config import settings  # pylint: disable=import-outside-toplevel

        limits = httpx.Limits(
            max_connections=settings.httpx_max_connections,
            max_keepalive_connections=settings.httpx_max_keepalive_connections,
            keepalive_expiry=settings.httpx_keepalive_expiry,
        )

        timeout = httpx.Timeout(
            connect=settings.httpx_connect_timeout,
            read=settings.httpx_read_timeout,
            write=settings.httpx_write_timeout,
            pool=settings.httpx_pool_timeout,
        )

        self._client = httpx.AsyncClient(
            limits=limits,
            timeout=timeout,
            http2=settings.httpx_http2_enabled,
            follow_redirects=True,
            verify=not settings.skip_ssl_verify,
        )
        self._initialized = True

        logger.info(
            "Shared HTTP client initialized: max_connections=%d, keepalive=%d, http2=%s",
            settings.httpx_max_connections,
            settings.httpx_max_keepalive_connections,
            settings.httpx_http2_enabled,
        )

    @property
    def client(self) -> httpx.AsyncClient:
        """
        Get the shared HTTP client.

        Returns:
            httpx.AsyncClient: The shared client instance.

        Raises:
            RuntimeError: If the client has not been initialized.
        """
        if self._client is None:
            raise RuntimeError("SharedHttpClient not initialized. Call get_instance() first.")
        return self._client

    async def close(self) -> None:
        """Close the shared HTTP client and release all connections."""
        if self._client:
            await self._client.aclose()
            self._client = None
            self._initialized = False
            logger.info("Shared HTTP client closed")

    @classmethod
    async def shutdown(cls) -> None:
        """Shutdown the singleton instance during application shutdown."""
        if cls._instance:
            await cls._instance.close()
            cls._instance = None


# Module-level convenience functions


async def get_http_client() -> httpx.AsyncClient:
    """
    Get the shared HTTP client for making requests.

    This is the primary way to obtain an HTTP client in the application.
    The client is shared across all callers and manages connection pooling
    automatically.

    Returns:
        httpx.AsyncClient: The shared client instance.

    Example:
        client = await get_http_client()
        response = await client.post(url, json=data, headers={"X-Custom": "value"})
    """
    instance = await SharedHttpClient.get_instance()
    return instance.client


def get_http_limits() -> httpx.Limits:
    """
    Get configured HTTPX Limits for use with custom clients.

    Use this when you need to create a separate client (e.g., for SSE/streaming
    with mcp-sdk) but want to use the same connection limits as the shared client.

    Returns:
        httpx.Limits: Configured limits from settings.
    """
    # First-Party
    from mcpgateway.config import settings  # pylint: disable=import-outside-toplevel

    return httpx.Limits(
        max_connections=settings.httpx_max_connections,
        max_keepalive_connections=settings.httpx_max_keepalive_connections,
        keepalive_expiry=settings.httpx_keepalive_expiry,
    )


def get_http_timeout(
    read_timeout: Optional[float] = None,
    connect_timeout: Optional[float] = None,
) -> httpx.Timeout:
    """
    Get configured HTTPX Timeout for use with custom clients.

    Allows overriding specific timeout values while using defaults for others.

    Args:
        read_timeout: Override for read timeout (seconds).
        connect_timeout: Override for connect timeout (seconds).

    Returns:
        httpx.Timeout: Configured timeout from settings with optional overrides.
    """
    # First-Party
    from mcpgateway.config import settings  # pylint: disable=import-outside-toplevel

    return httpx.Timeout(
        connect=connect_timeout or settings.httpx_connect_timeout,
        read=read_timeout or settings.httpx_read_timeout,
        write=settings.httpx_write_timeout,
        pool=settings.httpx_pool_timeout,
    )


def get_admin_timeout() -> httpx.Timeout:
    """
    Get a shorter timeout for admin UI operations.

    Use this for operations where fast failure is preferred over waiting for slow
    upstreams (e.g., model list fetching, health checks, admin page data).

    Returns:
        httpx.Timeout: Timeout configured for admin operations (shorter read timeout).
    """
    # First-Party
    from mcpgateway.config import settings  # pylint: disable=import-outside-toplevel

    return httpx.Timeout(
        connect=settings.httpx_connect_timeout,
        read=settings.httpx_admin_read_timeout,
        write=settings.httpx_write_timeout,
        pool=settings.httpx_pool_timeout,
    )


def get_default_verify() -> bool:
    """
    Get the default SSL verification setting based on skip_ssl_verify config.

    Use this when creating factory clients that should respect the global
    skip_ssl_verify setting when no custom SSL context is provided.

    Returns:
        bool: True if SSL should be verified, False if skip_ssl_verify is enabled.
    """
    # First-Party
    from mcpgateway.config import settings  # pylint: disable=import-outside-toplevel

    return not settings.skip_ssl_verify


@asynccontextmanager
async def get_isolated_http_client(
    timeout: Optional[float] = None,
    headers: Optional[dict[str, str]] = None,
    verify: Optional[bool | ssl.SSLContext] = None,
    auth: Optional[httpx.Auth] = None,
    http2: Optional[bool] = None,
) -> AsyncIterator[httpx.AsyncClient]:
    """
    Create an isolated HTTP client with custom settings.

    WARNING: This creates a NEW client with its own connection pool.
    Connections are NOT shared with the singleton. Use sparingly for cases
    requiring custom TLS context or authentication that can't use the shared client.

    For most cases, prefer get_http_client() which reuses connections.

    Args:
        timeout: Optional read timeout override (seconds).
        headers: Optional default headers for all requests.
        verify: SSL verification setting (True, False, SSLContext, or None).
                If None, uses skip_ssl_verify setting to determine default.
        auth: Optional authentication handler.
        http2: Override HTTP/2 setting (default: use settings).

    Yields:
        httpx.AsyncClient: A new isolated client instance.

    Example:
        async with get_isolated_http_client(verify=custom_ssl_context) as client:
            response = await client.get("https://example.com/api")
    """
    # First-Party
    from mcpgateway.config import settings  # pylint: disable=import-outside-toplevel

    limits = get_http_limits()
    timeout_config = get_http_timeout(read_timeout=timeout)

    # Use skip_ssl_verify setting if no explicit verify value provided
    effective_verify: bool | ssl.SSLContext = verify if verify is not None else get_default_verify()

    async with httpx.AsyncClient(
        limits=limits,
        timeout=timeout_config,
        headers=headers,
        verify=effective_verify,
        auth=auth,
        http2=http2 if http2 is not None else settings.httpx_http2_enabled,
        follow_redirects=True,
    ) as client:
        yield client
