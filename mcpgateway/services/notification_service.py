# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/notification_service.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Authors: Keval Mahajan

Description:
    MCP Notification Service for handling server notifications with debounced
    gateway refresh. Provides centralized notification handling for MCP sessions
    including tools/list_changed, resources/list_changed, and prompts/list_changed.

    Key Features:
    - Debounced refresh to prevent notification storms
    - Flag merging during debounce (notifications within window merge their refresh flags)
    - Per-gateway refresh locking to prevent concurrent refresh races
    - Per-gateway refresh tracking with capability awareness
    - Compatible with MCPSessionPool for pooled session notification handling
    - Per-gateway session isolation ensures correct notification attribution
    - Supports tools, resources, and prompts list_changed notifications

    Capable of handling other tasks as well like cancellation, progress notifications, etc. (to be implemented here)

Usage:
    ```python
    from mcpgateway.services.notification_service import NotificationService

    # Create service instance
    notification_service = NotificationService()
    await notification_service.initialize()

    # Create a message handler for a specific gateway
    handler = notification_service.create_message_handler(gateway_id="gw-123")

    # Pass handler to ClientSession
    session = ClientSession(read_stream, write_stream, message_handler=handler)
    ```
"""

# Future
from __future__ import annotations

# Standard
import asyncio
from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any, Awaitable, Callable, Dict, Optional, Set, TYPE_CHECKING

# Third-Party
from mcp.shared.session import RequestResponder
import mcp.types as mcp_types

# First-Party
from mcpgateway.services.logging_service import LoggingService

if TYPE_CHECKING:
    # First-Party
    from mcpgateway.services.gateway_service import GatewayService

# Type alias for message handler callback
MessageHandlerCallback = Callable[
    [RequestResponder[mcp_types.ServerRequest, mcp_types.ClientResult] | mcp_types.ServerNotification | Exception],
    Awaitable[None],
]

# Initialize logging
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class NotificationType(Enum):
    """Types of MCP list_changed notifications.

    Attributes:
        TOOLS_LIST_CHANGED: Notification for tool list changes.
        RESOURCES_LIST_CHANGED: Notification for resource list changes.
        PROMPTS_LIST_CHANGED: Notification for prompt list changes.
    """

    TOOLS_LIST_CHANGED = "notifications/tools/list_changed"
    RESOURCES_LIST_CHANGED = "notifications/resources/list_changed"
    PROMPTS_LIST_CHANGED = "notifications/prompts/list_changed"


@dataclass
class GatewayCapabilities:
    """Tracks list_changed capabilities for a gateway.

    Attributes:
        tools_list_changed: Whether the gateway supports tool list changes.
        resources_list_changed: Whether the gateway supports resource list changes.
        prompts_list_changed: Whether the gateway supports prompt list changes.
    """

    tools_list_changed: bool = False
    resources_list_changed: bool = False
    prompts_list_changed: bool = False


def _empty_notification_type_set() -> Set[NotificationType]:
    """Factory function for creating an empty set of NotificationType.

    Returns:
        An empty set typed for NotificationType elements.
    """
    return set()


@dataclass
class PendingRefresh:
    """Represents a pending refresh operation with debounce tracking.

    Attributes:
        gateway_id: The ID of the gateway to refresh.
        enqueued_at: The timestamp when the refresh was enqueued.
        include_resources: Whether to include resources in the refresh.
        include_prompts: Whether to include prompts in the refresh.
        triggered_by: The set of notification types that triggered this refresh.
    """

    gateway_id: str
    enqueued_at: float = field(default_factory=time.time)
    include_resources: bool = True
    include_prompts: bool = True
    # Track which notification types triggered this refresh
    triggered_by: Set[NotificationType] = field(default_factory=_empty_notification_type_set)


class NotificationService:
    """Centralized service for handling MCP server notifications.

    Provides debounced refresh triggering based on list_changed notifications
    from MCP servers. Works with MCPSessionPool to handle notifications for
    pooled sessions while maintaining session isolation.

    Attributes:
        debounce_seconds: Minimum time between refresh operations for same gateway.
        max_queue_size: Maximum pending refreshes in the queue.

    Example:
        >>> service = NotificationService(debounce_seconds=5.0)
        >>> service.debounce_seconds
        5.0
        >>> service._gateway_capabilities == {}
        True
    """

    def __init__(
        self,
        debounce_seconds: float = 5.0,
        max_queue_size: int = 100,
    ) -> None:
        """Initialize the NotificationService.

        Args:
            debounce_seconds: Minimum time between refreshes for same gateway.
            max_queue_size: Maximum number of pending refreshes in queue.

        Example:
            >>> service = NotificationService(debounce_seconds=10.0, max_queue_size=50)
            >>> service.debounce_seconds
            10.0
            >>> service._max_queue_size
            50
        """
        self.debounce_seconds = debounce_seconds
        self._max_queue_size = max_queue_size

        # Track gateway capabilities for list_changed support
        self._gateway_capabilities: Dict[str, GatewayCapabilities] = {}

        # Debounce tracking: gateway_id -> last refresh enqueue time
        self._last_refresh_enqueued: Dict[str, float] = {}

        # Track pending refreshes by gateway_id to allow flag merging during debounce
        # When a notification arrives during debounce window, we merge flags instead of dropping
        self._pending_refresh_flags: Dict[str, PendingRefresh] = {}

        # Pending refresh queue
        self._refresh_queue: asyncio.Queue[PendingRefresh] = asyncio.Queue(maxsize=max_queue_size)

        # Background worker task
        self._worker_task: Optional[asyncio.Task[None]] = None
        self._shutdown_event = asyncio.Event()

        # Reference to gateway service for refresh operations (set during initialize)
        self._gateway_service: Optional["GatewayService"] = None

        # Metrics
        self._notifications_received = 0
        self._notifications_debounced = 0
        self._refreshes_triggered = 0
        self._refreshes_failed = 0

    async def initialize(self, gateway_service: Optional["GatewayService"] = None) -> None:
        """Initialize the notification service and start background worker.

        Args:
            gateway_service: Optional GatewayService reference for triggering refreshes.
                           Can be set later via set_gateway_service().

        Example:
            >>> import asyncio
            >>> async def test():
            ...     service = NotificationService()
            ...     await service.initialize()
            ...     is_running = service._worker_task is not None
            ...     await service.shutdown()
            ...     return is_running
            >>> asyncio.run(test())
            True
        """
        if gateway_service:
            self._gateway_service = gateway_service

        self._shutdown_event.clear()
        self._worker_task = asyncio.create_task(self._process_refresh_queue())
        logger.info("NotificationService initialized with debounce=%ss", self.debounce_seconds)

    def set_gateway_service(self, gateway_service: "GatewayService") -> None:
        """Set the gateway service reference for refresh operations.

        Args:
            gateway_service: The GatewayService instance to use for refreshes.

        Example:
            >>> from unittest.mock import Mock
            >>> service = NotificationService()
            >>> mock_gateway_service = Mock()
            >>> service.set_gateway_service(mock_gateway_service)
        """
        self._gateway_service = gateway_service

    async def shutdown(self) -> None:
        """Shutdown the notification service and cleanup resources.

        Example:
            >>> import asyncio
            >>> async def test():
            ...     service = NotificationService()
            ...     await service.initialize()
            ...     await service.shutdown()
            ...     return service._worker_task is None or service._worker_task.done()
            >>> asyncio.run(test())
            True
        """
        self._shutdown_event.set()

        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None

        self._gateway_capabilities.clear()
        self._last_refresh_enqueued.clear()
        self._pending_refresh_flags.clear()
        logger.info("NotificationService shutdown complete")

    def register_gateway_capabilities(
        self,
        gateway_id: str,
        capabilities: Dict[str, Any],
    ) -> None:
        """Register list_changed capabilities for a gateway.

        Extracts and stores which list_changed notifications the gateway supports
        based on server capabilities returned during initialization.

        Args:
            gateway_id: The gateway ID.
            capabilities: Server capabilities dict from initialize response.

        Example:
            >>> service = NotificationService()
            >>> caps = {"tools": {"listChanged": True}, "resources": {"listChanged": False}}
            >>> service.register_gateway_capabilities("gw-1", caps)
            >>> service.supports_list_changed("gw-1")
            True
            >>> service._gateway_capabilities["gw-1"].resources_list_changed
            False
        """
        tools_cap: Dict[str, Any] = capabilities.get("tools", {}) if isinstance(capabilities.get("tools"), dict) else {}
        resources_cap: Dict[str, Any] = capabilities.get("resources", {}) if isinstance(capabilities.get("resources"), dict) else {}
        prompts_cap: Dict[str, Any] = capabilities.get("prompts", {}) if isinstance(capabilities.get("prompts"), dict) else {}

        self._gateway_capabilities[gateway_id] = GatewayCapabilities(
            tools_list_changed=bool(tools_cap.get("listChanged", False)),
            resources_list_changed=bool(resources_cap.get("listChanged", False)),
            prompts_list_changed=bool(prompts_cap.get("listChanged", False)),
        )

        logger.debug(
            "Registered capabilities for gateway %s: tools=%s, resources=%s, prompts=%s",
            gateway_id,
            self._gateway_capabilities[gateway_id].tools_list_changed,
            self._gateway_capabilities[gateway_id].resources_list_changed,
            self._gateway_capabilities[gateway_id].prompts_list_changed,
        )

    def unregister_gateway(self, gateway_id: str) -> None:
        """Unregister a gateway and cleanup its state.

        Args:
            gateway_id: The gateway ID to unregister.

        Example:
            >>> service = NotificationService()
            >>> service.register_gateway_capabilities("gw-1", {"tools": {"listChanged": True}})
            >>> service.supports_list_changed("gw-1")
            True
            >>> service.unregister_gateway("gw-1")
            >>> service.supports_list_changed("gw-1")
            False
        """
        self._gateway_capabilities.pop(gateway_id, None)
        self._last_refresh_enqueued.pop(gateway_id, None)

    def supports_list_changed(self, gateway_id: str) -> bool:
        """Check if a gateway supports any list_changed notifications.

        Args:
            gateway_id: The gateway ID to check.

        Returns:
            True if gateway supports at least one list_changed notification type.

        Example:
            >>> service = NotificationService()
            >>> caps = {"tools": {"listChanged": True}}
            >>> service.register_gateway_capabilities("gw-1", caps)
            >>> service.supports_list_changed("gw-1")
            True
            >>> service.supports_list_changed("gw-unknown")
            False
        """
        caps = self._gateway_capabilities.get(gateway_id)
        if not caps:
            return False
        return caps.tools_list_changed or caps.resources_list_changed or caps.prompts_list_changed

    def create_message_handler(
        self,
        gateway_id: str,
        gateway_url: Optional[str] = None,
    ) -> MessageHandlerCallback:
        """Create a message handler callback for a specific gateway.

        Returns a callback suitable for passing to ClientSession's message_handler
        parameter. The handler routes notifications to this service for processing.

        Args:
            gateway_id: The gateway ID this handler is for.
            gateway_url: Optional URL for logging context.

        Returns:
            Async callable suitable for ClientSession message_handler.

        Example:
            >>> service = NotificationService()
            >>> handler = service.create_message_handler("gw-123")
            >>> callable(handler)
            True
        """

        async def message_handler(
            message: RequestResponder[mcp_types.ServerRequest, mcp_types.ClientResult] | mcp_types.ServerNotification | Exception,
        ) -> None:
            """Handle incoming messages from MCP server.

            Args:
                message: The message received from the server.
            """
            # Only process ServerNotification objects
            if isinstance(message, mcp_types.ServerNotification):
                await self._handle_notification(gateway_id, message, gateway_url)
            elif isinstance(message, Exception):
                logger.warning("Received exception from MCP server %s: %s", gateway_id, message)
            # RequestResponder messages are handled by the session itself

        return message_handler

    async def _handle_notification(
        self,
        gateway_id: str,
        notification: mcp_types.ServerNotification,
        gateway_url: Optional[str] = None,
    ) -> None:
        """Process an incoming server notification.

        Args:
            gateway_id: The gateway ID that sent the notification.
            notification: The notification object.
            gateway_url: Optional URL for logging context.
        """
        self._notifications_received += 1

        # Extract notification type from the notification object
        # ServerNotification has a 'root' attribute containing the actual notification
        notification_root = notification.root

        # Check for list_changed notifications
        notification_type: Optional[NotificationType] = None

        # Match notification types - check class names since mcp.types may vary
        root_class = type(notification_root).__name__

        if "ToolListChangedNotification" in root_class or "ToolsListChangedNotification" in root_class:
            notification_type = NotificationType.TOOLS_LIST_CHANGED
        elif "ResourceListChangedNotification" in root_class or "ResourcesListChangedNotification" in root_class:
            notification_type = NotificationType.RESOURCES_LIST_CHANGED
        elif "PromptListChangedNotification" in root_class or "PromptsListChangedNotification" in root_class:
            notification_type = NotificationType.PROMPTS_LIST_CHANGED

        if notification_type:
            logger.info(
                "Received %s notification from gateway %s (%s)",
                notification_type.value,
                gateway_id,
                gateway_url or "unknown",
            )
            await self._enqueue_refresh(gateway_id, notification_type)
        else:
            logger.info(
                "Received notification from gateway %s: %s",
                gateway_id,
                root_class,
            )

    async def _enqueue_refresh(
        self,
        gateway_id: str,
        notification_type: NotificationType,
    ) -> None:
        """Enqueue a refresh operation with debouncing and flag merging.

        When notifications arrive during the debounce window, their flags are
        merged into the pending refresh instead of being dropped. This ensures
        that if tools/list_changed arrives after resources/list_changed within
        the debounce window, tools will still be refreshed.

        Args:
            gateway_id: The gateway to refresh.
            notification_type: The type of notification that triggered this.
        """
        now = time.time()
        last_enqueued = self._last_refresh_enqueued.get(gateway_id, 0)

        # Determine what to include based on notification type
        include_resources = notification_type == NotificationType.RESOURCES_LIST_CHANGED
        include_prompts = notification_type == NotificationType.PROMPTS_LIST_CHANGED

        # For tools notification, include everything as tools are always primary
        if notification_type == NotificationType.TOOLS_LIST_CHANGED:
            include_resources = True
            include_prompts = True

        # Debounce: if within window, merge flags into pending refresh instead of dropping
        if now - last_enqueued < self.debounce_seconds:
            existing = self._pending_refresh_flags.get(gateway_id)
            if existing:
                # Merge flags - use OR to include all requested types
                existing.include_resources = existing.include_resources or include_resources
                existing.include_prompts = existing.include_prompts or include_prompts
                existing.triggered_by.add(notification_type)
                self._notifications_debounced += 1
                logger.debug(
                    "Merged %s into pending refresh for gateway %s (resources=%s, prompts=%s)",
                    notification_type.value,
                    gateway_id,
                    existing.include_resources,
                    existing.include_prompts,
                )
                return

            # No pending refresh found but within debounce - this shouldn't happen normally
            # but can occur if the refresh was already processed. Count as debounced.
            self._notifications_debounced += 1
            logger.debug(
                "Debounced refresh for gateway %s (last enqueued %.1fs ago, no pending)",
                gateway_id,
                now - last_enqueued,
            )
            return

        # Create new pending refresh
        pending = PendingRefresh(
            gateway_id=gateway_id,
            include_resources=include_resources,
            include_prompts=include_prompts,
            triggered_by={notification_type},
        )

        try:
            self._refresh_queue.put_nowait(pending)
            self._last_refresh_enqueued[gateway_id] = now
            self._pending_refresh_flags[gateway_id] = pending  # Track for flag merging
            logger.info(
                "Enqueued refresh for gateway %s (triggered by %s)",
                gateway_id,
                notification_type.value,
            )
        except asyncio.QueueFull:
            logger.warning(
                "Refresh queue full, dropping refresh request for gateway %s",
                gateway_id,
            )

    async def _process_refresh_queue(self) -> None:
        """Background worker that processes pending refresh operations.

        Continuously runs until shutdown is triggered, picking up pending
        refreshes from the queue and executing them.
        """
        logger.info("NotificationService refresh worker started")

        while not self._shutdown_event.is_set():
            try:
                # Wait for pending refresh with timeout to allow shutdown check
                try:
                    pending = await asyncio.wait_for(
                        self._refresh_queue.get(),
                        timeout=1.0,
                    )
                except asyncio.TimeoutError:
                    continue

                await self._execute_refresh(pending)
                self._refresh_queue.task_done()

            except asyncio.CancelledError:
                logger.debug("Refresh worker cancelled")
                break
            except Exception as e:
                logger.exception("Error in refresh worker: %s", e)

        logger.info("NotificationService refresh worker stopped")

    async def _execute_refresh(self, pending: PendingRefresh) -> None:
        """Execute a refresh operation.

        Acquires the per-gateway refresh lock to prevent concurrent refreshes
        with manual refresh or health check auto-refresh.

        Args:
            pending: The pending refresh to execute.
        """
        # pylint: disable=protected-access
        gateway_id = pending.gateway_id

        # Clear pending flag tracking now that we're processing this refresh
        self._pending_refresh_flags.pop(gateway_id, None)

        if not self._gateway_service:
            logger.warning(
                "Cannot execute refresh for gateway %s: GatewayService not set",
                gateway_id,
            )
            return

        # Acquire per-gateway lock to prevent concurrent refresh with manual/auto refresh
        lock = self._gateway_service._get_refresh_lock(gateway_id)  # pyright: ignore[reportPrivateUsage]

        # Skip if lock is already held (another refresh in progress)
        if lock.locked():
            logger.debug(
                "Skipping event-driven refresh for gateway %s: lock held (refresh in progress)",
                gateway_id,
            )
            self._notifications_debounced += 1
            return

        async with lock:
            logger.info(
                "Executing event-driven refresh for gateway %s (resources=%s, prompts=%s)",
                pending.gateway_id,
                pending.include_resources,
                pending.include_prompts,
            )

            try:
                # Use the existing refresh method (lock already held)
                result = await self._gateway_service._refresh_gateway_tools_resources_prompts(  # pyright: ignore[reportPrivateUsage]
                    gateway_id=pending.gateway_id,
                    created_via="notification_service",
                    include_resources=pending.include_resources,
                    include_prompts=pending.include_prompts,
                )

                self._refreshes_triggered += 1

                if result.get("success"):
                    logger.info(
                        "Event-driven refresh completed for gateway %s: tools_added=%d, tools_removed=%d",
                        pending.gateway_id,
                        result.get("tools_added", 0),
                        result.get("tools_removed", 0),
                    )
                else:
                    self._refreshes_failed += 1
                    logger.warning(
                        "Event-driven refresh failed for gateway %s: %s",
                        pending.gateway_id,
                        result.get("error"),
                    )

            except Exception as e:
                self._refreshes_failed += 1
                logger.exception(
                    "Error during event-driven refresh for gateway %s: %s",
                    pending.gateway_id,
                    e,
                )

    def get_metrics(self) -> Dict[str, Any]:
        """Return notification service metrics.

        Returns:
            Dict containing notification and refresh metrics.

        Example:
            >>> service = NotificationService()
            >>> metrics = service.get_metrics()
            >>> "notifications_received" in metrics
            True
        """
        return {
            "notifications_received": self._notifications_received,
            "notifications_debounced": self._notifications_debounced,
            "refreshes_triggered": self._refreshes_triggered,
            "refreshes_failed": self._refreshes_failed,
            "pending_refreshes": self._refresh_queue.qsize(),
            "registered_gateways": len(self._gateway_capabilities),
            "debounce_seconds": self.debounce_seconds,
        }


# Module-level singleton instance (initialized lazily)
_notification_service: Optional[NotificationService] = None


def get_notification_service() -> NotificationService:
    """Get the global NotificationService instance.

    Returns:
        The global NotificationService instance.

    Raises:
        RuntimeError: If service has not been initialized.

    Example:
        >>> try:
        ...     _ = init_notification_service()
        ...     service = get_notification_service()
        ...     result = isinstance(service, NotificationService)
        ... except RuntimeError:
        ...     result = False
        >>> result
        True
    """
    if _notification_service is None:
        raise RuntimeError("NotificationService not initialized. Call init_notification_service() first.")
    return _notification_service


def init_notification_service(
    debounce_seconds: float = 5.0,
    max_queue_size: int = 100,
) -> NotificationService:
    """Initialize the global NotificationService.

    Args:
        debounce_seconds: Minimum time between refreshes for same gateway.
        max_queue_size: Maximum number of pending refreshes in queue.

    Returns:
        The initialized NotificationService instance.

    Example:
        >>> service = init_notification_service(debounce_seconds=10.0)
        >>> service.debounce_seconds
        10.0
    """
    global _notification_service  # pylint: disable=global-statement
    _notification_service = NotificationService(
        debounce_seconds=debounce_seconds,
        max_queue_size=max_queue_size,
    )
    logger.info("Global NotificationService created")
    return _notification_service


async def close_notification_service() -> None:
    """Close the global NotificationService.

    Example:
        >>> import asyncio
        >>> async def test():
        ...     init_notification_service()
        ...     await close_notification_service()
        ...     try:
        ...         get_notification_service()
        ...     except RuntimeError:
        ...         return True
        ...     return False
        >>> asyncio.run(test())
        True
    """
    global _notification_service  # pylint: disable=global-statement
    if _notification_service is not None:
        await _notification_service.shutdown()
        _notification_service = None
        logger.info("Global NotificationService closed")
