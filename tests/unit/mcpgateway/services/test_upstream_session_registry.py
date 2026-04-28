# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_upstream_session_registry.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for UpstreamSessionRegistry (issue #4205).
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
"""

# Future
from __future__ import annotations

# Standard
import asyncio

# Third-Party
import pytest

# First-Party
from mcpgateway.services.upstream_session_registry import (
    get_upstream_session_registry,
    init_upstream_session_registry,
    SessionCreateRequest,
    shutdown_upstream_session_registry,
    TransportType,
    UpstreamSessionRegistry,
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
    created: list[tuple[SessionCreateRequest, FakeClientSession, asyncio.Event, asyncio.Task]] = []

    async def factory(req: SessionCreateRequest):
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

    async def slow_factory(req: SessionCreateRequest):
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


# ---------------------------------------------------------------------------
# Health probe branch coverage
# ---------------------------------------------------------------------------


class _ProbeChainSession:
    """Fake MCP ClientSession where each of the four probes can be programmed independently.

    Used to exercise the METHOD_NOT_FOUND / TimeoutError / success branches of
    UpstreamSessionRegistry._probe_health without needing a real MCP server.
    """

    def __init__(self, behaviours: dict):
        """behaviours maps method name → one of ('ok', 'method_not_found', 'timeout', 'oserror')."""
        self.behaviours = behaviours
        self.calls: list[str] = []

    async def _run(self, name: str) -> None:
        self.calls.append(name)
        b = self.behaviours.get(name, "ok")
        if b == "ok":
            return
        if b == "method_not_found":
            # Third-Party
            from mcp import McpError
            from mcp.types import ErrorData

            raise McpError(ErrorData(code=-32601, message="method not found"))
        if b == "timeout":
            raise TimeoutError("probe timed out")
        if b == "oserror":
            raise OSError("transport died")
        raise RuntimeError(f"unexpected behaviour {b}")

    async def send_ping(self) -> None:
        await self._run("ping")

    async def list_tools(self) -> None:
        await self._run("list_tools")

    async def list_prompts(self) -> None:
        await self._run("list_prompts")

    async def list_resources(self) -> None:
        await self._run("list_resources")


def _make_upstream_for_probe(session: _ProbeChainSession):
    """Build an UpstreamSession record wrapping the probe fake."""
    # First-Party
    from mcpgateway.services.upstream_session_registry import TransportType, UpstreamSession

    return UpstreamSession(
        downstream_session_id="s1",
        gateway_id="g1",
        url="http://probe/mcp",
        transport_type=TransportType.STREAMABLE_HTTP,
        session=session,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_probe_health_method_not_found_advances_to_next_probe(factory_and_records):
    """A server that 405s `ping` with METHOD_NOT_FOUND must advance to `list_tools`, not recreate."""
    factory, _ = factory_and_records
    reg = UpstreamSessionRegistry(session_factory=factory, idle_validation_seconds=1.0)
    session = _ProbeChainSession({"ping": "method_not_found", "list_tools": "ok"})
    upstream = _make_upstream_for_probe(session)

    assert await reg._probe_health(upstream) is True  # pylint: disable=protected-access
    assert session.calls == ["ping", "list_tools"]


@pytest.mark.asyncio
async def test_probe_health_timeout_advances_to_next_probe(factory_and_records):
    """A probe that times out must advance, not recreate — slow network ≠ dead session."""
    factory, _ = factory_and_records
    reg = UpstreamSessionRegistry(session_factory=factory, idle_validation_seconds=1.0)
    session = _ProbeChainSession({"ping": "timeout", "list_tools": "ok"})
    upstream = _make_upstream_for_probe(session)

    assert await reg._probe_health(upstream) is True  # pylint: disable=protected-access
    assert session.calls == ["ping", "list_tools"]


@pytest.mark.asyncio
async def test_probe_health_all_method_not_found_terminates_with_skip_returning_true(factory_and_records):
    """A server implementing none of the four probes still passes via the `skip` terminator."""
    factory, _ = factory_and_records
    reg = UpstreamSessionRegistry(session_factory=factory, idle_validation_seconds=1.0)
    session = _ProbeChainSession(
        {
            "ping": "method_not_found",
            "list_tools": "method_not_found",
            "list_prompts": "method_not_found",
            "list_resources": "method_not_found",
        }
    )
    upstream = _make_upstream_for_probe(session)

    assert await reg._probe_health(upstream) is True  # pylint: disable=protected-access
    assert session.calls == ["ping", "list_tools", "list_prompts", "list_resources"]


@pytest.mark.asyncio
async def test_probe_health_oserror_bails_out_early(factory_and_records):
    """OSError on the first probe means transport is dead; don't try the rest."""
    factory, _ = factory_and_records
    reg = UpstreamSessionRegistry(session_factory=factory, idle_validation_seconds=1.0)
    session = _ProbeChainSession({"ping": "oserror"})
    upstream = _make_upstream_for_probe(session)

    assert await reg._probe_health(upstream) is False  # pylint: disable=protected-access
    assert session.calls == ["ping"]
    assert reg.snapshot().health_check_failures == 1


@pytest.mark.asyncio
async def test_probe_health_unexpected_exception_propagates(factory_and_records):
    """An AttributeError from SDK drift must propagate so telemetry sees it, not silently recreate."""
    factory, _ = factory_and_records
    reg = UpstreamSessionRegistry(session_factory=factory, idle_validation_seconds=1.0)

    class _BrokenSession:
        async def send_ping(self):
            raise AttributeError("_write_stream removed from ClientSession in MCP SDK vNext")

    upstream = _make_upstream_for_probe(_BrokenSession())
    with pytest.raises(AttributeError):
        await reg._probe_health(upstream)  # pylint: disable=protected-access


