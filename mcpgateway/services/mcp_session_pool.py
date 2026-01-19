# -*- coding: utf-8 -*-
"""
MCP Session Pool Implementation.

Provides session pooling for MCP ClientSessions to reduce per-request overhead.
Sessions are isolated per user/tenant via identity hashing to prevent session collision.

Performance Impact:
    - Without pooling: 20-23ms per tool call (new session each time)
    - With pooling: 1-2ms per tool call (10-20x improvement)

Security:
    Sessions are isolated by (url, identity_hash, transport_type) to prevent:
    - Cross-user session sharing
    - Cross-tenant data leakage
    - Authentication bypass

Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti
"""

# flake8: noqa: DAR101, DAR201, DAR401

# Future
from __future__ import annotations

# Standard
import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import logging
import time
from typing import Any, Callable, Dict, Optional, Set, Tuple, TYPE_CHECKING

# Third-Party
import httpx
from mcp import ClientSession, McpError
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.session import RequestResponder
import mcp.types as mcp_types
import orjson

# First-Party
from mcpgateway.utils.url_auth import sanitize_url_for_logging

# JSON-RPC standard error code for method not found
METHOD_NOT_FOUND = -32601

if TYPE_CHECKING:
    # Standard
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)


class TransportType(Enum):
    """Supported MCP transport types."""

    SSE = "sse"
    STREAMABLE_HTTP = "streamablehttp"


@dataclass(eq=False)  # eq=False makes instances hashable by object identity
class PooledSession:
    """A pooled MCP session with metadata for lifecycle management.

    Note: eq=False is required because we store these in Sets for active session
    tracking. This makes instances hashable by their object id (identity).
    """

    session: ClientSession
    transport_context: Any  # The transport context manager (kept open)
    url: str
    transport_type: TransportType
    headers: Dict[str, str]  # Original headers (for reconnection)
    identity_key: str  # Identity hash component for headers
    user_identity: str = "anonymous"  # for user isolation
    gateway_id: str = ""  # Gateway ID for notification attribution
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    use_count: int = 0
    _closed: bool = field(default=False, repr=False)

    @property
    def age_seconds(self) -> float:
        """Return session age in seconds.

        Returns:
            float: Session age in seconds since creation.
        """
        return time.time() - self.created_at

    @property
    def idle_seconds(self) -> float:
        """Return seconds since last use.

        Returns:
            float: Seconds since last use of this session.
        """
        return time.time() - self.last_used

    @property
    def is_closed(self) -> bool:
        """Return whether this session has been closed.

        Returns:
            bool: True if session is closed, False otherwise.
        """
        return self._closed

    def mark_closed(self) -> None:
        """Mark this session as closed."""
        self._closed = True


# Type aliases
# Pool key includes transport type and gateway_id to prevent returning wrong transport for same URL
# and to ensure correct notification attribution when notifications are enabled
PoolKey = Tuple[str, str, str, str, str]  # (user_identity_hash, url, identity_hash, transport_type, gateway_id)
HttpxClientFactory = Callable[
    [Optional[Dict[str, str]], Optional[httpx.Timeout], Optional[httpx.Auth]],
    httpx.AsyncClient,
]


# Type alias for identity extractor callback
# Extracts stable identity from headers (e.g., decode JWT to get user_id)
IdentityExtractor = Callable[[Dict[str, str]], Optional[str]]

# Type alias for message handler factory
# Factory that creates message handlers given URL and optional gateway_id
# The handler receives ServerNotification, ServerRequest responders, or Exceptions
MessageHandlerFactory = Callable[
    [str, Optional[str]],  # (url, gateway_id)
    Callable[
        [RequestResponder[mcp_types.ServerRequest, mcp_types.ClientResult] | mcp_types.ServerNotification | Exception],
        Any,  # Coroutine
    ],
]


