# mcpgateway/services/orchestration_service.py
"""Service for tracking and cancelling active tool runs.

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
import logging
import time
from typing import Any, Awaitable, Callable, Dict, Optional

logger = logging.getLogger(__name__)

CancelCallback = Callable[[Optional[str]], Awaitable[None]]  # async callback(reason)


class OrchestrationService:
    """Track active runs and allow cancellation requests.

    Note: This is intentionally lightweight — it does not persist state and is
    suitable for gateway-local run tracking. The gateway will also broadcast
    a `notifications/cancelled` message to connected sessions to inform remote
    peers of the cancellation request.
    """

    def __init__(self) -> None:
        self._runs: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

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
        async with self._lock:
            entry = self._runs.get(run_id)
            if not entry:
                return False
            if entry.get("cancelled"):
                return True
            entry["cancelled"] = True
            cancel_cb = entry.get("cancel_callback")

        if cancel_cb:
            try:
                await cancel_cb(reason)
                logger.info("Cancel callback executed for %s", run_id)
            except Exception as e:
                logger.exception("Error in cancel callback for %s: %s", run_id, e)

        return True

    async def get_status(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Return the status dict for a run if known, else None.

        Args:
            run_id: Unique identifier for the run to query.

        Returns:
            Optional[Dict[str, Any]]: The status dictionary for the run if found, otherwise None.
        """
        async with self._lock:
            return self._runs.get(run_id)


# Module-level singleton for importers to use
orchestration_service = OrchestrationService()
