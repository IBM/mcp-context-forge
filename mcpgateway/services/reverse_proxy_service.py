# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/reverse_proxy_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Business logic for reverse proxy session management.

This service handles session lifecycle, Redis-based session affinity,
health monitoring, and message forwarding between workers.
"""

# Standard
import asyncio
from datetime import datetime, timezone
import os
import socket
from typing import Any, Dict, Optional
from urllib.parse import urlparse
import uuid

# Third-Party
import orjson

# First-Party
from mcpgateway.config import settings
from mcpgateway.services.logging_service import LoggingService

# Initialize logging
logging_service = LoggingService()
LOGGER = logging_service.get_logger("mcpgateway.services.reverse_proxy_service")


def get_worker_id() -> str:
    """Get the current worker ID (hostname:pid).

    This must be a function, not a module-level constant, because with
    gunicorn's preload_app=True, the module is imported in the parent process
    before forking. If we cache the PID at import time, all workers will
    have the parent's PID instead of their own.

    Returns:
        Worker ID string in format "hostname:pid"
    """
    return f"{socket.gethostname()}:{os.getpid()}"


class ReverseProxySession:
    """Manages a reverse proxy session."""

    def __init__(self, session_id: str, websocket: Any, user: Optional[str | dict] = None):
        """Initialize reverse proxy session.

        Args:
            session_id: Unique session identifier.
            websocket: WebSocket connection.
            user: Authenticated user info (if any).
        """
        self.session_id = session_id
        self.websocket = websocket
        self.user = user
        self.server_info: Dict[str, Any] = {}
        self.connected_at = datetime.now(tz=timezone.utc)
        self.last_activity = datetime.now(tz=timezone.utc)
        self.last_heartbeat = datetime.now(tz=timezone.utc)
        self.message_count = 0
        self.bytes_transferred = 0
        self.missed_heartbeats = 0
        # Timestamp (monotonic) of the last Redis ownership TTL refresh.
        # Used by ReverseProxyManager.refresh_session_ownership_if_due() to
        # throttle EXPIRE calls so we don't hit Redis on every heartbeat.
        self.last_ownership_refresh: float = 0.0

    async def send_message(self, message: Dict[str, Any]) -> None:
        """Send message to the client.

        Args:
            message: Message dictionary to send.
        """
        data = orjson.dumps(message).decode()
        await self.websocket.send_text(data)
        self.bytes_transferred += len(data)
        self.last_activity = datetime.now(tz=timezone.utc)

    async def receive_message(self) -> Dict[str, Any]:
        """Receive message from the client.

        Returns:
            Parsed message dictionary.
        """
        data = await self.websocket.receive_text()
        self.bytes_transferred += len(data)
        self.message_count += 1
        self.last_activity = datetime.now(tz=timezone.utc)
        return orjson.loads(data)


class ReverseProxyManager:
    """Manages all reverse proxy sessions with distributed session affinity support.

    Session affinity uses the same Redis Pub/Sub mechanism as SSE and Streamable HTTP
    transports (see ADR-038). The reverse proxy channel is integrated into the shared
    ``MCPSessionPool.start_rpc_listener()`` loop, which handles three message types:

    - ``rpc_forward``           → SSE JSON-RPC forwarding
    - ``http_forward``          → Streamable HTTP request forwarding
    - ``reverse_proxy_forward`` → Reverse proxy WebSocket message forwarding (this module)

    Redis key patterns used:
    - ``mcpgw:reverse_proxy_owner:{session_id}``  – ownership (same TTL as pool_owner)
    - ``mcpgw:reverse_proxy:{worker_id}``         – per-worker Pub/Sub channel
    - ``mcpgw:reverse_proxy_response:{uuid}``     – per-request response channel
    """

    def __init__(self):
        """Initialize the manager."""
        self.sessions: Dict[str, ReverseProxySession] = {}
        self._lock = asyncio.Lock()
        self._health_check_task: Optional[asyncio.Task] = None
        self._session_failure_counts: Dict[str, int] = {}

    async def register_session_ownership(self, session_id: str) -> None:
        """Register session ownership in Redis using an unconditional SET EX.

        Uses ``SET key value EX ttl`` (unconditional, **no NX**) so that a
        reconnecting proxy always claims ownership on the new worker, overwriting
        any stale key left by a previous connection that disconnected.

        Unlike ``MCPSessionPool.register_session_mapping()`` which uses NX (first
        writer wins for upstream pool sessions), the reverse proxy WebSocket
        connection IS the ownership proof — the live WebSocket always wins.

        The TTL is kept alive by ``refresh_session_ownership_if_due()`` (called
        from the heartbeat handler, throttled to at most once per ``TTL/2``
        seconds) and the key is explicitly deleted by
        ``release_session_ownership()`` on disconnect, so the TTL is only a
        safety net for crash recovery.

        Args:
            session_id: Session ID to register ownership for.
        """
        if not settings.mcpgateway_session_affinity_enabled:
            LOGGER.info(f"[REVERSE_PROXY_AFFINITY] Session affinity disabled – local-only mode for session {session_id[:8]}...")
            return

        # First-Party
        from mcpgateway.utils.redis_client import get_redis_client  # pylint: disable=import-outside-toplevel

        redis = await get_redis_client()
        if not redis:
            LOGGER.warning("[REVERSE_PROXY_AFFINITY] Redis not available – falling back to local-only mode (session affinity inactive)")
            return

        owner_key = f"mcpgw:reverse_proxy_owner:{session_id}"
        try:
            # Unconditional SET EX – new WebSocket connection always wins ownership.
            # This handles reconnects: if the proxy disconnected and reconnected
            # (possibly to a different worker), the new connection must be able to
            # claim ownership even if the old TTL key still exists in Redis.
            ttl = int(settings.mcpgateway_session_affinity_ttl)
            worker_id = get_worker_id()
            await redis.set(owner_key, worker_id, ex=ttl)
            LOGGER.info(f"[REVERSE_PROXY_AFFINITY] Worker {worker_id} | Session {session_id[:8]}... | Ownership CLAIMED (SET EX {ttl}s) → key {owner_key}")
        except Exception as e:
            LOGGER.error(f"[REVERSE_PROXY_AFFINITY] Worker {get_worker_id()} | Session {session_id[:8]}... | Failed to register ownership: {e}", exc_info=True)

    async def release_session_ownership(self, session_id: str) -> None:
        """Release session ownership in Redis by deleting the ownership key.

        Called on WebSocket disconnect so that a reconnecting proxy on any worker
        can immediately claim ownership without waiting for the TTL to expire.

        Args:
            session_id: Session ID to release ownership for.
        """
        if not settings.mcpgateway_session_affinity_enabled:
            return

        # First-Party
        from mcpgateway.utils.redis_client import get_redis_client  # pylint: disable=import-outside-toplevel

        redis = await get_redis_client()
        if not redis:
            return

        owner_key = f"mcpgw:reverse_proxy_owner:{session_id}"
        try:
            await redis.delete(owner_key)
            LOGGER.info(f"[REVERSE_PROXY_AFFINITY] Worker {get_worker_id()} | Session {session_id[:8]}... | Ownership RELEASED (DEL {owner_key})")
        except Exception as e:
            LOGGER.warning(f"[REVERSE_PROXY_AFFINITY] Worker {get_worker_id()} | Session {session_id[:8]}... | Failed to release ownership: {e}")

    async def refresh_session_ownership_if_due(self, session_id: str, session: "ReverseProxySession") -> None:
        """Refresh the Redis ownership TTL if enough time has passed since the last refresh.

        Called from the heartbeat handler.  Heartbeats may arrive frequently
        (e.g. every few seconds), so we throttle Redis ``EXPIRE`` calls to at
        most once per ``TTL/2`` seconds using ``session.last_ownership_refresh``.

        This keeps the ownership key alive for long-lived idle connections without
        hammering Redis on every heartbeat.

        Args:
            session_id: Session ID whose ownership TTL to refresh.
            session: The ``ReverseProxySession`` instance (holds the throttle timestamp).
        """
        if not settings.mcpgateway_session_affinity_enabled:
            return

        # Standard
        import time  # pylint: disable=import-outside-toplevel

        ttl = int(settings.mcpgateway_session_affinity_ttl)
        refresh_interval = max(ttl // 2, 30)  # Refresh at TTL/2, minimum 30s
        now = time.monotonic()

        if now - session.last_ownership_refresh < refresh_interval:
            return  # Not due yet – skip Redis call

        # First-Party
        from mcpgateway.utils.redis_client import get_redis_client  # pylint: disable=import-outside-toplevel

        redis = await get_redis_client()
        if not redis:
            return

        owner_key = f"mcpgw:reverse_proxy_owner:{session_id}"
        try:
            refreshed = await redis.expire(owner_key, int(ttl))
            session.last_ownership_refresh = now
            if refreshed:
                LOGGER.info(f"[REVERSE_PROXY_AFFINITY] Worker {get_worker_id()} | Session {session_id[:8]}... | " f"Ownership TTL refreshed via heartbeat (EXPIRE {ttl}s)")
            else:
                # Key expired between heartbeats – re-claim unconditionally
                worker_id = get_worker_id()
                LOGGER.warning(f"[REVERSE_PROXY_AFFINITY] Worker {worker_id} | Session {session_id[:8]}... | " f"Ownership key missing during heartbeat refresh – re-claiming")
                await redis.set(owner_key, worker_id, ex=ttl)
        except Exception as e:
            LOGGER.warning(f"[REVERSE_PROXY_AFFINITY] Worker {get_worker_id()} | Session {session_id[:8]}... | Heartbeat TTL refresh failed: {e}")

    async def get_session_owner(self, session_id: str) -> Optional[str]:
        """Get the worker ID that owns this session.

        Args:
            session_id: Session ID to check ownership for.

        Returns:
            Worker ID string that owns the session, or None if not found in Redis.
        """
        # First-Party
        from mcpgateway.utils.redis_client import get_redis_client  # pylint: disable=import-outside-toplevel

        redis = await get_redis_client()
        if not redis:
            LOGGER.info(f"[REVERSE_PROXY_AFFINITY] Redis unavailable – assuming local ownership for session {session_id[:8]}...")
            return get_worker_id()  # Assume local ownership when Redis unavailable

        owner_key = f"mcpgw:reverse_proxy_owner:{session_id}"
        try:
            owner = await redis.get(owner_key)
            owner_id = owner.decode() if isinstance(owner, bytes) else owner
            if owner_id:
                LOGGER.info(f"[REVERSE_PROXY_AFFINITY] Worker {get_worker_id()} | Session {session_id[:8]}... | Owner from Redis: {owner_id}")
            else:
                LOGGER.info(f"[REVERSE_PROXY_AFFINITY] Worker {get_worker_id()} | Session {session_id[:8]}... | No owner in Redis (unregistered session)")
            return owner_id
        except Exception as e:
            LOGGER.error(f"[REVERSE_PROXY_AFFINITY] Worker {get_worker_id()} | Session {session_id[:8]}... | Failed to get owner from Redis: {e}", exc_info=True)
            return get_worker_id()  # Fallback to local

    async def forward_message_to_owner(
        self,
        session_id: str,
        message: Dict[str, Any],
        timeout: float = 30.0,
    ) -> Dict[str, Any]:
        """Forward message to session owner via Redis Pub/Sub.

        Uses the same polling pattern as ``MCPSessionPool.forward_request_to_owner()``
        and ``forward_streamable_http_to_owner()``:
        subscribe → publish → poll with ``get_message()`` inside ``asyncio.timeout()``.

        Raises:
            RuntimeError: If the message forwarding fails or times out.

        Args:
            session_id: Session ID to forward message to.
            message: Message to forward.
            timeout: Timeout in seconds for response.

        Returns:
            Response from the owner worker.

        Raises:
            ValueError: If session not found.
            asyncio.TimeoutError: If request times out.
        """
        # First-Party
        from mcpgateway.utils.redis_client import get_redis_client  # pylint: disable=import-outside-toplevel

        redis = await get_redis_client()
        if not redis:
            raise RuntimeError("Redis unavailable for cross-worker forwarding")

        response_id = uuid.uuid4().hex
        response_channel = f"mcpgw:reverse_proxy_response:{response_id}"

        forward_data = {
            "type": "reverse_proxy_forward",
            "session_id": session_id,
            "message": message,
            "response_channel": response_channel,
            "original_worker": get_worker_id(),
        }

        owner = await self.get_session_owner(session_id)
        owner_channel = f"mcpgw:reverse_proxy:{owner}"

        # Subscribe to response channel BEFORE publishing (prevent race) –
        # same ordering as forward_streamable_http_to_owner()
        pubsub = redis.pubsub()
        await pubsub.subscribe(response_channel)
        LOGGER.info(f"[REVERSE_PROXY_AFFINITY] Worker {get_worker_id()} | Session {session_id[:8]}... | Subscribed to response channel {response_channel}")

        try:
            await redis.publish(owner_channel, orjson.dumps(forward_data))
            LOGGER.info(
                f"[REVERSE_PROXY_AFFINITY] Worker {get_worker_id()} | Session {session_id[:8]}... | "
                f"Published forward request to {owner_channel} | response_channel={response_channel} | timeout={timeout}s"
            )

            # Poll with get_message() inside asyncio.timeout() –
            # matches MCPSessionPool.forward_request_to_owner() pattern exactly
            async with asyncio.timeout(timeout):
                while True:
                    msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
                    if msg and msg["type"] == "message":
                        LOGGER.info(f"[REVERSE_PROXY_AFFINITY] Worker {get_worker_id()} | Session {session_id[:8]}... | Response received from owner {owner} via {response_channel}")
                        return orjson.loads(msg["data"])
        except asyncio.TimeoutError:
            LOGGER.error(f"[REVERSE_PROXY_AFFINITY] Worker {get_worker_id()} | Session {session_id[:8]}... | " f"TIMEOUT ({timeout}s) waiting for response from owner {owner} on {response_channel}")
            raise
        finally:
            await pubsub.unsubscribe(response_channel)
            LOGGER.info(f"[REVERSE_PROXY_AFFINITY] Worker {get_worker_id()} | Session {session_id[:8]}... | Unsubscribed from {response_channel}")

    async def _wait_for_response(self, request_id: str, pending_responses: Dict[str, asyncio.Future], timeout: float = 30.0) -> Dict[str, Any]:
        """Wait for a response to a request via the pending_responses dict.

        Args:
            request_id: Request ID to wait for.
            pending_responses: Dictionary of pending response futures.
            timeout: Timeout in seconds.

        Returns:
            Response message.

        Raises:
            asyncio.TimeoutError: If timeout occurs.
        """
        # Use get_running_loop() – get_event_loop() is deprecated in Python 3.10+
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        pending_responses[request_id] = future

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            pending_responses.pop(request_id, None)

    async def execute_forwarded_message(self, data: Dict[str, Any], redis: Any, pending_responses: Dict[str, asyncio.Future]) -> None:
        """Execute a forwarded reverse-proxy message on the owner worker.

        Called by ``MCPSessionPool.start_rpc_listener()`` when it receives a
        ``reverse_proxy_forward`` message on the worker's channel.  The response
        is published back to the requesting worker via ``data["response_channel"]``.

        Args:
            data: Forwarded message data containing session_id, message, and response_channel.
            redis: Redis client for publishing the response.
            pending_responses: Dictionary of pending response futures.
        """
        session_id = data["session_id"]
        message = data["message"]
        response_channel = data["response_channel"]
        original_worker = data.get("original_worker", "unknown")
        request_id = message.get("payload", {}).get("id")
        is_notification = request_id is None

        LOGGER.warning(
            f"[REVERSE_PROXY_AFFINITY] 📥 EXECUTING FORWARDED REQUEST 📥 | "
            f"Worker {get_worker_id()} | Session {session_id[:8]}... | "
            f"Received forwarded {'notification' if is_notification else f'request id={request_id}'} from worker {original_worker} | "
            f"This request was FORWARDED from another worker and will be EXECUTED LOCALLY on this worker"
        )

        session = await self.get_session(session_id)
        if not session:
            worker_id = get_worker_id()
            LOGGER.error(f"[REVERSE_PROXY_AFFINITY] Worker {worker_id} | Session {session_id[:8]}... | " f"Session NOT FOUND locally – cannot execute forwarded message from {original_worker}")
            error_response = {
                "error": f"Session {session_id} not found on owner worker {worker_id}",
                "status": "error",
            }
            await redis.publish(response_channel, orjson.dumps(error_response))
            return

        try:
            # Send message to the WebSocket client (reverse proxy agent)
            LOGGER.info(f"[REVERSE_PROXY_AFFINITY] 📤 FORWARDED → LOCAL SEND 📤 | " f"Worker {get_worker_id()} | Session {session_id[:8]}... | " f"Sending FORWARDED message to LOCAL WebSocket agent")
            await session.send_message(message)

            # Wait for response if this is a request (has id field in payload)
            if request_id:
                LOGGER.info(
                    f"[REVERSE_PROXY_AFFINITY] ⏳ WAITING FOR LOCAL RESPONSE (FORWARDED) ⏳ | "
                    f"Worker {get_worker_id()} | Session {session_id[:8]}... | "
                    f"Waiting for LOCAL agent response to FORWARDED request (request_id={request_id}, timeout={settings.mcpgateway_pool_rpc_forward_timeout}s)"
                )
                response = await self._wait_for_response(request_id, pending_responses, timeout=settings.mcpgateway_pool_rpc_forward_timeout)
                LOGGER.info(
                    f"[REVERSE_PROXY_AFFINITY] ✓ FORWARDED RESPONSE READY ✓ | "
                    f"Worker {get_worker_id()} | Session {session_id[:8]}... | "
                    f"LOCAL agent responded to FORWARDED request (request_id={request_id}) – publishing response back to requesting worker via {response_channel}"
                )
                await redis.publish(response_channel, orjson.dumps(response))
            else:
                # Notification – no response expected
                LOGGER.info(
                    f"[REVERSE_PROXY_AFFINITY] ✓ FORWARDED NOTIFICATION SENT ✓ | "
                    f"Worker {get_worker_id()} | Session {session_id[:8]}... | "
                    f"FORWARDED notification sent to LOCAL agent (no response expected)"
                )
                await redis.publish(response_channel, orjson.dumps({"status": "notification_sent"}))
        except asyncio.TimeoutError:
            LOGGER.error(
                f"[REVERSE_PROXY_AFFINITY] Worker {get_worker_id()} | Session {session_id[:8]}... | "
                f"TIMEOUT waiting for agent response (request_id={request_id}, timeout={settings.mcpgateway_pool_rpc_forward_timeout}s)"
            )
            await redis.publish(response_channel, orjson.dumps({"error": "Timeout waiting for agent response", "status": "error"}))
        except Exception as e:
            LOGGER.error(f"[REVERSE_PROXY_AFFINITY] Worker {get_worker_id()} | Session {session_id[:8]}... | Error executing forwarded message: {e}", exc_info=True)
            await redis.publish(response_channel, orjson.dumps({"error": str(e), "status": "error"}))

    async def start_health_monitoring(self) -> None:
        """Start the background health monitoring task for reverse proxy sessions.

        Each worker monitors its own local sessions independently (no leader election).
        """
        if self._health_check_task is None or self._health_check_task.done():
            self._health_check_task = asyncio.create_task(self._run_health_checks())
            LOGGER.info(f"[REVERSE_PROXY_HEALTH] Worker {get_worker_id()} | Started health monitoring task")

    async def stop_health_monitoring(self) -> None:
        """Stop the background health monitoring task."""
        if self._health_check_task and not self._health_check_task.done():
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
            LOGGER.info(f"[REVERSE_PROXY_HEALTH] Worker {get_worker_id()} | Stopped health monitoring task")

    async def _run_health_checks(self) -> None:
        """Background task that periodically checks session health.

        Runs independently on each worker, checking only local sessions.
        No leader election - each worker is responsible for its own sessions.
        """
        check_interval = settings.mcpgateway_reverse_proxy_health_check_interval
        LOGGER.info(f"[REVERSE_PROXY_HEALTH] Worker {get_worker_id()} | Health check loop started (interval={check_interval}s)")

        while True:
            try:
                await asyncio.sleep(check_interval)

                # Get snapshot of current sessions
                async with self._lock:
                    sessions_to_check = list(self.sessions.values())

                if sessions_to_check:
                    LOGGER.debug(f"[REVERSE_PROXY_HEALTH] Worker {get_worker_id()} | Checking {len(sessions_to_check)} local sessions")
                    await self._check_sessions_health(sessions_to_check)

            except asyncio.CancelledError:
                LOGGER.info(f"[REVERSE_PROXY_HEALTH] Worker {get_worker_id()} | Health check loop cancelled")
                break
            except Exception as e:
                LOGGER.error(f"[REVERSE_PROXY_HEALTH] Worker {get_worker_id()} | Error in health check loop: {e}", exc_info=True)
                # Continue running despite errors

    async def _check_sessions_health(self, sessions: list[ReverseProxySession]) -> None:
        """Check health of multiple sessions.

        Args:
            sessions: List of sessions to check
        """
        now = datetime.now(tz=timezone.utc)
        heartbeat_timeout = settings.mcpgateway_reverse_proxy_heartbeat_timeout
        failure_threshold = settings.mcpgateway_reverse_proxy_failure_threshold

        for session in sessions:
            try:
                time_since_heartbeat = (now - session.last_heartbeat).total_seconds()

                if time_since_heartbeat > heartbeat_timeout:
                    # Heartbeat timeout detected
                    session.missed_heartbeats += 1
                    LOGGER.warning(
                        f"[REVERSE_PROXY_HEALTH] Worker {get_worker_id()} | Session {session.session_id[:8]}... | "
                        f"Heartbeat timeout ({time_since_heartbeat:.1f}s > {heartbeat_timeout}s) | "
                        f"Missed heartbeats: {session.missed_heartbeats}/{failure_threshold}"
                    )

                    # Check if threshold exceeded
                    if failure_threshold > 0 and session.missed_heartbeats >= failure_threshold:
                        LOGGER.error(
                            f"[REVERSE_PROXY_HEALTH] Worker {get_worker_id()} | Session {session.session_id[:8]}... | "
                            f"Failure threshold reached ({session.missed_heartbeats}/{failure_threshold}) - marking gateway unreachable"
                        )
                        await self._mark_gateway_unreachable(session.session_id)
                        # Close the WebSocket connection
                        try:
                            await session.websocket.close(code=1001, reason="Heartbeat timeout")
                        except Exception as close_error:
                            LOGGER.debug(f"[REVERSE_PROXY_HEALTH] Error closing WebSocket for {session.session_id[:8]}...: {close_error}")
                else:
                    # Heartbeat is healthy - reset counter if it was previously elevated
                    if session.missed_heartbeats > 0:
                        LOGGER.info(
                            f"[REVERSE_PROXY_HEALTH] Worker {get_worker_id()} | Session {session.session_id[:8]}... | "
                            f"Heartbeat recovered - resetting missed count from {session.missed_heartbeats} to 0"
                        )
                        session.missed_heartbeats = 0

            except Exception as e:
                LOGGER.error(f"[REVERSE_PROXY_HEALTH] Worker {get_worker_id()} | Session {session.session_id[:8]}... | " f"Error checking session health: {e}", exc_info=True)

    async def _mark_gateway_unreachable(self, session_id: str) -> None:
        """Mark the gateway associated with this session as unreachable in the database.

        Args:
            session_id: Session ID (which is also the gateway ID for reverse proxy)
        """
        try:
            # Third-Party
            from sqlalchemy import select  # pylint: disable=import-outside-toplevel

            # First-Party
            from mcpgateway.db import Gateway, SessionLocal  # pylint: disable=import-outside-toplevel

            with SessionLocal() as db:
                gateway = db.execute(select(Gateway).where(Gateway.id == session_id)).scalar_one_or_none()
                if gateway:
                    if gateway.reachable:
                        gateway.reachable = False
                        db.commit()
                        LOGGER.info(f"[REVERSE_PROXY_HEALTH] Worker {get_worker_id()} | Session {session_id[:8]}... | " f"Gateway '{gateway.name}' marked as unreachable in database")
                    else:
                        LOGGER.debug(f"[REVERSE_PROXY_HEALTH] Worker {get_worker_id()} | Session {session_id[:8]}... | " f"Gateway '{gateway.name}' already marked unreachable")
                else:
                    LOGGER.warning(f"[REVERSE_PROXY_HEALTH] Worker {get_worker_id()} | Session {session_id[:8]}... | " f"Gateway not found in database")
        except Exception as e:
            LOGGER.error(f"[REVERSE_PROXY_HEALTH] Worker {get_worker_id()} | Session {session_id[:8]}... | " f"Failed to mark gateway unreachable: {e}", exc_info=True)

    async def _mark_gateway_reachable(self, session_id: str) -> None:
        """Mark the gateway associated with this session as reachable in the database.

        Args:
            session_id: Session ID (which is also the gateway ID for reverse proxy)
        """
        try:
            # Third-Party
            from sqlalchemy import select  # pylint: disable=import-outside-toplevel

            # First-Party
            from mcpgateway.db import Gateway, SessionLocal  # pylint: disable=import-outside-toplevel

            with SessionLocal() as db:
                gateway = db.execute(select(Gateway).where(Gateway.id == session_id)).scalar_one_or_none()
                if gateway:
                    if not gateway.reachable:
                        gateway.reachable = True
                        gateway.last_seen = datetime.now(tz=timezone.utc)
                        db.commit()
                        LOGGER.info(f"[REVERSE_PROXY_HEALTH] Worker {get_worker_id()} | Session {session_id[:8]}... | " f"Gateway '{gateway.name}' marked as reachable in database")
                    else:
                        # Update last_seen even if already reachable
                        gateway.last_seen = datetime.now(tz=timezone.utc)
                        db.commit()
                else:
                    LOGGER.warning(f"[REVERSE_PROXY_HEALTH] Worker {get_worker_id()} | Session {session_id[:8]}... | " f"Gateway not found in database")
        except Exception as e:
            LOGGER.error(f"[REVERSE_PROXY_HEALTH] Worker {get_worker_id()} | Session {session_id[:8]}... | " f"Failed to mark gateway reachable: {e}", exc_info=True)

    async def add_session(self, session: ReverseProxySession) -> None:
        """Add a new session.

        Args:
            session: Session to add.
        """
        async with self._lock:
            self.sessions[session.session_id] = session
            count = len(self.sessions)
        LOGGER.info(f"[REVERSE_PROXY] Worker {get_worker_id()} | Session {session.session_id[:8]}... | Added (total local sessions: {count})")

        # Mark gateway as reachable when session is added
        await self._mark_gateway_reachable(session.session_id)

    async def remove_session(self, session_id: str) -> None:
        """Remove a session.

        Args:
            session_id: Session ID to remove.
        """
        async with self._lock:
            existed = session_id in self.sessions
            if existed:
                del self.sessions[session_id]
            count = len(self.sessions)
        if existed:
            LOGGER.info(f"[REVERSE_PROXY] Worker {get_worker_id()} | Session {session_id[:8]}... | Removed (total local sessions: {count})")
            # Mark gateway as unreachable when session is removed
            await self._mark_gateway_unreachable(session_id)
        else:
            LOGGER.info(f"[REVERSE_PROXY] Worker {get_worker_id()} | Session {session_id[:8]}... | Remove called but session not found locally (may be on another worker)")

    async def get_session(self, session_id: str) -> Optional[ReverseProxySession]:
        """Get a session by ID.

        Args:
            session_id: Session ID to get.

        Returns:
            Session if found, None otherwise.
        """

        """Get a session safely."""
        async with self._lock:
            return self.sessions.get(session_id)

    async def list_sessions(self) -> list[Dict[str, Any]]:
        """List all active sessions.

        Returns:
            List of session information dictionaries.

        Examples:
            >>> from fastapi import WebSocket
            >>> manager = ReverseProxyManager()
            >>> sessions = manager.list_sessions()  # doctest: +SKIP
            >>> sessions  # doctest: +SKIP
            []
            >>> isinstance(sessions, list)  # doctest: +SKIP
            True
        """
        async with self._lock:
            # Return a shallow copy to prevent external mutation
            return [
                {
                    "session_id": session.session_id,
                    "server_info": session.server_info,
                    "connected_at": session.connected_at.isoformat(),
                    "last_activity": session.last_activity.isoformat(),
                    "message_count": session.message_count,
                    "bytes_transferred": session.bytes_transferred,
                    "user": session.user if isinstance(session.user, str) else session.user.get("sub") if isinstance(session.user, dict) else None,
                }
                for session in self.sessions.values()
            ]


def extract_session_id_from_url(url: str) -> str:
    """Extract session ID from URL path containing /sessions/{session_id}.

    Args:
        url: The URL string to parse for session ID extraction.

    Returns:
        str: The extracted session ID from the URL path.

    Raises:
        ValueError: If the URL format is invalid or session ID cannot be extracted.
    """
    LOGGER.info(f"extract_session_id_from_url {url}")
    path_parts = urlparse(url).path.strip("/").split("/")
    try:
        # Find the index of "sessions" and return the next element
        session_index = path_parts.index("sessions")
        return path_parts[session_index + 1]
    except (ValueError, IndexError):
        raise ValueError("Invalid URL format — could not extract session ID.")


def get_user_from_credentials(credentials: str | dict) -> tuple[str | None, bool]:
    """Extract user and admin status from credentials.

    Args:
        credentials: Auth credentials (dict from JWT or string)

    Returns:
        Tuple of (username, is_admin)
    """
    if isinstance(credentials, dict):
        user = credentials.get("sub") or credentials.get("email")
        # Check both top-level is_admin and nested user.is_admin (JWT tokens may nest it)
        is_admin = credentials.get("is_admin", False) or credentials.get("user", {}).get("is_admin", False)
        return user, is_admin
    elif credentials and credentials != "anonymous":
        return credentials, False
    return None, False


def validate_session_ownership(session: ReverseProxySession, user_email: Optional[str], is_admin: bool, action: str) -> bool:
    """Validate that the requesting user owns the session or is admin.

    Args:
        session: The session to validate ownership for
        user_email: Email of the requesting user
        is_admin: Whether the user is an admin
        action: Description of the action for logging

    Returns:
        True if authorized, False otherwise
    """
    if not session.user:
        # Session was created without auth - allow access
        return True

    # Admins can access any session
    if is_admin:
        return True

    # Session owner can access their own session
    session_owner = session.user if isinstance(session.user, str) else session.user.get("sub") if isinstance(session.user, dict) else None
    if user_email and session_owner and user_email == session_owner:
        return True

    # Not authorized
    LOGGER.warning(f"Session access denied: user {user_email} attempted to {action} session owned by {session_owner}")
    return False


class ReverseProxyService:
    """Service for managing reverse proxy operations.

    This service provides business logic for reverse proxy session management,
    message forwarding, and authentication without depending on FastAPI.
    """

    def __init__(self):
        """Initialize the service."""
        self.manager = ReverseProxyManager()
        self.pending_responses: Dict[str, asyncio.Future] = {}

    async def register_session_gateway_and_server(
        self,
        session_id: str,
        session: ReverseProxySession,
        server_info: Dict[str, Any],
        team_id: Optional[str],
        user: str,
    ) -> None:
        """Register or update gateway and virtual server for a reverse proxy session.

        This method handles the complete registration workflow:
        1. Sends immediate acknowledgment to client
        2. Creates/updates gateway in database
        3. Creates/updates virtual server in database
        4. Sends final completion status to client

        Args:
            session_id: Unique session identifier (also used as gateway ID).
            session: The ReverseProxySession instance.
            server_info: Server metadata from the registration message.
            team_id: Optional team ID for multi-tenancy.
            user: Email of the user registering the session.

        Note:
            This method runs asynchronously and handles all database operations
            and error responses internally. It does not raise exceptions to the caller.
        """
        # First-Party
        from mcpgateway.config import Settings  # pylint: disable=import-outside-toplevel
        from mcpgateway.db import SessionLocal  # pylint: disable=import-outside-toplevel
        from mcpgateway.schemas import GatewayCreate, GatewayUpdate, ServerCreate, ServerUpdate, TransportType  # pylint: disable=import-outside-toplevel
        from mcpgateway.services.gateway_service import GatewayDuplicateConflictError, GatewayNameConflictError, GatewayService  # pylint: disable=import-outside-toplevel
        from mcpgateway.services.server_service import ServerNameConflictError, ServerService  # pylint: disable=import-outside-toplevel

        # Send immediate acknowledgment so client knows we received the registration
        await session.send_message({"type": "register_ack", "sessionId": session_id, "status": "processing"})

        try:
            # Use separate database session for gateway and server registration
            # to avoid transaction conflicts
            with SessionLocal() as dbsession:
                LOGGER.info(f"[REVERSE_PROXY_SERVICE] Registering session {session_id}")
                app_domain = Settings().app_domain
                url = f"{app_domain}reverse-proxy/sessions/{session_id}/mcp"

                gateway = GatewayCreate(
                    name=server_info.get("name"),
                    url=url,
                    description=server_info.get("description"),
                    tags=[],
                    transport=TransportType.PROXIED,
                    visibility="team" if team_id is not None else "public",
                )

                # Gateway registration
                gateway_service = GatewayService()
                tool_ids = []
                resource_ids = []
                prompt_ids = []

                try:
                    # Try to register new gateway
                    gateway_read, tool_ids, resource_ids, prompt_ids = await gateway_service.register_proxy_gateway(
                        db=dbsession,
                        gateway=gateway,
                        team_id=team_id,
                        owner_email=user,
                        visibility=gateway.visibility,
                        gateway_id=session_id,
                        created_by=user,
                    )
                    LOGGER.info(f"[REVERSE_PROXY_SERVICE] Gateway {gateway_read.name} registered successfully with {len(tool_ids)} tools")

                except (GatewayDuplicateConflictError, GatewayNameConflictError) as e:
                    # Gateway already exists (duplicate or name conflict)
                    # Check if the existing gateway is owned by the current user
                    LOGGER.info(f"[REVERSE_PROXY_SERVICE] Gateway conflict detected (conflict: {type(e).__name__})")

                    # Get the conflicting gateway ID from the exception
                    conflicting_gateway_id = getattr(e, "gateway_id", None)

                    if not conflicting_gateway_id:
                        # No gateway ID in exception, cannot proceed
                        LOGGER.error("[REVERSE_PROXY_SERVICE] Gateway conflict but no gateway_id in exception")
                        raise ValueError(f"Gateway name '{gateway.name}' conflicts with an existing gateway")

                    # Get the existing gateway to check ownership
                    # Third-Party
                    from sqlalchemy import select  # pylint: disable=import-outside-toplevel

                    # First-Party
                    from mcpgateway.db import Gateway  # pylint: disable=import-outside-toplevel

                    existing_gateway = dbsession.execute(select(Gateway).where(Gateway.id == conflicting_gateway_id)).scalar_one_or_none()

                    if not existing_gateway:
                        LOGGER.error(f"[REVERSE_PROXY_SERVICE] Gateway {conflicting_gateway_id} not found in database")
                        raise ValueError(f"Gateway name '{gateway.name}' conflicts with a non-existent gateway")

                    # Check if this is the same gateway (by ID) that we're trying to register
                    if conflicting_gateway_id == session_id and existing_gateway.owner_email == user:
                        # User owns the gateway and it's the same session - update it
                        LOGGER.info(f"[REVERSE_PROXY_SERVICE] Gateway {session_id} owned by {user}, updating instead")

                        gateway_update = GatewayUpdate(
                            name=gateway.name,
                            url=gateway.url,
                            description=gateway.description,
                            tags=gateway.tags,
                            transport=gateway.transport,
                            visibility=gateway.visibility,
                        )

                        # update_gateway with modified_via="reverse_proxy" returns tuple with IDs
                        result = await gateway_service.update_gateway(
                            db=dbsession,
                            gateway_id=session_id,
                            gateway_update=gateway_update,
                            modified_by=user,
                            modified_via="reverse_proxy",
                            user_email=user,
                        )

                        if result:
                            # Unpack tuple returned by update_gateway for reverse_proxy
                            gateway_read, tool_ids, resource_ids, prompt_ids = result
                            LOGGER.info(f"[REVERSE_PROXY_SERVICE] Gateway {gateway_read.name} updated successfully with {len(tool_ids)} tools")
                        else:
                            raise Exception("Failed to update gateway")
                    else:
                        # Gateway name conflicts with a different gateway or owned by someone else
                        owner = existing_gateway.owner_email
                        LOGGER.error(
                            f"[REVERSE_PROXY_SERVICE] Gateway name conflict: '{gateway.name}' already exists "
                            f"(ID: {conflicting_gateway_id}, owner: {owner}). Current user: {user}, session: {session_id}"
                        )
                        raise ValueError(f"Gateway name '{gateway.name}' is already in use. " f"Please choose a different name for your MCP server.")

                # Register or update virtual server
                server_in = ServerCreate(
                    id=gateway_read.id,
                    name=gateway_read.name,
                    description=gateway_read.description,
                    associated_tools=tool_ids,
                    associated_resources=resource_ids,
                    associated_prompts=prompt_ids,
                    team_id=gateway_read.team_id,
                    visibility=gateway_read.visibility,
                )

                try:
                    # Try to register new server
                    server = await ServerService().register_server(
                        dbsession,
                        server_in,
                        team_id=gateway_read.team_id,
                        visibility=gateway_read.visibility,
                        created_via="reverse_proxy",
                        created_by=gateway_read.created_by,
                        owner_email=gateway_read.owner_email,
                    )
                    LOGGER.info(f"[REVERSE_PROXY_SERVICE] Virtual server {server.name} registered successfully with {len(tool_ids)} tools")

                except ServerNameConflictError as e:
                    # Server already exists (name conflict) - update it instead
                    LOGGER.info(f"[REVERSE_PROXY_SERVICE] Server {gateway_read.id} already exists (conflict: {type(e).__name__}), updating instead")

                    server_update = ServerUpdate(
                        name=server_in.name,
                        description=server_in.description,
                        associated_tools=tool_ids,
                        associated_resources=resource_ids,
                        associated_prompts=prompt_ids,
                        team_id=gateway_read.team_id,
                        visibility=gateway_read.visibility,
                        enabled=True,
                    )

                    server = await ServerService().update_server(
                        db=dbsession,
                        server_id=gateway_read.id,
                        server_update=server_update,
                        user_email=gateway_read.owner_email or user,
                        modified_by=gateway_read.created_by,
                        modified_via="reverse_proxy",
                    )
                    LOGGER.info(f"[REVERSE_PROXY_SERVICE] Virtual server {server.name} updated successfully with {len(tool_ids)} tools")

            # Send final success acknowledgment
            await session.send_message({"type": "register_complete", "sessionId": session_id, "status": "success"})

        except Exception as e:
            LOGGER.error(f"[REVERSE_PROXY_SERVICE] Failed to register gateway for session {session_id}: {e}", exc_info=True)
            await session.send_message({"type": "register_complete", "sessionId": session_id, "status": "error", "message": str(e)})

    async def forward_request_to_session(
        self,
        session_id: str,
        mcp_request: Dict[str, Any],
        authentication: Optional[Dict[str, str]] = None,
        auth_type: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Forward an MCP request to a reverse proxy session with session affinity support.

        Args:
            session_id: Session ID to forward the request to.
            mcp_request: MCP request dictionary to forward.
            authentication: Optional dictionary containing authentication headers.
            auth_type: Type of authentication being used (for logging/debugging).

        Returns:
            Response from the proxied server, or None for notifications.

        Raises:
            ValueError: If session is not found.
            asyncio.TimeoutError: If request times out.
            Exception: For any other errors during request forwarding.
        """
        method = mcp_request.get("method", "unknown")
        request_id = mcp_request.get("id")
        is_notification = request_id is None
        LOGGER.info(
            f"[REVERSE_PROXY] Worker {get_worker_id()} | Session {session_id[:8]}... | " f"forward_request_to_session method={method} {'(notification)' if is_notification else f'id={request_id}'}"
        )
        if authentication:
            LOGGER.info(f"[REVERSE_PROXY] Worker {get_worker_id()} | Session {session_id[:8]}... | Auth type={auth_type}, headers={list(authentication.keys())}")
        else:
            LOGGER.warning(f"[REVERSE_PROXY] Worker {get_worker_id()} | Session {session_id[:8]}... | NO AUTHENTICATION PROVIDED")

        # Check if we own the session or need to forward to owner (only when affinity is enabled)
        if settings.mcpgateway_session_affinity_enabled:
            owner = await self.manager.get_session_owner(session_id)

            worker_id = get_worker_id()
            if owner and owner != worker_id:
                # Forward to owner worker via Redis
                LOGGER.warning(
                    f"[REVERSE_PROXY_AFFINITY] ⚠️  CROSS-WORKER FORWARDING ⚠️  | "
                    f"Worker {worker_id} | Session {session_id[:8]}... | method={method} | "
                    f"NOT owner (owner={owner}) → FORWARDING REQUEST via Redis Pub/Sub to worker {owner}"
                )
                message = {"type": "request", "sessionId": session_id, "payload": mcp_request}

                # Include authentication details for cross-worker forwarding
                if authentication:
                    LOGGER.info(f"[REVERSE_PROXY] Adding authentication to cross-worker message: {list(authentication.keys())}")
                    message["authentication"] = authentication
                    if auth_type:
                        message["authType"] = auth_type
                else:
                    LOGGER.warning("[REVERSE_PROXY] No authentication to add to cross-worker message")

                return await self.manager.forward_message_to_owner(session_id, message)

            LOGGER.info(
                f"[REVERSE_PROXY_AFFINITY] ✓ LOCAL EXECUTION ✓ | "
                f"Worker {get_worker_id()} | Session {session_id[:8]}... | method={method} | "
                f"{'We own it' if owner == worker_id else 'No owner registered'} → EXECUTING LOCALLY on this worker"
            )
        else:
            LOGGER.info(f"[REVERSE_PROXY] ✓ LOCAL EXECUTION ✓ | " f"Worker {get_worker_id()} | Session {session_id[:8]}... | " f"Affinity disabled → EXECUTING LOCALLY on this worker")

        # We own it or Redis not available - process locally
        session = await self.manager.get_session(session_id)
        if not session:
            LOGGER.warning(f"[REVERSE_PROXY] Worker {get_worker_id()} | Session {session_id[:8]}... | " f"Session NOT FOUND locally despite ownership claim – cleaning up stale Redis key")

            # Clean up stale Redis ownership key to prevent future conflicts
            await self.manager.release_session_ownership(session_id)

            raise ValueError(f"Session with ID '{session_id}' is no longer active. Please reconnect the reverse proxy agent.")

        # Wrap the request in reverse proxy envelope
        message = {"type": "request", "sessionId": session_id, "payload": mcp_request}

        # Include authentication details if provided so the reverse proxy agent can use them
        if authentication:
            LOGGER.info(f"[REVERSE_PROXY] Adding authentication to local message: {list(authentication.keys())}")
            message["authentication"] = authentication
            if auth_type:
                message["authType"] = auth_type
        else:
            LOGGER.warning("[REVERSE_PROXY] No authentication to add to local message")

        try:
            LOGGER.info(f"[REVERSE_PROXY] 📤 LOCAL SEND 📤 | " f"Worker {get_worker_id()} | Session {session_id[:8]}... | " f"Sending message to LOCAL WebSocket agent (method={method})")
            await session.send_message(message)

            # Notifications don't expect a response
            if is_notification:
                LOGGER.info(f"[REVERSE_PROXY] ✓ NOTIFICATION SENT ✓ | " f"Worker {get_worker_id()} | Session {session_id[:8]}... | " f"Notification sent to LOCAL agent (no response expected)")
                return None

            # For requests, create a future and wait for response
            loop = asyncio.get_running_loop()
            future = loop.create_future()
            self.pending_responses[request_id] = future

            timeout = settings.mcpgateway_pool_rpc_forward_timeout
            LOGGER.info(
                f"[REVERSE_PROXY] ⏳ WAITING FOR LOCAL RESPONSE ⏳ | "
                f"Worker {get_worker_id()} | Session {session_id[:8]}... | "
                f"Waiting for LOCAL agent response (request_id={request_id}, timeout={timeout}s)"
            )
            # Wait for the response with a timeout
            response = await asyncio.wait_for(future, timeout=timeout)
            LOGGER.info(f"[REVERSE_PROXY] ✓ LOCAL RESPONSE RECEIVED ✓ | " f"Worker {get_worker_id()} | Session {session_id[:8]}... | " f"Response received from LOCAL agent (request_id={request_id})")
            return response

        except asyncio.TimeoutError:
            if request_id:
                self.pending_responses.pop(request_id, None)
            LOGGER.error(
                f"[REVERSE_PROXY] Worker {get_worker_id()} | Session {session_id[:8]}... | "
                f"TIMEOUT waiting for agent response (request_id={request_id}, timeout={settings.mcpgateway_pool_rpc_forward_timeout}s)"
            )
            raise

        except Exception:
            if request_id:
                self.pending_responses.pop(request_id, None)
            raise


# Global singleton service instance
_service_instance: Optional[ReverseProxyService] = None


def get_reverse_proxy_service() -> ReverseProxyService:
    """Get the global reverse proxy service instance.

    Returns:
        The singleton ReverseProxyService instance.
    """
    global _service_instance
    if _service_instance is None:
        _service_instance = ReverseProxyService()
    return _service_instance
