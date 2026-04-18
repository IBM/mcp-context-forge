# -*- coding: utf-8 -*-
"""Unit tests for UpstreamSessionRegistry (issue #4205).

The registry's contract under test:
  - 1:1 binding of (downstream_session_id, gateway_id) to an upstream MCP
    ClientSession. Never shared across downstream sessions.
  - Within one downstream session, concurrent acquires for the same gateway
    reuse a single upstream session (connection reuse survives).
  - Idle reuse triggers a health probe; a failed probe recreates.
  - evict_session / evict_gateway / close_all close the owner task cleanly.
  - The registry is in-process only; multi-worker correctness is the concern
    of the session-affinity layer (not tested here).

Tests avoid real MCP transports by injecting a fake SessionFactory that
returns a FakeClientSession recording the probe calls it receives.

Copyright 2026
SPDX-License-Identifier: Apache-2.0
"""

# Future
from __future__ import annotations

# Standard
import asyncio

# Third-Party
import pytest

# First-Party
from mcpgateway.services.upstream_session_registry import (
    TransportType,
    UpstreamSessionRegistry,
    _SessionCreateRequest,
    get_upstream_session_registry,
    init_upstream_session_registry,
    shutdown_upstream_session_registry,
)

# --------------------------------------------------------------------------- #
# Test doubles                                                                 #
# --------------------------------------------------------------------------- #


class FakeClientSession:
    """Stand-in for mcp.ClientSession. Records probe calls; controllable health."""

    def __init__(self) -> None:
        self.ping_calls = 0
        self.list_tools_calls = 0
        self.healthy = True
        self.probe_exception: BaseException | None = None

    async def send_ping(self) -> None:
        self.ping_calls += 1
        if self.probe_exception is not None:
            raise self.probe_exception
        if not self.healthy:
            # Use a transport-level error — production _probe_health narrows its
            # catch to (OSError, ...) so unexpected exception classes propagate
            # as signals of SDK drift rather than silent reconnect loops.
            raise OSError("ping failed")

    async def list_tools(self) -> None:
        self.list_tools_calls += 1
        if not self.healthy:
            raise OSError("list_tools failed")


def _make_fake_factory():
    """Return (factory, created_sessions) — tests can inspect what was built."""
    created: list[tuple[_SessionCreateRequest, FakeClientSession, asyncio.Event, asyncio.Task]] = []

    async def factory(req: _SessionCreateRequest):
        session = FakeClientSession()
        shutdown_event = asyncio.Event()

        async def owner() -> None:
            # Behaves like the real owner task: block on shutdown_event, then exit.
            await shutdown_event.wait()

        task = asyncio.create_task(owner(), name="fake-owner")
        # Match the real factory's smuggling convention so the registry can
        # find the owner task + shutdown event without a return-value contract.
        session._cf_owner_task = task  # type: ignore[attr-defined]
        session._cf_shutdown_event = shutdown_event  # type: ignore[attr-defined]
        created.append((req, session, shutdown_event, task))
        return session, object()  # transport_ctx is opaque to the registry

    return factory, created


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #


@pytest.fixture
def factory_and_records():
    return _make_fake_factory()


@pytest.fixture
async def registry(factory_and_records):
    factory, _ = factory_and_records
    reg = UpstreamSessionRegistry(
        session_factory=factory,
        idle_validation_seconds=0.05,
        health_check_timeout_seconds=1.0,
        session_create_timeout_seconds=1.0,
        shutdown_timeout_seconds=1.0,
    )
    yield reg
    await reg.close_all()


# --------------------------------------------------------------------------- #
# Core contract                                                                #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_acquire_creates_new_session_for_unseen_key(registry, factory_and_records):
    _, created = factory_and_records
    async with registry.acquire(
        downstream_session_id="s1",
        gateway_id="g1",
        url="http://upstream/mcp",
        headers=None,
        transport_type=TransportType.STREAMABLE_HTTP,
    ) as upstream:
        assert upstream.downstream_session_id == "s1"
        assert upstream.gateway_id == "g1"

    assert len(created) == 1
    snapshot = registry.snapshot()
    assert snapshot.creates == 1
    assert snapshot.reuses == 0
    assert snapshot.active_sessions == 1


@pytest.mark.asyncio
async def test_acquire_reuses_same_session_for_same_key(registry, factory_and_records):
    _, created = factory_and_records
    for _ in range(3):
        async with registry.acquire(
            downstream_session_id="s1",
            gateway_id="g1",
            url="http://upstream/mcp",
            headers=None,
            transport_type=TransportType.STREAMABLE_HTTP,
        ):
            pass

    # Only one upstream session ever built; the other two acquires reused it.
    assert len(created) == 1
    snapshot = registry.snapshot()
    assert snapshot.creates == 1
    assert snapshot.reuses == 2


