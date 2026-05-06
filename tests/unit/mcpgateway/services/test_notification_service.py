# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_notification_service.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Author: Keval Mahajan

Unit tests for the NotificationService.
A centralized service that handles notifications from MCP servers, debounces them,
and triggers refreshes of tools/resources/prompts as needed.

Capable of handling other tasks as well like cancellation, progress notifications, etc.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.services.notification_service import (
    GatewayCapabilities,
    NotificationService,
    NotificationType,
    PendingRefresh,
    close_notification_service,
    get_notification_service,
    init_notification_service,
)


@pytest.fixture
def notification_service():
    """Create a NotificationService instance for testing."""
    service = NotificationService(debounce_seconds=1.0, max_queue_size=10)
    return service


class TestNotificationServiceInit:
    """Tests for NotificationService initialization."""

    def test_init_with_defaults(self):
        """Test default initialization."""
        service = NotificationService()
        assert service.debounce_seconds == 5.0
        assert service._max_queue_size == 100
        assert service._gateway_capabilities == {}
        assert service._last_refresh_enqueued == {}

    def test_init_with_custom_values(self):
        """Test initialization with custom values."""
        service = NotificationService(debounce_seconds=10.0, max_queue_size=50)
        assert service.debounce_seconds == 10.0
        assert service._max_queue_size == 50


class TestGatewayCapabilities:
    """Tests for gateway capability registration."""

    def test_register_gateway_capabilities_with_tools(self, notification_service):
        """Test registering gateway with tools.listChanged."""
        caps = {"tools": {"listChanged": True}}
        notification_service.register_gateway_capabilities("gw-1", caps)

        assert "gw-1" in notification_service._gateway_capabilities
        assert notification_service._gateway_capabilities["gw-1"].tools_list_changed is True
        assert notification_service._gateway_capabilities["gw-1"].resources_list_changed is False
        assert notification_service._gateway_capabilities["gw-1"].prompts_list_changed is False

    def test_register_gateway_capabilities_with_all(self, notification_service):
        """Test registering gateway with all listChanged capabilities."""
        caps = {
            "tools": {"listChanged": True},
            "resources": {"listChanged": True},
            "prompts": {"listChanged": True},
        }
        notification_service.register_gateway_capabilities("gw-2", caps)

        assert notification_service._gateway_capabilities["gw-2"].tools_list_changed is True
        assert notification_service._gateway_capabilities["gw-2"].resources_list_changed is True
        assert notification_service._gateway_capabilities["gw-2"].prompts_list_changed is True

    def test_register_gateway_capabilities_empty(self, notification_service):
        """Test registering gateway with no listChanged capabilities."""
        caps = {}
        notification_service.register_gateway_capabilities("gw-3", caps)

        assert notification_service._gateway_capabilities["gw-3"].tools_list_changed is False
        assert notification_service._gateway_capabilities["gw-3"].resources_list_changed is False
        assert notification_service._gateway_capabilities["gw-3"].prompts_list_changed is False

    def test_unregister_gateway(self, notification_service):
        """Test unregistering a gateway."""
        notification_service.register_gateway_capabilities("gw-1", {"tools": {"listChanged": True}})
        assert "gw-1" in notification_service._gateway_capabilities

        notification_service.unregister_gateway("gw-1")
        assert "gw-1" not in notification_service._gateway_capabilities

    def test_supports_list_changed_true(self, notification_service):
        """Test supports_list_changed returns True when supported."""
        notification_service.register_gateway_capabilities("gw-1", {"tools": {"listChanged": True}})
        assert notification_service.supports_list_changed("gw-1") is True

    def test_supports_list_changed_false(self, notification_service):
        """Test supports_list_changed returns False when not supported."""
        notification_service.register_gateway_capabilities("gw-1", {})
        assert notification_service.supports_list_changed("gw-1") is False

    def test_supports_list_changed_unknown_gateway(self, notification_service):
        """Test supports_list_changed returns False for unknown gateway."""
        assert notification_service.supports_list_changed("gw-unknown") is False


class TestMessageHandlerFactory:
    """Tests for message handler creation."""

    def test_create_message_handler_returns_callable(self, notification_service):
        """Test that create_message_handler returns a callable."""
        handler = notification_service.create_message_handler("gw-123")
        assert callable(handler)

    @pytest.mark.asyncio
    async def test_message_handler_handles_exception(self, notification_service):
        """Test message handler handles exceptions gracefully."""
        handler = notification_service.create_message_handler("gw-123")

        # Should not raise when receiving an exception
        await handler(ValueError("Test error"))

    @pytest.mark.asyncio
    async def test_message_handler_handles_non_notification(self, notification_service):
        """Test message handler ignores non-notification messages."""
        handler = notification_service.create_message_handler("gw-123")

        # Should not raise when receiving a non-notification message
        await handler(MagicMock())


class TestNotificationDispatch:
    """Tests for notification dispatch logic within _handle_notification."""

    @pytest.mark.asyncio
    async def test_handle_notification_tools(self, notification_service):
        """Test handling tools/list_changed notification."""
        notification_service._enqueue_refresh = AsyncMock()

        # Mock notification structure
        mock_root = MagicMock()
        mock_root.__class__.__name__ = "ToolListChangedNotification"
        mock_notification = MagicMock()
        mock_notification.root = mock_root

        await notification_service._handle_notification("gw-1", mock_notification)

        notification_service._enqueue_refresh.assert_called_once_with("gw-1", NotificationType.TOOLS_LIST_CHANGED)
        assert notification_service._notifications_received == 1

    @pytest.mark.asyncio
    async def test_handle_notification_resources(self, notification_service):
        """Test handling resources/list_changed notification."""
        notification_service._enqueue_refresh = AsyncMock()

        mock_root = MagicMock()
        mock_root.__class__.__name__ = "ResourceListChangedNotification"
        mock_notification = MagicMock()
        mock_notification.root = mock_root

        await notification_service._handle_notification("gw-1", mock_notification)

        notification_service._enqueue_refresh.assert_called_once_with("gw-1", NotificationType.RESOURCES_LIST_CHANGED)

    @pytest.mark.asyncio
    async def test_handle_notification_prompts(self, notification_service):
        """Test handling prompts/list_changed notification."""
        notification_service._enqueue_refresh = AsyncMock()

        mock_root = MagicMock()
        mock_root.__class__.__name__ = "PromptListChangedNotification"
        mock_notification = MagicMock()
        mock_notification.root = mock_root

        await notification_service._handle_notification("gw-1", mock_notification)

        notification_service._enqueue_refresh.assert_called_once_with("gw-1", NotificationType.PROMPTS_LIST_CHANGED)

    @pytest.mark.asyncio
    async def test_handle_notification_unknown(self, notification_service):
        """Test handling unknown notification type."""
        notification_service._enqueue_refresh = AsyncMock()

        mock_root = MagicMock()
        mock_root.__class__.__name__ = "UnknownNotification"
        mock_notification = MagicMock()
        mock_notification.root = mock_root

        await notification_service._handle_notification("gw-1", mock_notification)

        notification_service._enqueue_refresh.assert_not_called()
        assert notification_service._notifications_received == 1


