# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/sessionless_connection_pool.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Bogdan-Marius Catanus

Sessionless MCP connection pool for protocol versions >= 2025-11-25.

Unlike the UpstreamSessionRegistry which binds upstream sessions 1:1 to
downstream Mcp-Session-Id values, this pool keys connections by gateway
and optionally auth context. This aligns with the sessionless MCP protocol
semantics where protocol-level sessions are removed and connection reuse
is based on stable request properties rather than session identity.

Connection reuse strategy:
- Gateway-scoped: Connections are keyed by (gateway_id, url, transport_type)
- Auth-aware: Optionally include auth fingerprint in the key for multi-tenant isolation
- No session binding: No dependency on downstream Mcp-Session-Id
- Health validation: Idle connections are health-checked before reuse
- Automatic cleanup: Connections are closed on pool shutdown

This pool is used when uses_sessionless_mcp_semantics() returns True.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import hashlib
import logging
import time
from typing import Any, AsyncIterator, Optional

# Third-Party
import anyio
from mcp import ClientSession, McpError
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client

# First-Party
from mcpgateway.services.upstream_session_registry import (
    _DEFAULT_HEALTH_CHECK_TIMEOUT_SECONDS,
    _DEFAULT_IDLE_VALIDATION_SECONDS,
    _DEFAULT_SESSION_CREATE_TIMEOUT_SECONDS,
    _DEFAULT_SHUTDOWN_TIMEOUT_SECONDS,
    _HEALTH_CHECK_CHAIN,
    _METHOD_NOT_FOUND,
    HttpxClientFactory,
    TransportType,
)
from mcpgateway.utils.url_auth import sanitize_url_for_logging

logger = logging.getLogger(__name__)


class SessionlessConnectionPoolNotInitializedError(RuntimeError):
    """Raised when get_sessionless_connection_pool() is called before init_sessionless_connection_pool()."""


@dataclass
class PooledConnection:
    """A pooled MCP connection for sessionless protocol semantics.

    Unlike UpstreamSession which is bound to a downstream session ID,
    this connection is keyed by gateway and auth context only.
    """

    session: ClientSession
    """The MCP ClientSession for this connection."""

    url: str
    """The upstream gateway URL."""

    transport_type: TransportType
    """The transport type (SSE or StreamableHTTP)."""

    transport_ctx: Any
    """The async context manager for the transport (for cleanup)."""

    auth_fingerprint: Optional[str] = None
    """Optional auth fingerprint for multi-tenant isolation."""

    created_at: float = field(default_factory=time.time)
    """When this connection was created."""

    last_used: float = field(default_factory=time.time)
    """When this connection was last used."""

    use_count: int = 0
    """How many times this connection has been acquired."""

    is_closed: bool = False
    """Whether this connection has been closed."""

    @property
    def idle_seconds(self) -> float:
        """Seconds since last use."""
        return time.time() - self.last_used


def _compute_auth_fingerprint(headers: Optional[dict[str, str]]) -> str:
    """Compute a stable fingerprint for auth headers.

    Used to isolate connections by auth context in multi-tenant scenarios.
    Returns empty string if no auth headers are present.
    """
    if not headers:
        return ""

    # Only consider auth-related headers for the fingerprint
    auth_keys = {"authorization", "x-api-key", "x-auth-token"}
    auth_values = []
    for key, value in sorted(headers.items()):
        if key.lower() in auth_keys and value:
            auth_values.append(f"{key.lower()}:{value}")

    if not auth_values:
        return ""

    # Hash the auth values to avoid storing sensitive data in the key
    fingerprint_input = "|".join(auth_values)
    return hashlib.sha256(fingerprint_input.encode()).hexdigest()[:16]