# ---------------------------------------------------------------------------
# close_all() drain semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_all_drains_in_parallel_not_series():
    """close_all() must run evictions concurrently — serial drain would stall multi-session shutdowns.

    We inject a factory whose owner task takes ~0.3s to drain; with 5 sessions a
    serial drain would need ~1.5s while a parallel drain completes in ~0.3s.
    Asserting with a generous headroom (0.9s) so CI scheduling jitter doesn't flake.
    """
    # Standard
    import time as _time

    created_events: list[asyncio.Event] = []

    async def slow_drain_factory(req):
        session = FakeClientSession()
        shutdown_event = asyncio.Event()
        created_events.append(shutdown_event)

        async def owner():
            await shutdown_event.wait()
            # Simulate slow transport teardown AFTER shutdown is signalled.
            await asyncio.sleep(0.3)

        task = asyncio.create_task(owner(), name="slow-owner")
        session._cf_owner_task = task  # type: ignore[attr-defined]
        session._cf_shutdown_event = shutdown_event  # type: ignore[attr-defined]
        return session, object()

    reg = UpstreamSessionRegistry(
        session_factory=slow_drain_factory,
        shutdown_timeout_seconds=2.0,
    )

    for i in range(5):
        async with reg.acquire(
            downstream_session_id=f"s{i}",
            gateway_id="g1",
            url="http://upstream/mcp",
            headers=None,
            transport_type=TransportType.STREAMABLE_HTTP,
        ):
            pass

    assert reg.snapshot().active_sessions == 5

    start = _time.monotonic()
    await reg.close_all()
    elapsed = _time.monotonic() - start

    assert reg.snapshot().active_sessions == 0
    assert elapsed < 0.9, f"close_all took {elapsed:.2f}s — drain appears to be serial, not parallel"


@pytest.mark.asyncio
async def test_close_all_continues_past_failing_evict():
    """A failing _evict_key for one session must not prevent the others from draining.

    close_all() uses asyncio.gather(..., return_exceptions=True) precisely so one
    broken session doesn't orphan the rest at shutdown. A regression that reverts
    to serial execution — or forgets return_exceptions — would fail this test.
    """
    factory, _ = _make_fake_factory()
    reg = UpstreamSessionRegistry(session_factory=factory, shutdown_timeout_seconds=1.0)

    for i in range(3):
        async with reg.acquire(
            downstream_session_id=f"s{i}",
            gateway_id="g1",
            url="http://upstream/mcp",
            headers=None,
            transport_type=TransportType.STREAMABLE_HTTP,
        ):
            pass

    # Poison _evict_key for one specific key so close_all hits an exception mid-drain.
    original_evict = reg._evict_key  # pylint: disable=protected-access

    async def flaky_evict(key):
        if key[0] == "s1":
            raise RuntimeError("evict failure for s1 only")
        return await original_evict(key)

    reg._evict_key = flaky_evict  # type: ignore[method-assign]

    await reg.close_all()

    # The two non-poisoned sessions must still be drained.
    remaining = [k for k in reg._sessions]  # pylint: disable=protected-access
    assert ("s0", "g1") not in remaining
    assert ("s2", "g1") not in remaining


# ---------------------------------------------------------------------------
# acquire() yield-body transport-error eviction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_acquire_evicts_on_closed_resource_error_in_body(registry, factory_and_records):
    """A ClosedResourceError raised inside the acquire() body must evict and re-raise."""
    # Third-Party
    import anyio

    _, created = factory_and_records
    with pytest.raises(anyio.ClosedResourceError):
        async with registry.acquire(
            downstream_session_id="s1",
            gateway_id="g1",
            url="http://upstream/mcp",
            headers=None,
            transport_type=TransportType.STREAMABLE_HTTP,
        ):
            raise anyio.ClosedResourceError()

    assert len(created) == 1  # the session was built
    assert registry.snapshot().active_sessions == 0  # and then evicted


@pytest.mark.asyncio
async def test_acquire_evicts_on_broken_resource_error_in_body(registry, factory_and_records):
    """A BrokenResourceError must also trigger eviction (symmetric to ClosedResourceError)."""
    # Third-Party
    import anyio

    _, _ = factory_and_records
    with pytest.raises(anyio.BrokenResourceError):
        async with registry.acquire(
            downstream_session_id="s1",
            gateway_id="g1",
            url="http://upstream/mcp",
            headers=None,
            transport_type=TransportType.STREAMABLE_HTTP,
        ):
            raise anyio.BrokenResourceError()

    assert registry.snapshot().active_sessions == 0


@pytest.mark.asyncio
async def test_acquire_evicts_on_oserror_in_body(registry, factory_and_records):
    """OSError from a broken socket must trigger eviction."""
    _, _ = factory_and_records
    with pytest.raises(OSError, match="socket hung up"):
        async with registry.acquire(
            downstream_session_id="s1",
            gateway_id="g1",
            url="http://upstream/mcp",
            headers=None,
            transport_type=TransportType.STREAMABLE_HTTP,
        ):
            raise OSError("socket hung up")

    assert registry.snapshot().active_sessions == 0


@pytest.mark.asyncio
async def test_acquire_does_not_evict_on_plain_value_error_in_body(registry, factory_and_records):
    """A caller-level exception (ValueError, etc.) leaves the session intact — the transport is fine."""
    _, _ = factory_and_records
    with pytest.raises(ValueError, match="caller-level bug"):
        async with registry.acquire(
            downstream_session_id="s1",
            gateway_id="g1",
            url="http://upstream/mcp",
            headers=None,
            transport_type=TransportType.STREAMABLE_HTTP,
        ):
            raise ValueError("caller-level bug")

    # Session stays put — next acquire reuses it.
    assert registry.snapshot().active_sessions == 1


# ---------------------------------------------------------------------------
# MCP SDK-internals transport-broken probe
# ---------------------------------------------------------------------------


def test_mcp_transport_is_broken_returns_false_when_session_has_no_write_stream():
    """No ``_write_stream`` attribute → we can't positively say the transport is dead."""
    # First-Party
    from mcpgateway.services.upstream_session_registry import _mcp_transport_is_broken

    class _Bare:
        pass

    assert _mcp_transport_is_broken(_Bare()) is False  # type: ignore[arg-type]


