# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_modern_listener_service.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for the ModernListenerService: standing subscriptions/listen
streams to modern (2026-07-28) gateways feeding the debounced refresh.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
import contextlib
import time
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from mcp.client.subscriptions import ListenNotSupportedError, PromptsListChanged, ResourcesListChanged, ResourceUpdated, ToolsListChanged
import pytest

# First-Party
from mcpgateway.services import modern_listener_service as mls
from mcpgateway.services.modern_listener_service import _GatewaySnapshot, ModernListenerService
from mcpgateway.services.notification_service import NotificationType


def _snapshot(**overrides) -> _GatewaySnapshot:
    values = {"id": "gw-1", "name": "modern-gw", "url": "http://example.test/mcp", "headers": {}}
    values.update(overrides)
    return _GatewaySnapshot(**values)


def _make_event(cls):
    """Instantiate an SDK event type without depending on its constructor signature."""
    return cls.__new__(cls)


@contextlib.asynccontextmanager
async def _fake_proxy_client(client, *_args, **_kwargs):
    yield client


class TestModernListenerService:
    """Event dispatch, era gating, eligibility filtering, and reconnect behavior."""

    @pytest.fixture(autouse=True)
    def _primary_worker(self, monkeypatch):
        monkeypatch.setattr(mls, "is_primary_worker", lambda: True)

    @pytest.mark.asyncio
    async def test_dispatch_maps_events_to_notification_types(self):
        notification_service = MagicMock()
        notification_service.notify_list_changed = AsyncMock()
        service = ModernListenerService(notification_service)
        gw = _snapshot()

        expected = [
            (_make_event(ToolsListChanged), NotificationType.TOOLS_LIST_CHANGED),
            (_make_event(PromptsListChanged), NotificationType.PROMPTS_LIST_CHANGED),
            (_make_event(ResourcesListChanged), NotificationType.RESOURCES_LIST_CHANGED),
            (_make_event(ResourceUpdated), NotificationType.RESOURCES_LIST_CHANGED),
        ]
        for event, notification_type in expected:
            await service._dispatch(gw, event)
            notification_service.notify_list_changed.assert_awaited_with(gw.id, notification_type)

        notification_service.notify_list_changed.reset_mock()
        await service._dispatch(gw, object())  # unrecognized event type
        notification_service.notify_list_changed.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_listen_unsupported_puts_gateway_on_cooldown(self):
        service = ModernListenerService(MagicMock())
        gw = _snapshot()

        client = MagicMock()
        client.listen = MagicMock(side_effect=ListenNotSupportedError("pre-2026"))

        with patch.object(mls, "mcp_proxy_client", lambda *a, **k: _fake_proxy_client(client)):
            await service._listen_forever(gw)

        assert service._unsupported_until[gw.id] > time.monotonic()

    @pytest.mark.asyncio
    async def test_reconnect_backoff_on_dropped_stream(self, monkeypatch):
        monkeypatch.setattr(mls, "BACKOFF_INITIAL_SECONDS", 0.01)
        monkeypatch.setattr(mls, "BACKOFF_MAX_SECONDS", 0.02)
        service = ModernListenerService(MagicMock())
        gw = _snapshot()

        attempts = 0

        @contextlib.asynccontextmanager
        async def failing_proxy_client(*_args, **_kwargs):
            nonlocal attempts
            attempts += 1
            if attempts >= 3:
                service._shutdown_event.set()
            raise ConnectionError("server down")
            yield  # pragma: no cover

        with patch.object(mls, "mcp_proxy_client", failing_proxy_client):
            await asyncio.wait_for(service._listen_forever(gw), timeout=5)

        assert attempts >= 3
        assert gw.id not in service._unsupported_until  # transient errors must not disable the gateway

    def test_load_eligible_gateways_skips_sse_and_oauth(self):
        def _row(name, transport="STREAMABLEHTTP", auth_type=None, auth_value=None, enabled=True):
            row = MagicMock()
            row.id = f"id-{name}"
            row.name = name
            row.url = f"http://{name}.test/mcp"
            row.transport = transport
            row.auth_type = auth_type
            row.auth_value = auth_value
            row.enabled = enabled
            return row

        rows = [
            _row("eligible", auth_value={"Authorization": "Bearer x"}),
            _row("legacy-sse", transport="SSE"),
            _row("oauth-gw", auth_type="oauth"),
        ]

        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = rows
        session_factory = MagicMock()
        session_factory.return_value.__enter__ = MagicMock(return_value=db)
        session_factory.return_value.__exit__ = MagicMock(return_value=False)

        service = ModernListenerService(MagicMock())
        with patch.object(mls, "SessionLocal", session_factory):
            snapshots = service._load_eligible_gateways()

        assert [s.name for s in snapshots] == ["eligible"]
        assert snapshots[0].headers == {"Authorization": "Bearer x"}

    @pytest.mark.asyncio
    async def test_reconcile_starts_and_stops_listeners(self):
        service = ModernListenerService(MagicMock())
        snapshots = [_snapshot()]

        started = asyncio.Event()

        async def fake_listen_forever(_gw):
            started.set()
            await asyncio.sleep(3600)

        with patch.object(service, "_load_eligible_gateways", side_effect=lambda: snapshots), patch.object(service, "_listen_forever", side_effect=fake_listen_forever):
            await service._reconcile()
            await asyncio.wait_for(started.wait(), timeout=2)
            assert "gw-1" in service._listener_tasks

            # Gateway disappears -> its listener is cancelled on the next pass.
            snapshots.clear()
            await service._reconcile()
            assert "gw-1" not in service._listener_tasks

        await service.shutdown()

    @pytest.mark.asyncio
    async def test_reconcile_respects_unsupported_cooldown(self):
        service = ModernListenerService(MagicMock())
        service._unsupported_until["gw-1"] = time.monotonic() + 3600

        with patch.object(service, "_load_eligible_gateways", return_value=[_snapshot()]), patch.object(service, "_listen_forever") as listen_mock:
            await service._reconcile()

        listen_mock.assert_not_called()
        assert "gw-1" not in service._listener_tasks


