# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/cache/tool_call_registry.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tool call to session mapping registry.

Tracks which client session initiated each tool call for proper
elicitation routing in multi-user deployments. This enables the gateway
to route elicitation requests from upstream MCP servers back to the
specific client that initiated the tool call.

Per MCP specification 2025-11-25, elicitation requests must be routed
to the correct client session to maintain security boundaries and prevent
cross-user information leakage.
"""

# Standard
import asyncio
import time
from typing import Dict, Optional, Tuple

# First-Party
from mcpgateway.services.logging_service import LoggingService

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class ToolCallRegistry:
    """Registry mapping tool call IDs to originating client sessions.

    This enables proper elicitation routing: when an upstream MCP server
    sends an elicitation request during tool execution, we can route it
    back to the specific client that initiated the tool call.

    The registry maintains mappings with timestamps for automatic cleanup
    of stale entries, preventing memory leaks in long-running deployments.

    Attributes:
        _mappings: Dictionary mapping tool_call_id to (session_id, timestamp)
        _cleanup_interval: How often to run cleanup task (seconds)
        _cleanup_task: Background task for cleaning up stale mappings
    """

    def __init__(self, cleanup_interval: int = 300):
        """Initialize the registry.

        Args:
            cleanup_interval: How often to clean up stale mappings (seconds)
        """
        self._mappings: Dict[str, Tuple[str, float]] = {}
        self._cleanup_interval = cleanup_interval
        self._cleanup_task: Optional[asyncio.Task[None]] = None
        logger.info(f"ToolCallRegistry initialized: cleanup_interval={cleanup_interval}s")

    async def start(self):
        """Start background cleanup task."""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            logger.info("ToolCallRegistry cleanup task started")

    async def shutdown(self):
        """Shutdown the registry and cancel cleanup task."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        mapping_count = len(self._mappings)
        self._mappings.clear()
        logger.info(f"ToolCallRegistry shutdown complete (cleared {mapping_count} mappings)")

    def register_tool_call(self, tool_call_id: str, session_id: str):
        """Register a tool call with its originating session.

        This should be called before invoking a tool to establish the
        mapping for potential elicitation routing.

        Args:
            tool_call_id: Unique identifier for the tool call
            session_id: Client session that initiated the call
        """
        self._mappings[tool_call_id] = (session_id, time.time())
        logger.debug(f"Registered tool call {tool_call_id} -> session {session_id}")

    def get_session_for_tool_call(self, tool_call_id: str) -> Optional[str]:
        """Get the session ID that initiated a tool call.

        Args:
            tool_call_id: The tool call identifier

        Returns:
            Session ID if found, None otherwise
        """
        mapping = self._mappings.get(tool_call_id)
        if mapping:
            return mapping[0]
        return None

    def unregister_tool_call(self, tool_call_id: str):
        """Remove a tool call mapping after completion.

        This should be called after tool execution completes (success or failure)
        to prevent memory leaks.

        Args:
            tool_call_id: The tool call identifier to remove
        """
        if self._mappings.pop(tool_call_id, None):
            logger.debug(f"Unregistered tool call {tool_call_id}")

    def get_mapping_count(self) -> int:
        """Get count of active tool call mappings.

        Returns:
            Number of currently tracked tool calls
        """
        return len(self._mappings)

    async def _cleanup_loop(self):
        """Background task to periodically clean up stale mappings.

        Raises:
            asyncio.CancelledError: If the task is cancelled during shutdown.
        """
        while True:
            try:
                await asyncio.sleep(self._cleanup_interval)
                await self._cleanup_stale()
            except asyncio.CancelledError:
                logger.info("ToolCallRegistry cleanup loop cancelled")
                raise
            except Exception as e:
                logger.error(f"Error in tool call registry cleanup loop: {e}", exc_info=True)

    async def _cleanup_stale(self):
        """Remove mappings older than 1 hour.

        Tool calls should complete within minutes, so 1 hour is a safe
        threshold for detecting abandoned mappings.
        """
        now = time.time()
        stale_threshold = 3600  # 1 hour
        stale_ids = [tool_call_id for tool_call_id, (_, timestamp) in self._mappings.items() if now - timestamp > stale_threshold]

        for tool_call_id in stale_ids:
            self._mappings.pop(tool_call_id, None)

        if stale_ids:
            logger.info(f"Cleaned up {len(stale_ids)} stale tool call mappings")


# Global singleton instance
_tool_call_registry: Optional[ToolCallRegistry] = None


def get_tool_call_registry() -> ToolCallRegistry:
    """Get the global ToolCallRegistry singleton instance.

    Returns:
        The global ToolCallRegistry instance
    """
    global _tool_call_registry  # pylint: disable=global-statement
    if _tool_call_registry is None:
        _tool_call_registry = ToolCallRegistry()
    return _tool_call_registry


def set_tool_call_registry(registry: ToolCallRegistry):
    """Set the global ToolCallRegistry instance.

    This is primarily used for testing to inject mock registries.

    Args:
        registry: The ToolCallRegistry instance to use globally
    """
    global _tool_call_registry  # pylint: disable=global-statement
    _tool_call_registry = registry