def test_mcp_transport_is_broken_detects_closed_write_stream():
    """Closed write stream is the clearest "transport gone" signal."""
    # First-Party
    from mcpgateway.services.upstream_session_registry import _mcp_transport_is_broken

    class _Stream:
        _closed = True

    class _Session:
        _write_stream = _Stream()

    assert _mcp_transport_is_broken(_Session()) is True  # type: ignore[arg-type]


def test_mcp_transport_is_broken_detects_drained_receive_channels():
    """open_receive_channels == 0 means all readers hung up."""
    # First-Party
    from mcpgateway.services.upstream_session_registry import _mcp_transport_is_broken

    class _State:
        open_receive_channels = 0

    class _Stream:
        _closed = False
        _state = _State()

    class _Session:
        _write_stream = _Stream()

    assert _mcp_transport_is_broken(_Session()) is True  # type: ignore[arg-type]


def test_mcp_transport_is_broken_first_drift_logs_warning_then_degrades_to_debug(caplog, monkeypatch):
    """First SDK-drift event per process is WARNING; subsequent events are DEBUG so sustained drift doesn't spam."""
    # First-Party
    from mcpgateway.services import upstream_session_registry as usr

    # Reset the one-shot sentinel so repeated test runs see first-call behaviour.
    monkeypatch.setattr(usr, "_sdk_drift_warning_emitted", False)

    class _BrokenStream:
        @property
        def _closed(self):
            # Not AttributeError — getattr() would silently swallow that.
            # RuntimeError simulates SDK internals that raise in a way the
            # probe can't recover from, so we fall through to the catch.
            raise RuntimeError("SDK drift: _closed raised from property")

    class _Session:
        _write_stream = _BrokenStream()

    # First call: WARNING expected.
    with caplog.at_level("DEBUG", logger=usr.logger.name):
        assert usr._mcp_transport_is_broken(_Session()) is False  # pylint: disable=protected-access  # type: ignore[arg-type]
    warnings = [rec for rec in caplog.records if rec.levelname == "WARNING" and "MCP transport-broken probe raised" in rec.getMessage()]
    assert len(warnings) == 1
    assert "SDK" in warnings[0].getMessage()  # mentions the validated range
    caplog.clear()

    # Second call on the same process: DEBUG only, no new WARNING.
    with caplog.at_level("DEBUG", logger=usr.logger.name):
        assert usr._mcp_transport_is_broken(_Session()) is False  # pylint: disable=protected-access  # type: ignore[arg-type]
    assert not any(rec.levelname == "WARNING" for rec in caplog.records)
    assert any(rec.levelname == "DEBUG" and "MCP transport-broken probe raised" in rec.getMessage() for rec in caplog.records)


# ---------------------------------------------------------------------------
# SessionCreateRequest validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs,match",
    [
        ({"url": ""}, r"url must be a non-empty string"),
        ({"downstream_session_id": ""}, r"downstream_session_id must be a non-empty string"),
        ({"timeout_seconds": 0}, r"timeout_seconds must be positive"),
        ({"timeout_seconds": -1.0}, r"timeout_seconds must be positive"),
        ({"gateway_id": ""}, r"gateway_id must be non-empty when provided"),
    ],
)
def test_session_create_request_rejects_invalid_inputs(kwargs, match):
    """Constructor validates inputs so bad callers fail loudly, not silently."""
    base = dict(
        url="http://u/mcp",
        transport_type=TransportType.STREAMABLE_HTTP,
        headers={},
        gateway_id="g1",
        downstream_session_id="s1",
        httpx_client_factory=None,
        message_handler_factory=None,
        timeout_seconds=5.0,
    )
    base.update(kwargs)
    with pytest.raises(ValueError, match=match):
        SessionCreateRequest(**base)


def test_session_create_request_is_frozen():
    """Frozen dataclass: the factory must not mutate the request it was handed."""
    req = SessionCreateRequest(
        url="http://u/mcp",
        transport_type=TransportType.STREAMABLE_HTTP,
        headers={},
        gateway_id="g1",
        downstream_session_id="s1",
        httpx_client_factory=None,
        message_handler_factory=None,
        timeout_seconds=5.0,
    )
    # Standard
    import dataclasses

    with pytest.raises(dataclasses.FrozenInstanceError):
        req.url = "http://other/mcp"  # type: ignore[misc]


def test_session_create_request_headers_are_immutable():
    """Headers are wrapped in MappingProxyType; in-place mutation must fail."""
    original = {"Authorization": "Bearer abc"}
    req = SessionCreateRequest(
        url="http://u/mcp",
        transport_type=TransportType.STREAMABLE_HTTP,
        headers=original,
        gateway_id="g1",
        downstream_session_id="s1",
        httpx_client_factory=None,
        message_handler_factory=None,
        timeout_seconds=5.0,
    )
    # The post-init defensively copies + freezes, so mutating the original
    # dict after construction must not leak into the frozen request.
    original["Authorization"] = "Bearer evil"
    assert req.headers["Authorization"] == "Bearer abc"

    # In-place mutation via the frozen proxy must fail.
    with pytest.raises(TypeError):
        req.headers["Authorization"] = "Bearer evil"  # type: ignore[index]
    with pytest.raises((TypeError, AttributeError)):
        req.headers.clear()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# UpstreamSession identity immutability
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field_name,new_value",
    [
        ("downstream_session_id", "other-session"),
        ("gateway_id", "other-gateway"),
        ("url", "http://elsewhere/mcp"),
        ("transport_type", TransportType.SSE),
    ],
)
def test_upstream_session_identity_fields_are_immutable(field_name, new_value):
    """Reassigning any of the four identity fields after construction raises AttributeError."""
    # First-Party
    from mcpgateway.services.upstream_session_registry import UpstreamSession

    upstream = UpstreamSession(
        downstream_session_id="s1",
        gateway_id="g1",
        url="http://upstream/mcp",
        transport_type=TransportType.STREAMABLE_HTTP,
        session=object(),  # type: ignore[arg-type]
    )
    with pytest.raises(AttributeError, match=f"{field_name!r} is immutable"):
        setattr(upstream, field_name, new_value)