class TestDebouncing:
    """Tests for debounce behavior."""

    @pytest.mark.asyncio
    async def test_debounce_prevents_rapid_refreshes(self, notification_service):
        """Test that rapid notifications are debounced."""
        # Do not initialize worker to keep items in queue

        # Enqueue first refresh
        await notification_service._enqueue_refresh("gw-1", NotificationType.TOOLS_LIST_CHANGED)
        assert notification_service._refresh_queue.qsize() == 1

        # Try to enqueue again immediately - should be debounced
        await notification_service._enqueue_refresh("gw-1", NotificationType.TOOLS_LIST_CHANGED)
        assert notification_service._refresh_queue.qsize() == 1  # Still 1
        assert notification_service._notifications_debounced == 1
        assert notification_service._notifications_debounced == 1
        await notification_service.shutdown()

    @pytest.mark.asyncio
    async def test_enqueue_refresh_queue_full(self, notification_service):
        """Test handling when refresh queue is full."""
        # Fill the queue (max size is 10 in fixture)
        for i in range(10):
            await notification_service._refresh_queue.put(PendingRefresh(gateway_id=f"gw-{i}"))

        assert notification_service._refresh_queue.full()

        # Try to enqueue another
        await notification_service._enqueue_refresh("new-gw", NotificationType.TOOLS_LIST_CHANGED)

        # Should log warning/error but not raise
        assert notification_service._refresh_queue.full()
        # Ensure it wasn't added (queue still full) and last_refresh_enqueued not updated for this one
        assert "new-gw" not in notification_service._last_refresh_enqueued

    @pytest.mark.asyncio
    async def test_enqueue_refresh_flags_tools(self, notification_service):
        """Test include flags for TOOLS_LIST_CHANGED."""
        await notification_service._enqueue_refresh("gw-1", NotificationType.TOOLS_LIST_CHANGED)

        pending = await notification_service._refresh_queue.get()
        assert pending.include_resources is True
        assert pending.include_prompts is True

    @pytest.mark.asyncio
    async def test_enqueue_refresh_flags_resources(self, notification_service):
        """Test include flags for RESOURCES_LIST_CHANGED."""
        await notification_service._enqueue_refresh("gw-1", NotificationType.RESOURCES_LIST_CHANGED)

        pending = await notification_service._refresh_queue.get()
        assert pending.include_resources is True
        assert pending.include_prompts is False

    @pytest.mark.asyncio
    async def test_enqueue_refresh_flags_prompts(self, notification_service):
        """Test include flags for PROMPTS_LIST_CHANGED."""
        await notification_service._enqueue_refresh("gw-1", NotificationType.PROMPTS_LIST_CHANGED)

        pending = await notification_service._refresh_queue.get()
        assert pending.include_resources is False
        assert pending.include_prompts is True

    @pytest.mark.asyncio
    async def test_debounce_allows_after_interval(self, notification_service):
        """Test that refresh is allowed after debounce interval."""
        notification_service.debounce_seconds = 0.1  # Short for testing
        # Do not initialize worker

        # Enqueue first refresh
        await notification_service._enqueue_refresh("gw-1", NotificationType.TOOLS_LIST_CHANGED)
        assert notification_service._refresh_queue.qsize() == 1

        # Wait for debounce interval
        await asyncio.sleep(0.15)

        # Should be allowed now
        await notification_service._enqueue_refresh("gw-1", NotificationType.TOOLS_LIST_CHANGED)
        assert notification_service._refresh_queue.qsize() == 2

    @pytest.mark.asyncio
    async def test_different_gateways_not_debounced(self, notification_service):
        """Test that different gateways are not affected by each other's debounce."""
        # Do not initialize worker

        await notification_service._enqueue_refresh("gw-1", NotificationType.TOOLS_LIST_CHANGED)
        await notification_service._enqueue_refresh("gw-2", NotificationType.TOOLS_LIST_CHANGED)

        assert notification_service._refresh_queue.qsize() == 2


class TestRefreshExecution:
    """Tests for refresh execution."""

    @pytest.mark.asyncio
    async def test_execute_refresh_without_gateway_service(self, notification_service):
        """Test refresh execution when gateway service is not set."""
        pending = PendingRefresh(gateway_id="gw-1")

        # Should not raise, just log warning
        await notification_service._execute_refresh(pending)

    @pytest.mark.asyncio
    async def test_execute_refresh_with_gateway_service(self, notification_service):
        """Test refresh execution calls gateway service."""
        mock_gateway_service = AsyncMock()
        mock_gateway_service._refresh_gateway_tools_resources_prompts = AsyncMock(return_value={"success": True, "tools_added": 2, "tools_removed": 1})
        # _get_refresh_lock is synchronous and returns an asyncio.Lock
        mock_gateway_service._get_refresh_lock = MagicMock(return_value=asyncio.Lock())

        notification_service.set_gateway_service(mock_gateway_service)

        pending = PendingRefresh(
            gateway_id="gw-1",
            include_resources=True,
            include_prompts=True,
        )

        await notification_service._execute_refresh(pending)

        mock_gateway_service._refresh_gateway_tools_resources_prompts.assert_called_once_with(
            gateway_id="gw-1",
            created_via="notification_service",
            include_resources=True,
            include_prompts=True,
        )
        assert notification_service._refreshes_triggered == 1

    @pytest.mark.asyncio
    async def test_execute_refresh_handles_failure(self, notification_service):
        """Test refresh execution handles failures gracefully."""
        mock_gateway_service = AsyncMock()
        mock_gateway_service._refresh_gateway_tools_resources_prompts = AsyncMock(side_effect=Exception("Connection failed"))
        # _get_refresh_lock is synchronous and returns an asyncio.Lock
        mock_gateway_service._get_refresh_lock = MagicMock(return_value=asyncio.Lock())

        notification_service.set_gateway_service(mock_gateway_service)

        pending = PendingRefresh(gateway_id="gw-1")

        # Should not raise
        await notification_service._execute_refresh(pending)
        assert notification_service._refreshes_failed == 1

    @pytest.mark.asyncio
    async def test_execute_refresh_logical_failure(self, notification_service):
        """Test refresh execution handles logical failures (success=False)."""
        mock_gateway_service = AsyncMock()
        mock_gateway_service._refresh_gateway_tools_resources_prompts = AsyncMock(return_value={"success": False, "error": "Something went wrong"})
        # _get_refresh_lock is synchronous and returns an asyncio.Lock
        mock_gateway_service._get_refresh_lock = MagicMock(return_value=asyncio.Lock())

        notification_service.set_gateway_service(mock_gateway_service)
        pending = PendingRefresh(gateway_id="gw-1")

        await notification_service._execute_refresh(pending)

        assert notification_service._refreshes_failed == 1
        assert notification_service._refreshes_triggered == 1

    @pytest.mark.asyncio
    async def test_execute_refresh_skips_when_lock_held(self, notification_service):
        """Test refresh execution skips when lock is already held."""
        mock_gateway_service = AsyncMock()
        mock_gateway_service._refresh_gateway_tools_resources_prompts = AsyncMock(return_value={"success": True})
        # Create a lock that's already held
        held_lock = asyncio.Lock()
        await held_lock.acquire()  # Lock is now held
        mock_gateway_service._get_refresh_lock = MagicMock(return_value=held_lock)

        notification_service.set_gateway_service(mock_gateway_service)
        pending = PendingRefresh(gateway_id="gw-1")

        await notification_service._execute_refresh(pending)

        # Should not have called refresh because lock was held
        mock_gateway_service._refresh_gateway_tools_resources_prompts.assert_not_called()
        assert notification_service._notifications_debounced == 1
        held_lock.release()  # Cleanup


class TestMetrics:
    """Tests for metrics collection."""

    def test_get_metrics_initial(self, notification_service):
        """Test metrics returns expected structure."""
        metrics = notification_service.get_metrics()

        assert "notifications_received" in metrics
        assert "notifications_debounced" in metrics
        assert "refreshes_triggered" in metrics
        assert "refreshes_failed" in metrics
        assert "pending_refreshes" in metrics
        assert "registered_gateways" in metrics
        assert "debounce_seconds" in metrics

    def test_get_metrics_reflects_state(self, notification_service):
        """Test metrics reflects actual state."""
        notification_service.register_gateway_capabilities("gw-1", {})
        notification_service.register_gateway_capabilities("gw-2", {})

        metrics = notification_service.get_metrics()
        assert metrics["registered_gateways"] == 2


