# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_issue_4205_upstream_session_isolation.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Integration reproducer for issue #4205 — upstream session isolation.
The original reproducer (Dawid Nowak, issue #4205): start a stateful MCP
server (rust-sdk counter example), register it with ContextForge, then
drive multiple downstream MCP sessions through the gateway. Before this
fix, ContextForge's identity-keyed session pool shared a single upstream
session across downstream clients carrying the same user identity, so
every client saw — and mutated — the same counter. Increment from one
browser tab leaked into another; resetting the counter was effectively
impossible.
This test recreates that scenario at the integration layer using:
  * the real ``UpstreamSessionRegistry`` (the 1:1 replacement for the
    deleted ``MCPSessionPool``);
  * an in-memory stateful counter that plays the role of the upstream
    MCP server, wired in via the registry's injectable SessionFactory;
  * two downstream sessions identified by different ``Mcp-Session-Id``s.
The load-bearing assertion is that counter state never leaks across
downstream sessions. If the registry's 1:1 contract ever regresses, the
``increment(5) … increment(3) … get_counter`` sequence below sees the
combined count and this test fails loudly, in the exact shape of the
original bug report.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
from typing import Any, List

# Third-Party
import pytest

# First-Party
from mcpgateway.services.upstream_session_registry import (
    SessionCreateRequest,
    TransportType,
    UpstreamSessionRegistry,
)

# --------------------------------------------------------------------------- #
# Stand-in for a stateful upstream MCP server                                 #
# --------------------------------------------------------------------------- #


class _CounterMcpServer:
    """In-memory stateful upstream — one instance per upstream MCP session.

    Implements the subset of the MCP ``ClientSession`` API that the
    registry and its callers exercise: ``call_tool``. Keeps a ``counter``
    attribute that increments per ``call_tool("increment")`` and is
    returned by ``call_tool("get_counter")``. The counter lives on the
    instance, so each upstream session built by the factory has its own.
    """

    def __init__(self) -> None:
        self.counter = 0

    async def call_tool(self, name: str, args: dict | None = None, meta: dict | None = None) -> dict[str, Any]:
        """Minimal MCP tool dispatcher. Returns a plain result envelope."""
        if name == "increment":
            self.counter += 1
            return {"content": [{"type": "text", "text": str(self.counter)}]}
        if name == "get_counter":
            return {"content": [{"type": "text", "text": str(self.counter)}]}
        raise ValueError(f"unknown tool: {name}")


def _make_counter_session_factory():
    """Return (factory, created) — the factory builds CounterMcpServer-backed sessions.

    ``created`` is a list of the session instances the factory has
    produced, in order; tests can inspect it to assert one-session-per-
    downstream-session (the #4205 invariant).
    """
    created: List[_CounterMcpServer] = []

    async def factory(req: SessionCreateRequest):
        # Fresh stateful upstream instance per call. If the registry ever
        # accidentally shares sessions across downstream session ids, two
        # acquires will produce only one _CounterMcpServer — the very
        # sharing pattern #4205 existed to prevent.
        session = _CounterMcpServer()
        shutdown_event = asyncio.Event()

        async def owner() -> None:
            await shutdown_event.wait()

        task = asyncio.create_task(owner(), name="counter-upstream-owner")
        # The registry looks for these two attributes on the session to
        # manage its lifecycle; the real default_session_factory smuggles
        # them on the MCP ClientSession the same way.
        session._cf_owner_task = task  # type: ignore[attr-defined]
        session._cf_shutdown_event = shutdown_event  # type: ignore[attr-defined]
        created.append(session)
        return session, object()

    return factory, created


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #


@pytest.fixture
def counter_factory_and_log():
    return _make_counter_session_factory()


@pytest.fixture
async def registry(counter_factory_and_log):
    factory, _ = counter_factory_and_log
    reg = UpstreamSessionRegistry(
        session_factory=factory,
        idle_validation_seconds=300.0,  # Never trigger the health probe mid-test.
        session_create_timeout_seconds=1.0,
        shutdown_timeout_seconds=1.0,
    )
    yield reg
    await reg.close_all()


# --------------------------------------------------------------------------- #
# The reproducer                                                               #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_issue_4205_two_downstream_sessions_keep_independent_counter_state(registry, counter_factory_and_log):
    """Dawid Nowak's reproducer for #4205 — counters must not leak between sessions.

    Scenario:
      * Two downstream MCP clients (session id A and session id B) connect to
        the gateway. Both talk to the same upstream counter-server gateway.
      * Client A increments five times; client B increments three times.
      * Each then reads its own counter.

    Expected (fixed):  A sees 5, B sees 3. Each downstream session has its own
    upstream ``ClientSession`` and therefore its own in-memory state on the
    upstream.

    Expected (broken): both see 8 — the pre-#4205 identity-keyed pool would
    have handed them the same upstream session, and every increment would
    land on one shared counter.
    """
    _, created = counter_factory_and_log
    gateway_id = "counter-gateway"
    url = "http://counter.example/mcp"

    # Client A: five increments through its own downstream session id.
    for _ in range(5):
        async with registry.acquire(
            downstream_session_id="session-A",
            gateway_id=gateway_id,
            url=url,
            headers=None,
            transport_type=TransportType.STREAMABLE_HTTP,
        ) as upstream:
            await upstream.session.call_tool("increment")

    # Client B: three increments through a distinct downstream session id.
    for _ in range(3):
        async with registry.acquire(
            downstream_session_id="session-B",
            gateway_id=gateway_id,
            url=url,
            headers=None,
            transport_type=TransportType.STREAMABLE_HTTP,
        ) as upstream:
            await upstream.session.call_tool("increment")

    # Client A reads its counter back.
    async with registry.acquire(
        downstream_session_id="session-A",
        gateway_id=gateway_id,
        url=url,
        headers=None,
        transport_type=TransportType.STREAMABLE_HTTP,
    ) as upstream_a:
        result_a = await upstream_a.session.call_tool("get_counter")

    # Client B reads its counter back.
    async with registry.acquire(
        downstream_session_id="session-B",
        gateway_id=gateway_id,
        url=url,
        headers=None,
        transport_type=TransportType.STREAMABLE_HTTP,
    ) as upstream_b:
        result_b = await upstream_b.session.call_tool("get_counter")

    assert result_a["content"][0]["text"] == "5", "session A counter leaked — #4205 has regressed"
    assert result_b["content"][0]["text"] == "3", "session B counter leaked — #4205 has regressed"

    # Structural invariant: exactly one upstream session per downstream session.
    # If this fails at 1, isolation itself has broken; if it fails at >2, the
    # registry is rebuilding on reuse (a separate regression).
    assert len(created) == 2, f"expected 2 upstream sessions, got {len(created)}"

    # And those two upstream instances carry the per-downstream state.
    assert {s.counter for s in created} == {5, 3}


@pytest.mark.asyncio
async def test_issue_4205_connection_reuse_within_one_downstream_session(registry, counter_factory_and_log):
    """Inside one downstream session, every tool call must reuse the same upstream session.

    This is the non-regression side of the #4205 fix: the registry still
    amortises the MCP ``initialize`` round-trip across many tool calls from
    the same downstream client. Breaking this would turn the fix into a
    throughput regression.
    """
    _, created = counter_factory_and_log
    gateway_id = "counter-gateway"
    url = "http://counter.example/mcp"

    for _ in range(10):
        async with registry.acquire(
            downstream_session_id="session-single",
            gateway_id=gateway_id,
            url=url,
            headers=None,
            transport_type=TransportType.STREAMABLE_HTTP,
        ) as upstream:
            await upstream.session.call_tool("increment")

    # Exactly one upstream session built — the registry reused it across the
    # ten calls.
    assert len(created) == 1
    assert created[0].counter == 10
    # Registry counters show nine reuses (one create + nine reuses = ten acquires).
    snap = registry.snapshot()
    assert snap.creates == 1
    assert snap.reuses == 9
    assert snap.active_sessions == 1


@pytest.mark.asyncio
async def test_issue_4205_evict_session_closes_upstream_so_next_acquire_rebuilds(registry, counter_factory_and_log):
    """``evict_session`` (wired into DELETE /mcp in the transport) must release upstream state.

    When a downstream client ends its MCP session, the upstream session
    bound to it has to close. The next client using the same session id
    (e.g. the same user reconnecting after a restart) must get a fresh
    counter — not pick up wherever the previous client left off.
    """
    _, created = counter_factory_and_log
    gateway_id = "counter-gateway"
    url = "http://counter.example/mcp"

    async with registry.acquire(
        downstream_session_id="session-reconnect",
        gateway_id=gateway_id,
        url=url,
        headers=None,
        transport_type=TransportType.STREAMABLE_HTTP,
    ) as upstream:
        await upstream.session.call_tool("increment")
        await upstream.session.call_tool("increment")

    evicted = await registry.evict_session("session-reconnect")
    assert evicted == 1

    # Fresh acquire with the same downstream session id → brand-new upstream,
    # brand-new counter.
    async with registry.acquire(
        downstream_session_id="session-reconnect",
        gateway_id=gateway_id,
        url=url,
        headers=None,
        transport_type=TransportType.STREAMABLE_HTTP,
    ) as upstream:
        result = await upstream.session.call_tool("get_counter")

    assert result["content"][0]["text"] == "0"
    assert len(created) == 2, "second acquire after evict must build a new upstream session"
    # The first instance stopped at 2, the second at 0.
    assert sorted(s.counter for s in created) == [0, 2]


@pytest.mark.asyncio
async def test_issue_4205_same_session_across_different_gateways_stays_isolated(registry, counter_factory_and_log):
    """One downstream session talking to two gateways must get two upstreams.

    A downstream MCP session can fan out to tools served by multiple
    federated gateways. Each gateway needs its own upstream ClientSession
    (different URL, possibly different credentials). The registry keys
    by ``(downstream_session_id, gateway_id)`` so this falls out naturally.
    This test pins that invariant; a regression that collapsed the key to
    just ``downstream_session_id`` would mix state from unrelated upstreams
    under the same downstream client, a subtle but equally-nasty variant
    of #4205.
    """
    _, created = counter_factory_and_log
    url_gw1 = "http://gw1.example/mcp"
    url_gw2 = "http://gw2.example/mcp"

    # Gateway 1, two increments.
    for _ in range(2):
        async with registry.acquire(
            downstream_session_id="session-fanout",
            gateway_id="gw-1",
            url=url_gw1,
            headers=None,
            transport_type=TransportType.STREAMABLE_HTTP,
        ) as upstream:
            await upstream.session.call_tool("increment")

    # Gateway 2, four increments.
    for _ in range(4):
        async with registry.acquire(
            downstream_session_id="session-fanout",
            gateway_id="gw-2",
            url=url_gw2,
            headers=None,
            transport_type=TransportType.STREAMABLE_HTTP,
        ) as upstream:
            await upstream.session.call_tool("increment")

    assert len(created) == 2
    assert sorted(s.counter for s in created) == [2, 4]