class SessionlessConnectionPool:
    """Connection pool for sessionless MCP protocol semantics.

    Manages MCP connections keyed by (gateway_id, url, transport_type, auth_fingerprint)
    instead of downstream session IDs. Provides connection reuse, health validation,
    and automatic cleanup.

    This pool is used when the MCP protocol version indicates sessionless semantics
    (>= 2025-11-25). For legacy sessionful protocols, use UpstreamSessionRegistry.
    """

    def __init__(
        self,
        *,
        idle_validation_seconds: float = _DEFAULT_IDLE_VALIDATION_SECONDS,
        health_check_timeout_seconds: float = _DEFAULT_HEALTH_CHECK_TIMEOUT_SECONDS,
        session_create_timeout_seconds: float = _DEFAULT_SESSION_CREATE_TIMEOUT_SECONDS,
        shutdown_timeout_seconds: float = _DEFAULT_SHUTDOWN_TIMEOUT_SECONDS,
    ) -> None:
        """Initialize the sessionless connection pool.

        Args:
            idle_validation_seconds: How long a connection can be idle before health check
            health_check_timeout_seconds: Timeout for health check operations
            session_create_timeout_seconds: Timeout for creating new connections
            shutdown_timeout_seconds: Timeout for closing connections during shutdown
        """
        self._idle_validation_seconds = idle_validation_seconds
        self._health_check_timeout_seconds = health_check_timeout_seconds
        self._session_create_timeout_seconds = session_create_timeout_seconds
        self._shutdown_timeout_seconds = shutdown_timeout_seconds

        # Pool storage: key is (gateway_id, url, transport_type, auth_fingerprint)
        self._connections: dict[tuple[str, str, str, str], PooledConnection] = {}
        self._key_locks: dict[tuple[str, str, str, str], asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

        # Metrics
        self._creates = 0
        self._reuses = 0
        self._health_check_recreates = 0

    async def _get_key_lock(self, key: tuple[str, str, str, str]) -> asyncio.Lock:
        """Get or create the lock for a specific connection key."""
        async with self._global_lock:
            if key not in self._key_locks:
                self._key_locks[key] = asyncio.Lock()
            return self._key_locks[key]

    async def _probe_health(self, connection: PooledConnection) -> bool:
        """Health-check a pooled connection.

        Tries methods in order: ping, list_tools, list_prompts, list_resources.
        Returns True if any method succeeds, False if all fail.
        """
        for method_name in _HEALTH_CHECK_CHAIN:
            if method_name == "skip":
                logger.debug("Health check chain exhausted, assuming connection is healthy")
                return True

            try:
                method = getattr(connection.session, method_name, None)
                if method is None:
                    continue

                async with anyio.fail_after(self._health_check_timeout_seconds):  # pylint: disable=not-async-context-manager
                    await method()
                logger.debug("Health check succeeded via %s", method_name)
                return True
            except McpError as exc:
                if getattr(exc, "code", None) == _METHOD_NOT_FOUND:
                    continue
                logger.debug("Health check failed via %s: %s", method_name, exc)
                return False
            except (TimeoutError, anyio.EndOfStream, OSError, anyio.ClosedResourceError, anyio.BrokenResourceError):
                logger.debug("Health check failed via %s (transport error)", method_name)
                return False
            except Exception as exc:  # noqa: BLE001
                logger.debug("Health check failed via %s: %s", method_name, exc)
                return False

        return False

    async def _close_connection(self, connection: PooledConnection) -> None:
        """Close a pooled connection."""
        if connection.is_closed:
            return

        try:
            async with anyio.fail_after(self._shutdown_timeout_seconds):  # pylint: disable=not-async-context-manager
                # Close the session first
                await connection.session.__aexit__(None, None, None)
                # Then close the transport context
                await connection.transport_ctx.__aexit__(None, None, None)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Error closing connection: %s", exc)
        finally:
            connection.is_closed = True

    async def _create_connection(
        self,
        *,
        gateway_id: str,
        url: str,
        headers: Optional[dict[str, str]],
        transport_type: TransportType,
        httpx_client_factory: Optional[HttpxClientFactory] = None,
    ) -> PooledConnection:
        """Create a new pooled connection."""
        sanitized_url = sanitize_url_for_logging(url)
        logger.info(
            "Creating sessionless connection (gateway=%s, transport=%s, url=%s)",
            gateway_id,
            transport_type.value,
            sanitized_url,
        )

        try:
            async with anyio.fail_after(self._session_create_timeout_seconds):  # pylint: disable=not-async-context-manager
                if transport_type == TransportType.SSE:
                    transport_ctx = sse_client(
                        url=url,
                        headers=headers,
                        httpx_client_factory=httpx_client_factory,
                    )
                elif transport_type == TransportType.STREAMABLE_HTTP:
                    transport_ctx = streamablehttp_client(
                        url=url,
                        headers=headers,
                        httpx_client_factory=httpx_client_factory,
                    )
                else:
                    raise ValueError(f"Unsupported transport type: {transport_type}")

                # Enter the transport context
                streams = await transport_ctx.__aenter__()  # pylint: disable=no-member
                read_stream, write_stream = streams[0], streams[1]

                # Create and initialize the session
                session = ClientSession(read_stream, write_stream)
                await session.__aenter__()  # pylint: disable=no-member
                await session.initialize()

                return PooledConnection(
                    session=session,
                    url=url,
                    transport_type=transport_type,
                    transport_ctx=transport_ctx,
                    auth_fingerprint=_compute_auth_fingerprint(headers),
                )
        except Exception as exc:
            logger.error(
                "Failed to create sessionless connection (gateway=%s, url=%s): %s",
                gateway_id,
                sanitized_url,
                exc,
            )
            raise

    @asynccontextmanager
    async def acquire(
        self,
        *,
        gateway_id: str,
        url: str,
        headers: Optional[dict[str, str]],
        transport_type: TransportType,
        httpx_client_factory: Optional[HttpxClientFactory] = None,
    ) -> AsyncIterator[PooledConnection]:
        """Acquire a pooled connection for sessionless MCP requests.

        Connections are keyed by (gateway_id, url, transport_type, auth_fingerprint).
        Idle connections are health-checked before reuse. Failed health checks
        trigger connection recreation.

        Args:
            gateway_id: The gateway identifier
            url: The upstream gateway URL
            headers: Request headers (used for auth fingerprint)
            transport_type: SSE or StreamableHTTP
            httpx_client_factory: Optional factory for creating httpx clients

        Yields:
            A pooled connection ready for use
        """
        if not gateway_id:
            raise ValueError("gateway_id is required")

        auth_fingerprint = _compute_auth_fingerprint(headers)
        key = (gateway_id, url, transport_type.value, auth_fingerprint)
        key_lock = await self._get_key_lock(key)

        async with key_lock:
            connection = self._connections.get(key)
            should_create = False

            if connection is None or connection.is_closed:
                should_create = True
            elif connection.idle_seconds > self._idle_validation_seconds:
                healthy = await self._probe_health(connection)
                if not healthy:
                    logger.info(
                        "Sessionless connection health probe failed, recreating (gateway=%s)",
                        gateway_id,
                    )
                    await self._close_connection(connection)
                    self._connections.pop(key, None)
                    self._health_check_recreates += 1
                    should_create = True

            if should_create:
                connection = await self._create_connection(
                    gateway_id=gateway_id,
                    url=url,
                    headers=headers,
                    transport_type=transport_type,
                    httpx_client_factory=httpx_client_factory,
                )
                self._connections[key] = connection
                self._creates += 1
            else:
                self._reuses += 1

            if connection is None:  # nosec B101
                raise RuntimeError("Connection unexpectedly None after acquire")

            connection.last_used = time.time()
            connection.use_count += 1

        # Yield connection without holding the lock
        try:
            yield connection
        except (OSError, anyio.ClosedResourceError, anyio.BrokenResourceError) as exc:
            logger.info(
                "Transport error on sessionless connection (gateway=%s), evicting: %s",
                gateway_id,
                exc,
            )
            async with key_lock:
                await self._close_connection(connection)
                self._connections.pop(key, None)
            raise

    async def shutdown(self) -> None:
        """Close all pooled connections."""
        logger.info("Shutting down sessionless connection pool")
        async with self._global_lock:
            for connection in list(self._connections.values()):
                await self._close_connection(connection)
            self._connections.clear()
            self._key_locks.clear()

    def get_metrics(self) -> dict[str, Any]:
        """Get pool metrics."""
        return {
            "creates": self._creates,
            "reuses": self._reuses,
            "health_check_recreates": self._health_check_recreates,
            "active_connections": len(self._connections),
        }


# Singleton instance
_sessionless_pool: Optional[SessionlessConnectionPool] = None
_sessionless_pool_lock = asyncio.Lock()


async def init_sessionless_connection_pool(
    *,
    idle_validation_seconds: float = _DEFAULT_IDLE_VALIDATION_SECONDS,
    health_check_timeout_seconds: float = _DEFAULT_HEALTH_CHECK_TIMEOUT_SECONDS,
    session_create_timeout_seconds: float = _DEFAULT_SESSION_CREATE_TIMEOUT_SECONDS,
    shutdown_timeout_seconds: float = _DEFAULT_SHUTDOWN_TIMEOUT_SECONDS,
) -> SessionlessConnectionPool:
    """Initialize the global sessionless connection pool singleton.

    This should be called during application startup. Multiple calls are safe
    and will return the existing instance.
    """
    global _sessionless_pool  # noqa: PLW0603
    async with _sessionless_pool_lock:
        if _sessionless_pool is None:
            _sessionless_pool = SessionlessConnectionPool(
                idle_validation_seconds=idle_validation_seconds,
                health_check_timeout_seconds=health_check_timeout_seconds,
                session_create_timeout_seconds=session_create_timeout_seconds,
                shutdown_timeout_seconds=shutdown_timeout_seconds,
            )
            logger.info("Sessionless connection pool initialized")
        return _sessionless_pool


def get_sessionless_connection_pool() -> SessionlessConnectionPool:
    """Get the global sessionless connection pool singleton.

    Raises:
        SessionlessConnectionPoolNotInitializedError: If init_sessionless_connection_pool() has not been called
    """
    if _sessionless_pool is None:
        raise SessionlessConnectionPoolNotInitializedError("Sessionless connection pool not initialized. Call init_sessionless_connection_pool() first.")
    return _sessionless_pool


async def shutdown_sessionless_connection_pool() -> None:
    """Shutdown the global sessionless connection pool singleton."""
    global _sessionless_pool  # noqa: PLW0603
    async with _sessionless_pool_lock:
        if _sessionless_pool is not None:
            await _sessionless_pool.shutdown()
            _sessionless_pool = None
            logger.info("Sessionless connection pool shut down")