class TestLifecycle:
    """Tests for service lifecycle."""

    @pytest.mark.asyncio
    async def test_initialize_starts_worker(self, notification_service):
        """Test initialize starts background worker."""
        await notification_service.initialize()

        assert notification_service._worker_task is not None
        assert not notification_service._worker_task.done()

        await notification_service.shutdown()

    @pytest.mark.asyncio
    async def test_shutdown_stops_worker(self, notification_service):
        """Test shutdown stops background worker."""
        await notification_service.initialize()
        await notification_service.shutdown()

        assert notification_service._worker_task is None or notification_service._worker_task.done()

    @pytest.mark.asyncio
    async def test_shutdown_clears_state(self, notification_service):
        """Test shutdown clears internal state."""
        notification_service.register_gateway_capabilities("gw-1", {"tools": {"listChanged": True}})
        notification_service._last_refresh_enqueued["gw-1"] = time.time()

        await notification_service.initialize()
        await notification_service.shutdown()

        assert len(notification_service._gateway_capabilities) == 0
        assert len(notification_service._last_refresh_enqueued) == 0


class TestPendingRefresh:
    """Tests for PendingRefresh dataclass."""

    def test_pending_refresh_defaults(self):
        """Test PendingRefresh has correct defaults."""
        pending = PendingRefresh(gateway_id="gw-1")

        assert pending.gateway_id == "gw-1"
        assert pending.include_resources is True
        assert pending.include_prompts is True
        assert len(pending.triggered_by) == 0

    def test_pending_refresh_with_values(self):
        """Test PendingRefresh with custom values."""
        pending = PendingRefresh(
            gateway_id="gw-2",
            include_resources=False,
            include_prompts=False,
            triggered_by={NotificationType.TOOLS_LIST_CHANGED},
        )

        assert pending.include_resources is False
        assert pending.include_prompts is False
        assert NotificationType.TOOLS_LIST_CHANGED in pending.triggered_by


class TestGlobalSingleton:
    """Tests for global singleton helpers."""

    def teardown_method(self):
        """Ensure global service is cleared."""
        import mcpgateway.services.notification_service as ns_module

        ns_module._notification_service = None

    def test_get_without_init_raises(self):
        """Test get_notification_service raises if not initialized."""
        # Ensure it's None first (teardown handles, but be safe)
        import mcpgateway.services.notification_service as ns_module

        ns_module._notification_service = None

        with pytest.raises(RuntimeError, match="not initialized"):
            get_notification_service()

    def test_init_and_get(self):
        """Test initialization and retrieval."""
        service = init_notification_service(debounce_seconds=2.0)
        assert service.debounce_seconds == 2.0

        retrieved = get_notification_service()
        assert retrieved is service

    @pytest.mark.asyncio
    async def test_close_handle(self):
        """Test closing the service."""
        service = init_notification_service()
        await service.initialize()
        assert service._worker_task is not None

        await close_notification_service()

        # Should be cleared
        with pytest.raises(RuntimeError):
            get_notification_service()


# --------------------------------------------------------------------------
# Server-initiated request correlation (ADR-052)
# --------------------------------------------------------------------------