def test_upstream_session_bookkeeping_fields_remain_mutable():
    """Non-identity fields (last_used, use_count, _closed) must stay mutable — the registry updates them."""
    # First-Party
    from mcpgateway.services.upstream_session_registry import UpstreamSession

    upstream = UpstreamSession(
        downstream_session_id="s1",
        gateway_id="g1",
        url="http://upstream/mcp",
        transport_type=TransportType.STREAMABLE_HTTP,
        session=object(),  # type: ignore[arg-type]
    )
    upstream.last_used = 1234.0
    upstream.use_count = 5
    upstream._closed = True  # pylint: disable=protected-access
    assert upstream.last_used == 1234.0
    assert upstream.use_count == 5
    assert upstream.is_closed is True


# ---------------------------------------------------------------------------
# _default_session_factory — transport + owner-task glue
# ---------------------------------------------------------------------------


class _FakeTransportCtx:
    """Async-CM stand-in for sse_client()/streamablehttp_client()."""

    def __init__(self, streams=(None, None), enter_exc: BaseException | None = None):
        self._streams = streams
        self._enter_exc = enter_exc
        self.entered = False
        self.exited = False

    async def __aenter__(self):
        self.entered = True
        if self._enter_exc is not None:
            raise self._enter_exc
        return self._streams

    async def __aexit__(self, exc_type, exc, tb):
        self.exited = True
        return False


class _FakeClientSessionCM:
    """Async-CM stand-in for mcp.ClientSession(...)."""

    last_message_handler = None

    def __init__(self, read_stream, write_stream, message_handler=None):
        self._read = read_stream
        self._write = write_stream
        _FakeClientSessionCM.last_message_handler = message_handler
        self.initialized = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def initialize(self):
        self.initialized = True


def _make_request(**overrides):
    """Build a SessionCreateRequest with sensible defaults."""
    defaults = dict(
        url="https://upstream.example.com/mcp",
        transport_type=TransportType.STREAMABLE_HTTP,
        headers={"h": "v"},
        gateway_id="g1",
        downstream_session_id="d1",
        httpx_client_factory=None,
        message_handler_factory=None,
        timeout_seconds=2.0,
    )
    defaults.update(overrides)
    return SessionCreateRequest(**defaults)


@pytest.mark.asyncio
async def test_default_session_factory_streamablehttp_path(monkeypatch):
    """STREAMABLEHTTP transport routes through streamablehttp_client and returns an initialized session."""
    # First-Party
    from mcpgateway.services import upstream_session_registry as usr

    captured = {}

    def fake_stream(**kwargs):
        captured.update(kwargs)
        captured["which"] = "streamable"
        return _FakeTransportCtx(streams=("r", "w", object()))

    def fake_sse(**_kwargs):
        raise AssertionError("sse_client must not be called for STREAMABLEHTTP transport")

    monkeypatch.setattr(usr, "streamablehttp_client", fake_stream)
    monkeypatch.setattr(usr, "sse_client", fake_sse)
    monkeypatch.setattr(usr, "ClientSession", _FakeClientSessionCM)

    req = _make_request()
    session, transport_ctx = await usr._default_session_factory(req)  # pylint: disable=protected-access

    assert isinstance(session, _FakeClientSessionCM)
    assert session.initialized is True
    assert captured["which"] == "streamable"
    assert captured["url"] == req.url
    assert captured["headers"] == req.headers
    assert transport_ctx.entered is True


@pytest.mark.asyncio
async def test_default_session_factory_sse_path(monkeypatch):
    """SSE transport routes through sse_client."""
    # First-Party
    from mcpgateway.services import upstream_session_registry as usr

    captured = {}

    def fake_sse(**kwargs):
        captured.update(kwargs)
        captured["which"] = "sse"
        return _FakeTransportCtx(streams=("r", "w"))

    def fake_stream(**_kwargs):
        raise AssertionError("streamablehttp_client must not be called for SSE transport")

    monkeypatch.setattr(usr, "sse_client", fake_sse)
    monkeypatch.setattr(usr, "streamablehttp_client", fake_stream)
    monkeypatch.setattr(usr, "ClientSession", _FakeClientSessionCM)

    req = _make_request(transport_type=TransportType.SSE)
    session, _ctx = await usr._default_session_factory(req)  # pylint: disable=protected-access

    assert session.initialized is True
    assert captured["which"] == "sse"


@pytest.mark.asyncio
async def test_default_session_factory_passes_httpx_factory(monkeypatch):
    """A provided httpx_client_factory is threaded through to the transport."""
    # First-Party
    from mcpgateway.services import upstream_session_registry as usr

    captured = {}
    sentinel_factory = object()

    def fake_stream(**kwargs):
        captured.update(kwargs)
        return _FakeTransportCtx(streams=("r", "w", object()))

    monkeypatch.setattr(usr, "streamablehttp_client", fake_stream)
    monkeypatch.setattr(usr, "ClientSession", _FakeClientSessionCM)

    req = _make_request(httpx_client_factory=sentinel_factory)
    await usr._default_session_factory(req)  # pylint: disable=protected-access

    assert captured.get("httpx_client_factory") is sentinel_factory


@pytest.mark.asyncio
async def test_default_session_factory_message_handler_factory_success(monkeypatch):
    """A provided message_handler_factory is called with (url, gateway_id, downstream_session_id) and its result flows into ClientSession."""
    # First-Party
    from mcpgateway.services import upstream_session_registry as usr

    sentinel_handler = object()
    factory_calls = []

    def handler_factory(url, gateway_id, *, downstream_session_id):
        factory_calls.append((url, gateway_id, downstream_session_id))
        return sentinel_handler

    monkeypatch.setattr(usr, "streamablehttp_client", lambda **_kw: _FakeTransportCtx(streams=("r", "w", object())))
    monkeypatch.setattr(usr, "ClientSession", _FakeClientSessionCM)

    req = _make_request(message_handler_factory=handler_factory)
    await usr._default_session_factory(req)  # pylint: disable=protected-access

    assert factory_calls == [(req.url, req.gateway_id, req.downstream_session_id)]
    assert _FakeClientSessionCM.last_message_handler is sentinel_handler