@pytest.mark.asyncio
async def test_isolation_different_downstream_sessions_get_different_upstream_sessions(registry, factory_and_records):
    """The core #4205 invariant: session A must not share upstream with session B."""
    _, created = factory_and_records

    async with registry.acquire(
        downstream_session_id="session-A",
        gateway_id="g1",
        url="http://upstream/mcp",
        headers=None,
        transport_type=TransportType.STREAMABLE_HTTP,
    ) as upstream_a:
        pass

    async with registry.acquire(
        downstream_session_id="session-B",
        gateway_id="g1",
        url="http://upstream/mcp",
        headers=None,
        transport_type=TransportType.STREAMABLE_HTTP,
    ) as upstream_b:
        pass

    assert len(created) == 2
    assert upstream_a.session is not upstream_b.session
    assert registry.snapshot().active_sessions == 2


@pytest.mark.asyncio
async def test_same_session_across_different_gateways_builds_distinct_upstreams(registry, factory_and_records):
    _, created = factory_and_records
    async with registry.acquire(
        downstream_session_id="s1",
        gateway_id="g1",
        url="http://upstream-1/mcp",
        headers=None,
        transport_type=TransportType.STREAMABLE_HTTP,
    ):
        pass
    async with registry.acquire(
        downstream_session_id="s1",
        gateway_id="g2",
        url="http://upstream-2/mcp",
        headers=None,
        transport_type=TransportType.STREAMABLE_HTTP,
    ):
        pass

    assert len(created) == 2
    assert registry.snapshot().active_sessions == 2


@pytest.mark.asyncio
async def test_missing_downstream_session_id_is_rejected(registry):
    with pytest.raises(ValueError, match="downstream_session_id is required"):
        async with registry.acquire(
            downstream_session_id="",
            gateway_id="g1",
            url="http://upstream/mcp",
            headers=None,
            transport_type=TransportType.STREAMABLE_HTTP,
        ):
            pass


@pytest.mark.asyncio
async def test_missing_gateway_id_is_rejected(registry):
    with pytest.raises(ValueError, match="gateway_id is required"):
        async with registry.acquire(
            downstream_session_id="s1",
            gateway_id="",
            url="http://upstream/mcp",
            headers=None,
            transport_type=TransportType.STREAMABLE_HTTP,
        ):
            pass


# --------------------------------------------------------------------------- #
# Concurrency                                                                  #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_concurrent_acquires_for_same_key_create_exactly_one_session(factory_and_records):
    """Per-key lock must prevent two acquires from racing two upstream creates."""
    factory, created = factory_and_records

    # Slow the factory so both tasks pile up on the per-key lock.
    original = factory
    barrier = asyncio.Event()

    async def slow_factory(req: _SessionCreateRequest):
        await barrier.wait()
        return await original(req)

    reg = UpstreamSessionRegistry(session_factory=slow_factory, idle_validation_seconds=1_000)

    async def one_acquire():
        async with reg.acquire(
            downstream_session_id="s1",
            gateway_id="g1",
            url="http://upstream/mcp",
            headers=None,
            transport_type=TransportType.STREAMABLE_HTTP,
        ):
            pass

    task_a = asyncio.create_task(one_acquire())
    task_b = asyncio.create_task(one_acquire())
    # Let both reach the lock.
    await asyncio.sleep(0.01)
    barrier.set()
    await task_a
    await task_b

    assert len(created) == 1
    snap = reg.snapshot()
    assert snap.creates == 1
    assert snap.reuses == 1
    await reg.close_all()


# --------------------------------------------------------------------------- #
# Health probe on reuse                                                        #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_idle_reuse_triggers_health_probe_and_reuses_on_success(registry, factory_and_records):
    _, created = factory_and_records
    async with registry.acquire(
        downstream_session_id="s1",
        gateway_id="g1",
        url="http://upstream/mcp",
        headers=None,
        transport_type=TransportType.STREAMABLE_HTTP,
    ):
        pass

    # Push idle past the validation threshold.
    session = created[0][1]
    assert session.ping_calls == 0
    await asyncio.sleep(0.06)  # idle_validation_seconds=0.05 in the fixture

    async with registry.acquire(
        downstream_session_id="s1",
        gateway_id="g1",
        url="http://upstream/mcp",
        headers=None,
        transport_type=TransportType.STREAMABLE_HTTP,
    ):
        pass

    assert session.ping_calls == 1
    assert len(created) == 1
    assert registry.snapshot().reuses == 1


@pytest.mark.asyncio
async def test_failed_health_probe_recreates_session(registry, factory_and_records):
    _, created = factory_and_records
    async with registry.acquire(
        downstream_session_id="s1",
        gateway_id="g1",
        url="http://upstream/mcp",
        headers=None,
        transport_type=TransportType.STREAMABLE_HTTP,
    ):
        pass

    # Mark the existing session unhealthy on ALL probe methods.
    original = created[0][1]
    original.healthy = False

    await asyncio.sleep(0.06)

    async with registry.acquire(
        downstream_session_id="s1",
        gateway_id="g1",
        url="http://upstream/mcp",
        headers=None,
        transport_type=TransportType.STREAMABLE_HTTP,
    ):
        pass

    assert len(created) == 2
    snap = registry.snapshot()
    assert snap.creates == 2
    assert snap.health_check_recreates == 1
    assert snap.health_check_failures >= 1