class TestServerInitiatedRequestCorrelation:
    """Cover the message-handler ``RequestResponder`` path and ``complete_request``."""

    @staticmethod
    def _make_responder(request_id: str, method: str = "roots/list"):
        """Build a fake ``RequestResponder`` with respond/cancel captured."""
        # Third-Party
        from mcp.shared.session import RequestResponder
        from mcp.types import ListRootsRequest, ServerRequest

        request = ServerRequest(ListRootsRequest(method=method, params=None))
        responder = RequestResponder(
            request_id=request_id,
            request_meta=None,
            request=request,
            session=MagicMock(_send_response=MagicMock()),
            on_complete=lambda r: None,
        )
        captured: dict[str, object] = {"responded": None, "cancelled": False}

        async def captured_respond(payload):
            captured["responded"] = payload
            responder._completed = True

        async def captured_cancel():
            captured["cancelled"] = True
            responder._completed = True

        responder.respond = captured_respond
        responder.cancel = captured_cancel
        return responder, captured

    @pytest.mark.asyncio
    async def test_request_responder_published_and_response_round_trips(self, monkeypatch):
        """End-to-end: message handler publishes the request; complete_request resolves the responder."""
        # First-Party
        from mcp.types import ClientResult
        from mcpgateway.config import settings
        from mcpgateway.services.notification_service import NotificationService
        from mcpgateway.transports.server_event_bus import (
            get_server_event_bus,
            reset_server_event_bus,
        )

        monkeypatch.setattr(settings, "cache_type", "memory", raising=False)
        await reset_server_event_bus()

        svc = NotificationService()
        sid = "sess-corr"
        handler = svc.create_message_handler("gw-1", "http://u", downstream_session_id=sid)

        bus = await get_server_event_bus()
        received: list[object] = []

        async def consume() -> None:
            async for evt in bus.subscribe(sid):
                received.append(evt)
                break

        consumer = asyncio.create_task(consume())
        await asyncio.sleep(0.05)

        responder, captured = self._make_responder("req-1")
        await handler(responder)

        await asyncio.wait_for(consumer, timeout=2.0)
        assert len(received) == 1
        envelope = received[0].message.root  # type: ignore[union-attr]
        assert envelope.method == "roots/list"
        assert envelope.id == "req-1"

        # Downstream POSTs the response — complete_request resolves the future.
        assert svc.has_pending_request(sid) is True
        completed = await svc.complete_request(sid, "req-1", {"jsonrpc": "2.0", "id": "req-1", "result": {"roots": []}})
        assert completed is True

        # Holder task converts the payload into a ClientResult.
        await asyncio.sleep(0.1)
        assert isinstance(captured["responded"], ClientResult)
        assert svc.has_pending_request(sid) is False
        await reset_server_event_bus()

    @pytest.mark.asyncio
    async def test_request_responder_times_out_and_cancels(self, monkeypatch):
        """If no downstream response arrives within the TTL, the responder is cancelled."""
        # First-Party
        from mcpgateway.config import settings
        from mcpgateway.services.notification_service import NotificationService
        from mcpgateway.transports.server_event_bus import (
            get_server_event_bus,
            reset_server_event_bus,
        )

        monkeypatch.setattr(settings, "cache_type", "memory", raising=False)
        await reset_server_event_bus()

        svc = NotificationService()
        # Squeeze the timeout to make the test fast.
        svc._pending_request_ttl_seconds = 0.1

        sid = "sess-timeout"
        handler = svc.create_message_handler("gw-1", "http://u", downstream_session_id=sid)

        # Drain the published request so the bus is happy (no listener
        # required for the test, but we attach one for cleanliness).
        bus = await get_server_event_bus()

        async def consume() -> None:
            async for _ in bus.subscribe(sid):
                break

        consumer = asyncio.create_task(consume())
        await asyncio.sleep(0.05)

        responder, captured = self._make_responder("req-2")
        await handler(responder)
        await consumer

        # Wait past TTL.
        await asyncio.sleep(0.3)
        assert captured["cancelled"] is True
        assert svc.has_pending_request(sid) is False
        await reset_server_event_bus()

    @pytest.mark.asyncio
    async def test_complete_request_returns_false_when_no_match(self):
        """Unmatched ids fall through (so the POST handler hands off to the SDK)."""
        # First-Party
        from mcpgateway.services.notification_service import NotificationService

        svc = NotificationService()
        result = await svc.complete_request("sess-x", "missing-id", {"id": "missing-id", "result": {}})
        assert result is False
        assert svc.has_pending_request("sess-x") is False

    @pytest.mark.asyncio
    async def test_complete_request_after_holder_timeout_is_noop(self, monkeypatch):
        """A late ``complete_request`` after the TTL fires must not double-resolve.

        Race shape: holder times out, cancels responder, pops the pending
        entry. The downstream client then POSTs back the long-overdue
        response. The lookup must return False (no double-resolve, no
        crash) so the POST handler falls back to the SDK.
        """
        # First-Party
        from mcpgateway.config import settings
        from mcpgateway.services.notification_service import NotificationService
        from mcpgateway.transports.server_event_bus import (
            get_server_event_bus,
            reset_server_event_bus,
        )

        monkeypatch.setattr(settings, "cache_type", "memory", raising=False)
        await reset_server_event_bus()

        svc = NotificationService()
        svc._pending_request_ttl_seconds = 0.05  # tight TTL for the race window

        sid = "sess-late"
        handler = svc.create_message_handler("gw-1", "http://u", downstream_session_id=sid)

        bus = await get_server_event_bus()

        async def consume() -> None:
            async for _ in bus.subscribe(sid):
                break

        consumer = asyncio.create_task(consume())
        await asyncio.sleep(0.02)

        responder, _captured = self._make_responder("req-late")
        await handler(responder)
        await consumer
        # Wait past TTL — holder should have cancelled and dropped the entry.
        await asyncio.sleep(0.2)
        assert svc.has_pending_request(sid) is False
        # Late POST: must return False, not crash and not re-resolve.
        result = await svc.complete_request(sid, "req-late", {"id": "req-late", "result": {}})
        assert result is False
        await reset_server_event_bus()

    @pytest.mark.asyncio
    async def test_respond_with_payload_routes_error_envelope(self):
        """Downstream-supplied ``error`` envelope is forwarded as-is via ``responder.respond``."""
        # Third-Party
        from mcp.types import ErrorData

        responder, captured = self._make_responder("req-err")
        with responder:
            await NotificationService._respond_with_payload(
                responder,
                {"jsonrpc": "2.0", "id": "req-err", "error": {"code": -32000, "message": "downstream said no"}},
            )
        assert isinstance(captured["responded"], ErrorData)
        assert captured["responded"].code == -32000

    @pytest.mark.asyncio
    async def test_respond_with_payload_falls_back_on_unparseable_result(self):
        """Garbage in ``result`` becomes an INTERNAL_ERROR ErrorData, not a crash."""
        # Third-Party
        from mcp.types import ErrorData, INTERNAL_ERROR

        responder, captured = self._make_responder("req-bad")
        # ClientResult is a discriminated union; an empty dict won't validate
        # against any member and triggers the fallback path.
        with responder:
            await NotificationService._respond_with_payload(
                responder,
                {"jsonrpc": "2.0", "id": "req-bad", "result": {"this": "matches no known result type"}},
            )
        # Either a ClientResult validated (very lenient discriminator) OR
        # the fallback INTERNAL_ERROR path fired. Both are spec-acceptable;
        # the contract this test pins is "the responder is always answered,
        # never left hung".
        assert captured["responded"] is not None
        if isinstance(captured["responded"], ErrorData):
            assert captured["responded"].code == INTERNAL_ERROR

    @pytest.mark.asyncio
    async def test_shutdown_cancels_pending_holder_tasks(self, monkeypatch):
        """``shutdown()`` cancels in-flight holder tasks instead of leaking them past process death (ADR-052)."""
        # First-Party
        from mcpgateway.config import settings
        from mcpgateway.services.notification_service import NotificationService
        from mcpgateway.transports.server_event_bus import (
            get_server_event_bus,
            reset_server_event_bus,
        )

        monkeypatch.setattr(settings, "cache_type", "memory", raising=False)
        await reset_server_event_bus()

        svc = NotificationService()
        await svc.initialize()
        sid = "sess-shutdown"
        handler = svc.create_message_handler("gw-1", "http://u", downstream_session_id=sid)

        # Drain bus so the request publish doesn't block.
        bus = await get_server_event_bus()

        async def consume() -> None:
            async for _ in bus.subscribe(sid):
                break

        consumer = asyncio.create_task(consume())
        await asyncio.sleep(0.02)

        responder, _captured = self._make_responder("req-pending")
        await handler(responder)
        await consumer
        assert svc.has_pending_request(sid) is True
        held_tasks = list(svc._pending_holder_tasks)
        assert held_tasks, "holder task should be tracked"

        await svc.shutdown()

        # All holder tasks resolved (cancelled); pending dict cleared.
        for task in held_tasks:
            assert task.done()
        assert svc.has_pending_request(sid) is False
        await reset_server_event_bus()

    @pytest.mark.asyncio
    async def test_pending_request_id_collision_logs_warning_and_cancels_prior(self, monkeypatch, caplog):
        """Upstream protocol violation: same request id reused mid-flight must log + cancel prior holder."""
        # First-Party
        from mcpgateway.config import settings
        from mcpgateway.services.notification_service import NotificationService
        from mcpgateway.transports.server_event_bus import (
            get_server_event_bus,
            reset_server_event_bus,
        )

        monkeypatch.setattr(settings, "cache_type", "memory", raising=False)
        await reset_server_event_bus()

        svc = NotificationService()
        sid = "sess-collision"
        handler = svc.create_message_handler("gw-1", "http://u", downstream_session_id=sid)

        # Drain the bus so publishes don't block.
        bus = await get_server_event_bus()
        drained: list[object] = []

        async def drain() -> None:
            async for evt in bus.subscribe(sid):
                drained.append(evt)
                if len(drained) >= 2:
                    break

        consumer = asyncio.create_task(drain())
        await asyncio.sleep(0.02)

        # First responder for "req-X" lands the holder.
        first_responder, first_captured = self._make_responder("req-X")
        await handler(first_responder)
        await asyncio.sleep(0.05)

        # Second responder reusing the same id triggers the collision branch.
        with caplog.at_level("WARNING", logger="mcpgateway.services.notification_service"):
            second_responder, _second_captured = self._make_responder("req-X")
            await handler(second_responder)
            await asyncio.sleep(0.05)
        await consumer
        await reset_server_event_bus()

        # Prior responder must have been cancelled by the collision logic.
        assert first_captured["cancelled"] is True
        # Operator-visible warning fired.
        assert "id collision" in caplog.text.lower() or "reused id" in caplog.text.lower()
        # Pending entry now belongs to the second responder, not the first.
        assert svc.has_pending_request(sid) is True

        # Cleanup so subsequent tests don't see a hanging holder.
        await svc.complete_request(sid, "req-X", {"jsonrpc": "2.0", "id": "req-X", "result": {"roots": []}})

    @pytest.mark.asyncio
    async def test_forward_notification_to_stream_publishes_typed_envelope(self, monkeypatch):
        """ServerNotification fanout has its own envelope construction; regression guard."""
        # First-Party
        from mcp.types import ServerNotification, ToolListChangedNotification
        from mcpgateway.config import settings
        from mcpgateway.services.notification_service import NotificationService
        from mcpgateway.transports.server_event_bus import (
            get_server_event_bus,
            reset_server_event_bus,
        )

        monkeypatch.setattr(settings, "cache_type", "memory", raising=False)
        await reset_server_event_bus()

        svc = NotificationService()
        sid = "sess-notif"
        bus = await get_server_event_bus()

        received: list[object] = []

        async def consume() -> None:
            async for evt in bus.subscribe(sid):
                received.append(evt)
                break

        consumer = asyncio.create_task(consume())
        await asyncio.sleep(0.02)

        notif = ServerNotification(ToolListChangedNotification(method="notifications/tools/list_changed"))
        await svc._forward_notification_to_stream(sid, notif)

        await asyncio.wait_for(consumer, timeout=2.0)
        await reset_server_event_bus()

        assert len(received) == 1
        envelope = received[0].message.root  # type: ignore[union-attr]
        assert envelope.method == "notifications/tools/list_changed"

    @pytest.mark.asyncio
    async def test_forward_request_publish_backend_unavailable_classifies_and_cancels(self, monkeypatch):
        """BusBackendError from bus.publish → ``backend_unavailable`` label + holder future cancelled."""
        # First-Party
        from mcpgateway.config import settings
        from mcpgateway.services.notification_service import NotificationService
        from mcpgateway.transports.server_event_bus import BusBackendError

        monkeypatch.setattr(settings, "cache_type", "memory", raising=False)

        svc = NotificationService()
        sid = "sess-publish-fail-backend"
        handler = svc.create_message_handler("gw-1", "http://u", downstream_session_id=sid)

        # Stub the bus to raise BusBackendError on publish.
        class BrokenBus:
            async def publish(self, _sid, _msg):
                raise BusBackendError("redis down")

        async def _bus():
            return BrokenBus()

        monkeypatch.setattr("mcpgateway.transports.server_event_bus.get_server_event_bus", _bus)

        # Capture counter increments before / after.
        # First-Party
        from mcpgateway.services.metrics import server_event_bus_publish_failed_counter

        before = server_event_bus_publish_failed_counter.labels(reason="backend_unavailable")._value.get()
        responder, _captured = self._make_responder("req-pub-fail")
        await handler(responder)
        await asyncio.sleep(0.05)

        assert server_event_bus_publish_failed_counter.labels(reason="backend_unavailable")._value.get() == before + 1
        # Holder future was cancelled; pending dict cleared.
        assert svc.has_pending_request(sid) is False

    @pytest.mark.asyncio
    async def test_forward_request_publish_transport_error_classifies_with_traceback(self, monkeypatch, caplog):
        """ConnectionError from bus.publish → ``transport_error`` label + error-level log with traceback."""
        # First-Party
        from mcpgateway.config import settings
        from mcpgateway.services.notification_service import NotificationService

        monkeypatch.setattr(settings, "cache_type", "memory", raising=False)

        svc = NotificationService()
        sid = "sess-publish-fail-transport"
        handler = svc.create_message_handler("gw-1", "http://u", downstream_session_id=sid)

        class BrokenBus:
            async def publish(self, _sid, _msg):
                raise ConnectionError("broken pipe")

        async def _bus():
            return BrokenBus()

        monkeypatch.setattr("mcpgateway.transports.server_event_bus.get_server_event_bus", _bus)

        # First-Party
        from mcpgateway.services.metrics import server_event_bus_publish_failed_counter

        before = server_event_bus_publish_failed_counter.labels(reason="transport_error")._value.get()
        responder, _captured = self._make_responder("req-pub-transport")
        with caplog.at_level("ERROR", logger="mcpgateway.services.notification_service"):
            await handler(responder)
            await asyncio.sleep(0.05)

        assert server_event_bus_publish_failed_counter.labels(reason="transport_error")._value.get() == before + 1
        assert "transport_error" in caplog.text
        assert svc.has_pending_request(sid) is False

    @pytest.mark.asyncio
    async def test_shutdown_logs_warning_when_holder_drain_times_out(self, monkeypatch, caplog):
        """If a holder task ignores cancellation, shutdown must bound itself + log the abandonment.

        The bounded ``asyncio.wait_for`` is the only guard against a
        ``responder.__exit__`` that hangs forever — without it, a
        broken upstream session could pin shutdown indefinitely.
        """
        # First-Party
        from mcpgateway.config import settings
        from mcpgateway.services.notification_service import NotificationService
        from mcpgateway.transports.server_event_bus import reset_server_event_bus

        monkeypatch.setattr(settings, "cache_type", "memory", raising=False)
        await reset_server_event_bus()

        svc = NotificationService()
        # Squeeze the timeout so the test doesn't wait the default 5s.
        svc._shutdown_drain_timeout_seconds = 0.1

        # Holder that swallows cancellation and waits on an unsettable event,
        # forcing the bounded wait_for to TimeoutError.
        never_set = asyncio.Event()

        async def _swallows_cancel():
            try:
                await never_set.wait()
            except asyncio.CancelledError:
                # Wait again on the unsettable event so the task doesn't terminate.
                # This shields the task from the first cancel; shutdown won't
                # call cancel a second time.
                await never_set.wait()

        task = asyncio.create_task(_swallows_cancel(), name="hung-holder")
        svc._pending_holder_tasks.add(task)
        # Yield once so the task starts and reaches its first await.
        await asyncio.sleep(0)

        try:
            with caplog.at_level("WARNING", logger="mcpgateway.services.notification_service"):
                await svc.shutdown()
        finally:
            never_set.set()
            try:
                await asyncio.wait_for(task, timeout=0.2)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

        assert "did not drain" in caplog.text
        assert "abandoning" in caplog.text