@pytest.mark.asyncio
async def test_default_session_factory_message_handler_factory_failure_is_logged_not_fatal(monkeypatch, caplog):
    """If the handler factory raises, the session still opens and the error is logged."""
    # First-Party
    from mcpgateway.services import upstream_session_registry as usr

    def bad_factory(_url, _gw, *, downstream_session_id):  # pylint: disable=unused-argument
        raise ValueError("handler factory boom")

    monkeypatch.setattr(usr, "streamablehttp_client", lambda **_kw: _FakeTransportCtx(streams=("r", "w", object())))
    monkeypatch.setattr(usr, "ClientSession", _FakeClientSessionCM)
    _FakeClientSessionCM.last_message_handler = "leftover"

    req = _make_request(message_handler_factory=bad_factory)
    with caplog.at_level("WARNING", logger=usr.logger.name):
        session, _ctx = await usr._default_session_factory(req)  # pylint: disable=protected-access

    assert session.initialized is True
    assert _FakeClientSessionCM.last_message_handler is None
    assert any("Failed to build message handler" in rec.getMessage() for rec in caplog.records)


@pytest.mark.asyncio
async def test_default_session_factory_transport_failure_raises_with_context(monkeypatch):
    """If the transport CM setup blows up, the factory caller sees a wrapped RuntimeError."""
    # First-Party
    from mcpgateway.services import upstream_session_registry as usr

    def fake_stream(**_kw):
        return _FakeTransportCtx(enter_exc=OSError("connect refused"))

    monkeypatch.setattr(usr, "streamablehttp_client", fake_stream)
    monkeypatch.setattr(usr, "ClientSession", _FakeClientSessionCM)

    req = _make_request()
    with pytest.raises(RuntimeError, match="Failed to create upstream MCP session"):
        await usr._default_session_factory(req)  # pylint: disable=protected-access


@pytest.mark.asyncio
async def test_default_session_factory_owner_task_exit_is_logged(monkeypatch, caplog):
    """A BaseException escaping the owner task after ready is set surfaces as WARNING via the done-callback.

    The owner's broad `except Exception` deliberately does NOT catch
    BaseException classes (SystemExit, KeyboardInterrupt) — they must propagate
    so the task exits promptly during shutdown. When they do, the task's
    `exception()` is non-None and the `_log_owner_exit` done-callback fires a
    WARNING so ops see the orphaned upstream session.
    """
    # First-Party
    from mcpgateway.services import upstream_session_registry as usr

    class _CustomBaseException(BaseException):
        """A BaseException that `except Exception` does NOT catch — the owner's broad catch must let it through."""

    class _BoomClientSession:
        """ClientSession that initialises fine but raises _CustomBaseException from __aexit__."""

        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc_info):
            raise _CustomBaseException("BaseException escaping owner")

        async def initialize(self):
            return None

    monkeypatch.setattr(usr, "streamablehttp_client", lambda **_kw: _FakeTransportCtx(streams=("r", "w", object())))
    monkeypatch.setattr(usr, "ClientSession", _BoomClientSession)

    req = _make_request()
    session, _ctx = await usr._default_session_factory(req)  # pylint: disable=protected-access
    assert isinstance(session, _BoomClientSession)

    # Drive the owner task to completion by firing its shutdown event.
    # The BaseException escapes `except Exception`, so task.exception() returns
    # it and the done-callback hits its warning branch.
    shutdown_event = getattr(session, "_cf_shutdown_event")  # smuggled by the factory
    owner_task = getattr(session, "_cf_owner_task")
    shutdown_event.set()

    with caplog.at_level("WARNING", logger=usr.logger.name):
        with pytest.raises(_CustomBaseException):
            await owner_task

    warnings = [rec for rec in caplog.records if rec.levelname == "WARNING" and "owner task" in rec.getMessage()]
    assert len(warnings) == 1, f"expected 1 WARNING; got {[(r.levelname, r.getMessage()) for r in caplog.records]}"
    msg = warnings[0].getMessage()
    assert "_CustomBaseException" in msg and "orphaned" in msg


# ---------------------------------------------------------------------------
# Branch coverage: small probe + dataclass paths not otherwise exercised
# ---------------------------------------------------------------------------


def test_mcp_transport_is_broken_returns_false_when_write_stream_has_no_state():
    """write_stream exists and isn't closed, but has no ``_state`` → ambiguity → False.

    Covers upstream_session_registry.py:210 (the `state is None: return False` branch).
    """
    # First-Party
    from mcpgateway.services.upstream_session_registry import _mcp_transport_is_broken

    class _Stream:
        _closed = False  # not closed
        # no _state attribute at all

    class _Session:
        _write_stream = _Stream()

    assert _mcp_transport_is_broken(_Session()) is False  # type: ignore[arg-type]


def test_upstream_session_age_seconds_exposes_wallclock_age():
    """UpstreamSession.age_seconds is a convenience property; ensure it reports a positive delta.

    Covers upstream_session_registry.py:273.
    """
    # First-Party
    from mcpgateway.services.upstream_session_registry import UpstreamSession

    upstream = UpstreamSession(
        downstream_session_id="s1",
        gateway_id="g1",
        url="http://upstream/mcp",
        transport_type=TransportType.STREAMABLE_HTTP,
        session=object(),  # type: ignore[arg-type]
    )
    age = upstream.age_seconds
    assert age >= 0
    assert age < 1.0  # this test should be fast enough that the session isn't ancient


