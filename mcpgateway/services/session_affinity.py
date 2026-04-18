# -*- coding: utf-8 -*-
"""Multi-worker session affinity for downstream MCP sessions.

Keeps each downstream MCP session (identified by its ``Mcp-Session-Id``)
pinned to one gateway worker across the horizontal-scale deployment, so
the worker-local ``UpstreamSessionRegistry`` can serve subsequent calls
without rebuilding upstream state. The upstream ClientSession pooling
that used to live in this file is gone — see
``mcpgateway.services.upstream_session_registry`` for the 1:1 replacement
(issue #4205).

What survives here:

* Redis-backed ``(downstream_session_id, url, transport, gateway_id)`` →
  owning-worker mapping so any worker can look up who owns a session.
* Worker heartbeat (``SET EX``) so dead workers can be reclaimed.
* Atomic ownership claim via ``SET NX`` and a Lua CAS reclaim script.
* Session-owner HTTP/RPC forwarding for cross-worker fanout.
* Pub/Sub listener for RPC-style cross-worker requests.
* ``is_valid_mcp_session_id`` validation used by the transport layer.

Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti
"""

# ruff: noqa: D417

# Future
from __future__ import annotations

# Standard
import asyncio
import hashlib
import logging
import os
import re
import socket
import time
from typing import Any, Callable, Dict, Optional
import uuid

# Third-Party
import httpx
from mcp.shared.session import RequestResponder
import mcp.types as mcp_types
import orjson

# First-Party
from mcpgateway.common.validators import SecurityValidator
from mcpgateway.config import settings
from mcpgateway.utils.internal_http import internal_loopback_base_url, internal_loopback_verify

# Shared session-id validation (downstream MCP session IDs used for affinity).
# Intentionally strict: protects Redis key/channel construction and log lines.
_MCP_SESSION_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")

# Worker ID for multi-worker session affinity
# Uses hostname + PID to be unique across Docker containers (each container has PID 1)
# and across gunicorn workers within the same container
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"


logger = logging.getLogger(__name__)


# Type alias for message handler factory.
# Factory that creates message handlers given URL and optional gateway_id.
# The handler receives ServerNotification, ServerRequest responders, or Exceptions.
MessageHandlerFactory = Callable[
    [str, Optional[str]],  # (url, gateway_id)
    Callable[
        [RequestResponder[mcp_types.ServerRequest, mcp_types.ClientResult] | mcp_types.ServerNotification | Exception],
        Any,  # Coroutine
    ],
]


