# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/notification_service.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Authors: Keval Mahajan

Description:
    Centralized handler for MCP server-to-gateway notifications AND the
    server-to-client fanout surface introduced by ADR-052 (GET /mcp stream).
    Connects upstream ``ClientSession`` message-handler callbacks to the
    per-session event bus and to the worker-local request-correlation dict
    that lets downstream POSTs resolve held ``RequestResponder`` instances.

    Responsibilities:
    - Debounced gateway refresh triggered by ``tools/resources/prompts
      list_changed`` notifications (with flag merging during the debounce
      window, per-gateway refresh lock, capability-aware filtering).
    - ``ServerNotification`` fanout to the GET /mcp event bus so
      downstream clients on the SSE stream see the notification.
    - ``ServerRequest`` correlation (``_forward_request_to_stream`` +
      ``complete_request``) for sampling / elicitation / roots-list —
      registers the responder under ``(session_id, request_id)``, spawns
      a holder task, publishes the envelope, and waits for a downstream
      POST to resolve it. Timeout is per-task via ``wait_for``; there is
      no background sweeper.
    - Bounded ``shutdown`` that drains holder tasks within a configurable
      timeout and cancels any stragglers.

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


def _record_publish_failure(
    downstream_session_id: str,
    request_id: str,
    *,
    reason: str,
    exc: BaseException,
    counter: Any,
) -> None:
    """Increment the publish-failure counter and log the failure at the correct level.

    Shared between ``_forward_request_to_stream`` (request fanout) and
    ``_forward_notification_to_stream`` (notification fanout) so a
    sustained Redis outage moves both metrics identically and
    operators get the same traceback treatment regardless of which
    publish path fired.
    """
    try:
        counter.labels(reason=reason).inc()
    except Exception as metric_exc:  # noqa: BLE001 — metric failures must not crash the publish path
        logger.debug("publish-failed counter raised: %s", metric_exc)
    log_method = logger.warning if reason == "backend_unavailable" else logger.error
    log_method(
        "Failed to publish server-initiated message %s/%s (%s): %s — cancelling responder",
        downstream_session_id,
        request_id,
        reason,
        exc,
        exc_info=exc if reason == "transport_error" else None,
    )


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
    from MCP servers. Works with SessionAffinity to handle notifications for
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

        # Server-initiated request correlation (ADR-052). Worker-local: the
        # POST carrying the response is affinity-routed to the worker that
        # holds the upstream RequestResponder, so a process-local dict is
        # sufficient — no Redis dispatch table needed. Key:
        # (downstream_session_id, request_id). Value: future the holder task
        # awaits; the response payload is set when the downstream POST lands.
        self._pending_requests: Dict[tuple[str, str], asyncio.Future[Any]] = {}
        self._pending_lock = asyncio.Lock()
        self._pending_request_ttl_seconds: float = 60.0
        self._pending_holder_tasks: Set[asyncio.Task[None]] = set()
        # Bounded shutdown drain — see shutdown() docstring rationale.
        self._shutdown_drain_timeout_seconds: float = 5.0

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

        # Idempotent: two init paths can call this — `main.lifespan` runs
        # it once for the single-node case, and (when affinity is on)
        # `start_affinity_notification_service` re-runs it later with the
        # gateway_service set. Refresh the reference but don't double-spawn
        # the worker — that would leak the first task and produce duplicate refreshes.
        if self._worker_task is not None and not self._worker_task.done():
            logger.debug("NotificationService already initialized; refreshing gateway_service ref only")
            return

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

    @staticmethod
    async def _safe_cancel(
        responder: "RequestResponder[mcp_types.ServerRequest, mcp_types.ClientResult]",
        downstream_session_id: str,
        request_id: str,
    ) -> None:
        """Wrap ``responder.cancel()`` so its exceptions never escape the holder task.

        ``RequestResponder.cancel()`` sends a cancellation *error response*
        back through the upstream session (``ErrorData(code=0,
        message="Request cancelled")``, not a JSON-RPC notification) and
        can raise on a broken transport (``BrokenResourceError``,
        ``ClosedResourceError``, etc). If those exceptions escape, the
        holder-task done-callback logs them as a generic
        ``exited with exception`` line — losing the cancel-vs-respond
        context that an operator needs to tell "downstream never
        responded" apart from "upstream session already torn down".
        Catching and logging here produces a specific cancel-site log
        line and lets the holder task finish its normal return path.
        """
        try:
            await responder.cancel()
        except Exception as exc:  # noqa: BLE001 — by design; logged + swallowed
            logger.warning(
                "responder.cancel() raised for %s/%s: %s",
                downstream_session_id,
                request_id,
                exc,
            )

    async def shutdown(self) -> None:
        """Shutdown the notification service and cleanup resources.

        Cancels the refresh-queue worker AND any in-flight server-initiated
        request holder tasks (ADR-052). Without the holder cleanup, every
        held responder would sit in ``wait_for(60s)`` past process shutdown,
        keeping the upstream MCP session's responder context manager alive
        and leaking tasks.

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

        # Cancel and drain holder tasks. Snapshot the set first because each
        # task's done-callback mutates `_pending_holder_tasks` on completion.
        # Bounded wait — each holder's ``responder.__exit__`` sends a
        # cancellation notification through the upstream session, which is
        # the very thing that may be hung. Don't block shutdown forever.
        holders = list(self._pending_holder_tasks)
        for task in holders:
            task.cancel()
        if holders:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*holders, return_exceptions=True),
                    timeout=self._shutdown_drain_timeout_seconds,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "NotificationService.shutdown: %d holder tasks did not drain within %ss; abandoning",
                    sum(1 for t in holders if not t.done()),
                    self._shutdown_drain_timeout_seconds,
                )
        self._pending_holder_tasks.clear()

        # Drop any remaining pending entries so a late `complete_request`
        # call after shutdown doesn't hang on a future nobody is awaiting.
        async with self._pending_lock:
            for key, future in list(self._pending_requests.items()):
                if not future.done():
                    future.cancel()
                self._pending_requests.pop(key, None)

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
        *,
        downstream_session_id: Optional[str] = None,
    ) -> MessageHandlerCallback:
        """Create a message handler callback for a specific gateway.

        Returns a callback suitable for passing to ClientSession's message_handler
        parameter. The handler routes notifications to this service for processing
        AND, when ``downstream_session_id`` is provided, forwards
        ``ServerNotification`` envelopes to the GET /mcp listener for that
        session via the server event bus (ADR-052).

        Args:
            gateway_id: The gateway ID this handler is for.
            gateway_url: Optional URL for logging context.
            downstream_session_id: Downstream MCP session id (the
                ``Mcp-Session-Id`` from the client). When provided,
                server-initiated notifications are published to the GET
                stream for this session.

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
            if isinstance(message, mcp_types.ServerNotification):
                # Internal handling: list-changed → debounced refresh.
                await self._handle_notification(gateway_id, message, gateway_url)
                # Spec-defined fanout: forward the envelope to the GET /mcp
                # listener for this downstream session, if a listener exists.
                if downstream_session_id is not None:
                    await self._forward_notification_to_stream(downstream_session_id, message)
            elif isinstance(message, RequestResponder):
                if downstream_session_id is not None:
                    await self._forward_request_to_stream(downstream_session_id, message)
                # If no downstream session is wired the responder will be
                # auto-cancelled when the message handler returns and the SDK
                # cleans up; we deliberately do nothing in that path.
            elif isinstance(message, Exception):
                logger.warning("Received exception from MCP server %s: %s", gateway_id, message)

        return message_handler

    async def _forward_request_to_stream(
        self,
        downstream_session_id: str,
        responder: "RequestResponder[mcp_types.ServerRequest, mcp_types.ClientResult]",
    ) -> None:
        """Forward a server-initiated request to the GET /mcp listener and hold the responder.

        We register a future in the worker-local pending dict, publish the
        JSON-RPC request envelope on the event bus, and spawn a holder task
        that enters the responder's context manager and awaits the future.
        When the downstream client POSTs back the response, ``complete_request``
        sets the future and the holder relays it to the responder.

        Failure to forward (no event bus, no listener, etc.) cancels the
        responder so the upstream session sees a clean error rather than
        hanging.

        Args:
            downstream_session_id: Target downstream MCP session id.
            responder: The SDK ``RequestResponder`` to hold open until the
                downstream client replies.
        """
        try:
            # First-Party
            from mcpgateway.transports.server_event_bus import get_server_event_bus  # pylint: disable=import-outside-toplevel
            from mcp.types import JSONRPCMessage, JSONRPCRequest  # pylint: disable=import-outside-toplevel
        except ImportError as exc:  # pragma: no cover
            logger.debug("Server event bus unavailable, cancelling responder: %s", exc)
            with responder:
                await responder.cancel()
            return

        # Third-Party
        from pydantic import ValidationError  # pylint: disable=import-outside-toplevel

        request_id = str(responder.request_id)
        # Build the JSON-RPC request envelope from the SDK's typed request.
        # The narrow catch lets shape-drift bugs (AttributeError when
        # ``responder.request`` loses ``root``, ValidationError from
        # ``model_dump``, TypeError from a typed-args mismatch) surface
        # with a traceback instead of being smuggled into a generic
        # warning. ``exc_info`` preserves the stack — operators chasing
        # "envelope build failed" otherwise have nothing to file a bug
        # against.
        try:
            inner = responder.request.root if hasattr(responder.request, "root") else responder.request
            payload = inner.model_dump(by_alias=True, exclude_none=True)
        except (AttributeError, ValidationError, TypeError, ValueError) as exc:
            logger.warning(
                "Failed to build request payload for %s/%s: %s",
                downstream_session_id,
                request_id,
                exc,
                exc_info=exc,
            )
            with responder:
                await responder.cancel()
            return
        # JSON-RPC requires a non-empty ``method``. Defense-in-depth:
        # if upstream ever hands us a request without one, log and
        # cancel rather than publishing a malformed wire frame.
        method = payload.get("method")
        if not isinstance(method, str) or not method:
            logger.warning(
                "Refusing to publish server-initiated request %s/%s with empty method (payload shape: %r)",
                downstream_session_id,
                request_id,
                sorted(payload.keys()) if isinstance(payload, dict) else type(payload).__name__,
            )
            with responder:
                await responder.cancel()
            return
        envelope = JSONRPCMessage(
            JSONRPCRequest(
                jsonrpc="2.0",
                id=responder.request_id,
                method=method,
                params=payload.get("params"),
            )
        )

        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()
        key = (downstream_session_id, request_id)

        # Order: register pending → spawn holder → publish (with cleanup
        # on failure). The reverse order (publish first) loses fast
        # downstream responses in multi-node: node A publishes, the
        # listener on node B delivers to the client, the client POSTs the
        # response back, and node A's complete_request finds an empty
        # pending dict because the register hadn't happened yet. With
        # this order, complete_request can match the response as soon as
        # it arrives. The holder uses ``wait_for(future)`` and tolerates
        # being cancelled by the publish-failure cleanup below — that
        # race is benign (just one extra cancel call).
        async with self._pending_lock:
            # Upstream is supposed to issue unique JSON-RPC ids per session,
            # but we've seen reuse occur during reconnect / recovery. When
            # it does, the prior in-flight request gets silently cancelled
            # by this defensive replace — log loudly so the protocol
            # violation has a forensic trail (operators looking at timed-out
            # responder errors otherwise have no way to tell "downstream
            # never replied" apart from "we cancelled it because of id reuse").
            existing = self._pending_requests.pop(key, None)
            if existing is not None and not existing.done():
                logger.warning(
                    "Server-initiated request id collision for %s/%s — upstream reused id; cancelling prior pending future (likely an upstream protocol violation)",
                    downstream_session_id,
                    request_id,
                )
                existing.cancel()
            self._pending_requests[key] = future

        async def hold() -> None:
            """Hold the responder open until ``future`` resolves or the TTL elapses."""
            primary_exc: Optional[BaseException] = None
            try:
                try:
                    with responder:
                        try:
                            response_payload = await asyncio.wait_for(
                                future,
                                timeout=self._pending_request_ttl_seconds,
                            )
                        except asyncio.TimeoutError:
                            logger.info(
                                "Server-initiated request %s/%s timed out; cancelling",
                                downstream_session_id,
                                request_id,
                            )
                            await self._safe_cancel(responder, downstream_session_id, request_id)
                            return
                        except asyncio.CancelledError as exc:
                            # Track the primary failure so we can detect
                            # if responder.__exit__ shadows it on the way
                            # out. Without this, the done-callback would
                            # log the wrong cause and operators would
                            # chase a teardown error instead of the real
                            # cancellation.
                            primary_exc = exc
                            await self._safe_cancel(responder, downstream_session_id, request_id)
                            raise
                        try:
                            await self._respond_with_payload(responder, response_payload)
                        except Exception as respond_exc:  # noqa: BLE001 — surface the failure, don't crash the task silently
                            logger.warning(
                                "responder.respond() raised for %s/%s: %s",
                                downstream_session_id,
                                request_id,
                                respond_exc,
                            )
                except BaseException as exc:
                    if primary_exc is not None and exc is not primary_exc:
                        logger.warning(
                            "responder.__exit__ raised %s for %s/%s, shadowing primary %s — operator should investigate teardown failure",
                            type(exc).__name__,
                            downstream_session_id,
                            request_id,
                            type(primary_exc).__name__,
                        )
                    raise
            finally:
                async with self._pending_lock:
                    if self._pending_requests.get(key) is future:
                        self._pending_requests.pop(key, None)

        def _on_holder_done(t: "asyncio.Task[None]") -> None:
            """Discard the holder task and log any exception that escaped.

            asyncio's "Task exception was never retrieved" warning at GC
            time is unreliable; this captures the failure into the
            standard logger immediately.
            """
            self._pending_holder_tasks.discard(t)
            if t.cancelled():
                return
            exc = t.exception()
            if exc is not None:
                logger.warning(
                    "Request-holder task for %s/%s exited with exception: %s",
                    downstream_session_id,
                    request_id,
                    exc,
                    exc_info=exc,
                )

        task = asyncio.create_task(hold(), name=f"request-holder:{downstream_session_id[:8]}:{request_id}")
        self._pending_holder_tasks.add(task)
        task.add_done_callback(_on_holder_done)

        # Separate try blocks for the two distinct failure modes:
        #
        #   (a) ``get_server_event_bus()`` — bus singleton construction
        #       or config resolution. A RuntimeError or BusBackendError
        #       here is expected when Redis is unavailable; anything
        #       else is a programming error and should propagate with a
        #       traceback in the done-callback rather than being
        #       bucketed as a publish failure.
        #
        #   (b) ``bus.publish()`` — the actual wire call. Typed
        #       ``BusBackendError`` is a retryable Redis outage;
        #       ``ConnectionError`` / ``OSError`` are transient
        #       transport failures. Narrow both so real bugs in the
        #       publish path propagate instead of being classified as
        #       "transport_error".
        # First-Party
        from mcpgateway.services.metrics import server_event_bus_publish_failed_counter  # pylint: disable=import-outside-toplevel
        from mcpgateway.transports.server_event_bus import BusBackendError  # pylint: disable=import-outside-toplevel

        try:
            bus = await get_server_event_bus()
        except (RuntimeError, BusBackendError) as exc:
            _record_publish_failure(
                downstream_session_id,
                request_id,
                reason="backend_unavailable",
                exc=exc,
                counter=server_event_bus_publish_failed_counter,
            )
            if not future.done():
                future.cancel()
            return
        try:
            await bus.publish(downstream_session_id, envelope)
        except (BusBackendError, ConnectionError, OSError) as exc:
            reason = "backend_unavailable" if isinstance(exc, BusBackendError) else "transport_error"
            _record_publish_failure(
                downstream_session_id,
                request_id,
                reason=reason,
                exc=exc,
                counter=server_event_bus_publish_failed_counter,
            )
            if not future.done():
                future.cancel()

    @staticmethod
    async def _respond_with_payload(
        responder: "RequestResponder[mcp_types.ServerRequest, mcp_types.ClientResult]",
        payload: Dict[str, Any],
    ) -> None:
        """Translate a downstream JSON-RPC response payload into ``responder.respond()``.

        Args:
            responder: The held SDK responder.
            payload: Parsed JSON-RPC envelope from the downstream POST.
        """
        # Third-Party
        from pydantic import ValidationError  # pylint: disable=import-outside-toplevel

        if "error" in payload and payload["error"] is not None:
            try:
                error = mcp_types.ErrorData.model_validate(payload["error"])
            except ValidationError as exc:
                # Substituting INTERNAL_ERROR silently strips the original
                # error context — operators would only see a generic
                # message and have no way to trace what the downstream
                # actually said. Log at warning + include the raw payload
                # at debug so the trail isn't lost.
                logger.warning(
                    "Downstream error payload failed validation; substituting INTERNAL_ERROR: %s",
                    exc,
                )
                logger.debug("Original error payload: %r", payload.get("error"))
                error = mcp_types.ErrorData(
                    code=mcp_types.INTERNAL_ERROR,
                    message="Malformed error from downstream",
                    data=None,
                )
            await responder.respond(error)
            return
        try:
            result = mcp_types.ClientResult.model_validate(payload.get("result") or {})
        except ValidationError as exc:
            logger.warning("Could not validate downstream result, sending error: %s", exc)
            await responder.respond(
                mcp_types.ErrorData(
                    code=mcp_types.INTERNAL_ERROR,
                    message=f"Downstream returned an unrecognized result: {exc}",
                    data=None,
                )
            )
            return
        await responder.respond(result)

    def has_pending_request(self, downstream_session_id: str) -> bool:
        """Return True if any server-initiated request is awaiting a response.

        Cheap O(n) scan over a dict that is normally empty or has a handful
        of entries — used by the POST handler to decide whether to peek at
        the request body for response interception. No lock taken: stale
        reads are acceptable here. A stale-missing entry (returns ``False``
        when one was just registered) means the POST falls through to the
        SDK; the held responder TTLs out and the client retries — no data
        loss. A stale-present entry (returns ``True`` when no entry
        actually matches by id) costs one wasted body-buffer plus an SDK
        replay, with no functional harm.

        Args:
            downstream_session_id: The session whose pending requests are
                being checked.

        Returns:
            True if there is at least one pending server-initiated request
            for this session.
        """
        # Snapshot via tuple() so a concurrent _forward_request_to_stream /
        # complete_request / shutdown that mutates the dict during our
        # scan can't trigger ``RuntimeError: dictionary changed size
        # during iteration``. The docstring above commits to lock-free
        # reads; this is the cheapest way to keep that promise honest
        # for the dict's typical "handful of entries" size.
        return any(sid == downstream_session_id for sid, _ in tuple(self._pending_requests))

    async def complete_request(
        self,
        downstream_session_id: str,
        request_id: str,
        payload: Dict[str, Any],
    ) -> bool:
        """Resolve a held server-initiated request with the downstream's response payload.

        Args:
            downstream_session_id: The session the response arrived on.
            request_id: JSON-RPC id of the response.
            payload: Full JSON-RPC envelope (must include ``result`` or
                ``error``).

        Returns:
            True if a held request was matched and its future resolved,
            False otherwise (the POST handler then falls through to the
            normal SDK path).
        """
        key = (downstream_session_id, str(request_id))
        async with self._pending_lock:
            future = self._pending_requests.get(key)
            if future is None:
                # No holder for this id — common case (downstream
                # responded after the holder TTL'd, or the id never had
                # a holder because the request was dispatched the
                # legacy SDK way).
                logger.debug(
                    "complete_request: no pending holder for %s/%s",
                    downstream_session_id,
                    request_id,
                )
                return False
            if future.done():
                # done() covers "already resolved" and "cancelled by
                # shutdown between the get() and our set_result()". We
                # check inside the lock so concurrent shutdown can't
                # cancel between this check and the set_result below.
                # Distinct from the no-holder case because the SDK
                # fall-through here will 4xx/5xx with no responder
                # waiting; operators chasing those errors need the
                # breadcrumb to tie them back to the cancelled holder.
                logger.debug(
                    "complete_request: holder for %s/%s already done (cancelled by shutdown or duplicate response); SDK fall-through will surface as 4xx",
                    downstream_session_id,
                    request_id,
                )
                return False
            future.set_result(payload)
        return True

    async def _forward_notification_to_stream(
        self,
        downstream_session_id: str,
        notification: mcp_types.ServerNotification,
    ) -> None:
        """Publish a server-initiated notification to the GET /mcp event bus.

        Failure here must not break upstream message processing — the bus is
        best-effort delivery, not a transactional path. We log at debug
        level when no listener is wired (common during tests / single-process
        boot before the bus singleton is created).

        Args:
            downstream_session_id: Target downstream session id.
            notification: The ServerNotification envelope from the upstream
                MCP session.
        """
        try:
            # First-Party
            from mcpgateway.transports.server_event_bus import get_server_event_bus  # pylint: disable=import-outside-toplevel
            from mcp.types import JSONRPCMessage, JSONRPCNotification  # pylint: disable=import-outside-toplevel
        except ImportError as exc:  # pragma: no cover — dependency presence is invariant in this codebase
            logger.debug("Server event bus unavailable, dropping notification: %s", exc)
            return
        # Third-Party
        from pydantic import ValidationError  # pylint: disable=import-outside-toplevel

        # First-Party
        from mcpgateway.services.metrics import server_event_bus_publish_failed_counter  # pylint: disable=import-outside-toplevel
        from mcpgateway.transports.server_event_bus import BusBackendError  # pylint: disable=import-outside-toplevel

        # Envelope-build first (narrow catch) so shape-drift bugs surface
        # with a traceback rather than being bucketed as a publish
        # failure.
        try:
            # ServerNotification.root is the underlying typed notification
            # (e.g. ToolsListChangedNotification). We re-wrap as a
            # JSON-RPC envelope so the SSE listener can serialize it
            # without knowing about MCP's typed-union shape.
            inner = notification.root
            payload = inner.model_dump(by_alias=True, exclude_none=True)
        except (AttributeError, ValidationError, TypeError, ValueError) as exc:
            logger.warning(
                "Failed to build notification payload for %s: %s",
                downstream_session_id,
                exc,
                exc_info=exc,
            )
            return
        method = payload.get("method")
        if not isinstance(method, str) or not method:
            # Defense-in-depth: publishing a notification with an empty
            # ``method`` would put a malformed JSON-RPC frame on the wire.
            logger.warning(
                "Refusing to publish server-initiated notification to %s with empty method (payload shape: %r)",
                downstream_session_id,
                sorted(payload.keys()) if isinstance(payload, dict) else type(payload).__name__,
            )
            return
        envelope = JSONRPCMessage(
            JSONRPCNotification(
                jsonrpc="2.0",
                method=method,
                params=payload.get("params"),
            )
        )
        # Separate try for bus-get vs publish so a ``get_server_event_bus``
        # programming bug doesn't get bucketed as ``transport_error``.
        try:
            bus = await get_server_event_bus()
        except (RuntimeError, BusBackendError) as exc:
            _record_publish_failure(
                downstream_session_id,
                f"notif/{method}",
                reason="backend_unavailable",
                exc=exc,
                counter=server_event_bus_publish_failed_counter,
            )
            return
        try:
            await bus.publish(downstream_session_id, envelope)
        except (BusBackendError, ConnectionError, OSError) as exc:
            reason = "backend_unavailable" if isinstance(exc, BusBackendError) else "transport_error"
            _record_publish_failure(
                downstream_session_id,
                f"notif/{method}",
                reason=reason,
                exc=exc,
                counter=server_event_bus_publish_failed_counter,
            )

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

        Raises:
            asyncio.CancelledError: If the task is cancelled during shutdown.
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
                raise
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