@pytest.mark.asyncio
async def test_default_session_factory_sse_with_httpx_client_factory(monkeypatch):
    """SSE transport + httpx_client_factory routes through sse_client with the factory threaded in.

    Covers upstream_session_registry.py:295 — the SSE + httpx_client_factory branch.
    """
    # First-Party
    from mcpgateway.services import upstream_session_registry as usr

    captured = {}
    sentinel_factory = object()

    def fake_sse(**kwargs):
        captured.update(kwargs)
        return _FakeTransportCtx(streams=("r", "w"))

    monkeypatch.setattr(usr, "sse_client", fake_sse)
    monkeypatch.setattr(usr, "ClientSession", _FakeClientSessionCM)

    req = _make_request(transport_type=TransportType.SSE, httpx_client_factory=sentinel_factory)
    await usr._default_session_factory(req)  # pylint: disable=protected-access

    assert captured.get("httpx_client_factory") is sentinel_factory


@pytest.mark.asyncio
async def test_default_session_factory_cancelled_path_runs_on_ready_timeout(monkeypatch):
    """When ready times out, the finally clause cancels the owner task and `await task` sees CancelledError.

    Covers upstream_session_registry.py:385-387. The sibling `except Exception`
    branch (388-393) is defensive — the owner's own `except Exception` catches
    all Exception subclasses, so a regular Exception cannot escape `await task`.
    """
    # First-Party
    from mcpgateway.services import upstream_session_registry as usr

    # Transport context that hangs inside __aenter__ so ready.set_result never fires.
    class _HangingCtx:
        async def __aenter__(self):
            await asyncio.sleep(10.0)  # far longer than the factory timeout
            return ("r", "w", object())

        async def __aexit__(self, *_exc):
            return False

    monkeypatch.setattr(usr, "streamablehttp_client", lambda **_kw: _HangingCtx())
    monkeypatch.setattr(usr, "ClientSession", _FakeClientSessionCM)

    req = _make_request(timeout_seconds=0.05)
    with pytest.raises((asyncio.TimeoutError, TimeoutError)):
        await usr._default_session_factory(req)  # pylint: disable=protected-access

    # The important property: the factory surfaced the TimeoutError cleanly —
    # meaning the finally-clause cleanup completed, which requires the
    # CancelledError branch to have swallowed the cancellation of the hung owner.


@pytest.mark.asyncio
async def test_evict_key_returns_false_when_key_already_gone(registry):
    """Calling _evict_key on a missing key must return False without raising.

    Covers upstream_session_registry.py:606-607 — the `session is None: return False` branch.
    """
    result = await registry._evict_key(("unknown-session", "unknown-gateway"))  # pylint: disable=protected-access
    assert result is False


@pytest.mark.asyncio
async def test_probe_health_mcp_error_other_than_method_not_found_fails_fast(factory_and_records):
    """An McpError with a code other than METHOD_NOT_FOUND must bail out (don't keep probing).

    Covers upstream_session_registry.py:689-690 — `return False` on non-method-not-found McpError.
    """
    factory, _ = factory_and_records
    reg = UpstreamSessionRegistry(session_factory=factory, idle_validation_seconds=1.0)

    # Third-Party
    from mcp import McpError
    from mcp.types import ErrorData

    class _DeniedSession:
        async def send_ping(self):
            raise McpError(ErrorData(code=-32000, message="permission denied — token rotated"))

    upstream = _make_upstream_for_probe(_DeniedSession())
    assert await reg._probe_health(upstream) is False  # pylint: disable=protected-access
    assert reg.snapshot().health_check_failures == 1


@pytest.mark.asyncio
async def test_probe_health_exhausted_chain_without_skip_fails(factory_and_records, monkeypatch):
    """If the health-check chain is patched to remove "skip", exhausting it must fail.

    Defensive fallthrough at upstream_session_registry.py:697-698. Without "skip" as the
    final terminator, a server that answers METHOD_NOT_FOUND to every probe would loop
    and hit the tail-return. Covered by temporarily shortening the chain.
    """
    # First-Party
    from mcpgateway.services import upstream_session_registry as usr

    factory, _ = factory_and_records
    reg = UpstreamSessionRegistry(session_factory=factory, idle_validation_seconds=1.0)

    # Trim "skip" off the end so the loop actually exhausts.
    monkeypatch.setattr(usr, "_HEALTH_CHECK_CHAIN", ("ping", "list_tools"))

    session = _ProbeChainSession({"ping": "method_not_found", "list_tools": "method_not_found"})
    upstream = _make_upstream_for_probe(session)
    assert await reg._probe_health(upstream) is False  # pylint: disable=protected-access
    assert reg.snapshot().health_check_failures == 1


@pytest.mark.asyncio
async def test_close_session_short_circuits_when_already_closed(registry, factory_and_records):
    """_close_session on an already-closed UpstreamSession must return immediately.

    Covers upstream_session_registry.py:702-703.
    """
    _, created = factory_and_records
    async with registry.acquire(
        downstream_session_id="s1",
        gateway_id="g1",
        url="http://upstream/mcp",
        headers=None,
        transport_type=TransportType.STREAMABLE_HTTP,
    ):
        pass
    _, _session_obj, _event, _task = created[0]

    # First eviction drains the session cleanly.
    key = ("s1", "g1")
    assert await registry._evict_key(key) is True  # pylint: disable=protected-access

    # _close_session on the already-closed UpstreamSession must be a no-op.
    # Recover the UpstreamSession wrapper from the factory's created list and invoke directly.
    # (After eviction, the wrapper's _closed flag is True.)
    upstream_wrapper = registry._sessions.get(key)  # pylint: disable=protected-access
    if upstream_wrapper is None:
        # Session was evicted — build a minimal closed wrapper to exercise the short-circuit.
        # First-Party
        from mcpgateway.services.upstream_session_registry import UpstreamSession

        fake = UpstreamSession(
            downstream_session_id="s1",
            gateway_id="g1",
            url="http://upstream/mcp",
            transport_type=TransportType.STREAMABLE_HTTP,
            session=object(),  # type: ignore[arg-type]
        )
        fake._closed = True  # pylint: disable=protected-access
        # Should return without touching any task / event — prior test already proved this is safe.
        await registry._close_session(fake)  # pylint: disable=protected-access


