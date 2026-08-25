# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_notification_service.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

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

        # In MCP v2 the notification is passed directly. The service matches
        # by ``type(notification_root).__name__`` — only a real class instance
        # can produce the right ``type().__name__`` (a MagicMock always reports
        # ``MagicMock``).
        class ToolListChangedNotification:
            method = "notifications/tools/list_changed"

        await notification_service._handle_notification("gw-1", ToolListChangedNotification())

        notification_service._enqueue_refresh.assert_called_once_with("gw-1", NotificationType.TOOLS_LIST_CHANGED)
        assert notification_service._notifications_received == 1

    @pytest.mark.asyncio
    async def test_handle_notification_resources(self, notification_service):
        """Test handling resources/list_changed notification."""
        notification_service._enqueue_refresh = AsyncMock()

        class ResourcesListChangedNotification:
            method = "notifications/resources/list_changed"

        await notification_service._handle_notification("gw-1", ResourcesListChangedNotification())

        notification_service._enqueue_refresh.assert_called_once_with("gw-1", NotificationType.RESOURCES_LIST_CHANGED)

    @pytest.mark.asyncio
    async def test_handle_notification_prompts(self, notification_service):
        """Test handling prompts/list_changed notification."""
        notification_service._enqueue_refresh = AsyncMock()

        class PromptsListChangedNotification:
            method = "notifications/prompts/list_changed"

        await notification_service._handle_notification("gw-1", PromptsListChangedNotification())

        notification_service._enqueue_refresh.assert_called_once_with("gw-1", NotificationType.PROMPTS_LIST_CHANGED)

    @pytest.mark.asyncio
    async def test_handle_notification_unknown(self, notification_service):
        """Test handling unknown notification type."""
        notification_service._enqueue_refresh = AsyncMock()

        class UnknownNotification:
            method = "notifications/unknown/things"

        await notification_service._handle_notification("gw-1", UnknownNotification())

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


class TestRespondWithPayloadValidationBranches:
    """Cover the ValidationError branches in ``_respond_with_payload``."""

    @pytest.mark.asyncio
    async def test_malformed_error_payload_substitutes_internal_error(self, caplog):
        """A non-validating ``error`` payload falls back to INTERNAL_ERROR."""
        from mcp_types import ErrorData, INTERNAL_ERROR

        cap: dict = {"responded": None}
        class _Resp:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            async def respond(self, payload): cap["responded"] = payload
        responder = _Resp()
        with caplog.at_level("WARNING", logger="mcpgateway.services.notification_service"):
            with responder:
                # Missing required "code" field → ValidationError.
                await NotificationService._respond_with_payload(
                    responder,
                    {"jsonrpc": "2.0", "id": "req-bad-err", "error": {"no_code": True}},
                )
        assert isinstance(cap["responded"], ErrorData)
        assert cap["responded"].code == INTERNAL_ERROR
        assert "Malformed error from downstream" in cap["responded"].message
        assert "substituting INTERNAL_ERROR" in caplog.text

    @pytest.mark.asyncio
    async def test_unvalidatable_result_falls_back_to_error(self, monkeypatch, caplog):
        """If ClientResult validation fails, respond with an ErrorData containing the message."""
        # MCP v2: code uses client_result_adapter.validate_python, not
        # ClientResult.model_validate.  The adapter now matches lenient union
        # variants, so force a validation failure by replacing the adapter's
        # validate_python with one that raises.
        import mcp_types
        from mcp_types import ErrorData, INTERNAL_ERROR
        from pydantic import ValidationError

        def raise_validation(*_args, **_kwargs):
            # Construct a real ValidationError via pydantic for accurate typing.
            try:
                mcp_types.ErrorData.model_validate({})
            except ValidationError as e:
                raise e

        monkeypatch.setattr(mcp_types.client_result_adapter, "validate_python", raise_validation)

        captured2: dict = {"responded": None}
        class _FakeResponder2:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            async def respond(self, payload): captured2["responded"] = payload
        responder2 = _FakeResponder2()
        with caplog.at_level("WARNING", logger="mcpgateway.services.notification_service"):
            with responder2:
                await NotificationService._respond_with_payload(
                    responder2,
                    {"jsonrpc": "2.0", "id": "req-bad-result", "result": {"whatever": 1}},
                )

        assert isinstance(captured2["responded"], ErrorData)
        assert captured2["responded"].code == INTERNAL_ERROR
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
        """A notification whose ``model_dump`` raises is logged and dropped."""
        # First-Party
        from mcpgateway.config import settings

        monkeypatch.setattr(settings, "cache_type", "memory", raising=False)

        svc = NotificationService()

        # MCP v2: notification.model_dump() is called directly (no .root).
        notif = MagicMock()
        notif.model_dump = MagicMock(side_effect=ValueError("shape drift"))

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

        # MCP v2: notification.model_dump() is called directly.
        notif = MagicMock()
        notif.model_dump = MagicMock(return_value={"params": None})  # no method

        with caplog.at_level("WARNING", logger="mcpgateway.services.notification_service"):
            await svc._forward_notification_to_stream("sess-nm", notif)

        assert "empty method" in caplog.text

    @pytest.mark.asyncio
    async def test_notification_get_bus_runtime_error(self, monkeypatch):
        """``get_server_event_bus`` raising during notification fanout → backend_unavailable metric."""
        # MCP v2: ServerNotification is a UnionType, not a wrapper.
        # First-Party
        from mcp_types import ToolListChangedNotification
        from mcpgateway.config import settings
        from mcpgateway.services.metrics import server_event_bus_publish_failed_counter

        monkeypatch.setattr(settings, "cache_type", "memory", raising=False)

        async def _bus():
            raise RuntimeError("bus config broken")

        monkeypatch.setattr("mcpgateway.transports.server_event_bus.get_server_event_bus", _bus)

        svc = NotificationService()
        notif = ToolListChangedNotification(method="notifications/tools/list_changed")
        before = server_event_bus_publish_failed_counter.labels(reason="backend_unavailable")._value.get()

        await svc._forward_notification_to_stream("sess-nb", notif)

        assert server_event_bus_publish_failed_counter.labels(reason="backend_unavailable")._value.get() == before + 1

    @pytest.mark.asyncio
    async def test_notification_publish_transport_error(self, monkeypatch):
        """``bus.publish`` raising ConnectionError → transport_error metric."""
        # MCP v2: ServerNotification is a UnionType, not a wrapper.
        # First-Party
        from mcp_types import ToolListChangedNotification
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
        notif = ToolListChangedNotification(method="notifications/tools/list_changed")
        before = server_event_bus_publish_failed_counter.labels(reason="transport_error")._value.get()

        await svc._forward_notification_to_stream("sess-nt", notif)

        assert server_event_bus_publish_failed_counter.labels(reason="transport_error")._value.get() == before + 1

    @pytest.mark.asyncio
    async def test_notification_publish_backend_error(self, monkeypatch):
        """``bus.publish`` raising BusBackendError → backend_unavailable metric."""
        # MCP v2: ServerNotification is a UnionType, not a wrapper.
        # First-Party
        from mcp_types import ToolListChangedNotification
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
        notif = ToolListChangedNotification(method="notifications/tools/list_changed")
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
        # MCP v2: ServerNotification is a UnionType, not a wrapper.
        # The typed notification IS the notification — isinstance() still
        # matches it against the union.
        from mcp_types import ToolListChangedNotification

        # First-Party
        from mcpgateway.config import settings
        from mcpgateway.transports.server_event_bus import reset_server_event_bus

        monkeypatch.setattr(settings, "cache_type", "memory", raising=False)
        await reset_server_event_bus()

        svc = NotificationService()
        svc._handle_notification = AsyncMock()  # type: ignore[assignment]
        svc._forward_notification_to_stream = AsyncMock()  # type: ignore[assignment]

        handler = svc.create_message_handler("gw-1", "http://u", downstream_session_id="sess-sn")
        notif = ToolListChangedNotification(method="notifications/tools/list_changed")

        await handler(notif)

        svc._handle_notification.assert_awaited_once_with("gw-1", notif, "http://u")
        svc._forward_notification_to_stream.assert_awaited_once_with("sess-sn", notif)

    @pytest.mark.asyncio
    async def test_server_notification_without_session_id_skips_fanout(self):
        """No downstream_session_id → only internal handling, no fanout."""
        # MCP v2: ServerNotification is a UnionType.
        from mcp_types import ToolListChangedNotification

        svc = NotificationService()
        svc._handle_notification = AsyncMock()  # type: ignore[assignment]
        svc._forward_notification_to_stream = AsyncMock()  # type: ignore[assignment]

        handler = svc.create_message_handler("gw-1")
        notif = ToolListChangedNotification(method="notifications/tools/list_changed")

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


