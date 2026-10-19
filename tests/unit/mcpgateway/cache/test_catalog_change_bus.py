# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/cache/test_catalog_change_bus.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for mcpgateway.cache.catalog_change_bus.
"""

# Standard
import asyncio

# Third-Party
from mcp.server.subscriptions import InMemorySubscriptionBus, ListenHandler
from mcp.shared.subscriptions import PromptsListChanged, ResourcesListChanged, ServerEvent, ToolsListChanged
import pytest

# First-Party
from mcpgateway.cache import catalog_change_bus as bus_module
from mcpgateway.cache.catalog_change_bus import COALESCE_SECONDS, get_listen_bus, get_listen_handler, notify_catalog_change


@pytest.fixture(autouse=True)
def _reset_bus_state(monkeypatch: pytest.MonkeyPatch):
    """Give each test fresh singletons and pending state."""
    monkeypatch.setattr(bus_module, "_listen_bus", None)
    monkeypatch.setattr(bus_module, "_listen_handler", None)
    monkeypatch.setattr(bus_module, "_pending", bus_module.weakref.WeakKeyDictionary())
    monkeypatch.setattr(bus_module, "_publish_tasks", set())


@pytest.fixture
def captured() -> list[ServerEvent]:
    """Collect every event published on the listen bus."""
    events: list[ServerEvent] = []
    get_listen_bus().subscribe(events.append)
    return events


async def _settle(windows: int = 2) -> None:
    await asyncio.sleep(COALESCE_SECONDS * windows)


async def test_tools_maps_to_tools_list_changed(captured):
    notify_catalog_change("tools")
    await _settle()
    assert captured == [ToolsListChanged()]


async def test_servers_maps_to_all_three_kinds(captured):
    notify_catalog_change("servers")
    await _settle()
    assert len(captured) == 3
    assert set(map(type, captured)) == {ToolsListChanged, PromptsListChanged, ResourcesListChanged}


@pytest.mark.parametrize("cache_type", ["agents", "gateways", "catalog"])
async def test_unmapped_types_publish_nothing(captured, cache_type):
    notify_catalog_change(cache_type)
    await _settle()
    assert captured == []


async def test_burst_of_1000_publishes_one_event_per_kind(captured):
    for _ in range(1000):
        notify_catalog_change("tools")
    await _settle()
    assert captured == [ToolsListChanged()]


async def test_mixed_burst_coalesces_per_kind(captured):
    notify_catalog_change("tools")
    notify_catalog_change("prompts")
    notify_catalog_change("tools")
    await _settle()
    assert sorted(map(type, captured), key=lambda t: t.__name__) == [PromptsListChanged, ToolsListChanged]


async def test_second_window_publishes_again(captured):
    notify_catalog_change("tools")
    await _settle()
    notify_catalog_change("tools")
    await _settle()
    assert captured == [ToolsListChanged(), ToolsListChanged()]


def test_notify_without_running_loop_is_noop():
    notify_catalog_change("tools")
    assert not bus_module._pending


async def test_listener_exception_does_not_propagate(captured):
    def boom(_event: ServerEvent) -> None:
        raise RuntimeError("bad listener")

    get_listen_bus().subscribe(boom)
    other: list[ServerEvent] = []
    get_listen_bus().subscribe(other.append)

    notify_catalog_change("tools")
    await _settle()

    assert captured == [ToolsListChanged()]
    assert other == [ToolsListChanged()]


async def test_publish_tasks_released_after_completion(captured):
    notify_catalog_change("tools")
    await _settle()
    assert not bus_module._publish_tasks


def test_singletons():
    assert isinstance(get_listen_bus(), InMemorySubscriptionBus)
    assert get_listen_bus() is get_listen_bus()
    assert isinstance(get_listen_handler(), ListenHandler)
    assert get_listen_handler() is get_listen_handler()