class _EmptySubscription:
    """A listen subscription the server closes gracefully without events."""

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


def _graceful_client():
    client = MagicMock()

    @contextlib.asynccontextmanager
    async def listen(**_kwargs):
        yield _EmptySubscription()

    client.listen = listen
    return client


async def _sleep_forever(_gw):
    await asyncio.sleep(3600)


class TestModernListenerPrimaryGate:
    """Listeners run only on the primary worker (``is_primary_worker()``)."""

    @pytest.mark.asyncio
    async def test_reconcile_skips_when_not_primary(self, monkeypatch):
        monkeypatch.setattr(mls, "is_primary_worker", lambda: False)
        service = ModernListenerService(MagicMock())

        with patch.object(service, "_load_eligible_gateways", return_value=[_snapshot()]), patch.object(service, "_listen_forever") as listen_mock:
            await service._reconcile()

        listen_mock.assert_not_called()
        assert service._listener_tasks == {}

    @pytest.mark.asyncio
    async def test_reconcile_starts_when_primary(self, monkeypatch):
        monkeypatch.setattr(mls, "is_primary_worker", lambda: True)
        service = ModernListenerService(MagicMock())

        with patch.object(service, "_load_eligible_gateways", return_value=[_snapshot()]), patch.object(service, "_listen_forever", side_effect=_sleep_forever):
            await service._reconcile()
            assert "gw-1" in service._listener_tasks

        await service.shutdown()

    @pytest.mark.asyncio
    async def test_losing_primary_cancels_listeners(self, monkeypatch):
        primary = True
        monkeypatch.setattr(mls, "is_primary_worker", lambda: primary)
        service = ModernListenerService(MagicMock())

        with patch.object(service, "_load_eligible_gateways", return_value=[_snapshot()]), patch.object(service, "_listen_forever", side_effect=_sleep_forever):
            await service._reconcile()
            task = service._listener_tasks["gw-1"]

            primary = False
            await service._reconcile()

        assert service._listener_tasks == {}
        await asyncio.sleep(0)
        assert task.cancelled()


class TestModernListenerReconnect:
    """Jittered reconnect and the refresh that follows a re-listen."""

    def test_backoff_with_jitter_bounds(self):
        jitter = ModernListenerService._backoff_with_jitter
        assert jitter(10.0, rand=lambda: 0.0) == 5.0
        assert jitter(10.0, rand=lambda: 1.0) == 15.0
        assert jitter(mls.BACKOFF_MAX_SECONDS, rand=lambda: 1.0) == mls.BACKOFF_MAX_SECONDS

    @pytest.mark.asyncio
    async def test_graceful_close_waits_before_relisten(self, monkeypatch):
        notification_service = MagicMock()
        notification_service.notify_list_changed = AsyncMock()
        service = ModernListenerService(notification_service)
        waits = []
        monkeypatch.setattr(ModernListenerService, "_backoff_with_jitter", staticmethod(lambda backoff: waits.append(backoff) or 0.05))

        attempts = 0
        connect_times = []

        @contextlib.asynccontextmanager
        async def proxy_client(*_args, **_kwargs):
            nonlocal attempts
            attempts += 1
            connect_times.append(time.monotonic())
            if attempts >= 2:
                service._shutdown_event.set()
                raise ConnectionError("stop")
            yield _graceful_client()

        with patch.object(mls, "mcp_proxy_client", proxy_client):
            await asyncio.wait_for(service._listen_forever(_snapshot()), timeout=5)

        assert waits[0] == mls.BACKOFF_INITIAL_SECONDS
        assert connect_times[1] - connect_times[0] >= 0.04
        notification_service.notify_list_changed.assert_not_awaited()  # the first connect never refreshes

    @pytest.mark.asyncio
    async def test_relisten_after_drop_triggers_refresh(self, monkeypatch):
        notification_service = MagicMock()
        notification_service.notify_list_changed = AsyncMock()
        service = ModernListenerService(notification_service)
        monkeypatch.setattr(ModernListenerService, "_backoff_with_jitter", staticmethod(lambda backoff: 0.0))

        attempts = 0

        @contextlib.asynccontextmanager
        async def proxy_client(*_args, **_kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ConnectionError("dropped")
            service._shutdown_event.set()
            yield _graceful_client()

        gw = _snapshot()
        with patch.object(mls, "mcp_proxy_client", proxy_client):
            await asyncio.wait_for(service._listen_forever(gw), timeout=5)

        awaited = [c.args for c in notification_service.notify_list_changed.await_args_list]
        assert len(awaited) == 3
        assert set(awaited) == {(gw.id, NotificationType.TOOLS_LIST_CHANGED), (gw.id, NotificationType.PROMPTS_LIST_CHANGED), (gw.id, NotificationType.RESOURCES_LIST_CHANGED)}