class MCPSessionPool:  # pylint: disable=too-many-instance-attributes
    """
    Pool of MCP ClientSessions keyed by (user_identity, server URL, identity hash, transport type, gateway_id).

    Thread-Safety:
        This pool is designed for asyncio concurrency. It uses asyncio.Lock
        for synchronization, which is safe for coroutine-based concurrency
        but NOT for multi-threaded access.

    Session Isolation:
        Sessions are isolated per user/tenant to prevent session collision.
        The identity hash is derived from authentication headers ensuring
        that different users never share MCP sessions.

    Transport Isolation:
        Sessions are also isolated by transport type (SSE vs STREAMABLE_HTTP).
        The same URL with different transports will use separate pools.

    Gateway Isolation:
        Sessions are isolated by gateway_id for correct notification attribution.
        When notifications are enabled, each gateway gets its own pooled sessions
        even if they share the same URL and authentication.

    Features:
        - Session reuse across requests (10-20x latency improvement)
        - Per-user/tenant session isolation (prevents session collision)
        - Per-transport session isolation (prevents transport mismatch)
        - TTL-based expiration with configurable lifetime
        - Health checks on acquire for stale sessions
        - Configurable pool size per URL+identity+transport
        - Circuit breaker for failing endpoints
        - Idle pool key eviction to prevent unbounded growth
        - Custom identity extractor for rotating tokens (e.g., JWT decode)
        - Metrics for monitoring (hits, misses, evictions)
        - Graceful shutdown with close_all()

    Usage:
        pool = MCPSessionPool()

        # Use as context manager for lifecycle management
        async with pool:
            pooled = await pool.acquire(url, headers)
            try:
                result = await pooled.session.call_tool("my_tool", {})
            finally:
                await pool.release(pooled)

        # With custom identity extractor for JWT tokens:
        def extract_user_id(headers: dict) -> str:
            token = headers.get("Authorization", "").replace("Bearer ", "")
            claims = jwt.decode(token, options={"verify_signature": False})
            return claims.get("sub") or claims.get("user_id")

        pool = MCPSessionPool(identity_extractor=extract_user_id)
    """

    # Headers that contribute to session identity (case-insensitive)
    DEFAULT_IDENTITY_HEADERS: frozenset[str] = frozenset(
        [
            "authorization",
            "x-tenant-id",
            "x-user-id",
            "x-api-key",
            "cookie",
        ]
    )

    def __init__(
        self,
        max_sessions_per_key: int = 10,
        session_ttl_seconds: float = 300.0,
        health_check_interval_seconds: float = 60.0,
        acquire_timeout_seconds: float = 30.0,
        session_create_timeout_seconds: float = 30.0,
        circuit_breaker_threshold: int = 5,
        circuit_breaker_reset_seconds: float = 60.0,
        identity_headers: Optional[frozenset[str]] = None,
        identity_extractor: Optional[IdentityExtractor] = None,
        idle_pool_eviction_seconds: float = 600.0,
        default_transport_timeout_seconds: float = 30.0,
        health_check_methods: Optional[list[str]] = None,
        health_check_timeout_seconds: float = 5.0,
        message_handler_factory: Optional[MessageHandlerFactory] = None,
    ):
        """
        Initialize the session pool.

        Args:
            max_sessions_per_key: Maximum pooled sessions per (URL, identity, transport).
            session_ttl_seconds: Session TTL in seconds before forced expiration.
            health_check_interval_seconds: Seconds of idle time before health check.
            acquire_timeout_seconds: Timeout for waiting when pool is exhausted.
            session_create_timeout_seconds: Timeout for creating new sessions.
            circuit_breaker_threshold: Consecutive failures before circuit opens.
            circuit_breaker_reset_seconds: Seconds before circuit breaker resets.
            identity_headers: Headers that contribute to identity hash.
            identity_extractor: Optional callback to extract stable identity from headers.
                               Use this when tokens rotate frequently (e.g., short-lived JWTs).
                               Should return a stable user/tenant ID string.
            idle_pool_eviction_seconds: Evict empty pool keys after this many seconds of no use.
            default_transport_timeout_seconds: Default timeout for transport connections.
            health_check_methods: Ordered list of health check methods to try.
                                 Options: ping, list_tools, list_prompts, list_resources, skip.
                                 Default: ["ping", "skip"] (try ping, skip if unsupported).
            health_check_timeout_seconds: Timeout for each health check attempt.
            message_handler_factory: Optional factory for creating message handlers.
                                    Called with (url, gateway_id) to create handlers for
                                    each new session. Enables notification handling.
        """
        # Configuration
        self._max_sessions = max_sessions_per_key
        self._session_ttl = session_ttl_seconds
        self._health_check_interval = health_check_interval_seconds
        self._acquire_timeout = acquire_timeout_seconds
        self._session_create_timeout = session_create_timeout_seconds
        self._circuit_breaker_threshold = circuit_breaker_threshold
        self._circuit_breaker_reset = circuit_breaker_reset_seconds
        self._identity_headers = identity_headers or self.DEFAULT_IDENTITY_HEADERS
        self._identity_extractor = identity_extractor
        self._idle_pool_eviction = idle_pool_eviction_seconds
        self._default_transport_timeout = default_transport_timeout_seconds
        self._health_check_methods = health_check_methods or ["ping", "skip"]
        self._health_check_timeout = health_check_timeout_seconds
        self._message_handler_factory = message_handler_factory

        # State - protected by _global_lock for creation, per-key locks for access
        self._global_lock = asyncio.Lock()
        self._pools: Dict[PoolKey, asyncio.Queue[PooledSession]] = {}
        self._active: Dict[PoolKey, Set[PooledSession]] = {}
        self._locks: Dict[PoolKey, asyncio.Lock] = {}
        self._semaphores: Dict[PoolKey, asyncio.Semaphore] = {}
        self._pool_last_used: Dict[PoolKey, float] = {}  # Track last use time per pool key

        # Circuit breaker state
        self._failures: Dict[str, int] = {}  # url -> consecutive failure count
        self._circuit_open_until: Dict[str, float] = {}  # url -> timestamp

        # Eviction throttling - only run eviction once per interval
        self._last_eviction_run: float = 0.0
        self._eviction_run_interval: float = 60.0  # Run eviction at most every 60 seconds

        # Metrics
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._health_check_failures = 0
        self._circuit_breaker_trips = 0
        self._pool_keys_evicted = 0
        self._sessions_reaped = 0  # Sessions closed during background eviction
        self._anonymous_identity_count = 0  # Count of requests with no identity headers

        # Lifecycle
        self._closed = False

    async def __aenter__(self) -> "MCPSessionPool":
        """Async context manager entry.

        Returns:
            MCPSessionPool: This pool instance.
        """
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit - closes all sessions.

        Args:
            exc_type: Exception type if an exception was raised.
            exc_val: Exception value if an exception was raised.
            exc_tb: Exception traceback if an exception was raised.
        """
        await self.close_all()

    def _compute_identity_hash(self, headers: Optional[Dict[str, str]]) -> str:
        """
        Compute a hash of identity-relevant headers.

        This ensures sessions are isolated per user/tenant. Different users
        with different Authorization headers will have different identity hashes
        and thus separate session pools.

        If an identity_extractor is configured, it is called first to extract
        a stable identity (e.g., user_id from JWT). This prevents unbounded pool
        growth when tokens rotate frequently.

        Args:
            headers: Request headers dict.

        Returns:
            Identity hash string, or "anonymous" if no identity headers present.
        """
        if not headers:
            self._anonymous_identity_count += 1
            logger.debug("Session pool identity collapsed to 'anonymous' (no headers provided). " + "Sessions will be shared. Ensure this is intentional for stateless MCP servers.")
            return "anonymous"

        # Try custom identity extractor first (for rotating tokens like JWTs)
        if self._identity_extractor:
            try:
                extracted = self._identity_extractor(headers)
                if extracted:
                    return hashlib.sha256(extracted.encode()).hexdigest()
            except Exception as e:
                logger.debug(f"Identity extractor failed, falling back to header hash: {e}")

        # Normalize and extract identity headers (case-insensitive)
        identity_parts = []
        headers_lower = {k.lower(): v for k, v in headers.items()}

        for header in sorted(self._identity_headers):
            if header in headers_lower:
                identity_parts.append(f"{header}:{headers_lower[header]}")

        if not identity_parts:
            self._anonymous_identity_count += 1
            logger.debug(
                "Session pool identity collapsed to 'anonymous' (no identity headers found). " + "Expected headers: %s. Sessions will be shared.",
                list(self._identity_headers),
            )
            return "anonymous"

        # Create a stable, deterministic hash using JSON serialization
        # Prevents delimiter-collision or injection issues present in string joining
        serialized_identity = orjson.dumps(identity_parts)
        return hashlib.sha256(serialized_identity).hexdigest()

    def _make_pool_key(
        self,
        url: str,
        headers: Optional[Dict[str, str]],
        transport_type: TransportType,
        user_identity: str,
        gateway_id: Optional[str] = None,
    ) -> PoolKey:
        """Create composite pool key from URL, identity, transport type, user identity, and gateway_id.

        Including gateway_id ensures correct notification attribution when multiple gateways
        share the same URL/auth. Sessions are isolated per gateway for proper event routing.
        """
        identity_hash = self._compute_identity_hash(headers)

        # Anonymize user identity by hashing it (unless it's commonly "anonymous")
        # Use full hash for collision resistance - truncate only for display in logs/metrics
        if user_identity == "anonymous":
            user_hash = "anonymous"
        else:
            user_hash = hashlib.sha256(user_identity.encode()).hexdigest()

        # Use empty string for None gateway_id to maintain consistent key type
        gw_id = gateway_id or ""

        return (user_hash, url, identity_hash, transport_type.value, gw_id)

    async def _get_or_create_lock(self, pool_key: PoolKey) -> asyncio.Lock:
        """Get or create a lock for the given pool key (thread-safe)."""
        async with self._global_lock:
            if pool_key not in self._locks:
                self._locks[pool_key] = asyncio.Lock()
            return self._locks[pool_key]

    async def _get_or_create_pool(self, pool_key: PoolKey) -> asyncio.Queue[PooledSession]:
        """Get or create a pool queue for the given key (thread-safe)."""
        async with self._global_lock:
            if pool_key not in self._pools:
                self._pools[pool_key] = asyncio.Queue(maxsize=self._max_sessions)
                self._active[pool_key] = set()
                self._semaphores[pool_key] = asyncio.Semaphore(self._max_sessions)
            return self._pools[pool_key]

    def _is_circuit_open(self, url: str) -> bool:
        """Check if circuit breaker is open for a URL."""
        if url not in self._circuit_open_until:
            return False
        if time.time() >= self._circuit_open_until[url]:
            # Circuit breaker reset
            del self._circuit_open_until[url]
            self._failures[url] = 0
            logger.info(f"Circuit breaker reset for {sanitize_url_for_logging(url)}")
            return False
        return True

    def _record_failure(self, url: str) -> None:
        """Record a failure and potentially trip circuit breaker."""
        self._failures[url] = self._failures.get(url, 0) + 1
        if self._failures[url] >= self._circuit_breaker_threshold:
            self._circuit_open_until[url] = time.time() + self._circuit_breaker_reset
            self._circuit_breaker_trips += 1
            logger.warning(f"Circuit breaker opened for {sanitize_url_for_logging(url)} after {self._failures[url]} failures. " f"Will reset in {self._circuit_breaker_reset}s")

    def _record_success(self, url: str) -> None:
        """Record a success, resetting failure count."""
        self._failures[url] = 0

    async def acquire(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        transport_type: TransportType = TransportType.STREAMABLE_HTTP,
        httpx_client_factory: Optional[HttpxClientFactory] = None,
        timeout: Optional[float] = None,
        user_identity: Optional[str] = None,
        gateway_id: Optional[str] = None,
    ) -> PooledSession:
        """
        Acquire a session for the given URL, identity, and transport type.

        Sessions are isolated by identity (derived from auth headers) AND
        transport type. Returns an initialized, healthy session ready for tool calls.

        Args:
            url: The MCP server URL.
            headers: Request headers (used for identity hashing and passed to server).
            transport_type: The transport type (SSE or STREAMABLE_HTTP).
            httpx_client_factory: Optional factory for creating httpx clients
                                  (for custom SSL/timeout configuration).
            timeout: Optional timeout in seconds for transport connection.
            gateway_id: Optional gateway ID for notification handler context.

        Returns:
            PooledSession ready for use.

        Raises:
            asyncio.TimeoutError: If acquire times out waiting for available session.
            RuntimeError: If pool is closed or circuit breaker is open.
            Exception: If session creation fails.
        """
        if self._closed:
            raise RuntimeError("Session pool is closed")

        if self._is_circuit_open(url):
            raise RuntimeError(f"Circuit breaker open for {url}")

        # Use default timeout if not provided
        effective_timeout = timeout if timeout is not None else self._default_transport_timeout

        user_id = user_identity or "anonymous"
        pool_key = self._make_pool_key(url, headers, transport_type, user_id, gateway_id)
        pool = await self._get_or_create_pool(pool_key)

        # Update pool key last used time IMMEDIATELY after getting pool
        # This prevents race with eviction removing keys between awaits
        self._pool_last_used[pool_key] = time.time()

        lock = await self._get_or_create_lock(pool_key)

        # Guard semaphore access - eviction may have removed it between awaits
        # If so, re-create the pool structures
        if pool_key not in self._semaphores:
            pool = await self._get_or_create_pool(pool_key)
            self._pool_last_used[pool_key] = time.time()

        semaphore = self._semaphores[pool_key]

        # Throttled eviction - only run if enough time has passed (inline, not spawned)
        await self._maybe_evict_idle_pool_keys()

        # Try to get from pool first (quick path, no lock needed for queue get)
        while True:
            try:
                pooled = pool.get_nowait()
            except asyncio.QueueEmpty:
                break

            # Validate the session outside the lock
            if await self._validate_session(pooled):
                pooled.last_used = time.time()
                pooled.use_count += 1
                self._hits += 1
                async with lock:
                    self._active[pool_key].add(pooled)
                logger.debug(f"Pool hit for {sanitize_url_for_logging(url)} (identity={pool_key[2][:8]}, transport={transport_type.value})")
                return pooled

            # Session invalid, close it
            await self._close_session(pooled)
            self._evictions += 1
            semaphore.release()  # Free up a slot

        # No valid session in pool - try to create one or wait
        try:
            # Use semaphore with timeout to limit concurrent sessions
            acquired = await asyncio.wait_for(semaphore.acquire(), timeout=self._acquire_timeout)
            if not acquired:
                raise asyncio.TimeoutError("Failed to acquire session slot")
        except asyncio.TimeoutError:
            raise asyncio.TimeoutError(f"Timeout waiting for available session for {sanitize_url_for_logging(url)}") from None

        # Create new session (semaphore acquired)
        try:
            pooled = await asyncio.wait_for(
                self._create_session(url, headers, transport_type, httpx_client_factory, effective_timeout, gateway_id),
                timeout=self._session_create_timeout,
            )
            # Store identity components for key reconstruction
            pooled.identity_key = pool_key[2]
            pooled.user_identity = user_id

            self._misses += 1
            self._record_success(url)
            async with lock:
                self._active[pool_key].add(pooled)
            logger.debug(f"Pool miss for {sanitize_url_for_logging(url)} - created new session (transport={transport_type.value})")
            return pooled
        except BaseException as e:
            # Release semaphore on ANY failure (including CancelledError)
            semaphore.release()
            if not isinstance(e, asyncio.CancelledError):
                self._record_failure(url)
                logger.warning(f"Failed to create session for {sanitize_url_for_logging(url)}: {e}")
            raise

    async def release(self, pooled: PooledSession) -> None:
        """
        Return a session to the pool for reuse.

        Args:
            pooled: The session to release.
        """
        if pooled.is_closed:
            logger.warning("Attempted to release already-closed session")
            return

        # Pool key includes transport type, user identity, and gateway_id
        # Re-compute user hash from stored raw identity (full hash for collision resistance)
        user_hash = "anonymous"
        if pooled.user_identity != "anonymous":
            user_hash = hashlib.sha256(pooled.user_identity.encode()).hexdigest()

        pool_key = (user_hash, pooled.url, pooled.identity_key, pooled.transport_type.value, pooled.gateway_id)
        lock = await self._get_or_create_lock(pool_key)
        pool = await self._get_or_create_pool(pool_key)

        async with lock:
            # Update last-used FIRST to prevent eviction race:
            # If eviction runs between removing from _active and putting back in pool,
            # it would see key as idle + inactive and evict it. By updating last-used
            # while still holding the lock and before removing from _active, we ensure
            # eviction sees recent activity.
            self._pool_last_used[pool_key] = time.time()
            self._active.get(pool_key, set()).discard(pooled)

        # Check if session should be returned to pool
        if self._closed or pooled.age_seconds > self._session_ttl:
            await self._close_session(pooled)
            if pool_key in self._semaphores:
                self._semaphores[pool_key].release()
            if pooled.age_seconds > self._session_ttl:
                self._evictions += 1
            return

        # Return to pool (pool may have been evicted in edge case, recreate if needed)
        if pool_key not in self._pools:
            pool = await self._get_or_create_pool(pool_key)
            self._pool_last_used[pool_key] = time.time()

        try:
            pool.put_nowait(pooled)
            logger.debug(f"Session returned to pool for {sanitize_url_for_logging(pooled.url)}")
        except asyncio.QueueFull:
            # Pool full (shouldn't happen with semaphore), close session
            await self._close_session(pooled)
            if pool_key in self._semaphores:
                self._semaphores[pool_key].release()

    async def _maybe_evict_idle_pool_keys(self) -> None:
        """
        Reap stale sessions and evict idle pool keys.

        This method is throttled - it only runs eviction if enough time has
        passed since the last run (default: 60 seconds). This prevents:
        - Unbounded task spawning on every acquire
        - Lock contention under high load

        Two-phase cleanup:
        1. Close expired/stale sessions parked in idle pools (frees connections)
        2. Evict pool keys that are now empty and have no active sessions

        This prevents unbounded connection and pool key growth when using
        rotating tokens (e.g., short-lived JWTs with unique identifiers).
        """
        if self._closed:
            return

        now = time.time()

        # Throttle: only run eviction once per interval
        if now - self._last_eviction_run < self._eviction_run_interval:
            return

        self._last_eviction_run = now

        # Collect sessions to close and keys to evict (minimize time holding lock)
        sessions_to_close: list[PooledSession] = []
        keys_to_evict: list[PoolKey] = []

        async with self._global_lock:
            for pool_key, last_used in list(self._pool_last_used.items()):
                # Skip recently-used pools
                if now - last_used < self._idle_pool_eviction:
                    continue

                pool = self._pools.get(pool_key)
                active = self._active.get(pool_key, set())

                # Skip if there are active sessions (in use)
                if active:
                    continue

                if pool:
                    # Phase 1: Drain and collect expired/stale sessions from idle pools
                    while not pool.empty():
                        try:
                            session = pool.get_nowait()
                            # Close if expired OR idle too long (defense in depth)
                            if session.age_seconds > self._session_ttl or session.idle_seconds > self._idle_pool_eviction:
                                sessions_to_close.append(session)
                                # Release semaphore slot for this session
                                if pool_key in self._semaphores:
                                    self._semaphores[pool_key].release()
                            else:
                                # Session still valid, put it back
                                pool.put_nowait(session)
                                break  # Stop draining if we find a valid session
                        except asyncio.QueueEmpty:
                            break

                    # Phase 2: Evict pool key if now empty
                    if pool.empty():
                        keys_to_evict.append(pool_key)

            # Remove evicted keys from all tracking dicts
            for pool_key in keys_to_evict:
                self._pools.pop(pool_key, None)
                self._active.pop(pool_key, None)
                self._locks.pop(pool_key, None)
                self._semaphores.pop(pool_key, None)
                self._pool_last_used.pop(pool_key, None)
                self._pool_keys_evicted += 1
                logger.debug(f"Evicted idle pool key: {pool_key[0][:8]}|{pool_key[1]}|{pool_key[2][:8]}")

        # Close sessions outside the lock (I/O operations)
        for session in sessions_to_close:
            await self._close_session(session)
            self._sessions_reaped += 1
            logger.debug(f"Reaped stale session for {sanitize_url_for_logging(session.url)} (age={session.age_seconds:.1f}s)")

    async def _validate_session(self, pooled: PooledSession) -> bool:
        """
        Validate a session is still usable.

        Checks TTL and performs health check if session is stale.

        Args:
            pooled: The session to validate.

        Returns:
            True if session is valid, False otherwise.
        """
        if pooled.is_closed:
            return False

        # Check TTL
        if pooled.age_seconds > self._session_ttl:
            logger.debug(f"Session expired (age={pooled.age_seconds:.1f}s)")
            return False

        # Health check if stale
        if pooled.idle_seconds > self._health_check_interval:
            return await self._run_health_check_chain(pooled)

        return True

    async def _run_health_check_chain(self, pooled: PooledSession) -> bool:
        """
        Run health check methods in configured order until one succeeds.

        The health check chain allows configuring which methods to try and in what order.
        This supports both modern servers (with ping support) and legacy servers
        (that may only support list_tools or no health check at all).

        Args:
            pooled: The session to health check.

        Returns:
            True if any health check method succeeds, False if all fail.
        """
        for method in self._health_check_methods:
            try:
                if method == "ping":
                    await asyncio.wait_for(pooled.session.send_ping(), timeout=self._health_check_timeout)
                    logger.debug(f"Health check passed: ping (url={sanitize_url_for_logging(pooled.url)})")
                    return True
                if method == "list_tools":
                    await asyncio.wait_for(pooled.session.list_tools(), timeout=self._health_check_timeout)
                    logger.debug(f"Health check passed: list_tools (url={sanitize_url_for_logging(pooled.url)})")
                    return True
                if method == "list_prompts":
                    await asyncio.wait_for(pooled.session.list_prompts(), timeout=self._health_check_timeout)
                    logger.debug(f"Health check passed: list_prompts (url={sanitize_url_for_logging(pooled.url)})")
                    return True
                if method == "list_resources":
                    await asyncio.wait_for(pooled.session.list_resources(), timeout=self._health_check_timeout)
                    logger.debug(f"Health check passed: list_resources (url={sanitize_url_for_logging(pooled.url)})")
                    return True
                if method == "skip":
                    logger.debug(f"Health check skipped per configuration (url={sanitize_url_for_logging(pooled.url)})")
                    return True
                logger.warning(f"Unknown health check method '{method}', skipping")
                continue

            except McpError as e:
                # METHOD_NOT_FOUND (-32601) means the method isn't supported - try next
                if e.error.code == METHOD_NOT_FOUND:
                    logger.debug(f"Health check method '{method}' not supported by server, trying next")
                    continue
                # Other MCP errors are real failures
                logger.debug(f"Health check '{method}' failed with MCP error: {e}")
                self._health_check_failures += 1
                return False

            except asyncio.TimeoutError:
                logger.debug(f"Health check '{method}' timed out after {self._health_check_timeout}s, trying next")
                continue

            except Exception as e:
                logger.debug(f"Health check '{method}' failed: {e}")
                self._health_check_failures += 1
                return False

        # All methods failed or were unsupported
        logger.warning(f"All health check methods failed or unsupported (methods={self._health_check_methods})")
        self._health_check_failures += 1
        return False

    async def _create_session(
        self,
        url: str,
        headers: Optional[Dict[str, str]],
        transport_type: TransportType,
        httpx_client_factory: Optional[HttpxClientFactory],
        timeout: Optional[float] = None,
        gateway_id: Optional[str] = None,
    ) -> PooledSession:
        """
        Create a new initialized MCP session.

        Args:
            url: Server URL.
            headers: Request headers.
            transport_type: Transport type to use.
            httpx_client_factory: Optional factory for httpx clients.
            timeout: Optional timeout in seconds for transport connection.
            gateway_id: Optional gateway ID for notification handler context.

        Returns:
            Initialized PooledSession.

        Raises:
            RuntimeError: If session creation or initialization fails.
            asyncio.CancelledError: If cancelled during creation.
        """
        # Merge headers with defaults
        merged_headers = {"Accept": "application/json, text/event-stream"}
        if headers:
            merged_headers.update(headers)

        identity_key = self._compute_identity_hash(headers)
        transport_ctx = None
        session = None
        success = False

        try:
            # Create transport context
            if transport_type == TransportType.SSE:
                if httpx_client_factory:
                    transport_ctx = sse_client(url=url, headers=merged_headers, httpx_client_factory=httpx_client_factory, timeout=timeout)
                else:
                    transport_ctx = sse_client(url=url, headers=merged_headers, timeout=timeout)
                # pylint: disable=unnecessary-dunder-call,no-member
                streams = await transport_ctx.__aenter__()  # Must call directly for manual lifecycle management
                read_stream, write_stream = streams[0], streams[1]
            else:  # STREAMABLE_HTTP
                if httpx_client_factory:
                    transport_ctx = streamablehttp_client(url=url, headers=merged_headers, httpx_client_factory=httpx_client_factory, timeout=timeout)
                else:
                    transport_ctx = streamablehttp_client(url=url, headers=merged_headers, timeout=timeout)
                # pylint: disable=unnecessary-dunder-call,no-member
                read_stream, write_stream, _ = await transport_ctx.__aenter__()  # Must call directly for manual lifecycle management

            # Create message handler if factory is configured
            message_handler = None
            if self._message_handler_factory:
                try:
                    message_handler = self._message_handler_factory(url, gateway_id)
                    logger.debug(f"Created message handler for session {sanitize_url_for_logging(url)} (gateway={gateway_id})")
                except Exception as e:
                    logger.warning(f"Failed to create message handler for {sanitize_url_for_logging(url)}: {e}")

            # Create and initialize session
            session = ClientSession(read_stream, write_stream, message_handler=message_handler)
            # pylint: disable=unnecessary-dunder-call
            await session.__aenter__()  # Must call directly for manual lifecycle management
            await session.initialize()

            logger.info(f"Created new MCP session for {sanitize_url_for_logging(url)} (transport={transport_type.value})")
            success = True

            return PooledSession(
                session=session,
                transport_context=transport_ctx,
                url=url,
                transport_type=transport_type,
                headers=merged_headers,
                identity_key=identity_key,
                gateway_id=gateway_id or "",
            )

        except asyncio.CancelledError:  # pylint: disable=try-except-raise
            # Re-raise CancelledError after cleanup (handled in finally)
            raise

        except Exception as e:
            raise RuntimeError(f"Failed to create MCP session for {url}: {e}") from e

        finally:
            # Clean up on ANY failure (Exception, CancelledError, etc.)
            # Only clean up if we didn't succeed
            if not success:
                if session is not None:
                    try:
                        await session.__aexit__(None, None, None)  # pylint: disable=unnecessary-dunder-call
                    except Exception:  # nosec B110 - Best effort cleanup on connection failure
                        pass
                if transport_ctx is not None:
                    try:
                        await transport_ctx.__aexit__(None, None, None)  # pylint: disable=unnecessary-dunder-call
                    except Exception:  # nosec B110 - Best effort cleanup on connection failure
                        pass

    async def _close_session(self, pooled: PooledSession) -> None:
        """
        Close a session and its transport.

        Args:
            pooled: The session to close.
        """
        if pooled.is_closed:
            return

        pooled.mark_closed()

        try:
            await pooled.session.__aexit__(None, None, None)  # pylint: disable=unnecessary-dunder-call
        except Exception as e:
            logger.debug(f"Error closing session: {e}")

        try:
            await pooled.transport_context.__aexit__(None, None, None)  # pylint: disable=unnecessary-dunder-call
        except Exception as e:
            logger.debug(f"Error closing transport: {e}")

        logger.debug(f"Closed session for {sanitize_url_for_logging(pooled.url)} (uses={pooled.use_count})")

    async def close_all(self) -> None:
        """
        Gracefully close all pooled and active sessions.

        Should be called during application shutdown.
        """
        self._closed = True
        logger.info("Closing all pooled sessions...")

        async with self._global_lock:
            # Close all pooled sessions
            for _pool_key, pool in list(self._pools.items()):
                while not pool.empty():
                    try:
                        pooled = pool.get_nowait()
                        await self._close_session(pooled)
                    except asyncio.QueueEmpty:
                        break

            # Close all active sessions
            for _pool_key, active_set in list(self._active.items()):
                for pooled in list(active_set):
                    await self._close_session(pooled)

            self._pools.clear()
            self._active.clear()
            self._locks.clear()
            self._semaphores.clear()

        logger.info("All sessions closed")

    def get_metrics(self) -> Dict[str, Any]:
        """
        Return pool metrics for monitoring.

        Returns:
            Dict with hits, misses, evictions, hit_rate, and per-pool stats.
        """
        total_requests = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "evictions": self._evictions,
            "health_check_failures": self._health_check_failures,
            "circuit_breaker_trips": self._circuit_breaker_trips,
            "pool_keys_evicted": self._pool_keys_evicted,
            "sessions_reaped": self._sessions_reaped,
            "anonymous_identity_count": self._anonymous_identity_count,
            "hit_rate": self._hits / total_requests if total_requests > 0 else 0.0,
            "pool_key_count": len(self._pools),
            "pools": {
                f"{url}|{identity[:8]}|{transport}|{user}|{gw_id[:8] if gw_id else 'none'}": {
                    "available": pool.qsize(),
                    "active": len(self._active.get((user, url, identity, transport, gw_id), set())),
                    "max": self._max_sessions,
                }
                for (user, url, identity, transport, gw_id), pool in self._pools.items()
            },
            "circuit_breakers": {
                url: {
                    "failures": self._failures.get(url, 0),
                    "open_until": self._circuit_open_until.get(url),
                }
                for url in set(self._failures.keys()) | set(self._circuit_open_until.keys())
            },
        }

    @asynccontextmanager
    async def session(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        transport_type: TransportType = TransportType.STREAMABLE_HTTP,
        httpx_client_factory: Optional[HttpxClientFactory] = None,
        timeout: Optional[float] = None,
        user_identity: Optional[str] = None,
        gateway_id: Optional[str] = None,
    ) -> "AsyncIterator[PooledSession]":
        """
        Context manager for acquiring and releasing a session.

        Usage:
            async with pool.session(url, headers) as pooled:
                result = await pooled.session.call_tool("my_tool", {})

        Args:
            url: The MCP server URL.
            headers: Request headers.
            transport_type: Transport type to use.
            httpx_client_factory: Optional factory for httpx clients.
            timeout: Optional timeout in seconds for transport connection.
            user_identity: Optional user identity for strict isolation.
            gateway_id: Optional gateway ID for notification handler context.

        Yields:
            PooledSession ready for use.
        """
        pooled = await self.acquire(url, headers, transport_type, httpx_client_factory, timeout, user_identity, gateway_id)
        try:
            yield pooled
        finally:
            await self.release(pooled)


# Global pool instance - initialized by FastAPI lifespan
_mcp_session_pool: Optional[MCPSessionPool] = None


def get_mcp_session_pool() -> MCPSessionPool:
    """Get the global MCP session pool instance.

    Returns:
        The global MCPSessionPool instance.

    Raises:
        RuntimeError: If pool has not been initialized.
    """
    if _mcp_session_pool is None:
        raise RuntimeError("MCP session pool not initialized. Call init_mcp_session_pool() first.")
    return _mcp_session_pool


def init_mcp_session_pool(
    max_sessions_per_key: int = 10,
    session_ttl_seconds: float = 300.0,
    health_check_interval_seconds: float = 60.0,
    acquire_timeout_seconds: float = 30.0,
    session_create_timeout_seconds: float = 30.0,
    circuit_breaker_threshold: int = 5,
    circuit_breaker_reset_seconds: float = 60.0,
    identity_headers: Optional[frozenset[str]] = None,
    identity_extractor: Optional[IdentityExtractor] = None,
    idle_pool_eviction_seconds: float = 600.0,
    default_transport_timeout_seconds: float = 30.0,
    health_check_methods: Optional[list[str]] = None,
    health_check_timeout_seconds: float = 5.0,
    message_handler_factory: Optional[MessageHandlerFactory] = None,
    enable_notifications: bool = True,
    notification_debounce_seconds: float = 5.0,
) -> MCPSessionPool:
    """Initialize the global MCP session pool.

    Args:
        See MCPSessionPool.__init__ for argument descriptions.
        enable_notifications: Enable automatic notification service for list_changed events.
        notification_debounce_seconds: Debounce interval for notification-triggered refreshes.

    Returns:
        The initialized MCPSessionPool instance.
    """
    global _mcp_session_pool  # pylint: disable=global-statement

    # Auto-create notification service if enabled and no custom handler provided
    effective_handler_factory = message_handler_factory
    if enable_notifications and message_handler_factory is None:
        # First-Party
        from mcpgateway.services.notification_service import (  # pylint: disable=import-outside-toplevel
            init_notification_service,
        )

        # Initialize notification service (will be started during acquire with gateway context)
        notification_svc = init_notification_service(debounce_seconds=notification_debounce_seconds)

        # Create default handler factory that uses notification service
        def default_handler_factory(url: str, gateway_id: Optional[str]):
            """Create a message handler for MCP session notifications.

            Args:
                url: The MCP server URL for the session.
                gateway_id: Optional gateway ID for attribution, falls back to URL if not provided.

            Returns:
                A message handler that forwards notifications to the notification service.
            """
            return notification_svc.create_message_handler(gateway_id or url, url)

        effective_handler_factory = default_handler_factory
        logger.info("MCP notification service created (debounce=%ss)", notification_debounce_seconds)

    _mcp_session_pool = MCPSessionPool(
        max_sessions_per_key=max_sessions_per_key,
        session_ttl_seconds=session_ttl_seconds,
        health_check_interval_seconds=health_check_interval_seconds,
        acquire_timeout_seconds=acquire_timeout_seconds,
        session_create_timeout_seconds=session_create_timeout_seconds,
        circuit_breaker_threshold=circuit_breaker_threshold,
        circuit_breaker_reset_seconds=circuit_breaker_reset_seconds,
        identity_headers=identity_headers,
        identity_extractor=identity_extractor,
        idle_pool_eviction_seconds=idle_pool_eviction_seconds,
        default_transport_timeout_seconds=default_transport_timeout_seconds,
        health_check_methods=health_check_methods,
        health_check_timeout_seconds=health_check_timeout_seconds,
        message_handler_factory=effective_handler_factory,
    )
    logger.info("MCP session pool initialized")
    return _mcp_session_pool


async def close_mcp_session_pool() -> None:
    """Close the global MCP session pool and notification service."""
    global _mcp_session_pool  # pylint: disable=global-statement
    if _mcp_session_pool is not None:
        await _mcp_session_pool.close_all()
        _mcp_session_pool = None
        logger.info("MCP session pool closed")

    # Close notification service if it was initialized
    try:
        # First-Party
        from mcpgateway.services.notification_service import (  # pylint: disable=import-outside-toplevel
            close_notification_service,
        )

        await close_notification_service()
    except (ImportError, RuntimeError):
        pass  # Notification service not initialized


async def start_pool_notification_service(gateway_service: Any = None) -> None:
    """Start the notification service background worker.

    Call this after gateway_service is initialized to enable event-driven refresh.

    Args:
        gateway_service: Optional GatewayService instance for triggering refreshes.
    """
    try:
        # First-Party
        from mcpgateway.services.notification_service import (  # pylint: disable=import-outside-toplevel
            get_notification_service,
        )

        notification_svc = get_notification_service()
        await notification_svc.initialize(gateway_service)
        logger.info("MCP notification service started")
    except RuntimeError:
        logger.debug("Notification service not configured, skipping start")


def register_gateway_capabilities_for_notifications(gateway_id: str, capabilities: Dict[str, Any]) -> None:
    """Register gateway capabilities for notification handling.

    Call this after gateway initialization to enable list_changed notifications.

    Args:
        gateway_id: The gateway ID.
        capabilities: Server capabilities from initialization response.
    """
    try:
        # First-Party
        from mcpgateway.services.notification_service import (  # pylint: disable=import-outside-toplevel
            get_notification_service,
        )

        notification_svc = get_notification_service()
        notification_svc.register_gateway_capabilities(gateway_id, capabilities)
    except RuntimeError:
        pass  # Notification service not initialized


def unregister_gateway_from_notifications(gateway_id: str) -> None:
    """Unregister a gateway from notification handling.

    Call this when a gateway is deleted.

    Args:
        gateway_id: The gateway ID to unregister.
    """
    try:
        # First-Party
        from mcpgateway.services.notification_service import (  # pylint: disable=import-outside-toplevel
            get_notification_service,
        )

        notification_svc = get_notification_service()
        notification_svc.unregister_gateway(gateway_id)
    except RuntimeError:
        pass  # Notification service not initialized
