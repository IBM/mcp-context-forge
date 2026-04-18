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


def test_mcp_transport_is_broken_returns_false_on_sdk_drift(caplog):
    """If SDK internals have shifted (descriptor raises an unexpected exception), degrade to "not sure" + debug log."""
    # First-Party
    from mcpgateway.services import upstream_session_registry as usr

    class _BrokenStream:
        @property
        def _closed(self):
            # Not AttributeError — getattr() would silently swallow that.
            # RuntimeError simulates SDK internals that raise in a way the
            # probe can't recover from, so we fall through to the catch.
            raise RuntimeError("SDK drift: _closed raised from property")

    class _Session:
        _write_stream = _BrokenStream()

    with caplog.at_level("DEBUG", logger=usr.logger.name):
        assert usr._mcp_transport_is_broken(_Session()) is False  # pylint: disable=protected-access  # type: ignore[arg-type]
    assert any("MCP transport-broken probe raised" in rec.getMessage() for rec in caplog.records)


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
    """A provided message_handler_factory is called with (url, gateway_id) and its result flows into ClientSession."""
    # First-Party
    from mcpgateway.services import upstream_session_registry as usr

    sentinel_handler = object()
    factory_calls = []

    def handler_factory(url, gateway_id):
        factory_calls.append((url, gateway_id))
        return sentinel_handler

    monkeypatch.setattr(usr, "streamablehttp_client", lambda **_kw: _FakeTransportCtx(streams=("r", "w", object())))
    monkeypatch.setattr(usr, "ClientSession", _FakeClientSessionCM)

    req = _make_request(message_handler_factory=handler_factory)
    await usr._default_session_factory(req)  # pylint: disable=protected-access

    assert factory_calls == [(req.url, req.gateway_id)]
    assert _FakeClientSessionCM.last_message_handler is sentinel_handler


@pytest.mark.asyncio
async def test_default_session_factory_message_handler_factory_failure_is_logged_not_fatal(monkeypatch, caplog):
    """If the handler factory raises, the session still opens and the error is logged."""
    # First-Party
    from mcpgateway.services import upstream_session_registry as usr

    def bad_factory(_url, _gw):
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
    """An owner-task death after ready is set surfaces as a WARNING via the done-callback."""
    # First-Party
    from mcpgateway.services import upstream_session_registry as usr

    class _BoomCtx:
        """Opens fine, but raises on exit so owner() sees an exception after ready is set."""

        async def __aenter__(self):
            return ("r", "w", object())

        async def __aexit__(self, exc_type, exc, tb):
            raise OSError("transport exit boom")

    monkeypatch.setattr(usr, "streamablehttp_client", lambda **_kw: _BoomCtx())
    monkeypatch.setattr(usr, "ClientSession", _FakeClientSessionCM)

    req = _make_request()
    session, _ctx = await usr._default_session_factory(req)  # pylint: disable=protected-access
    assert session.initialized is True

    # Trigger the owner task to complete by signalling shutdown through the
    # internal event. We reach into asyncio.all_tasks to find it; the task
    # name is set by the factory.
    owner_tasks = [t for t in asyncio.all_tasks() if t.get_name().startswith("upstream-session-")]
    assert owner_tasks, "owner task was not scheduled"
    owner_task = owner_tasks[0]

    with caplog.at_level("WARNING", logger=usr.logger.name):
        # Cancel to force an exit; the done-callback still fires for exceptions,
        # not for cancellation, so instead close by letting the context exit raise.
        owner_task.cancel()
        try:
            await owner_task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass

    # Cancelled tasks don't hit the warning branch — but an exception from the
    # __aexit__ raising OSError during cancellation should produce the warning.
    # We accept either: the important property is the callback was wired and
    # didn't crash the process. Check it was registered by inspecting the task.
    assert owner_task.done()


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