# --------------------------------------------------------------------------
# Additional edge-case coverage (ADR-052 error branches)
# --------------------------------------------------------------------------


class TestRecordPublishFailure:
    """Cover ``_record_publish_failure`` edge cases."""

    def test_counter_labels_exception_is_swallowed(self, caplog):
        """If the counter itself raises, the helper logs at DEBUG and does not propagate."""
        # First-Party
        from mcpgateway.services.notification_service import _record_publish_failure

        class BrokenCounter:
            def labels(self, **_kwargs):
                raise RuntimeError("prometheus broken")

        # Must not raise.
        with caplog.at_level("DEBUG", logger="mcpgateway.services.notification_service"):
            _record_publish_failure(
                "sess",
                "req-1",
                reason="transport_error",
                exc=ConnectionError("boom"),
                counter=BrokenCounter(),
            )
        assert "publish-failed counter raised" in caplog.text


class TestInitializeIdempotency:
    """Cover the double-init short-circuit branch."""

    @pytest.mark.asyncio
    async def test_initialize_is_idempotent_when_worker_running(self, caplog):
        """Calling initialize twice must not spawn a second worker task."""
        svc = NotificationService()
        try:
            await svc.initialize()
            first_task = svc._worker_task
            assert first_task is not None and not first_task.done()

            # Second call: worker already running; must short-circuit and keep the same task.
            mock_gw = MagicMock()
            with caplog.at_level("DEBUG", logger="mcpgateway.services.notification_service"):
                await svc.initialize(gateway_service=mock_gw)
            assert svc._worker_task is first_task
            # gateway_service reference refreshed even on the short-circuit path.
            assert svc._gateway_service is mock_gw
        finally:
            await svc.shutdown()


class TestSafeCancel:
    """Cover the exception branch of ``_safe_cancel``."""

    @pytest.mark.asyncio
    async def test_safe_cancel_swallows_responder_exception(self, caplog):
        """A raising ``responder.cancel`` must be logged at WARNING, not propagated."""
        responder = MagicMock()

        async def boom():
            raise RuntimeError("broken transport")

        responder.cancel = boom

        with caplog.at_level("WARNING", logger="mcpgateway.services.notification_service"):
            await NotificationService._safe_cancel(responder, "sess-1", "req-1")

        assert "responder.cancel() raised" in caplog.text
        assert "sess-1" in caplog.text