class TestRespondWithPayloadV2Fallback:
    """Cover the mcp v2 RequestResponder fallback warnings in _respond_with_payload."""

    @pytest.mark.asyncio
    async def test_error_payload_without_respond_logs_warning(self, caplog):
        # Standard
        import logging
        from types import SimpleNamespace

        # First-Party
        from mcpgateway.services.notification_service import NotificationService

        with caplog.at_level(logging.WARNING):
            await NotificationService._respond_with_payload(SimpleNamespace(), {"error": {"code": -32600, "message": "bad"}})

        assert "error dropped" in caplog.text

    @pytest.mark.asyncio
    async def test_invalid_result_payload_without_respond_logs_warning(self, caplog):
        # Standard
        import logging
        from types import SimpleNamespace

        # First-Party
        from mcpgateway.services.notification_service import NotificationService

        with caplog.at_level(logging.WARNING):
            await NotificationService._respond_with_payload(SimpleNamespace(), {"result": 12345})

        assert "validation error dropped" in caplog.text

    @pytest.mark.asyncio
    async def test_valid_result_without_respond_logs_warning(self, caplog):
        # Standard
        import logging
        from types import SimpleNamespace

        # First-Party
        from mcpgateway.services.notification_service import NotificationService

        with caplog.at_level(logging.WARNING):
            await NotificationService._respond_with_payload(SimpleNamespace(), {"result": {}})

        assert "downstream result dropped" in caplog.text


class TestV2ClientCallbacks:
    """Tests for typed v2 callbacks used by upstream Client."""

    @pytest.mark.asyncio
    async def test_list_roots_callback_round_trips_through_event_bus(self):
        service = NotificationService()
        published = []

        class FakeBus:
            async def publish(self, session_id, message):
                published.append((session_id, message))
                await service.complete_request(
                    session_id,
                    str(message.id),
                    {"jsonrpc": "2.0", "id": message.id, "result": {"roots": []}},
                )

        async def get_bus():
            return FakeBus()

        callbacks = service.create_client_callbacks(
            gateway_id="gw-1",
            gateway_url="https://upstream.example/mcp",
            downstream_session_id="downstream-1",
        )
        with patch("mcpgateway.transports.server_event_bus.get_server_event_bus", get_bus):
            result = await callbacks["list_roots_callback"](MagicMock())

        assert result.roots == []
        assert published[0][0] == "downstream-1"
        assert published[0][1].method == "roots/list"
