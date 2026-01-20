# -*- coding: utf-8 -*-
# mcpgateway/services/cancellation_service.py
"""Location: ./mcpgateway/services/cancellation_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Service for tracking and cancelling active tool runs.

Provides a simple in-memory registry for run metadata and an optional async
cancel callback that can be invoked when a cancellation is requested. This
service is intentionally small and designed to be a single-process helper for
local run lifecycle management; the gateway remains authoritative for
cancellation and also broadcasts a `notifications/cancelled` JSON-RPC
notification to connected sessions.
"""
# Future
from __future__ import annotations

# Standard
import asyncio
import json
import time
from typing import Any, Awaitable, Callable, Dict, Optional

# First-Party
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.utils.redis_client import get_redis_client

logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

CancelCallback = Callable[[Optional[str]], Awaitable[None]]  # async callback(reason)


class CancellationService:
    """Track active runs and allow cancellation requests.

    Note: This is intentionally lightweight — it does not persist state and is
    suitable for gateway-local run tracking. The gateway will also broadcast
    a `notifications/cancelled` message to connected sessions to inform remote
    peers of the cancellation request.

    Multi-worker deployments: When Redis is available, cancellation events are
    published to the "cancellation:cancel" channel to propagate across workers.
    """

    def __init__(self) -> None:
        """Initialize the cancellation service."""
        self._runs: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._redis = None
        self._pubsub_task: Optional[asyncio.Task] = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize Redis pubsub if available for multi-worker support."""
        if self._initialized:
            return

        self._initialized = True

        try:
            self._redis = await get_redis_client()
            if self._redis:
                # Start listening for cancellation events from other workers
                self._pubsub_task = asyncio.create_task(self._listen_for_cancellations())
                logger.info("CancellationService: Redis pubsub initialized for multi-worker cancellation")
        except Exception as e:
            logger.warning(f"CancellationService: Could not initialize Redis pubsub: {e}")

    async def shutdown(self) -> None:
        """Shutdown Redis pubsub listener."""
        if self._pubsub_task and not self._pubsub_task.done():
            self._pubsub_task.cancel()
            try:
                await self._pubsub_task
            except asyncio.CancelledError:
                pass
        logger.info("CancellationService: Shutdown complete")

    async def _listen_for_cancellations(self) -> None:
        """Listen for cancellation events from other workers via Redis pubsub.

        Raises:
            asyncio.CancelledError: When the listener task is cancelled during shutdown.
        """
        if not self._redis:
            return

        try:
            pubsub = self._redis.pubsub()
            await pubsub.subscribe("cancellation:cancel")
            logger.info("CancellationService: Subscribed to cancellation:cancel channel")

            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        # Normalize run_id to string (handle id=0 which is valid per JSON-RPC)
                        raw_run_id = data.get("run_id")
                        run_id = str(raw_run_id) if raw_run_id is not None else None
                        reason = data.get("reason")

                        if run_id is not None:
                            # Cancel locally if we have this run (don't re-publish)
                            await self._cancel_run_local(run_id, reason=reason)
                    except Exception as e:
                        logger.warning(f"Error processing cancellation message: {e}")
        except asyncio.CancelledError:
            logger.info("CancellationService: Pubsub listener cancelled")
            raise
        except Exception as e:
            logger.error(f"CancellationService: Pubsub listener error: {e}")

    async def _cancel_run_local(self, run_id: str, reason: Optional[str] = None) -> bool:
        """Cancel a run locally without publishing to Redis (internal use).

        Args:
            run_id: Unique identifier for the run to cancel.
            reason: Optional textual reason for the cancellation request.

        Returns:
            bool: True if the run was found and cancelled, False if not found.
        """
        async with self._lock:
            entry = self._runs.get(run_id)
            if not entry:
                return False
            if entry.get("cancelled"):
                return True
            entry["cancelled"] = True
            entry["cancelled_at"] = time.time()
            entry["cancel_reason"] = reason
            cancel_cb = entry.get("cancel_callback")

        logger.info("Tool execution cancelled (from Redis): run_id=%s, reason=%s, tool=%s", run_id, reason or "not specified", entry.get("name", "unknown"))

        if cancel_cb:
            try:
                await cancel_cb(reason)
                logger.info("Cancel callback executed for %s", run_id)
            except Exception as e:
                logger.exception("Error in cancel callback for %s: %s", run_id, e)

        return True

    async def register_run(self, run_id: str, name: Optional[str] = None, cancel_callback: Optional[CancelCallback] = None) -> None:
        """Register a run for future cancellation.

        Args:
            run_id: Unique run identifier (string)
            name: Optional friendly name for debugging/observability
            cancel_callback: Optional async callback called when a cancel is requested
        """
        async with self._lock:
            self._runs[run_id] = {"name": name, "registered_at": time.time(), "cancel_callback": cancel_callback, "cancelled": False}
            logger.info("Registered run %s (%s)", run_id, name)

    async def unregister_run(self, run_id: str) -> None:
        """Remove a run from tracking.

        Args:
            run_id: Unique identifier for the run to unregister.
        """
        async with self._lock:
            if run_id in self._runs:
                self._runs.pop(run_id, None)
                logger.info("Unregistered run %s", run_id)

    async def cancel_run(self, run_id: str, reason: Optional[str] = None) -> bool:
        """Attempt to cancel a run.

        Args:
            run_id: Unique identifier for the run to cancel.
            reason: Optional textual reason for the cancellation request.

        Returns:
            bool: True if the run was found and cancellation was attempted (or already marked),
            False if the run was not known locally.
        """
        cancel_cb = None
        entry = None

        async with self._lock:
            entry = self._runs.get(run_id)
            if not entry:
                # Entry not found - will publish to Redis outside the lock
                pass
            elif entry.get("cancelled"):
                logger.debug("Run %s already cancelled", run_id)
                return True
            else:
                entry["cancelled"] = True
                entry["cancelled_at"] = time.time()
                entry["cancel_reason"] = reason
                cancel_cb = entry.get("cancel_callback")

        # Handle unknown run case outside the lock
        if not entry:
            logger.info("Cancellation requested for unknown run %s (queued for remote peers)", run_id)
            # Publish to Redis for other workers (outside lock to avoid blocking)
            await self._publish_cancellation(run_id, reason)
            return False

        # Log cancellation with reason and request_id for observability
        logger.info("Tool execution cancelled: run_id=%s, reason=%s, tool=%s", run_id, reason or "not specified", entry.get("name", "unknown"))

        if cancel_cb:
            try:
                await cancel_cb(reason)
                logger.info("Cancel callback executed for %s", run_id)
            except Exception as e:
                logger.exception("Error in cancel callback for %s: %s", run_id, e)

        # Publish to Redis for other workers
        await self._publish_cancellation(run_id, reason)

        return True

    async def _publish_cancellation(self, run_id: str, reason: Optional[str] = None) -> None:
        """Publish cancellation event to Redis for other workers.

        Args:
            run_id: Unique identifier for the run being cancelled.
            reason: Optional textual reason for the cancellation.
        """
        if not self._redis:
            return

        try:
            message = json.dumps({"run_id": run_id, "reason": reason})
            await self._redis.publish("cancellation:cancel", message)
            logger.debug("Published cancellation to Redis: run_id=%s", run_id)
        except Exception as e:
            logger.warning(f"Failed to publish cancellation to Redis: {e}")

    async def get_status(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Return the status dict for a run if known, else None.

        Args:
            run_id: Unique identifier for the run to query.

        Returns:
            Optional[Dict[str, Any]]: The status dictionary for the run if found, otherwise None.
        """
        async with self._lock:
            return self._runs.get(run_id)

    async def is_registered(self, run_id: str) -> bool:
        """Check if a run is currently registered.

        Args:
            run_id: Unique identifier for the run to check.

        Returns:
            bool: True if the run is registered, False otherwise.
        """
        async with self._lock:
            return run_id in self._runs


# Module-level singleton for importers to use
cancellation_service = CancellationService()