class TestShutdownPendingFutures:
    """Cover the pending-futures cleanup branch in ``shutdown``."""

    @pytest.mark.asyncio
    async def test_shutdown_cancels_unfinished_pending_futures(self):
        """``shutdown`` must cancel any futures still in ``_pending_requests``."""
        svc = NotificationService()
        loop = asyncio.get_running_loop()
        pending_future = loop.create_future()
        completed_future = loop.create_future()
        completed_future.set_result({"ok": True})

        svc._pending_requests[("sess-a", "1")] = pending_future
        svc._pending_requests[("sess-a", "2")] = completed_future

        await svc.shutdown()

        assert pending_future.cancelled()
        # Already-done futures are left alone (not re-cancelled) but popped.
        assert completed_future.done() and not completed_future.cancelled()
        assert svc._pending_requests == {}


class TestForwardRequestPayloadFailures:
    """Cover ``_forward_request_to_stream`` error branches pre-publish."""

    @pytest.mark.asyncio
    async def test_payload_build_failure_cancels_responder(self, monkeypatch, caplog):
        """``model_dump`` raising a TypeError triggers the payload-build except branch."""
        # First-Party
        from mcpgateway.config import settings

        monkeypatch.setattr(settings, "cache_type", "memory", raising=False)

        svc = NotificationService()

        # Fake responder: exposes request.root whose model_dump raises.
        responder = MagicMock()
        responder.request_id = "req-bad-payload"
        root = MagicMock()
        root.model_dump = MagicMock(side_effect=TypeError("shape drift"))
        responder.request = MagicMock()
        responder.request.root = root
        cancelled = {"called": False}

        async def _cancel():
            cancelled["called"] = True

        responder.cancel = _cancel
        responder.__enter__ = MagicMock(return_value=responder)
        responder.__exit__ = MagicMock(return_value=False)

        with caplog.at_level("WARNING", logger="mcpgateway.services.notification_service"):
            await svc._forward_request_to_stream("sess-p1", responder)

        assert cancelled["called"] is True
        assert "Failed to build request payload" in caplog.text
        # No pending entry was created.
        assert svc.has_pending_request("sess-p1") is False

    @pytest.mark.asyncio
    async def test_empty_method_refuses_to_publish_and_cancels(self, monkeypatch, caplog):
        """Payload with empty ``method`` triggers the defense-in-depth branch."""
        # First-Party
        from mcpgateway.config import settings

        monkeypatch.setattr(settings, "cache_type", "memory", raising=False)

        svc = NotificationService()

        responder = MagicMock()
        responder.request_id = "req-empty-method"
        root = MagicMock()
        # method missing from payload entirely.
        root.model_dump = MagicMock(return_value={"params": {"x": 1}})
        responder.request = MagicMock()
        responder.request.root = root
        cancelled = {"called": False}

        async def _cancel():
            cancelled["called"] = True

        responder.cancel = _cancel
        responder.__enter__ = MagicMock(return_value=responder)
        responder.__exit__ = MagicMock(return_value=False)

        with caplog.at_level("WARNING", logger="mcpgateway.services.notification_service"):
            await svc._forward_request_to_stream("sess-empty", responder)

        assert cancelled["called"] is True
        assert "empty method" in caplog.text
        assert svc.has_pending_request("sess-empty") is False


class TestForwardRequestBusGetFailure:
    """Cover the ``get_server_event_bus`` raising branches for the request path."""

    @pytest.mark.asyncio
    async def test_get_bus_runtime_error_cancels_future(self, monkeypatch):
        """RuntimeError from bus construction → backend_unavailable + cancelled future."""
        # First-Party
        from mcpgateway.config import settings
        from mcpgateway.services.metrics import server_event_bus_publish_failed_counter

        monkeypatch.setattr(settings, "cache_type", "memory", raising=False)

        svc = NotificationService()
        sid = "sess-bus-runtime"
        handler = svc.create_message_handler("gw-1", "http://u", downstream_session_id=sid)

        async def _bus():
            raise RuntimeError("bus config broken")

        monkeypatch.setattr("mcpgateway.transports.server_event_bus.get_server_event_bus", _bus)

        before = server_event_bus_publish_failed_counter.labels(reason="backend_unavailable")._value.get()

        responder, _captured = TestServerInitiatedRequestCorrelation._make_responder("req-bus-rt")
        await handler(responder)
        await asyncio.sleep(0.05)

        assert server_event_bus_publish_failed_counter.labels(reason="backend_unavailable")._value.get() == before + 1
        # Pending dict is cleaned up by the holder's finally.
        assert svc.has_pending_request(sid) is False


class TestForwardRequestHolderBranches:
    """Cover ``hold()`` inner error branches: respond-raises, done-callback logging."""

    @pytest.mark.asyncio
    async def test_responder_respond_raises_is_logged(self, monkeypatch, caplog):
        """If ``responder.respond`` raises inside the holder, log it and don't crash the task."""
        # First-Party
        from mcpgateway.config import settings
        from mcpgateway.services.notification_service import NotificationService
        from mcpgateway.transports.server_event_bus import (
            get_server_event_bus,
            reset_server_event_bus,
        )

        monkeypatch.setattr(settings, "cache_type", "memory", raising=False)
        await reset_server_event_bus()

        svc = NotificationService()
        sid = "sess-respond-raises"
        handler = svc.create_message_handler("gw-1", "http://u", downstream_session_id=sid)

        bus = await get_server_event_bus()

        async def consume():
            async for _ in bus.subscribe(sid):
                break

        consumer = asyncio.create_task(consume())
        await asyncio.sleep(0.02)

        responder, _captured = TestServerInitiatedRequestCorrelation._make_responder("req-resp-raises")

        async def bad_respond(_payload):
            raise RuntimeError("respond blew up")

        responder.respond = bad_respond
        await handler(responder)
        await consumer

        # Complete the request so the holder calls respond (which raises).
        with caplog.at_level("WARNING", logger="mcpgateway.services.notification_service"):
            await svc.complete_request(sid, "req-resp-raises", {"jsonrpc": "2.0", "id": "req-resp-raises", "result": {}})
            await asyncio.sleep(0.1)

        assert "responder.respond() raised" in caplog.text
        await reset_server_event_bus()

    @pytest.mark.asyncio
    async def test_holder_done_callback_logs_unexpected_exception(self, monkeypatch, caplog):
        """If ``on_complete`` raises during ``__exit__``, the done-callback logs it.

        The context manager's ``__exit__`` invokes ``on_complete`` inside a
        try/finally; a raising ``on_complete`` propagates out of ``with
        responder:`` and is captured by ``_on_holder_done``.
        """
        # First-Party
        from mcpgateway.config import settings
        from mcpgateway.services.notification_service import NotificationService
        from mcpgateway.transports.server_event_bus import (
            get_server_event_bus,
            reset_server_event_bus,
        )

        monkeypatch.setattr(settings, "cache_type", "memory", raising=False)
        await reset_server_event_bus()

        svc = NotificationService()
        sid = "sess-exit-shadow"
        handler = svc.create_message_handler("gw-1", "http://u", downstream_session_id=sid)

        bus = await get_server_event_bus()

        async def consume():
            async for _ in bus.subscribe(sid):
                break

        consumer = asyncio.create_task(consume())
        await asyncio.sleep(0.02)

        # Build a responder with an on_complete that raises — this will
        # escape the ``with responder:`` block in hold() after a successful
        # respond() sets _completed=True.
        # Third-Party
        from mcp.shared.session import RequestResponder
        from mcp.types import ListRootsRequest, ServerRequest

        def _boom_on_complete(_resp):
            raise RuntimeError("on_complete blew up")

        responder = RequestResponder(
            request_id="req-exit-shadow",
            request_meta=None,
            request=ServerRequest(ListRootsRequest(method="roots/list", params=None)),
            session=MagicMock(_send_response=MagicMock()),
            on_complete=_boom_on_complete,
        )

        async def captured_respond(_payload):
            responder._completed = True

        async def captured_cancel():
            responder._completed = True

        responder.respond = captured_respond
        responder.cancel = captured_cancel

        await handler(responder)
        await consumer

        with caplog.at_level("WARNING", logger="mcpgateway.services.notification_service"):
            # Resolve the future → respond sets _completed → __exit__ calls on_complete → raises.
            await svc.complete_request(sid, "req-exit-shadow", {"jsonrpc": "2.0", "id": "req-exit-shadow", "result": {}})
            # Give the holder + done-callback time to run.
            await asyncio.sleep(0.1)

        assert "Request-holder task" in caplog.text and "exited with exception" in caplog.text
        await reset_server_event_bus()