@pytest.mark.asyncio
async def test_close_session_returns_immediately_when_owner_task_already_done(factory_and_records):
    """If the owner task completed before _close_session runs, return without awaiting.

    Covers upstream_session_registry.py:718 — the `owner_task.done()` short-circuit
    after `_shutdown_event.set()`.
    """
    # First-Party
    from mcpgateway.services.upstream_session_registry import UpstreamSession

    factory, _ = factory_and_records
    reg = UpstreamSessionRegistry(session_factory=factory, shutdown_timeout_seconds=1.0)

    # Build an owner task that exits immediately, before we call _close_session.
    async def _already_done():
        return None

    task = asyncio.create_task(_already_done())
    await task  # ensure it's done before we proceed

    upstream = UpstreamSession(
        downstream_session_id="s-done",
        gateway_id="g-done",
        url="http://upstream/mcp",
        transport_type=TransportType.STREAMABLE_HTTP,
        session=object(),  # type: ignore[arg-type]
        _owner_task=task,
        _shutdown_event=asyncio.Event(),
    )

    # Should return immediately — no timeout, no warnings.
    await reg._close_session(upstream)  # pylint: disable=protected-access
    assert upstream._closed is True  # pylint: disable=protected-access


@pytest.mark.asyncio
async def test_close_session_logs_debug_when_owner_exits_with_exception(caplog):
    """An owner task that exits with a regular Exception inside the grace window surfaces as DEBUG.

    Covers upstream_session_registry.py:730 — the `logger.debug("Owner task ... exited with ...")`
    branch after the task completes non-cancelled with an exception.
    """
    # First-Party
    from mcpgateway.services import upstream_session_registry as usr
    from mcpgateway.services.upstream_session_registry import UpstreamSession

    factory, _ = _make_fake_factory()
    reg = UpstreamSessionRegistry(session_factory=factory, shutdown_timeout_seconds=1.0)

    shutdown = asyncio.Event()

    async def _raises_after_shutdown():
        await shutdown.wait()
        raise RuntimeError("owner blew up during teardown")

    task = asyncio.create_task(_raises_after_shutdown())
    upstream = UpstreamSession(
        downstream_session_id="s-err",
        gateway_id="g-err",
        url="http://upstream/mcp",
        transport_type=TransportType.STREAMABLE_HTTP,
        session=object(),  # type: ignore[arg-type]
        _owner_task=task,
        _shutdown_event=shutdown,
    )

    with caplog.at_level("DEBUG", logger=usr.logger.name):
        await reg._close_session(upstream)  # pylint: disable=protected-access

    debug_msgs = [rec.getMessage() for rec in caplog.records if rec.levelname == "DEBUG"]
    assert any("exited during _close_session" in m and "RuntimeError" in m for m in debug_msgs)


@pytest.mark.asyncio
async def test_close_session_consumes_final_exception_after_force_cancel():
    """After force-cancel + re-completion, `.result()` is called inside `contextlib.suppress` so the exception doesn't leak.

    Covers upstream_session_registry.py:758-759. Scenario: the grace window elapses,
    force-cancel fires, task finishes with a non-CancelledError exception.
    """
    # First-Party
    from mcpgateway.services.upstream_session_registry import UpstreamSession

    factory, _ = _make_fake_factory()
    reg = UpstreamSessionRegistry(session_factory=factory, shutdown_timeout_seconds=0.05)

    # Task that ignores the graceful shutdown but exits with an Exception when cancelled.
    async def _raises_on_cancel():
        try:
            await asyncio.sleep(10)  # longer than the grace window
        except asyncio.CancelledError:
            # On cancel, raise a regular Exception (not CancelledError).
            raise RuntimeError("exited via force-cancel with a real exception")  # pylint: disable=raise-missing-from

    task = asyncio.create_task(_raises_on_cancel())
    upstream = UpstreamSession(
        downstream_session_id="s-raise-on-cancel",
        gateway_id="g-raise-on-cancel",
        url="http://upstream/mcp",
        transport_type=TransportType.STREAMABLE_HTTP,
        session=object(),  # type: ignore[arg-type]
        _owner_task=task,
        _shutdown_event=asyncio.Event(),
    )

    # Should complete without propagating the RuntimeError.
    await reg._close_session(upstream)  # pylint: disable=protected-access

    # Task is done with the exception consumed.
    assert task.done()
    assert not task.cancelled()
    # The RuntimeError was retrieved (via .result()) inside contextlib.suppress.
    # Asserting no warning about "Task exception was never retrieved" is implicit —
    # but we can at least check that accessing .exception() doesn't raise InvalidStateError.
    assert isinstance(task.exception(), RuntimeError)