# --------------------------------------------------------------------------- #
# Eviction                                                                     #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_evict_session_closes_all_upstreams_for_that_downstream_session(registry, factory_and_records):
    _, created = factory_and_records
    for gw in ("g1", "g2"):
        async with registry.acquire(
            downstream_session_id="s1",
            gateway_id=gw,
            url=f"http://{gw}/mcp",
            headers=None,
            transport_type=TransportType.STREAMABLE_HTTP,
        ):
            pass
    async with registry.acquire(
        downstream_session_id="s2",
        gateway_id="g1",
        url="http://g1/mcp",
        headers=None,
        transport_type=TransportType.STREAMABLE_HTTP,
    ):
        pass
    assert registry.snapshot().active_sessions == 3

    evicted = await registry.evict_session("s1")

    assert evicted == 2
    assert registry.snapshot().active_sessions == 1
    # s1's owner tasks completed cleanly; s2's still running.
    s1_tasks = [rec[3] for rec in created if rec[0].downstream_session_id == "s1"]
    s2_tasks = [rec[3] for rec in created if rec[0].downstream_session_id == "s2"]
    for t in s1_tasks:
        assert t.done()
    for t in s2_tasks:
        assert not t.done()


@pytest.mark.asyncio
async def test_evict_gateway_closes_every_upstream_for_that_gateway(registry, factory_and_records):
    _, created = factory_and_records
    for sid in ("s1", "s2", "s3"):
        async with registry.acquire(
            downstream_session_id=sid,
            gateway_id="g-target",
            url="http://g-target/mcp",
            headers=None,
            transport_type=TransportType.STREAMABLE_HTTP,
        ):
            pass
    async with registry.acquire(
        downstream_session_id="s1",
        gateway_id="g-other",
        url="http://g-other/mcp",
        headers=None,
        transport_type=TransportType.STREAMABLE_HTTP,
    ):
        pass

    evicted = await registry.evict_gateway("g-target")

    assert evicted == 3
    assert registry.snapshot().active_sessions == 1


@pytest.mark.asyncio
async def test_evict_session_for_unknown_id_is_a_noop(registry):
    evicted = await registry.evict_session("never-existed")
    assert evicted == 0


@pytest.mark.asyncio
async def test_close_all_drains_every_session(registry, factory_and_records):
    _, created = factory_and_records
    for sid in ("s1", "s2"):
        async with registry.acquire(
            downstream_session_id=sid,
            gateway_id="g1",
            url="http://upstream/mcp",
            headers=None,
            transport_type=TransportType.STREAMABLE_HTTP,
        ):
            pass
    assert registry.snapshot().active_sessions == 2

    await registry.close_all()

    assert registry.snapshot().active_sessions == 0
    assert registry.snapshot().evictions == 2
    for rec in created:
        assert rec[3].done()


# --------------------------------------------------------------------------- #
# Dead-session detection                                                       #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_dead_owner_task_forces_recreate_on_next_acquire(registry, factory_and_records):
    """If the owner task died (e.g., upstream dropped), the next acquire rebuilds."""
    _, created = factory_and_records
    async with registry.acquire(
        downstream_session_id="s1",
        gateway_id="g1",
        url="http://upstream/mcp",
        headers=None,
        transport_type=TransportType.STREAMABLE_HTTP,
    ):
        pass

    # Kill the owner task out of band.
    _, _, shutdown_event, task = created[0]
    shutdown_event.set()
    await task

    # Next acquire sees is_closed == True and rebuilds.
    async with registry.acquire(
        downstream_session_id="s1",
        gateway_id="g1",
        url="http://upstream/mcp",
        headers=None,
        transport_type=TransportType.STREAMABLE_HTTP,
    ):
        pass

    assert len(created) == 2
    assert registry.snapshot().creates == 2


# --------------------------------------------------------------------------- #
# Header stripping                                                             #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_gateway_internal_session_headers_are_stripped_before_upstream(registry, factory_and_records):
    _, created = factory_and_records
    async with registry.acquire(
        downstream_session_id="s1",
        gateway_id="g1",
        url="http://upstream/mcp",
        headers={
            "Authorization": "Bearer token",
            "Mcp-Session-Id": "should-not-leak",
            "X-Mcp-Session-Id": "also-should-not-leak",
        },
        transport_type=TransportType.STREAMABLE_HTTP,
    ):
        pass

    forwarded_headers = created[0][0].headers
    # Authorization passes through; gateway-internal session id headers do not.
    assert forwarded_headers.get("Authorization") == "Bearer token"
    assert "Mcp-Session-Id" not in forwarded_headers
    assert "X-Mcp-Session-Id" not in forwarded_headers
    # The SDK always wants this Accept value.
    assert forwarded_headers.get("Accept") == "application/json, text/event-stream"


# --------------------------------------------------------------------------- #
# Singleton accessors                                                          #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_singleton_accessors_round_trip():
    # A fresh process starts uninitialized.
    with pytest.raises(RuntimeError, match="has not been initialized"):
        get_upstream_session_registry()

    reg = init_upstream_session_registry()
    assert get_upstream_session_registry() is reg

    await shutdown_upstream_session_registry()
    with pytest.raises(RuntimeError, match="has not been initialized"):
        get_upstream_session_registry()