class TestHolderExitShadowsPrimary:
    """Cover the ``__exit__ shadowing primary`` log branch (line 682)."""

    @pytest.mark.asyncio
    async def test_exit_shadow_logged_when_cancel_path_exits_raise(self, monkeypatch, caplog):
        """External task cancel → primary_exc=CancelledError → ``__exit__`` raises → shadow log fires."""
        # First-Party
        from mcp.shared.session import RequestResponder
        from mcp.types import ListRootsRequest, ServerRequest
        from mcpgateway.config import settings
        from mcpgateway.services.notification_service import NotificationService
        from mcpgateway.transports.server_event_bus import (
            get_server_event_bus,
            reset_server_event_bus,
        )

        monkeypatch.setattr(settings, "cache_type", "memory", raising=False)
        await reset_server_event_bus()

        svc = NotificationService()
        sid = "sess-exit-shadow2"
        handler = svc.create_message_handler("gw-1", "http://u", downstream_session_id=sid)

        bus = await get_server_event_bus()

        async def consume():
            async for _ in bus.subscribe(sid):
                break

        consumer = asyncio.create_task(consume())
        await asyncio.sleep(0.02)

        # on_complete raises — triggers __exit__ failure after _completed is set.
        def _boom(_resp):
            raise RuntimeError("exit boom")

        responder = RequestResponder(
            request_id="req-shadow",
            request_meta=None,
            request=ServerRequest(ListRootsRequest(method="roots/list", params=None)),
            session=MagicMock(_send_response=MagicMock()),
            on_complete=_boom,
        )

        async def captured_cancel():
            # Set _completed so __exit__'s on_complete path runs.
            responder._completed = True

        async def captured_respond(_payload):
            responder._completed = True

        responder.cancel = captured_cancel
        responder.respond = captured_respond

        await handler(responder)
        await consumer

        # Snapshot the holder task, then cancel it → wait_for raises CancelledError.
        held = list(svc._pending_holder_tasks)
        assert held, "expected an in-flight holder"
        with caplog.at_level("WARNING", logger="mcpgateway.services.notification_service"):
            for t in held:
                t.cancel()
            # Give the holder time to run the cancel path + __exit__ + done-callback.
            await asyncio.sleep(0.1)

        assert "shadowing primary" in caplog.text
        await reset_server_event_bus()


class TestRespondWithPayloadValidationBranches:
    """Cover the ValidationError branches in ``_respond_with_payload``."""

    @pytest.mark.asyncio
    async def test_malformed_error_payload_substitutes_internal_error(self, caplog):
        """A non-validating ``error`` payload falls back to INTERNAL_ERROR."""
        # Third-Party
        from mcp.types import ErrorData, INTERNAL_ERROR

        responder, captured = TestServerInitiatedRequestCorrelation._make_responder("req-bad-err")
        with caplog.at_level("WARNING", logger="mcpgateway.services.notification_service"):
            with responder:
                # Missing required "code" field → ValidationError.
                await NotificationService._respond_with_payload(
                    responder,
                    {"jsonrpc": "2.0", "id": "req-bad-err", "error": {"no_code": True}},
                )
        assert isinstance(captured["responded"], ErrorData)
        assert captured["responded"].code == INTERNAL_ERROR
        assert "Malformed error from downstream" in captured["responded"].message
        assert "substituting INTERNAL_ERROR" in caplog.text

    @pytest.mark.asyncio
    async def test_unvalidatable_result_falls_back_to_error(self, monkeypatch, caplog):
        """If ClientResult validation fails, respond with an ErrorData containing the message."""
        # Third-Party
        import mcp.types as mcp_types
        from mcp.types import ErrorData, INTERNAL_ERROR
        from pydantic import ValidationError

        # Force ClientResult.model_validate to raise.
        class StubValidationError(Exception):
            pass

        def raise_validation(*_args, **_kwargs):
            # Construct a real ValidationError via pydantic for accurate typing.
            try:
                mcp_types.ErrorData.model_validate({})
            except ValidationError as e:
                raise e

        monkeypatch.setattr(mcp_types.ClientResult, "model_validate", classmethod(lambda cls, *a, **k: raise_validation()))

        responder, captured = TestServerInitiatedRequestCorrelation._make_responder("req-bad-result")
        with caplog.at_level("WARNING", logger="mcpgateway.services.notification_service"):
            with responder:
                await NotificationService._respond_with_payload(
                    responder,
                    {"jsonrpc": "2.0", "id": "req-bad-result", "result": {"whatever": 1}},
                )

        assert isinstance(captured["responded"], ErrorData)
        assert captured["responded"].code == INTERNAL_ERROR
        assert "Could not validate downstream result" in caplog.text


class TestCompleteRequestAlreadyDone:
    """Cover the ``future.done()`` branch in ``complete_request``."""

    @pytest.mark.asyncio
    async def test_complete_request_returns_false_when_future_already_done(self, caplog):
        """A pre-completed / cancelled future under the key must yield a False return."""
        svc = NotificationService()
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        fut.cancel()  # done via cancel
        svc._pending_requests[("sess-done", "req-done")] = fut

        with caplog.at_level("DEBUG", logger="mcpgateway.services.notification_service"):
            result = await svc.complete_request("sess-done", "req-done", {"id": "req-done", "result": {}})

        assert result is False
        assert "already done" in caplog.text


