# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_notification_service.py
Copyright 2026
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

        # Mock notification structure
        mock_root = MagicMock()
        mock_root.__class__.__name__ = "ToolListChangedNotification"
        mock_notification = MagicMock()
        mock_notification.root = mock_root

        await notification_service._handle_notification("gw-1", mock_notification)

        notification_service._enqueue_refresh.assert_called_once_with(
            "gw-1", NotificationType.TOOLS_LIST_CHANGED
        )
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

        notification_service._enqueue_refresh.assert_called_once_with(
            "gw-1", NotificationType.RESOURCES_LIST_CHANGED
        )

    @pytest.mark.asyncio
    async def test_handle_notification_prompts(self, notification_service):
        """Test handling prompts/list_changed notification."""
        notification_service._enqueue_refresh = AsyncMock()

        mock_root = MagicMock()
        mock_root.__class__.__name__ = "PromptListChangedNotification"
        mock_notification = MagicMock()
        mock_notification.root = mock_root

        await notification_service._handle_notification("gw-1", mock_notification)

        notification_service._enqueue_refresh.assert_called_once_with(
            "gw-1", NotificationType.PROMPTS_LIST_CHANGED
        )

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
        mock_gateway_service._refresh_gateway_tools_resources_prompts = AsyncMock(
            return_value={"success": True, "tools_added": 2, "tools_removed": 1}
        )
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
        mock_gateway_service._refresh_gateway_tools_resources_prompts = AsyncMock(
            side_effect=Exception("Connection failed")
        )
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
        mock_gateway_service._refresh_gateway_tools_resources_prompts = AsyncMock(
            return_value={"success": False, "error": "Something went wrong"}
        )
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
        mock_gateway_service._refresh_gateway_tools_resources_prompts = AsyncMock(
            return_value={"success": True}
        )
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
