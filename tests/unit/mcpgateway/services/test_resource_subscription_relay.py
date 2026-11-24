# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_resource_subscription_relay.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for the upstream resource subscription relay (#6644).
"""

# Standard
import asyncio
from contextlib import asynccontextmanager

# Third-Party
from mcp import Client
from mcp.client.subscriptions import ListenNotSupportedError, SubscriptionLost
from mcp.server.mcpserver import MCPServer
from mcp.server.subscriptions import InMemorySubscriptionBus
from mcp.shared.subscriptions import ToolsListChanged
from mcp.shared.subscriptions import ResourceUpdated
import pytest

# First-Party
from mcpgateway.cache.catalog_change_bus import get_listen_bus
from mcpgateway.services import resource_subscription_relay as relay_module
from mcpgateway.services.resource_subscription_relay import ResourceSubscriptionRelay, scoped_listen_bus, UpstreamResourceTarget, UpstreamResourceUpdated

URI = "test://note"
TARGET = UpstreamResourceTarget(gateway_id="gw-1", url="http://upstream.invalid/mcp", uri=URI)
UPDATED = UpstreamResourceUpdated(uri=URI, gateway_id="gw-1")


def _modern_upstream() -> tuple[MCPServer, InMemorySubscriptionBus]:
    """Build an in-memory 2026-07-28 upstream with one resource and an exposed listen bus."""
    bus = InMemorySubscriptionBus()
    server = MCPServer("relay-upstream", subscriptions=bus)

    @server.resource(URI)
    def note() -> str:
        """Return the note."""
        return "v1"

    return server, bus


def _patch_upstream_client(monkeypatch, make_client):
    """Route the relay's upstream connections to ``make_client`` and count them."""
    opened = []

    @asynccontextmanager
    async def fake_proxy_client(url, headers=None, **_kwargs):
        opened.append((url, headers))
        async with make_client() as client:
            yield client

    monkeypatch.setattr(relay_module, "mcp_proxy_client", fake_proxy_client)
    return opened


@pytest.fixture
def gateway_events():
    """Collect events published on the gateway's worker-local listen bus."""
    events = []
    unsubscribe = get_listen_bus().subscribe(events.append)
    yield events
    unsubscribe()


async def _wait_for(predicate, timeout: float = 5.0) -> None:
    """Poll ``predicate`` until it holds or fail after ``timeout`` seconds."""
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


async def test_relay_publishes_resource_updated_on_upstream_change(monkeypatch, gateway_events):
    """An upstream resources/updated for the watched URI reaches the gateway listen bus."""
    server, upstream_bus = _modern_upstream()
    _patch_upstream_client(monkeypatch, lambda: Client(server, mode="2026-07-28"))
    relay = ResourceSubscriptionRelay()

    async with relay.watch([TARGET]):
        await _wait_for(lambda: upstream_bus._listeners)
        await upstream_bus.publish(ResourceUpdated(uri=URI))
        await _wait_for(lambda: UPDATED in gateway_events)

    await relay.shutdown()


async def test_relay_shares_one_upstream_listen_per_target(monkeypatch):
    """Two watchers of one target share one upstream stream; the last release cancels it."""
    server, upstream_bus = _modern_upstream()
    opened = _patch_upstream_client(monkeypatch, lambda: Client(server, mode="2026-07-28"))
    relay = ResourceSubscriptionRelay()

    async with relay.watch([TARGET]):
        async with relay.watch([TARGET]):
            await _wait_for(lambda: upstream_bus._listeners)
        task = relay._watches[(TARGET.gateway_id, URI)].task
        assert not task.done()
        assert len(opened) == 1

    await _wait_for(task.done)
    assert relay._watches == {}
    await _wait_for(lambda: not upstream_bus._listeners)


async def test_relay_stops_on_legacy_upstream(monkeypatch):
    """A pre-2026 upstream ends the relay for that target without reconnecting."""

    class LegacyClient:
        @asynccontextmanager
        async def listen(self, **_kwargs):
            raise ListenNotSupportedError("2025-11-25")
            yield  # pragma: no cover

    @asynccontextmanager
    async def legacy():
        yield LegacyClient()

    opened = _patch_upstream_client(monkeypatch, legacy)
    monkeypatch.setattr(relay_module, "BACKOFF_INITIAL_SECONDS", 0.01)
    relay = ResourceSubscriptionRelay()

    async with relay.watch([TARGET]):
        task = relay._watches[(TARGET.gateway_id, URI)].task
        await _wait_for(task.done)
        await asyncio.sleep(0.05)
        assert len(opened) == 1

    # The gateway stays marked unsupported, so a new stream neither probes it nor gets its URI admitted.
    async with relay.watch([TARGET]) as admitted:
        assert admitted == []
    assert len(opened) == 1