class SessionAffinity:
    """Multi-worker MCP session-affinity service.

    Owns the Redis state (session→worker mapping, worker heartbeat,
    ownership lease, RPC listener) that pins each downstream MCP session
    to one gateway worker across a horizontal-scale deployment. See the
    module docstring for the full surface; see
    ``mcpgateway.services.upstream_session_registry`` for the per-worker
    upstream-session layer this service routes to.
    """

    def __init__(
        self,
        *,
        message_handler_factory: Optional[MessageHandlerFactory] = None,
    ):
        """Initialize the affinity service.

        Args:
            message_handler_factory: Optional factory that builds a message
                handler for forwarded upstream sessions. Affinity itself does
                not drive these handlers, but exposes the factory for callers
                that build MCP clients against routed owners.
        """
        self._message_handler_factory = message_handler_factory

        # Lifecycle
        self._global_lock = asyncio.Lock()
        self._closed = False

        # Background tasks owned by this instance
        self._rpc_listener_task: Optional[asyncio.Task[None]] = None
        self._heartbeat_task: Optional[asyncio.Task[None]] = None

        # Affinity metrics
        self._session_affinity_local_hits = 0
        self._session_affinity_redis_hits = 0
        self._session_affinity_misses = 0
        self._forwarded_requests = 0
        self._forwarded_request_failures = 0
        self._forwarded_request_timeouts = 0

    @staticmethod
    def is_valid_mcp_session_id(session_id: str) -> bool:
        """Validate downstream MCP session ID format for affinity.

        Used for:
        - Redis key construction (ownership + mapping)
        - Pub/Sub channel naming
        - Avoiding log spam / injection
        """
        if not session_id:
            return False
        return bool(_MCP_SESSION_ID_PATTERN.match(session_id))

    def _sanitize_redis_key_component(self, value: str) -> str:
        """Sanitize a value for use in Redis key construction.

        Replaces any characters that could cause key collision or injection.

        Args:
            value: The value to sanitize.

        Returns:
            Sanitized value safe for Redis key construction.
        """
        if not value:
            return ""

        # Replace problematic characters with underscores
        return re.sub(r"[^a-zA-Z0-9_-]", "_", value)

    def _session_mapping_redis_key(self, mcp_session_id: str, url: str, transport_type: str, gateway_id: str) -> str:
        """Compute a bounded Redis key for session mapping.

        The URL is hashed to keep keys small and avoid special character issues.
        """
        sanitized_session_id = self._sanitize_redis_key_component(mcp_session_id)
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
        return f"mcpgw:session_mapping:{sanitized_session_id}:{url_hash}:{transport_type}:{gateway_id}"

    @staticmethod
    def _session_owner_key(mcp_session_id: str) -> str:
        """Return Redis key for session ownership tracking."""
        return f"mcpgw:pool_owner:{mcp_session_id}"

    def _worker_heartbeat_key(self) -> str:
        """Redis key for this worker's heartbeat."""
        return f"mcpgw:worker_heartbeat:{WORKER_ID}"

    def start_heartbeat(self) -> None:
        """Start the worker heartbeat background task.

        Must be called from an async context. Safe to call multiple times;
        subsequent calls are no-ops if the heartbeat is already running.
        """
        if not settings.mcpgateway_session_affinity_enabled:
            return
        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(self._run_heartbeat_loop())

    async def _run_heartbeat_loop(self) -> None:
        """Maintain worker heartbeat in Redis."""
        # First-Party
        from mcpgateway.utils.redis_client import get_redis_client

        while not self._closed:
            try:
                redis = await get_redis_client()
                if redis:
                    # Refresh heartbeat with 30s TTL (much shorter than session TTL)
                    await redis.setex(self._worker_heartbeat_key(), 30, "alive")
            except Exception as e:
                logger.debug(f"Heartbeat update failed: {e}")

            await asyncio.sleep(10)  # Refresh every 10s

    async def _is_worker_alive(self, worker_id: str) -> bool:
        """Check if a worker is alive via heartbeat."""
        try:
            # First-Party
            from mcpgateway.utils.redis_client import get_redis_client

            redis = await get_redis_client()
            if not redis:
                return True  # Assume alive if Redis unavailable

            heartbeat_key = f"mcpgw:worker_heartbeat:{worker_id}"
            return await redis.exists(heartbeat_key) > 0
        except Exception:
            return True  # Fail open

    async def register_session_mapping(
        self,
        mcp_session_id: str,
        url: str,
        gateway_id: str,
        transport_type: str,
        user_email: Optional[str] = None,
    ) -> None:
        """Claim ownership of a downstream MCP session in Redis before any request routes to it.

        Writes two Redis entries keyed on ``mcp_session_id``:
          * ``mcp_session_id → {url, user_hash, identity_hash, transport_type,
            gateway_id}`` — used cross-worker to locate the owner of a session.
          * ``session_owner:<mcp_session_id> → WORKER_ID`` via ``SET NX`` —
            atomically claims this worker as the owner so a second worker
            racing the same session doesn't start creating a parallel
            upstream connection.

        Both entries carry the configured session-affinity TTL and are
        refreshed on subsequent calls. Redis failure is non-fatal — same-worker
        requests can still route via the owner claim, and a fresh call will
        retry. Safe to call repeatedly for an already-owned session.

        Args:
            mcp_session_id: The downstream MCP session ID from x-mcp-session-id header.
            url: The upstream MCP server URL.
            gateway_id: The gateway ID.
            transport_type: The transport type (sse, streamablehttp).
            user_email: The email of the authenticated user (or "system" for unauthenticated).
        """
        if not settings.mcpgateway_session_affinity_enabled:
            return

        # Validate mcp_session_id to prevent Redis key injection
        if not self.is_valid_mcp_session_id(mcp_session_id):
            logger.warning(f"Invalid mcp_session_id format, skipping session mapping: {mcp_session_id[:20]}...")
            return

        # Use user email for user_identity, or "anonymous" if not provided
        user_identity = user_email or "anonymous"

        # Normalize gateway_id to empty string if None for consistent key matching
        normalized_gateway_id = gateway_id or ""

        # Compute the identity + user hashes used for the Redis mapping value.
        identity_hash = hashlib.sha256(mcp_session_id.encode()).hexdigest()
        if user_identity == "anonymous":
            user_hash = "anonymous"
        else:
            user_hash = hashlib.sha256(user_identity.encode()).hexdigest()

        logger.debug(f"Session affinity pre-registering: {mcp_session_id[:8]}... → {url}, " f"user={SecurityValidator.sanitize_log_message(user_identity)}")

        # Store in Redis for multi-worker support AND register ownership atomically
        # Registering ownership HERE (during mapping) instead of in acquire() prevents
        # a race condition where two workers could both start creating sessions before
        # either registers ownership
        try:
            # First-Party
            from mcpgateway.utils.redis_client import get_redis_client  # pylint: disable=import-outside-toplevel

            redis = await get_redis_client()
            if redis:
                redis_key = self._session_mapping_redis_key(mcp_session_id, url, transport_type, normalized_gateway_id)

                # Store pool_key as JSON for easy deserialization
                pool_key_data = {
                    "user_hash": user_hash,
                    "url": url,
                    "identity_hash": identity_hash,
                    "transport_type": transport_type,
                    "gateway_id": normalized_gateway_id,
                }
                await redis.setex(redis_key, settings.mcpgateway_session_affinity_ttl, orjson.dumps(pool_key_data))  # TTL from config

                # CRITICAL: Register ownership atomically with mapping.
                # This claims ownership BEFORE any session creation attempt, preventing
                # the race condition where two workers both start creating sessions
                owner_key = self._session_owner_key(mcp_session_id)
                # Atomic claim with TTL (avoids the SETNX/EXPIRE crash window).
                was_set = await redis.set(owner_key, WORKER_ID, nx=True, ex=settings.mcpgateway_session_affinity_ttl)
                if was_set:
                    logger.debug(f"Session ownership claimed (SET NX): {mcp_session_id[:8]}... → worker {WORKER_ID}")
                else:
                    # Another worker already claimed ownership
                    existing_owner = await redis.get(owner_key)
                    owner_id = existing_owner.decode() if isinstance(existing_owner, bytes) else existing_owner
                    logger.debug(f"Session ownership already claimed by {owner_id}: {mcp_session_id[:8]}...")

                logger.debug(f"Session affinity pre-registered (Redis): {mcp_session_id[:8]}... TTL={settings.mcpgateway_session_affinity_ttl}s")
        except Exception as e:
            # Redis failure is non-fatal - local mapping still works for same-worker requests
            logger.debug(f"Failed to store session mapping in Redis: {e}")

    async def _cleanup_session_owner(self, mcp_session_id: str) -> None:
        """Clear the session-owner Redis key when a downstream MCP session closes.

        Only deletes the key if this worker owns it (to prevent removing other workers' ownership).

        Args:
            mcp_session_id: The MCP session ID from x-mcp-session-id header.
        """
        try:
            # First-Party
            from mcpgateway.utils.redis_client import get_redis_client  # pylint: disable=import-outside-toplevel

            redis = await get_redis_client()
            if redis:
                key = self._session_owner_key(mcp_session_id)
                # Only delete if we own it
                owner = await redis.get(key)
                if owner:
                    owner_id = owner.decode() if isinstance(owner, bytes) else owner
                    if owner_id == WORKER_ID:
                        await redis.delete(key)
                        logger.debug(f"Cleaned up session owner owner: {mcp_session_id[:8]}...")
        except Exception as e:
            # Cleanup failure is non-fatal
            logger.debug(f"Failed to cleanup session owner owner in Redis: {e}")

    async def cleanup_session_owner(self, mcp_session_id: str) -> None:
        """Public wrapper for cleaning up Streamable HTTP session ownership.

        This is used by trusted internal MCP session teardown paths that need to
        remove affinity ownership without reaching into private helpers.
        """
        if not self.is_valid_mcp_session_id(mcp_session_id):
            logger.debug("Invalid mcp_session_id for owner cleanup, skipping")
            return
        await self._cleanup_session_owner(mcp_session_id)

    async def close_all(self) -> None:
        """Stop background tasks and clear affinity state. Call at shutdown."""
        self._closed = True
        logger.info("Closing session-affinity service...")

        # Stop RPC listener if running
        if self._rpc_listener_task and not self._rpc_listener_task.done():
            self._rpc_listener_task.cancel()
            try:
                await self._rpc_listener_task
            except asyncio.CancelledError:
                pass
            self._rpc_listener_task = None

        # Stop heartbeat if running
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None

        logger.info("Session-affinity service closed")

    async def drain_all(self) -> None:
        """No-op hook kept for SIGHUP wiring (session-affinity has no in-memory state to drain).

        Historically this cleared a local session-id → pool-key cache that has
        since been removed — ownership now lives entirely in Redis (where TTLs
        and explicit cleanup handle reuse) and the upstream session lifetime is
        owned by ``UpstreamSessionRegistry``. The method remains so SIGHUP and
        other drain coordinators have a stable entry point, and to advertise
        "there is no worker-local affinity state to blow away on reload."
        """
        logger.info("Session-affinity drain requested; no worker-local state to clear")

    async def register_session_owner(self, mcp_session_id: str) -> None:
        """Claim this worker as the owner of a downstream MCP session, or refresh the existing lease.

        Runs a single Lua CAS: ``SET EX`` on miss (first-time claim), ``EXPIRE``
        on hit where the cached owner matches this worker (TTL refresh), no-op
        otherwise (another worker already owns it). Callers don't need to
        distinguish claim from refresh — the semantics are identical from
        their side. Redis failure is non-fatal and logged at debug.

        Args:
            mcp_session_id: The downstream ``Mcp-Session-Id`` header value.
        """
        if not settings.mcpgateway_session_affinity_enabled:
            return

        if not self.is_valid_mcp_session_id(mcp_session_id):
            logger.debug("Invalid mcp_session_id for owner registration, skipping")
            return

        try:
            # First-Party
            from mcpgateway.utils.redis_client import get_redis_client  # pylint: disable=import-outside-toplevel

            redis = await get_redis_client()
            if redis:
                key = self._session_owner_key(mcp_session_id)

                # Do not steal ownership: only claim if missing, or refresh TTL if we already own.
                # Lua keeps this atomic.
                script = """
                local cur = redis.call('GET', KEYS[1])
                if not cur then
                  redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2])
                  return 1
                end
                if cur == ARGV[1] then
                  redis.call('EXPIRE', KEYS[1], ARGV[2])
                  return 2
                end
                return 0
                """
                ttl = int(settings.mcpgateway_session_affinity_ttl)
                outcome = await redis.eval(script, 1, key, WORKER_ID, ttl)
                logger.debug(f"Owner registration outcome={outcome} for session {mcp_session_id[:8]}...")
        except Exception as e:
            # Redis failure is non-fatal - single worker mode still works
            logger.debug(f"Failed to register session owner in Redis: {e}")

    async def _get_session_owner(self, mcp_session_id: str) -> Optional[str]:
        """Return the worker id that owns ``mcp_session_id``, or None if unclaimed.

        Args:
            mcp_session_id: The downstream ``Mcp-Session-Id`` header value.

        Returns:
            The owning worker id, or None if the session is unclaimed or Redis
            is unavailable.
        """
        if not settings.mcpgateway_session_affinity_enabled:
            return None

        if not self.is_valid_mcp_session_id(mcp_session_id):
            return None

        try:
            # First-Party
            from mcpgateway.utils.redis_client import get_redis_client  # pylint: disable=import-outside-toplevel

            redis = await get_redis_client()
            if redis:
                key = self._session_owner_key(mcp_session_id)
                owner = await redis.get(key)
                if owner:
                    decoded = owner.decode() if isinstance(owner, bytes) else owner
                    return decoded
        except Exception as e:
            logger.debug(f"Failed to get session owner from Redis: {e}")
        return None

    async def forward_request_to_owner(
        self,
        mcp_session_id: str,
        request_data: Dict[str, Any],
        timeout: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """Forward RPC request to the worker that owns the session owner.

        This method checks Redis to find which worker owns the session owner for
        the given mcp_session_id. If owned by another worker, it forwards the
        request via Redis pub/sub and waits for the response.

        Args:
            mcp_session_id: The MCP session ID from x-mcp-session-id header.
            request_data: The RPC request data to forward.
            timeout: Optional timeout in seconds (default from config).

        Returns:
            The response from the owner worker, or None if we own the session
            (caller should execute locally) or if Redis is unavailable.

        Raises:
            asyncio.TimeoutError: If the forwarded request times out.
        """
        if not settings.mcpgateway_session_affinity_enabled:
            return None

        if not self.is_valid_mcp_session_id(mcp_session_id):
            return None

        effective_timeout = timeout if timeout is not None else settings.mcpgateway_pool_rpc_forward_timeout

        try:
            # First-Party
            from mcpgateway.utils.redis_client import get_redis_client  # pylint: disable=import-outside-toplevel

            redis = await get_redis_client()
            if not redis:
                return None  # Execute locally - no Redis

            # Check who owns this session
            owner = await redis.get(self._session_owner_key(mcp_session_id))
            method = request_data.get("method", "unknown")
            if not owner:
                logger.info(f"[AFFINITY] Worker {WORKER_ID} | Session {mcp_session_id[:8]}... | Method: {method} | No owner → execute locally (new session)")
                return None  # No owner registered - execute locally (new session)

            owner_id = owner.decode() if isinstance(owner, bytes) else owner
            if owner_id == WORKER_ID:
                logger.info(f"[AFFINITY] Worker {WORKER_ID} | Session {mcp_session_id[:8]}... | Method: {method} | We own it → execute locally")
                return None  # We own it - execute locally

            if not await self._is_worker_alive(owner_id):
                logger.warning(f"[AFFINITY] Owner {owner_id} is dead for session {mcp_session_id[:8]}...")
                # CAS: reclaim only if still owned by the dead worker
                cas_script = """
                local cur = redis.call('GET', KEYS[1])
                if cur == ARGV[1] then
                  redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[3])
                  return 1
                end
                return 0
                """
                ttl = int(settings.mcpgateway_session_affinity_ttl)
                reclaimed = await redis.eval(cas_script, 1, self._session_owner_key(mcp_session_id), owner_id, WORKER_ID, ttl)
                if reclaimed == 1:
                    logger.info(f"[AFFINITY] Reclaimed session {mcp_session_id[:8]}... from dead worker {owner_id} → execute locally")
                    return None  # We won the reclaim - execute locally
                # Another worker already reclaimed; re-read the new owner and forward
                new_owner = await redis.get(self._session_owner_key(mcp_session_id))
                if not new_owner:
                    return None  # Key vanished - execute locally
                owner_id = new_owner.decode() if isinstance(new_owner, bytes) else new_owner
                if owner_id == WORKER_ID:
                    return None  # We ended up as owner
                logger.info(f"[AFFINITY] Session {mcp_session_id[:8]}... reclaimed by {owner_id} → forwarding to new owner")

            logger.info(f"[AFFINITY] Worker {WORKER_ID} | Session {mcp_session_id[:8]}... | Method: {method} | Owner: {owner_id} → forwarding")

            # Forward to owner worker via pub/sub
            response_id = str(uuid.uuid4())
            response_channel = f"mcpgw:pool_rpc_response:{response_id}"

            # Subscribe to response channel
            pubsub = redis.pubsub()
            await pubsub.subscribe(response_channel)

            try:
                # Prepare request with response channel
                forward_data = {
                    "type": "rpc_forward",
                    **request_data,
                    "response_channel": response_channel,
                    "mcp_session_id": mcp_session_id,
                }

                # Publish request to owner's channel
                await redis.publish(f"mcpgw:pool_rpc:{owner_id}", orjson.dumps(forward_data))
                self._forwarded_requests += 1
                logger.info(f"[AFFINITY] Worker {WORKER_ID} | Session {mcp_session_id[:8]}... | Method: {method} | Published to worker {owner_id}")

                # Wait for response
                async with asyncio.timeout(effective_timeout):
                    async for msg in pubsub.listen():
                        if msg["type"] == "message":
                            return orjson.loads(msg["data"])
            finally:
                await pubsub.unsubscribe(response_channel)

        except asyncio.TimeoutError:
            self._forwarded_request_timeouts += 1
            logger.warning(f"Timeout forwarding request to owner for session {mcp_session_id[:8]}...")
            raise
        except Exception as e:
            self._forwarded_request_failures += 1
            logger.debug(f"Error forwarding request to owner: {e}")
            return None  # Execute locally on error

    async def start_rpc_listener(self) -> None:
        """Start listening for forwarded RPC and HTTP requests on this worker's channels.

        This method subscribes to Redis pub/sub channels specific to this worker
        and processes incoming forwarded requests from other workers:
        - mcpgw:pool_rpc:{WORKER_ID} - for SSE transport JSON-RPC forwards
        - mcpgw:pool_http:{WORKER_ID} - for Streamable HTTP request forwards
        """
        if not settings.mcpgateway_session_affinity_enabled:
            return

        try:
            # First-Party
            from mcpgateway.utils.redis_client import get_redis_client  # pylint: disable=import-outside-toplevel

            redis = await get_redis_client()
            if not redis:
                logger.debug("Redis not available, RPC listener not started")
                return

            rpc_channel = f"mcpgw:pool_rpc:{WORKER_ID}"
            http_channel = f"mcpgw:pool_http:{WORKER_ID}"
            pubsub = redis.pubsub()
            await pubsub.subscribe(rpc_channel, http_channel)
            logger.info(f"RPC/HTTP listener started for worker {WORKER_ID} on channels: {rpc_channel}, {http_channel}")

            try:
                while not self._closed:
                    try:
                        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                        if msg and msg["type"] == "message":
                            request = orjson.loads(msg["data"])
                            forward_type = request.get("type")
                            response_channel = request.get("response_channel")

                            if response_channel:
                                if forward_type == "rpc_forward":
                                    # Execute forwarded RPC request for SSE transport
                                    response = await self._execute_forwarded_request(request)
                                    await redis.publish(response_channel, orjson.dumps(response))
                                    logger.debug(f"Processed forwarded RPC request, response sent to {response_channel}")
                                elif forward_type == "http_forward":
                                    # Execute forwarded HTTP request for Streamable HTTP transport
                                    await self._execute_forwarded_http_request(request, redis)
                                else:
                                    logger.warning(f"Unknown forward type: {forward_type}")
                    except Exception as e:
                        logger.warning(f"Error processing forwarded request: {e}")
            finally:
                await pubsub.unsubscribe(rpc_channel, http_channel)
                logger.info(f"RPC/HTTP listener stopped for worker {WORKER_ID}")

        except Exception as e:
            logger.warning(f"RPC/HTTP listener failed: {e}")

    async def _execute_forwarded_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a forwarded RPC request locally via internal HTTP call.

        This method handles RPC requests that were forwarded from another worker.
        Instead of handling specific methods here, we make an internal HTTP call
        to the local /rpc endpoint which reuses ALL existing method handling logic.

        The x-forwarded-internally header prevents infinite forwarding loops.

        Args:
            request: The forwarded RPC request containing method, params, headers, req_id, etc.

        Returns:
            The JSON-RPC response from the local endpoint.
        """
        try:
            method = request.get("method")
            params = request.get("params", {})
            headers = request.get("headers", {})
            req_id = request.get("req_id", 1)
            mcp_session_id = request.get("mcp_session_id", "unknown")
            session_short = mcp_session_id[:8] if len(mcp_session_id) >= 8 else mcp_session_id

            logger.info(f"[AFFINITY] Worker {WORKER_ID} | Session {session_short}... | Method: {method} | Received forwarded request, executing locally")

            # Make internal HTTP/HTTPS call to local /rpc endpoint.
            # This reuses ALL existing method handling logic without duplication.
            internal_base_url = internal_loopback_base_url()
            async with httpx.AsyncClient(verify=internal_loopback_verify()) as client:
                # Build headers for internal request - forward original headers
                # but add x-forwarded-internally to prevent infinite loops.
                # Relies on the originating transport having already filtered
                # passthrough headers via extract_headers_for_loopback (#3640).
                internal_headers = dict(headers)
                internal_headers["x-forwarded-internally"] = "true"
                # Ensure content-type is set
                internal_headers["content-type"] = "application/json"

                response = await client.post(
                    f"{internal_base_url}/rpc",
                    json={"jsonrpc": "2.0", "method": method, "params": params, "id": req_id},
                    headers=internal_headers,
                    timeout=settings.mcpgateway_pool_rpc_forward_timeout,
                )

                # Gate on HTTP status first: non-2xx responses are errors
                # even if the body parses as JSON.
                if not response.is_success:
                    try:
                        response_data = response.json()
                    except ValueError:
                        response_data = {}
                    if not isinstance(response_data, dict):
                        response_data = {}

                    # If body is a JSON-RPC error ({"error": {...}}), propagate it
                    if "error" in response_data and isinstance(response_data["error"], dict):
                        logger.info(f"[AFFINITY] Worker {WORKER_ID} | Session {session_short}... | Method: {method} | Forwarded execution completed with error (HTTP {response.status_code})")
                        return {"error": response_data["error"]}

                    # Non-JSON-RPC error body (e.g. {"detail": "..."}): map to JSON-RPC error
                    detail = response_data.get("detail", response.text[:200] or "Unknown error")
                    logger.info(f"[AFFINITY] Worker {WORKER_ID} | Session {session_short}... | Method: {method} | Forwarded execution failed with HTTP {response.status_code}")
                    return {"error": {"code": -32603, "message": f"Forwarded request failed (HTTP {response.status_code}): {detail}"}}

                # Parse successful response
                response_data = response.json()

                # Extract result or error from JSON-RPC response
                if "error" in response_data:
                    logger.info(f"[AFFINITY] Worker {WORKER_ID} | Session {session_short}... | Method: {method} | Forwarded execution completed with error")
                    return {"error": response_data["error"]}
                logger.info(f"[AFFINITY] Worker {WORKER_ID} | Session {session_short}... | Method: {method} | Forwarded execution completed successfully")
                return {"result": response_data.get("result", {})}

        except httpx.TimeoutException:
            logger.warning(f"Timeout executing forwarded request: {request.get('method')}")
            return {"error": {"code": -32603, "message": "Internal request timeout"}}
        except Exception as e:
            logger.warning(f"Error executing forwarded request: {e}")
            return {"error": {"code": -32603, "message": str(e)}}

    async def _execute_forwarded_http_request(self, request: Dict[str, Any], redis: Any) -> None:
        """Execute a forwarded HTTP request locally and return response via Redis.

        This method handles full HTTP requests forwarded from other workers for
        Streamable HTTP transport session affinity. It reconstructs the HTTP request,
        makes an internal call to the appropriate endpoint, and publishes the response
        back through Redis.

        Args:
            request: Serialized HTTP request data from Redis Pub/Sub containing:
                - type: "http_forward"
                - response_channel: Redis channel to publish response to
                - mcp_session_id: Session identifier
                - method: HTTP method (GET, POST, DELETE)
                - path: Request path (e.g., /mcp)
                - query_string: Query parameters
                - headers: Request headers dict
                - body: Hex-encoded request body
            redis: Redis client for publishing response
        """
        response_channel = None
        try:
            response_channel = request.get("response_channel")
            method = request.get("method")
            path = request.get("path")
            query_string = request.get("query_string", "")
            headers = request.get("headers", {})
            body_hex = request.get("body", "")
            mcp_session_id = request.get("mcp_session_id")

            # Decode hex body back to bytes
            body = bytes.fromhex(body_hex) if body_hex else b""

            session_short = mcp_session_id[:8] if mcp_session_id and len(mcp_session_id) >= 8 else "unknown"
            logger.debug(f"[HTTP_AFFINITY] Worker {WORKER_ID} | Session {session_short}... | Received forwarded HTTP request: {method} {path}")

            # Add internal forwarding headers to prevent loops.
            # Relies on the originating transport having already filtered
            # passthrough headers via extract_headers_for_loopback (#3640).
            internal_headers = dict(headers)
            internal_headers["x-forwarded-internally"] = "true"
            internal_headers["x-original-worker"] = request.get("original_worker", "unknown")

            # Make internal HTTP/HTTPS request to local endpoint
            url = f"{internal_loopback_base_url()}{path}"
            if query_string:
                url = f"{url}?{query_string}"

            async with httpx.AsyncClient(verify=internal_loopback_verify()) as client:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=internal_headers,
                    content=body,
                    timeout=settings.mcpgateway_pool_rpc_forward_timeout,
                )

                logger.debug(f"[HTTP_AFFINITY] Worker {WORKER_ID} | Session {session_short}... | Executed locally: {response.status_code}")

                # Serialize response for Redis transport
                response_data = {
                    "status": response.status_code,
                    "headers": dict(response.headers),
                    "body": response.content.hex(),  # Hex encode binary response
                }

                # Publish response back to requesting worker
                if redis and response_channel:
                    await redis.publish(response_channel, orjson.dumps(response_data))
                    logger.debug(f"[HTTP_AFFINITY] Published HTTP response to Redis channel: {response_channel}")

        except Exception as e:
            logger.error(f"Error executing forwarded HTTP request: {e}")
            # Try to send error response if possible
            if redis and response_channel:
                error_response = {
                    "status": 500,
                    "headers": {"content-type": "application/json"},
                    "body": orjson.dumps({"error": "Internal forwarding error"}).hex(),
                }
                try:
                    await redis.publish(response_channel, orjson.dumps(error_response))
                except Exception as publish_error:
                    logger.debug(f"Failed to publish error response via Redis: {publish_error}")

    async def get_session_owner(self, mcp_session_id: str) -> Optional[str]:
        """Get the worker ID that owns a Streamable HTTP session.

        This is a public wrapper around _get_session_owner for use by
        streamablehttp_transport to check session ownership before handling requests.

        Args:
            mcp_session_id: The MCP session ID from mcp-session-id header.

        Returns:
            Worker ID if found, None otherwise.
        """
        return await self._get_session_owner(mcp_session_id)

    async def forward_to_owner(
        self,
        owner_worker_id: str,
        mcp_session_id: str,
        method: str,
        path: str,
        headers: Dict[str, str],
        body: bytes,
        query_string: str = "",
    ) -> Optional[Dict[str, Any]]:
        """Forward a Streamable HTTP request to the worker that owns the session via Redis Pub/Sub.

        This method forwards the entire HTTP request to another worker using Redis
        Pub/Sub channels, similar to forward_request_to_owner() for SSE transport.
        This ensures session affinity works correctly in single-host multi-worker
        deployments where hostname-based routing fails.

        Args:
            owner_worker_id: The worker ID that owns the session.
            mcp_session_id: The MCP session ID.
            method: HTTP method (GET, POST, DELETE).
            path: Request path (e.g., /mcp).
            headers: Request headers.
            body: Request body bytes.
            query_string: Query string if any.

        Returns:
            Dict with 'status', 'headers', and 'body' from the owner worker's response,
            or None if forwarding fails.
        """
        if not settings.mcpgateway_session_affinity_enabled:
            return None

        if not self.is_valid_mcp_session_id(mcp_session_id):
            return None

        session_short = mcp_session_id[:8] if len(mcp_session_id) >= 8 else mcp_session_id
        logger.debug(f"[HTTP_AFFINITY] Worker {WORKER_ID} | Session {session_short}... | {method} {path} | Forwarding to worker {owner_worker_id}")

        try:
            # First-Party
            from mcpgateway.utils.redis_client import get_redis_client  # pylint: disable=import-outside-toplevel

            redis = await get_redis_client()
            if not redis:
                logger.warning("Redis unavailable for HTTP forwarding, executing locally")
                return None  # Fall back to local execution

            # Generate unique response channel for this request
            response_uuid = uuid.uuid4().hex
            response_channel = f"mcpgw:pool_http_response:{response_uuid}"

            # Serialize HTTP request for Redis transport
            forward_data = {
                "type": "http_forward",
                "response_channel": response_channel,
                "mcp_session_id": mcp_session_id,
                "method": method,
                "path": path,
                "query_string": query_string,
                "headers": headers,
                "body": body.hex() if body else "",  # Hex encode binary body
                "original_worker": WORKER_ID,
                "timestamp": time.time(),
            }

            # Subscribe to response channel BEFORE publishing request (prevent race)
            pubsub = redis.pubsub()
            await pubsub.subscribe(response_channel)

            try:
                # Publish forwarded request to owner worker's HTTP channel
                owner_channel = f"mcpgw:pool_http:{owner_worker_id}"
                await redis.publish(owner_channel, orjson.dumps(forward_data))
                logger.debug(f"[HTTP_AFFINITY] Published HTTP request to Redis channel: {owner_channel}")

                # Wait for response with timeout
                timeout = settings.mcpgateway_pool_rpc_forward_timeout
                async with asyncio.timeout(timeout):
                    while True:
                        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
                        if msg and msg["type"] == "message":
                            response_data = orjson.loads(msg["data"])
                            logger.debug(f"[HTTP_AFFINITY] Received HTTP response via Redis: status={response_data.get('status')}")

                            # Decode hex body back to bytes
                            body_hex = response_data.get("body", "")
                            response_data["body"] = bytes.fromhex(body_hex) if body_hex else b""

                            self._forwarded_requests += 1
                            return response_data

            finally:
                await pubsub.unsubscribe(response_channel)

        except asyncio.TimeoutError:
            self._forwarded_request_timeouts += 1
            logger.warning(f"Timeout forwarding HTTP request to owner {owner_worker_id}")
            return None
        except Exception as e:
            self._forwarded_request_failures += 1
            logger.warning(f"Error forwarding HTTP request via Redis: {e}")
            return None


_mcp_session_pool: Optional[SessionAffinity] = None


def get_session_affinity() -> SessionAffinity:
    """Return the global session-affinity service instance.

    Raises:
        RuntimeError: If the service has not been initialized.
    """
    if _mcp_session_pool is None:
        raise RuntimeError("Session-affinity service not initialized. Call init_session_affinity() first.")
    return _mcp_session_pool


def init_session_affinity(
    *,
    message_handler_factory: Optional[MessageHandlerFactory] = None,
    enable_notifications: bool = True,
    notification_debounce_seconds: float = 5.0,
) -> SessionAffinity:
    """Initialize the global session-affinity service.

    Args:
        message_handler_factory: Optional factory that builds MCP message
            handlers for routed upstream sessions.
        enable_notifications: When True (default) and no explicit handler
            factory is provided, wire a handler that forwards server
            notifications to the notification service.
        notification_debounce_seconds: Debounce interval for
            notification-triggered refreshes.

    Returns:
        The initialized ``SessionAffinity`` instance.
    """
    global _mcp_session_pool  # pylint: disable=global-statement

    effective_handler_factory = message_handler_factory
    if enable_notifications and message_handler_factory is None:
        # First-Party
        from mcpgateway.services.notification_service import (  # pylint: disable=import-outside-toplevel
            init_notification_service,
        )

        notification_svc = init_notification_service(debounce_seconds=notification_debounce_seconds)

        def default_handler_factory(url: str, gateway_id: Optional[str]):
            """Create a message handler that routes MCP notifications to the notification service."""
            return notification_svc.create_message_handler(gateway_id or url, url)

        effective_handler_factory = default_handler_factory
        logger.info("MCP notification service created (debounce=%ss)", notification_debounce_seconds)

    _mcp_session_pool = SessionAffinity(message_handler_factory=effective_handler_factory)
    logger.info("Session-affinity service initialized")
    return _mcp_session_pool


async def close_session_affinity() -> None:
    """Close the global MCP session pool and notification service."""
    global _mcp_session_pool  # pylint: disable=global-statement
    if _mcp_session_pool is not None:
        await _mcp_session_pool.close_all()
        _mcp_session_pool = None
        logger.info("Session-affinity service closed")

    # Close notification service if it was initialized
    try:
        # First-Party
        from mcpgateway.services.notification_service import (  # pylint: disable=import-outside-toplevel
            close_notification_service,
        )

        await close_notification_service()
    except (ImportError, RuntimeError):
        pass  # Notification service not initialized


async def drain_session_affinity() -> None:
    """Delegate to ``SessionAffinity.drain_all()`` on the global service.

    Worker-local affinity state was removed when the per-worker pool was
    retired, so ``drain_all`` is now a log-only no-op that exists purely as
    a stable entry point for SIGHUP wiring. Kept so callers don't need to
    branch on whether the global service is initialised.
    """
    if _mcp_session_pool is not None:
        await _mcp_session_pool.drain_all()


async def start_affinity_notification_service(gateway_service: Any = None) -> None:
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