@pytest.mark.asyncio
async def test_close_session_bails_out_when_force_cancel_itself_wedges(caplog):
    """If the owner task ignores cancellation, _close_session must still bail out — never hang shutdown.

    A rogue owner that catches CancelledError without re-raising would keep
    ``await upstream._owner_task`` blocked indefinitely (asyncio propagates
    the caller's cancellation into the awaited task, but the awaited task
    can refuse). Production uses ``asyncio.wait(..., timeout=...)`` instead
    of a bare ``await`` so the total close time is bounded even when the
    task refuses to die.
    """
    # First-Party
    from mcpgateway.services import upstream_session_registry as usr
    from mcpgateway.services.upstream_session_registry import UpstreamSession

    factory, _ = _make_fake_factory()
    reg = UpstreamSessionRegistry(session_factory=factory, shutdown_timeout_seconds=0.1)

    # Release gate so we can let the rogue task finish after the test asserts.
    release = asyncio.Event()

    async def cancel_ignoring_owner():
        while not release.is_set():
            try:
                await asyncio.sleep(0.05)
            except asyncio.CancelledError:
                # Intentionally swallow cancellation — simulate a misbehaving
                # transport SDK that has `except Exception: pass` around its
                # stream reads.
                pass

    stuck_task = asyncio.create_task(cancel_ignoring_owner(), name="cancel-ignorer")
    upstream = UpstreamSession(
        downstream_session_id="s-wedged",
        gateway_id="g-wedged",
        url="http://upstream/mcp",
        transport_type=TransportType.STREAMABLE_HTTP,
        session=object(),  # type: ignore[arg-type]
        _owner_task=stuck_task,
        _shutdown_event=asyncio.Event(),
    )

    with caplog.at_level("WARNING", logger=usr.logger.name):
        # Total budget: ~2 * shutdown_timeout_seconds (0.1) + overhead. 1.0s is plenty.
        await asyncio.wait_for(reg._close_session(upstream), timeout=1.0)  # pylint: disable=protected-access

    warnings = [rec.getMessage() for rec in caplog.records if rec.levelname == "WARNING"]
    assert any("force-cancelling" in m for m in warnings)
    assert any("did not complete" in m and "orphaned" in m for m in warnings)

    # Release the rogue task so pytest-asyncio can tear down cleanly.
    release.set()
    # Give the rogue task one sleep-cycle to notice the release flag, then await.
    done, _pending = await asyncio.wait({stuck_task}, timeout=0.5)
    if stuck_task not in done:
        # Test framework will still exit; just make sure pytest-asyncio doesn't hang.
        stuck_task.cancel()


@pytest.mark.asyncio
async def test_close_session_force_cancels_stuck_owner_task(caplog):
    """A stuck owner task triggers the shutdown-timeout WARNING + force-cancel branch.

    Covers upstream_session_registry.py:723-735 (force-cancel warning + final cancel cleanup).
    Calls ``_close_session`` directly against a crafted ``UpstreamSession`` so we control the
    exact owner-task behaviour end to end.
    """
    # First-Party
    from mcpgateway.services import upstream_session_registry as usr
    from mcpgateway.services.upstream_session_registry import UpstreamSession

    factory, _ = _make_fake_factory()
    reg = UpstreamSessionRegistry(session_factory=factory, shutdown_timeout_seconds=0.2)

    # Build an owner task that ignores shutdown and hangs forever — simulating
    # a stuck upstream teardown (network stack in D-state, TLS handshake
    # deadlock, etc.).
    stop_forever = asyncio.Event()  # never set

    async def stuck_owner():
        await stop_forever.wait()

    stuck_task = asyncio.create_task(stuck_owner(), name="stuck-forever")
    stuck_shutdown = asyncio.Event()

    upstream = UpstreamSession(
        downstream_session_id="s-stuck",
        gateway_id="g-stuck",
        url="http://upstream/mcp",
        transport_type=TransportType.STREAMABLE_HTTP,
        session=object(),  # type: ignore[arg-type]
        _owner_task=stuck_task,
        _shutdown_event=stuck_shutdown,
    )

    with caplog.at_level("WARNING", logger=usr.logger.name):
        await reg._close_session(upstream)  # pylint: disable=protected-access

    # Force-cancel WARNING surfaces the stuck session with full triage context.
    warnings = [rec for rec in caplog.records if rec.levelname == "WARNING" and "force-cancelling" in rec.getMessage()]
    assert len(warnings) == 1
    msg = warnings[0].getMessage()
    assert "s-stuck" in msg  # downstream_session_id in the log
    assert "g-stuck" in msg  # gateway_id in the log

    # After force-cancel, the task is cancelled.
    assert stuck_task.cancelled() or stuck_task.done()


# ---------------------------------------------------------------------------
# downstream_session_id_from_request_context
# ---------------------------------------------------------------------------


def test_downstream_session_id_helper_prefers_x_mcp_session_id_header():
    """The X- prefixed variant wins over the RFC header (transport-internal convention)."""
    # First-Party
    from mcpgateway.services.upstream_session_registry import downstream_session_id_from_request_context
    from mcpgateway.transports.streamablehttp_transport import request_headers_var

    token = request_headers_var.set({"X-Mcp-Session-Id": "x-prefix", "mcp-session-id": "rfc-name"})
    try:
        assert downstream_session_id_from_request_context() == "x-prefix"
    finally:
        request_headers_var.reset(token)


def test_downstream_session_id_helper_falls_back_to_mcp_session_id_header():
    """When only the RFC name is present, it's returned."""
    # First-Party
    from mcpgateway.services.upstream_session_registry import downstream_session_id_from_request_context
    from mcpgateway.transports.streamablehttp_transport import request_headers_var

    token = request_headers_var.set({"mcp-session-id": "rfc-only"})
    try:
        assert downstream_session_id_from_request_context() == "rfc-only"
    finally:
        request_headers_var.reset(token)


def test_downstream_session_id_helper_returns_none_when_no_header_present():
    """No header → None (not empty string)."""
    # First-Party
    from mcpgateway.services.upstream_session_registry import downstream_session_id_from_request_context
    from mcpgateway.transports.streamablehttp_transport import request_headers_var

    token = request_headers_var.set({"authorization": "Bearer xyz"})
    try:
        assert downstream_session_id_from_request_context() is None
    finally:
        request_headers_var.reset(token)


def test_downstream_session_id_helper_is_case_insensitive():
    """Header lookup normalises to lowercase before matching."""
    # First-Party
    from mcpgateway.services.upstream_session_registry import downstream_session_id_from_request_context
    from mcpgateway.transports.streamablehttp_transport import request_headers_var

    token = request_headers_var.set({"MCP-Session-Id": "mixed-case"})
    try:
        assert downstream_session_id_from_request_context() == "mixed-case"
    finally:
        request_headers_var.reset(token)


# ---------------------------------------------------------------------------
# Singleton accessors
# ---------------------------------------------------------------------------


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