async def test_relay_stops_when_upstream_does_not_honor_uri(monkeypatch):
    """An upstream ack that leaves the URI out ends the relay; no stream is held for nothing."""

    class Sub:
        honored = type("Honored", (), {"resource_subscriptions": None})()

    class RefusingClient:
        @asynccontextmanager
        async def listen(self, **_kwargs):
            yield Sub()

    @asynccontextmanager
    async def refusing():
        yield RefusingClient()

    opened = _patch_upstream_client(monkeypatch, refusing)
    relay = ResourceSubscriptionRelay()

    async with relay.watch([TARGET]):
        await _wait_for(relay._watches[(TARGET.gateway_id, URI)].task.done)
        assert len(opened) == 1


async def test_relay_reconnects_after_drop_and_signals_possible_miss(monkeypatch, gateway_events):
    """A dropped upstream stream re-listens after backoff and publishes one update for the gap."""
    server, upstream_bus = _modern_upstream()
    attempts = []

    @asynccontextmanager
    async def flaky():
        attempts.append(1)
        if len(attempts) == 1:
            raise SubscriptionLost("dropped")
        async with Client(server, mode="2026-07-28") as client:
            yield client

    _patch_upstream_client(monkeypatch, flaky)
    monkeypatch.setattr(relay_module, "BACKOFF_INITIAL_SECONDS", 0.01)
    relay = ResourceSubscriptionRelay()

    async with relay.watch([TARGET]):
        await _wait_for(lambda: len(attempts) == 2 and upstream_bus._listeners)
        await _wait_for(lambda: UPDATED in gateway_events)

    await relay.shutdown()


async def test_relay_shutdown_cancels_every_watch(monkeypatch):
    """Shutdown cancels running relays and forgets every watch."""
    server, upstream_bus = _modern_upstream()
    _patch_upstream_client(monkeypatch, lambda: Client(server, mode="2026-07-28"))
    relay = ResourceSubscriptionRelay()

    async with relay.watch([TARGET]):
        await _wait_for(lambda: upstream_bus._listeners)
        task = relay._watches[(TARGET.gateway_id, URI)].task
        await relay.shutdown()
        assert task.done()
        assert relay._watches == {}


def test_target_forwards_headers_as_dict():
    """Headers ride as a hashable tuple and convert back for the upstream client."""
    target = UpstreamResourceTarget(gateway_id="g", url="u", uri="x", headers=(("Authorization", "Bearer t"),))
    assert target.header_dict() == {"Authorization": "Bearer t"}


async def test_relay_caps_distinct_watches_per_worker(monkeypatch):
    """Past MAX_RELAY_WATCHES a new target is not admitted; an already watched target still is."""
    server, _upstream_bus = _modern_upstream()
    _patch_upstream_client(monkeypatch, lambda: Client(server, mode="2026-07-28"))
    monkeypatch.setattr(relay_module, "MAX_RELAY_WATCHES", 1)
    other = UpstreamResourceTarget(gateway_id="gw-2", url="http://other.invalid/mcp", uri=URI)
    relay = ResourceSubscriptionRelay()

    async with relay.watch([TARGET, other]) as first:
        assert first == [TARGET]
        async with relay.watch([other, TARGET]) as second:
            assert second == [TARGET]
            assert relay._watches[(TARGET.gateway_id, URI)].count == 2

    await relay.shutdown()


async def test_scoped_bus_keeps_other_gateways_updates_out():
    """A stream scoped to gw-1 gets gw-1 updates and list events, never another gateway's update for the same URI."""
    received = []
    scoped = scoped_listen_bus([TARGET])
    unsubscribe = scoped.subscribe(received.append)
    try:
        await scoped.publish(UpstreamResourceUpdated(uri=URI, gateway_id="gw-2"))
        await scoped.publish(ResourceUpdated(uri=URI))
        await scoped.publish(UPDATED)
        await scoped.publish(ToolsListChanged())
    finally:
        unsubscribe()

    assert received == [UPDATED, ToolsListChanged()]