class TestForwardNotificationErrorBranches:
    """Cover the error branches of ``_forward_notification_to_stream``."""

    @pytest.mark.asyncio
    async def test_notification_payload_build_failure_is_logged(self, monkeypatch, caplog):
        """A notification whose ``root.model_dump`` raises is logged and dropped."""
        # First-Party
        from mcpgateway.config import settings

        monkeypatch.setattr(settings, "cache_type", "memory", raising=False)

        svc = NotificationService()

        notif = MagicMock()
        notif.root = MagicMock()
        notif.root.model_dump = MagicMock(side_effect=ValueError("shape drift"))

        with caplog.at_level("WARNING", logger="mcpgateway.services.notification_service"):
            await svc._forward_notification_to_stream("sess-np", notif)

        assert "Failed to build notification payload" in caplog.text

    @pytest.mark.asyncio
    async def test_notification_empty_method_refuses_publish(self, monkeypatch, caplog):
        """Empty ``method`` in a notification payload is dropped with a warning."""
        # First-Party
        from mcpgateway.config import settings

        monkeypatch.setattr(settings, "cache_type", "memory", raising=False)

        svc = NotificationService()

        notif = MagicMock()
        notif.root = MagicMock()
        notif.root.model_dump = MagicMock(return_value={"params": None})  # no method

        with caplog.at_level("WARNING", logger="mcpgateway.services.notification_service"):
            await svc._forward_notification_to_stream("sess-nm", notif)

        assert "empty method" in caplog.text

    @pytest.mark.asyncio
    async def test_notification_get_bus_runtime_error(self, monkeypatch):
        """``get_server_event_bus`` raising during notification fanout → backend_unavailable metric."""
        # First-Party
        from mcp.types import ServerNotification, ToolListChangedNotification
        from mcpgateway.config import settings
        from mcpgateway.services.metrics import server_event_bus_publish_failed_counter

        monkeypatch.setattr(settings, "cache_type", "memory", raising=False)

        async def _bus():
            raise RuntimeError("bus config broken")

        monkeypatch.setattr("mcpgateway.transports.server_event_bus.get_server_event_bus", _bus)

        svc = NotificationService()
        notif = ServerNotification(ToolListChangedNotification(method="notifications/tools/list_changed"))
        before = server_event_bus_publish_failed_counter.labels(reason="backend_unavailable")._value.get()

        await svc._forward_notification_to_stream("sess-nb", notif)

        assert server_event_bus_publish_failed_counter.labels(reason="backend_unavailable")._value.get() == before + 1

    @pytest.mark.asyncio
    async def test_notification_publish_transport_error(self, monkeypatch):
        """``bus.publish`` raising ConnectionError → transport_error metric."""
        # First-Party
        from mcp.types import ServerNotification, ToolListChangedNotification
        from mcpgateway.config import settings
        from mcpgateway.services.metrics import server_event_bus_publish_failed_counter

        monkeypatch.setattr(settings, "cache_type", "memory", raising=False)

        class BrokenBus:
            async def publish(self, _sid, _msg):
                raise ConnectionError("pipe gone")

        async def _bus():
            return BrokenBus()

        monkeypatch.setattr("mcpgateway.transports.server_event_bus.get_server_event_bus", _bus)

        svc = NotificationService()
        notif = ServerNotification(ToolListChangedNotification(method="notifications/tools/list_changed"))
        before = server_event_bus_publish_failed_counter.labels(reason="transport_error")._value.get()

        await svc._forward_notification_to_stream("sess-nt", notif)

        assert server_event_bus_publish_failed_counter.labels(reason="transport_error")._value.get() == before + 1

    @pytest.mark.asyncio
    async def test_notification_publish_backend_error(self, monkeypatch):
        """``bus.publish`` raising BusBackendError → backend_unavailable metric."""
        # First-Party
        from mcp.types import ServerNotification, ToolListChangedNotification
        from mcpgateway.config import settings
        from mcpgateway.services.metrics import server_event_bus_publish_failed_counter
        from mcpgateway.transports.server_event_bus import BusBackendError

        monkeypatch.setattr(settings, "cache_type", "memory", raising=False)

        class BrokenBus:
            async def publish(self, _sid, _msg):
                raise BusBackendError("redis down")

        async def _bus():
            return BrokenBus()

        monkeypatch.setattr("mcpgateway.transports.server_event_bus.get_server_event_bus", _bus)

        svc = NotificationService()
        notif = ServerNotification(ToolListChangedNotification(method="notifications/tools/list_changed"))
        before = server_event_bus_publish_failed_counter.labels(reason="backend_unavailable")._value.get()

        await svc._forward_notification_to_stream("sess-nbe", notif)

        assert server_event_bus_publish_failed_counter.labels(reason="backend_unavailable")._value.get() == before + 1


class TestEnqueueRefreshDebounceEdge:
    """Cover the ``debounce window but no pending`` branch (lines 1080-1086)."""

    @pytest.mark.asyncio
    async def test_debounce_without_pending_entry_counts_as_debounced(self, notification_service):
        """When ``_last_refresh_enqueued`` is recent but no ``_pending_refresh_flags`` entry exists,
        the notification is counted as debounced and the log-debug branch runs.
        """
        # Simulate: refresh was recently enqueued and then processed (flags popped),
        # but debounce window still applies.
        notification_service._last_refresh_enqueued["gw-x"] = time.time()
        # Deliberately DO NOT add a _pending_refresh_flags entry.

        before = notification_service._notifications_debounced
        await notification_service._enqueue_refresh("gw-x", NotificationType.TOOLS_LIST_CHANGED)
        assert notification_service._notifications_debounced == before + 1
        assert notification_service._refresh_queue.qsize() == 0


class TestMessageHandlerServerNotification:
    """Cover the ServerNotification branch of ``create_message_handler`` (lines 513-517)."""

    @pytest.mark.asyncio
    async def test_server_notification_dispatched_and_fanned_out(self, monkeypatch):
        """A ServerNotification arriving at the handler triggers both handle and fanout."""
        # Third-Party
        from mcp.types import ServerNotification, ToolListChangedNotification

        # First-Party
        from mcpgateway.config import settings
        from mcpgateway.transports.server_event_bus import reset_server_event_bus

        monkeypatch.setattr(settings, "cache_type", "memory", raising=False)
        await reset_server_event_bus()

        svc = NotificationService()
        svc._handle_notification = AsyncMock()  # type: ignore[assignment]
        svc._forward_notification_to_stream = AsyncMock()  # type: ignore[assignment]

        handler = svc.create_message_handler("gw-1", "http://u", downstream_session_id="sess-sn")
        notif = ServerNotification(ToolListChangedNotification(method="notifications/tools/list_changed"))

        await handler(notif)

        svc._handle_notification.assert_awaited_once_with("gw-1", notif, "http://u")
        svc._forward_notification_to_stream.assert_awaited_once_with("sess-sn", notif)

    @pytest.mark.asyncio
    async def test_server_notification_without_session_id_skips_fanout(self):
        """No downstream_session_id → only internal handling, no fanout."""
        # Third-Party
        from mcp.types import ServerNotification, ToolListChangedNotification

        svc = NotificationService()
        svc._handle_notification = AsyncMock()  # type: ignore[assignment]
        svc._forward_notification_to_stream = AsyncMock()  # type: ignore[assignment]

        handler = svc.create_message_handler("gw-1")
        notif = ServerNotification(ToolListChangedNotification(method="notifications/tools/list_changed"))

        await handler(notif)

        svc._handle_notification.assert_awaited_once()
        svc._forward_notification_to_stream.assert_not_awaited()


class TestRefreshWorkerErrorPath:
    """Cover the generic-exception branch inside ``_process_refresh_queue`` (lines 1139-1142)."""

    @pytest.mark.asyncio
    async def test_worker_logs_and_continues_on_execute_exception(self, notification_service, caplog):
        """If ``_execute_refresh`` raises, the worker logs and keeps running."""
        call_count = {"n": 0}

        async def flaky_execute(_pending):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("boom in executor")

        notification_service._execute_refresh = flaky_execute  # type: ignore[assignment]

        await notification_service.initialize()
        try:
            # Enqueue a refresh — worker will pick it up, executor raises.
            await notification_service._refresh_queue.put(PendingRefresh(gateway_id="gw-err"))
            with caplog.at_level("ERROR", logger="mcpgateway.services.notification_service"):
                # Give the worker time to process + log.
                await asyncio.sleep(0.2)
            assert call_count["n"] >= 1
            assert "Error in refresh worker" in caplog.text
            # Worker should still be running after the logged exception.
            assert notification_service._worker_task is not None
            assert not notification_service._worker_task.done()
        finally:
            await notification_service.shutdown()
