# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/transports/test_mcp_ingress_mount.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for ``mcpgateway.transports.mcp_ingress_mount.MCPIngressMount``.

The mount is intentionally tiny: a registry of named ASGI apps + a
selector function. These tests exercise the registry/selector/fallback
contract in isolation from the runtime-mode policy that drives it in
production (see ``test_main_extended.py`` for the integrated tests).
"""

# Future
from __future__ import annotations

# Standard
from typing import List

# Third-Party
import pytest

# First-Party
from mcpgateway.transports.mcp_ingress_mount import MCPIngressMount


def _make_recording_app(label: str, sink: List[str]):
    async def _app(scope, _receive, _send):
        sink.append(f"{label}:{scope.get('path', '/')}")

    return _app


@pytest.mark.asyncio
async def test_dispatch_routes_to_registered_ingress():
    sink: List[str] = []
    mount = MCPIngressMount(selector=lambda _scope: "alpha")
    mount.register("alpha", _make_recording_app("alpha", sink))
    mount.register("beta", _make_recording_app("beta", sink))

    async def _no_send(_msg):
        pass

    async def _no_receive():
        return {"type": "http.request"}

    await mount.dispatch({"type": "http", "path": "/mcp"}, _no_receive, _no_send)
    assert sink == ["alpha:/mcp"]


@pytest.mark.asyncio
async def test_set_selector_swaps_routing_atomically():
    sink: List[str] = []
    mount = MCPIngressMount(selector=lambda _scope: "alpha")
    mount.register("alpha", _make_recording_app("alpha", sink))
    mount.register("beta", _make_recording_app("beta", sink))

    async def _noop(*_):
        pass

    await mount.dispatch({"type": "http", "path": "/1"}, _noop, _noop)
    mount.set_selector(lambda _scope: "beta")
    await mount.dispatch({"type": "http", "path": "/2"}, _noop, _noop)
    assert sink == ["alpha:/1", "beta:/2"]


@pytest.mark.asyncio
async def test_unregister_returns_app_and_routes_fall_through_to_fallback():
    sink: List[str] = []
    fallback = _make_recording_app("fallback", sink)
    mount = MCPIngressMount(selector=lambda _scope: "alpha", fallback=fallback)
    alpha_app = _make_recording_app("alpha", sink)
    mount.register("alpha", alpha_app)

    removed = mount.unregister("alpha")
    assert removed is alpha_app

    async def _noop(*_):
        pass

    await mount.dispatch({"type": "http", "path": "/x"}, _noop, _noop)
    assert sink == ["fallback:/x"]


@pytest.mark.asyncio
async def test_dispatch_503s_when_selector_misses_and_no_fallback():
    mount = MCPIngressMount(selector=lambda _scope: "ghost")
    mount.register("alpha", _make_recording_app("alpha", []))

    captured = {}

    async def _capture_send(message):
        captured.setdefault("messages", []).append(message)

    async def _noop_receive():
        return {"type": "http.request"}

    await mount.dispatch({"type": "http", "path": "/x"}, _noop_receive, _capture_send)
    start = captured["messages"][0]
    body = captured["messages"][1]
    assert start["status"] == 503
    body_text = body["body"].decode("utf-8")
    assert "'ghost'" in body_text
    assert "alpha" in body_text  # available list


@pytest.mark.asyncio
async def test_dispatch_logs_warning_when_falling_back_to_fallback(caplog):
    """Selector miss + fallback → warning log so a misrouted ingress is never silent."""
    sink: List[str] = []
    fallback = _make_recording_app("fallback", sink)
    mount = MCPIngressMount(selector=lambda _scope: "ghost", fallback=fallback)
    mount.register("alpha", _make_recording_app("alpha", sink))

    async def _noop(*_):
        pass

    caplog.set_level("WARNING", logger="mcpgateway.transports.mcp_ingress_mount")
    await mount.dispatch({"type": "http", "path": "/x"}, _noop, _noop)

    assert sink == ["fallback:/x"]
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert any("'ghost'" in w.message and "alpha" in w.message for w in warnings)


@pytest.mark.asyncio
async def test_dispatch_503_path_logs_warning(caplog):
    """Selector miss + no fallback → 503 ALSO emits a warning, not just a wire response."""
    mount = MCPIngressMount(selector=lambda _scope: "ghost")
    mount.register("alpha", _make_recording_app("alpha", []))

    async def _capture_send(_msg):
        pass

    async def _noop_receive():
        return {"type": "http.request"}

    caplog.set_level("WARNING", logger="mcpgateway.transports.mcp_ingress_mount")
    await mount.dispatch({"type": "http", "path": "/x"}, _noop_receive, _capture_send)

    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert any("'ghost'" in w.message and "503" in w.message for w in warnings)


def test_register_is_idempotent_and_replaces():
    sink: List[str] = []
    mount = MCPIngressMount(selector=lambda _scope: "alpha")
    first = _make_recording_app("first", sink)
    second = _make_recording_app("second", sink)
    mount.register("alpha", first)
    mount.register("alpha", second)
    assert mount._ingresses["alpha"] is second  # noqa: SLF001 — direct registry inspection in test


def test_names_returns_sorted_registered_ingresses():
    mount = MCPIngressMount(selector=lambda _scope: "alpha")
    mount.register("zebra", _make_recording_app("z", []))
    mount.register("alpha", _make_recording_app("a", []))
    mount.register("mike", _make_recording_app("m", []))
    assert mount.names() == ["alpha", "mike", "zebra"]


@pytest.mark.asyncio
async def test_set_fallback_swaps_the_fallback_app_at_runtime():
    """set_fallback replaces the fallback so a misconfigured selector routes to the new app on the next request."""
    sink: List[str] = []
    mount = MCPIngressMount(selector=lambda _scope: "ghost")
    mount.set_fallback(_make_recording_app("first", sink))

    async def _noop(*_):
        pass

    await mount.dispatch({"type": "http", "path": "/a"}, _noop, _noop)
    mount.set_fallback(_make_recording_app("second", sink))
    await mount.dispatch({"type": "http", "path": "/b"}, _noop, _noop)
    # set_fallback(None) restores the 503-on-miss behavior.
    mount.set_fallback(None)
    captured = []

    async def _capture(message):
        captured.append(message)

    async def _no_receive():
        return {"type": "http.request"}

    await mount.dispatch({"type": "http", "path": "/c"}, _no_receive, _capture)

    assert sink == ["first:/a", "second:/b"]
    assert any(msg.get("type") == "http.response.start" and msg.get("status") == 503 for msg in captured)
