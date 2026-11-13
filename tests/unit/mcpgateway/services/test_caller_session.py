# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_caller_session.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Exercise caller-binding isolation, credential rotation, and bounded lifecycle."""

import asyncio
import importlib
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from mcpgateway.services.caller_session import (
    CallerOwnershipLostError,
    CallerOwnershipState,
    CallerOwnershipTicket,
    CallerSessionError,
    connection_fingerprint,
    forwarded_caller_ownership,
    InvalidSessionKeyError,
    resolve_caller_binding,
    session_key_from_meta,
    SESSION_KEY_META,
    upstream_meta,
    verified_caller_identity,
)
from mcpgateway.services.upstream_session_registry import SessionLifecycle, TransportType, UpstreamSessionRegistry


@pytest.mark.asyncio
async def test_concurrent_first_routes_preserve_counter_state(caller_registry, monkeypatch):
    """Concurrent first-use claims never evict state initialized by another admitted call."""
    from mcpgateway.services import session_affinity as module

    registry, created = caller_registry
    registry._caller_idle_timeout = 600
    selected = binding()
    both_read, first_used = asyncio.Event(), asyncio.Event()

    class Redis:
        reads = 0
        claims = 0

        async def get(self, key):
            self.reads += 1
            if self.reads == 2:
                both_read.set()
            await both_read.wait()

        async def eval(self, script, *args):
            if "caller_claim_v1" in script:
                self.claims += 1
                return [module.get_worker_id().encode(), b"generation-one", int(self.claims == 1), 300000]
            if "caller_validate_v1" in script:
                return 300000
            self.claims += 1
            if self.claims == 2:
                await first_used.wait()
            return module.get_worker_id().encode()

    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=Redis()))
    monkeypatch.setattr("mcpgateway.services.upstream_session_registry.get_upstream_session_registry", lambda: registry)
    affinity = module.SessionAffinity()
    monkeypatch.setattr(affinity, "forward_request_to_owner", AsyncMock(return_value=None))
    counts = []

    async def call():
        route = await affinity.forward_caller_request(selected.routing_key, {"method": "tools/call"}, "verified")
        kwargs = {"ownership": route} if route is not None else {}
        async with registry.acquire_caller(binding=selected, gateway_id="gateway", url="https://upstream/mcp", headers={}, transport_type=TransportType.STREAMABLE_HTTP, **kwargs) as upstream:
            upstream.session.counter += 1
            counts.append(upstream.session.counter)
        first_used.set()

    await asyncio.wait_for(asyncio.gather(call(), call()), 5)
    assert counts == [1, 2]
    assert len(created) == 1


@pytest.mark.asyncio
async def test_queued_call_cannot_reconnect_after_ownership_loss(caller_registry):
    """Ownership revocation rejects a queued call before replacement creation or dispatch."""
    from contextlib import asynccontextmanager

    registry, created = caller_registry
    selected = binding()
    waiting = asyncio.Event()
    dispatched = []

    async def queued():
        async with acquire(registry, selected):
            dispatched.append(True)

    async with acquire(registry, selected):
        entry = next(iter(registry._callers.values()))
        original_lock = entry.lock

        @asynccontextmanager
        async def observed_lock():
            waiting.set()
            async with original_lock:
                yield

        entry.lock = observed_lock()
        task = asyncio.create_task(queued())
        await asyncio.wait_for(waiting.wait(), 5)
        await registry.evict_caller_route(selected.routing_key)
    with pytest.raises(CallerSessionError, match="ownership lost"):
        await asyncio.wait_for(task, 5)
    assert dispatched == []
    assert len(created) == 1


def binding(token="token-a", key=None, downstream=None, server="server-a", enabled=True):
    """Resolve a binding from simulated verified ingress context."""
    return resolve_caller_binding(
        caller_identity=verified_caller_identity(token, "user@example.com", "issuer"),
        server_id=server,
        downstream_session_id=downstream,
        meta={SESSION_KEY_META: key} if key is not None else None,
        pin_sessions_by_caller=enabled,
    )


@pytest.mark.parametrize("value", [None, "", " ", 1, True, [], {}, "x" * 257, "\ud800"])
def test_invalid_explicit_key_rejected(value):
    """Malformed supplied keys never create bindings."""
    with pytest.raises(InvalidSessionKeyError):
        session_key_from_meta({SESSION_KEY_META: value})


def test_binding_policy_preserves_defaults_and_isolation():
    """Explicit keys opt in; token, server, and real session boundaries remain separate."""
    assert binding(enabled=False) is None
    assert binding(downstream="existing") is None
    assert binding(key="conversation", enabled=False) == binding(key="conversation", enabled=True)
    assert binding() != binding(token="token-b")
    assert binding(key="a") != binding(key="b")
    assert binding(key="a", downstream="one") != binding(key="a", downstream="two")
    assert binding(server="one") != binding(server="two")
    assert resolve_caller_binding(caller_identity=None, server_id=None, downstream_session_id=None, meta={SESSION_KEY_META: "a"}, pin_sessions_by_caller=True) is None


def test_connection_fingerprint_ignores_only_request_headers():
    """Credential headers and TLS changes force replacement; tracing does not."""
    base = connection_fingerprint("https://upstream/mcp", "sse", {"Authorization": "one"})
    assert base == connection_fingerprint("https://upstream/mcp", "sse", {"authorization": "one", "traceparent": "new"})
    assert base != connection_fingerprint("https://upstream/mcp", "sse", {"Authorization": "two"})
    assert base != connection_fingerprint("https://upstream/mcp", "sse", {"Authorization": "one", "X-Plugin-Key": "new"})
    assert base != connection_fingerprint("https://upstream/mcp", "sse", {"Authorization": "one"}, "new-client-cert")


@pytest.fixture
async def caller_registry():
    """Create a real registry with a stateful in-memory upstream factory."""
    created = []

    async def factory(req):
        session = MagicMock()
        session.counter = 0
        session.send_ping = AsyncMock()
        created.append((req, session))
        return session, SessionLifecycle(owner_task=None, shutdown_event=None, client=None)

    registry = UpstreamSessionRegistry(session_factory=factory, caller_max_bindings=2, caller_idle_timeout=0.1)
    yield registry, created
    await registry.close_all()


def acquire(registry, selected=None, headers=None, ownership=None):
    """Acquire a caller session using effective connection material."""
    return registry.acquire_caller(
        binding=selected or binding(),
        gateway_id="gateway",
        url="https://upstream/mcp",
        headers=headers or {"Authorization": "upstream-token"},
        transport_type=TransportType.STREAMABLE_HTTP,
        ownership=ownership,
    )


@pytest.mark.asyncio
async def test_counter_continuity_and_credential_replacement(caller_registry):
    """Reuse state until effective upstream credentials change."""
    registry, created = caller_registry
    counters = []
    for _ in range(3):
        async with acquire(registry) as upstream:
            upstream.session.counter += 1
            counters.append(upstream.session.counter)
    assert counters == [1, 2, 3]
    old = upstream
    async with acquire(registry, headers={"Authorization": "refreshed"}) as upstream:
        assert upstream.session.counter == 0
        assert old.is_closed
    assert len(created) == 2
    assert created[0][0].message_handler_factory is None


@pytest.mark.asyncio
async def test_capacity_rejects_new_bindings_and_preserves_existing(caller_registry):
    """Reject overflow without dispatching or resetting unexpired sessions."""
    registry, created = caller_registry
    async with acquire(registry):
        async with acquire(registry, binding(token="two")):
            with pytest.raises(CallerSessionError, match="capacity exhausted"):
                async with acquire(registry, binding(token="three")):
                    pytest.fail("capacity rejection must precede dispatch")
    async with acquire(registry) as upstream:
        assert upstream.use_count == 2
    assert len(created) == 2


@pytest.mark.asyncio
async def test_expiry_closes_idle_sessions_and_reclaims_capacity(caller_registry):
    """Expiry releases sessions and entries before admitting new bindings."""
    registry, _ = caller_registry
    async with acquire(registry) as old:
        pass
    for entry in registry._callers.values():
        entry.last_used = time.monotonic() - 1
    assert await registry.expire_callers() == 1
    assert old.is_closed
    async with acquire(registry) as fresh:
        assert fresh is not old


@pytest.mark.asyncio
async def test_queued_calls_protect_expiry_and_serialize_rotation(caller_registry):
    """Keep active sessions alive while credential-changing calls wait."""
    registry, created = caller_registry
    entered = asyncio.Event()

    async def queued():
        entered.set()
        async with acquire(registry, headers={"Authorization": "changed"}) as fresh:
            assert old.is_closed
            return fresh

    async with acquire(registry) as old:
        task = asyncio.create_task(queued())
        await entered.wait()
        await asyncio.sleep(0)
        for entry in registry._callers.values():
            entry.last_used = time.monotonic() - 1
        assert await registry.expire_callers() == 0
        assert not old.is_closed
        assert not task.done()
    assert await task is not old
    assert len(created) == 2


@pytest.mark.asyncio
async def test_failure_and_cancellation_release_creation_capacity(caller_registry):
    """Failed creation and cancelled waiters leave no reserved binding slots."""
    registry, _ = caller_registry
    original = registry._session_factory
    registry._session_factory = AsyncMock(side_effect=RuntimeError("connect failed"))
    with pytest.raises(RuntimeError, match="connect failed"):
        async with acquire(registry):
            pass
    assert not registry._callers
    registry._session_factory = original
    async with acquire(registry):

        async def waiter():
            async with acquire(registry):
                pass

        task = asyncio.create_task(waiter())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert next(iter(registry._callers.values())).users == 0


@pytest.mark.asyncio
async def test_gateway_and_downstream_eviction_close_matching_bindings(caller_registry):
    """Real downstream cleanup and gateway changes invalidate caller bindings."""
    registry, _ = caller_registry
    async with acquire(registry, binding(key="conversation", downstream="real-session")) as old:
        pass
    assert await registry.evict_session("real-session") == 1
    assert old.is_closed
    async with acquire(registry) as old:
        pass
    assert await registry.evict_gateway("gateway") == 1
    assert old.is_closed


@pytest.mark.asyncio
@pytest.mark.parametrize("wrapped", [False, True])
async def test_session_gone_evicts_without_replaying(caller_registry, wrapped):
    """An upstream session-gone response evicts the session before another operation."""
    from mcp.shared.exceptions import MCPError

    registry, created = caller_registry
    failure = MCPError(-32600, "Session terminated")
    if wrapped:
        failure = ExceptionGroup("SDK task group", [failure])
    with pytest.raises(type(failure)):
        async with acquire(registry) as old:
            old.session.counter += 1
            raise failure
    assert old.is_closed
    assert len(created) == 1
    async with acquire(registry) as fresh:
        assert fresh.session.counter == 0
    assert len(created) == 2


def test_migration_preserves_existing_rows_and_is_idempotent(monkeypatch):
    """Upgrade defaults existing rows to false; downgrade and repeat calls remain safe."""
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    import sqlalchemy as sa

    migration = importlib.import_module("mcpgateway.alembic.versions.7263b1a8c204_add_caller_session_pinning")
    engine = sa.create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as connection:
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            connection.execute(sa.text("CREATE TABLE gateways (id TEXT PRIMARY KEY)"))
            connection.execute(sa.text("INSERT INTO gateways VALUES ('existing')"))
            migration.upgrade()
            migration.upgrade()
            assert connection.execute(sa.text("SELECT pin_sessions_by_caller FROM gateways")).scalar_one() == 0
            migration.downgrade()
            migration.downgrade()
            assert connection.execute(sa.text("SELECT id FROM gateways")).scalar_one() == "existing"
    finally:
        engine.dispose()


def test_upstream_metadata_preserves_keys_without_forwarding_negotiation():
    """Forward application metadata while the upstream SDK negotiates its own connection."""
    supplied = {SESSION_KEY_META: "conversation", "io.modelcontextprotocol/protocolVersion": "2026-07-28", "io.modelcontextprotocol/clientCapabilities": {}, "traceparent": "trace"}
    assert upstream_meta(supplied) == {SESSION_KEY_META: "conversation", "traceparent": "trace"}
    assert "io.modelcontextprotocol/protocolVersion" in supplied
    assert session_key_from_meta({SESSION_KEY_META: "é" * 128}) == "é" * 128
    with pytest.raises(InvalidSessionKeyError):
        session_key_from_meta({SESSION_KEY_META: "é" * 129})


@pytest.mark.asyncio
async def test_caller_policy_eviction_preserves_legacy_bindings(caller_registry):
    """Changing caller pinning does not reset legacy downstream-session state."""
    registry, _ = caller_registry
    async with registry.acquire(downstream_session_id="legacy", gateway_id="gateway", url="https://upstream/mcp", headers=None, transport_type=TransportType.STREAMABLE_HTTP) as legacy:
        legacy.session.counter = 3
    async with acquire(registry) as caller:
        pass
    assert await registry.evict_gateway("gateway", callers_only=True) == 1
    assert caller.is_closed
    assert not legacy.is_closed
    assert legacy.session.counter == 3


@pytest.mark.asyncio
async def test_capacity_includes_concurrent_creation_reservations(caller_registry):
    """Concurrent creations cannot exceed the configured binding capacity."""
    registry, _ = caller_registry
    blocked = asyncio.Event()
    factory = registry._session_factory

    async def delayed(req):
        await blocked.wait()
        return await factory(req)

    registry._session_factory = delayed

    async def create(selected):
        async with acquire(registry, selected):
            pass

    tasks = [asyncio.create_task(create(binding(token=str(index)))) for index in range(2)]
    await asyncio.sleep(0)
    with pytest.raises(CallerSessionError, match="capacity exhausted"):
        await create(binding(token="overflow"))
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    assert not registry._callers


@pytest.mark.asyncio
async def test_affinity_storage_failure_never_dispatches_locally(monkeypatch):
    """Unavailable ownership storage fails closed for opted-in caller bindings."""
    from mcpgateway.services.session_affinity import SessionAffinity

    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=None))
    affinity = SessionAffinity()
    forward = AsyncMock()
    monkeypatch.setattr(affinity, "forward_request_to_owner", forward)
    with pytest.raises(CallerSessionError, match="ownership storage is unavailable"):
        await affinity.forward_caller_request(binding().routing_key, {"method": "tools/call"}, "verified-context")
    forward.assert_not_awaited()


@pytest.mark.asyncio
async def test_background_expiry_and_shutdown(caller_registry):
    """Periodic cleanup releases idle sessions and shutdown prevents new acquisitions."""
    registry, _ = caller_registry
    registry._caller_idle_timeout = 0.001
    async with acquire(registry) as old:
        pass
    registry.start_caller_cleanup()
    task = registry._caller_cleanup_task
    registry.start_caller_cleanup()
    assert registry._caller_cleanup_task is task
    await asyncio.sleep(0.03)
    assert old.is_closed
    assert not registry._callers
    await registry.close_all()
    assert task.done()
    with pytest.raises(CallerSessionError, match="closing"):
        async with acquire(registry):
            pass


@pytest.mark.asyncio
async def test_failed_idle_probe_recreates_caller_session(caller_registry):
    """Caller session reuse checks stale transports before dispatch."""
    registry, _ = caller_registry
    async with acquire(registry) as old:
        old.last_used = time.time() - 1000
        old.session.send_ping.side_effect = OSError("upstream closed")
    old.last_used = time.time() - 1000
    async with acquire(registry) as fresh:
        assert old.is_closed
        assert fresh is not old


@pytest.mark.asyncio
async def test_route_loss_invalidates_only_matching_sessions(caller_registry):
    """Losing ownership invalidates the matching route while active work completes."""
    registry, _ = caller_registry
    selected = binding()
    async with acquire(registry, selected) as old:
        await registry.evict_caller_route("different-route")
        assert registry.has_caller_route(selected.routing_key)
        await registry.evict_caller_route(selected.routing_key)
        assert not old.is_closed
    assert old.is_closed
    assert not registry.has_caller_route(selected.routing_key)
    async with acquire(registry, selected) as fresh:
        pass
    await registry.evict_caller_route(selected.routing_key)
    assert fresh.is_closed


@pytest.mark.asyncio
async def test_http_session_gone_evicts_but_tool_validation_error_preserves_state(caller_registry):
    """HTTP session loss rebuilds without replay; ordinary HTTP validation errors preserve the connection."""
    import httpx

    registry, _ = caller_registry
    for status, closed in ((422, False), (404, True)):
        with pytest.raises(httpx.HTTPStatusError):
            async with acquire(registry) as old:
                raise httpx.HTTPStatusError("upstream error", request=httpx.Request("POST", "https://upstream/mcp"), response=httpx.Response(status))
        assert old.is_closed is closed


@pytest.mark.asyncio
async def test_operation_headers_and_context_follow_each_call(monkeypatch):
    """Owner-task transports use current headers and context without retaining previous call state."""
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    import httpx2
    from opentelemetry import context as otel_context

    from mcpgateway.services import upstream_session_registry as module

    observed = []
    captured = {}

    async def handle(request):
        observed.append((dict(request.headers), otel_context.get_value("operation")))
        return httpx2.Response(200, json={})

    def client_factory(headers=None, timeout=None, auth=None):
        return httpx2.AsyncClient(headers=headers, transport=httpx2.MockTransport(handle))

    @asynccontextmanager
    async def transport(**kwargs):
        async with kwargs["httpx_client_factory"](headers=kwargs["headers"]) as client:
            captured["client"] = client
            yield None

    class Client:
        def __init__(self, transport_context, **kwargs):
            self.transport_context = transport_context
            self.session = MagicMock()

        async def __aenter__(self):
            await self.transport_context.__aenter__()
            return self

        async def __aexit__(self, *args):
            return await self.transport_context.__aexit__(*args)

    monkeypatch.setattr(module, "_resolve_pinned_session_target", AsyncMock(return_value=SimpleNamespace(is_pinned=False)))
    monkeypatch.setattr(module, "sse_client", transport)
    monkeypatch.setattr(module, "Client", Client)
    headers = {"traceparent": "first-trace"}
    context = {"value": otel_context.set_value("operation", "first")}
    request = module.SessionCreateRequest(
        url="https://upstream/sse",
        transport_type=TransportType.SSE,
        headers={"Authorization": "credential"},
        gateway_id="gateway",
        downstream_session_id="caller",
        httpx_client_factory=client_factory,
        message_handler_factory=None,
        timeout_seconds=2,
        request_headers=headers,
        operation_context=context,
    )
    _, lifecycle = await module._default_session_factory(request)
    try:
        client = captured["client"]
        await client.post("https://upstream/message")
        headers["traceparent"] = "second-trace"
        context["value"] = otel_context.set_value("operation", "second")
        await client.post("https://upstream/message")
        headers.clear()
        context.clear()
        await client.post("https://upstream/message")
        assert [item[0].get("traceparent") for item in observed] == ["first-trace", "second-trace", None]
        assert [item[1] for item in observed] == ["first", "second", None]
        assert all(item[0]["authorization"] == "credential" for item in observed)
        assert otel_context.get_value("operation") is None
    finally:
        lifecycle.shutdown_event.set()
        await lifecycle.owner_task


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [None, {"result": {"content": []}}, {"error": {"code": -32000, "message": "capacity"}}, RuntimeError("unavailable"), CallerSessionError("forwarding failed")])
async def test_forwarded_operation_preserves_results_and_errors(monkeypatch, response):
    """Forwarded operations preserve remote outcomes and never fall back after a forwarding failure."""
    from types import SimpleNamespace

    from mcpgateway.services import session_affinity as module

    monkeypatch.setattr(module.settings, "mcpgateway_session_affinity_enabled", True)
    forward = AsyncMock(side_effect=response) if isinstance(response, Exception) else AsyncMock(return_value=response)
    monkeypatch.setattr(module, "get_session_affinity", lambda: SimpleNamespace(forward_caller_request=forward))
    operation = module.forward_binding_operation(binding(), {"is_authenticated": True, "email": "user@example.com"}, "tools/call", {"name": "tool"}, {})
    if response is None or isinstance(response, Exception) or "error" in response:
        with pytest.raises(CallerSessionError):
            await operation
    else:
        assert (await operation).result == response["result"]
    forward.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("owner", [None, b"local", b"remote"])
async def test_caller_owner_claim_and_stale_local_eviction(caller_registry, monkeypatch, owner):
    """Atomic claim results initialize local authority or forward the exact remote generation."""
    from types import SimpleNamespace

    from mcpgateway.services import session_affinity as module

    registry, _ = caller_registry
    redis = SimpleNamespace(eval=AsyncMock(side_effect=lambda script, *args: [owner or b"local", b"generation", int(owner is None), 300000] if "caller_claim_v1" in script else 300000))
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=redis))
    monkeypatch.setattr("mcpgateway.services.upstream_session_registry.get_upstream_session_registry", lambda: registry)
    monkeypatch.setattr(module, "get_worker_id", lambda: "local")
    affinity = module.SessionAffinity()
    expected = {"result": {"content": []}}
    forward = AsyncMock(return_value=expected)
    monkeypatch.setattr(affinity, "_forward_rpc_to_worker", forward)
    selected = binding()
    response = await affinity.forward_caller_request(selected.routing_key, {"method": "tools/call"}, "verified")
    if owner == b"remote":
        assert response == expected
        assert forward.await_args.args[3]["caller_ownership"] == {"route": selected.routing_key, "owner": "remote", "generation": "generation"}
    else:
        assert response.state is CallerOwnershipState.READY
        assert response is registry._caller_ownership[selected.routing_key]
        forward.assert_not_awaited()
    assert bool(affinity._caller_routes) is (owner != b"remote")


@pytest.mark.asyncio
async def test_caller_claim_error_rejects_invocation(monkeypatch):
    """A failed atomic ownership claim never proceeds to execution or forwarding."""
    from types import SimpleNamespace

    from mcpgateway.services.session_affinity import SessionAffinity

    redis = SimpleNamespace(get=AsyncMock(return_value=None), eval=AsyncMock(side_effect=OSError("Redis failed")))
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=redis))
    affinity = SessionAffinity()
    forward = AsyncMock()
    monkeypatch.setattr(affinity, "forward_request_to_owner", forward)
    with pytest.raises(CallerSessionError):
        await affinity.forward_caller_request(binding().routing_key, {}, "verified")
    forward.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("live, renewed", [(False, False), (True, False), (True, True)])
async def test_caller_owner_heartbeat_tracks_binding_lifecycle(monkeypatch, live, renewed):
    """Heartbeat retains live ownership and invalidates sessions when ownership is lost."""
    from types import SimpleNamespace

    from mcpgateway.services import session_affinity as module

    selected = binding()
    registry = SimpleNamespace(has_caller_route=lambda key: live, evict_caller_route=AsyncMock())
    redis = SimpleNamespace(eval=AsyncMock(return_value=300000 if renewed else 0))
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=redis))
    monkeypatch.setattr("mcpgateway.services.upstream_session_registry.get_upstream_session_registry", lambda: registry)
    affinity = module.SessionAffinity()
    ticket = CallerOwnershipTicket(selected.routing_key, "worker", "generation", time.monotonic() + 300, AsyncMock(), state=CallerOwnershipState.READY, retained_until=0)
    affinity._caller_routes[selected.routing_key] = ticket
    await affinity._renew_caller_routes(redis)
    assert (ticket.state is CallerOwnershipState.READY) is (live and renewed)
    assert bool(registry.evict_caller_route.await_count) is (not live or not renewed)
    if registry.evict_caller_route.await_count:
        registry.evict_caller_route.assert_awaited_once_with(selected.routing_key, generation=ticket.generation)


@pytest.mark.asyncio
@pytest.mark.parametrize("owner", [None, b"dead"])
async def test_strict_forwarding_refuses_missing_or_changed_ownership(monkeypatch, owner):
    """Strict forwarding refuses local execution when an owner claim disappears."""
    from types import SimpleNamespace

    from mcpgateway.services import session_affinity as module

    monkeypatch.setattr(module.settings, "mcpgateway_session_affinity_enabled", True)
    redis = SimpleNamespace(get=AsyncMock(side_effect=[owner, None]), eval=AsyncMock(return_value=0))
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=redis))
    affinity = module.SessionAffinity()
    monkeypatch.setattr(affinity, "_is_worker_alive", AsyncMock(return_value=False))
    with pytest.raises(RuntimeError, match="ownership"):
        await affinity.forward_request_to_owner(binding().routing_key, {}, "verified", strict=True)


async def ready_ticket(registry, selected=None, generation="one", validator=None):
    """Publish a server-issued ticket in a real registry."""
    ticket = CallerOwnershipTicket((selected or binding()).routing_key, "local", generation, time.monotonic() + 300, validator or AsyncMock())
    await registry.install_caller_ownership(ticket)
    registry.publish_caller_ownership(ticket)
    return ticket


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["missing", "expired", "pending", "wrong-route", "revoked"])
async def test_distributed_admission_requires_live_matching_ticket(caller_registry, monkeypatch, invalid):
    """Invalid authority never reserves capacity, creates connections, or dispatches."""
    from mcpgateway.config import settings

    registry, created = caller_registry
    monkeypatch.setattr(settings, "mcpgateway_session_affinity_enabled", True)
    ticket = await ready_ticket(registry, binding(key="other") if invalid == "wrong-route" else None)
    if invalid == "expired":
        ticket.expires_at = 0
    elif invalid == "pending":
        ticket.state = CallerOwnershipState.PENDING
    elif invalid == "revoked":
        ticket.revoke()
    with pytest.raises(CallerOwnershipLostError):
        async with acquire(registry, ownership=None if invalid == "missing" else ticket):
            pytest.fail("invalid ownership reached dispatch")
    assert not registry._callers
    assert not created


@pytest.mark.asyncio
async def test_revoked_ticket_cannot_recreate_removed_entry(caller_registry):
    """Terminal revocation survives entry removal and same-worker generation replacement."""
    registry, created = caller_registry
    old_ticket = await ready_ticket(registry)
    async with acquire(registry, ownership=old_ticket) as old:
        pass
    await registry.evict_caller_route(binding().routing_key, generation=old_ticket.generation)
    assert old.is_closed
    assert not registry._callers
    with pytest.raises(CallerOwnershipLostError):
        async with acquire(registry, ownership=old_ticket):
            pytest.fail("revoked ticket recreated a removed entry")
    fresh_ticket = await ready_ticket(registry, generation="two")
    async with acquire(registry, ownership=fresh_ticket) as fresh:
        await registry.evict_caller_route(binding().routing_key, generation=old_ticket.generation)
        assert fresh_ticket.state is CallerOwnershipState.READY
        assert not fresh.is_closed
    assert len(created) == 2
    with pytest.raises(CallerOwnershipLostError):
        async with acquire(registry, ownership=old_ticket):
            pytest.fail("replacement generation revived an earlier ticket")


@pytest.mark.asyncio
@pytest.mark.parametrize("wait_point", ["create", "probe"])
async def test_ownership_loss_during_session_wait_closes_without_dispatch(caller_registry, wait_point):
    """Creation and health probes cannot admit operations after revocation during their waits."""
    registry, created = caller_registry
    ticket = await ready_ticket(registry)
    entered, resume = asyncio.Event(), asyncio.Event()
    if wait_point == "create":
        factory = registry._session_factory

        async def pause(req):
            entered.set()
            await resume.wait()
            return await factory(req)

        registry._session_factory = pause
    else:
        async with acquire(registry, ownership=ticket) as old:
            pass
        registry._idle_validation_seconds = -1

        async def pause():
            entered.set()
            await resume.wait()

        old.session.send_ping.side_effect = pause
    dispatched = []

    async def call():
        async with acquire(registry, ownership=ticket):
            dispatched.append(True)

    task = asyncio.create_task(call())
    await asyncio.wait_for(entered.wait(), 5)
    await registry.evict_caller_route(binding().routing_key, generation=ticket.generation)
    resume.set()
    with pytest.raises(CallerOwnershipLostError):
        await asyncio.wait_for(task, 5)
    assert dispatched == []
    assert not registry._callers
    assert len(created) == 1


@pytest.fixture
async def routed_registry(caller_registry, monkeypatch):
    """Use actual routing and registry code with a controllable ownership store."""
    from mcpgateway.services import session_affinity as module

    registry, created = caller_registry
    registry._caller_idle_timeout = 600

    class Redis:
        owner = None
        generation = None
        ttl = 300000
        fail_release = False

        async def eval(self, script, count, *args):
            values = args[count:]
            if "caller_claim_v1" in script:
                owner, proposed, _, expected, force, _ = values
                if expected and (self.owner != owner or self.generation != expected):
                    return ["", "", -1, 0]
                changed = self.owner is None or self.owner == owner and self.generation == force
                if changed:
                    self.owner, self.generation = owner, proposed
                return [self.owner, self.generation, int(changed), self.ttl]
            if "caller_release_v1" in script:
                if self.fail_release:
                    raise OSError("release unavailable")
                if (self.owner, self.generation) == tuple(values[:2]):
                    self.owner = self.generation = None
                return 1
            return self.ttl if (self.owner, self.generation) == tuple(values[:2]) else 0

    redis = Redis()
    affinity = module.SessionAffinity()
    monkeypatch.setattr(module, "get_worker_id", lambda: "local")
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=redis))
    monkeypatch.setattr("mcpgateway.services.upstream_session_registry.get_upstream_session_registry", lambda: registry)
    yield affinity, registry, redis, created
    await affinity.close_all()


@pytest.mark.asyncio
async def test_initialization_gate_drains_stale_state_before_admission(routed_registry):
    """Later claimants wait while replacement initialization drains an old active generation."""
    from mcpgateway.services.session_affinity import _CallerRouteGate

    affinity, registry, _, created = routed_registry
    selected = binding()
    old_ticket = await ready_ticket(registry, generation="stale")
    installing, waiting = asyncio.Event(), asyncio.Event()
    install = registry.install_caller_ownership

    async def observe(ticket):
        installing.set()
        await install(ticket)

    registry.install_caller_ownership = observe
    gate = _CallerRouteGate()
    original_lock = gate.lock

    class ObservedLock:
        async def __aenter__(self):
            if original_lock.locked():
                waiting.set()
            await original_lock.acquire()

        async def __aexit__(self, *args):
            original_lock.release()

    gate.lock = ObservedLock()
    affinity._caller_gates[selected.routing_key] = gate
    async with acquire(registry, ownership=old_ticket):
        first = asyncio.create_task(affinity.forward_caller_request(selected.routing_key, {}, "verified"))
        await asyncio.wait_for(installing.wait(), 5)
        second = asyncio.create_task(affinity.forward_caller_request(selected.routing_key, {}, "verified"))
        await asyncio.wait_for(waiting.wait(), 5)
        assert not first.done()
        assert not second.done()
    tickets = await asyncio.wait_for(asyncio.gather(first, second), 5)
    assert tickets[0] is tickets[1]
    assert old_ticket.state is CallerOwnershipState.REVOKED
    async with acquire(registry, ownership=tickets[0]):
        pass
    assert len(created) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_initialization_failure_rejects_waiters_and_releases_generation(routed_registry, cancel):
    """Failed coordinators revoke pending authority and reject already waiting admissions."""
    from mcpgateway.services.session_affinity import _CallerRouteGate

    affinity, registry, redis, created = routed_registry
    selected = binding()
    entered, waiting, resume = asyncio.Event(), asyncio.Event(), asyncio.Event()
    gate = _CallerRouteGate()
    original_lock = gate.lock

    class ObservedLock:
        async def __aenter__(self):
            if original_lock.locked():
                waiting.set()
            await original_lock.acquire()

        async def __aexit__(self, *args):
            original_lock.release()

    gate.lock = ObservedLock()
    affinity._caller_gates[selected.routing_key] = gate
    install = registry.install_caller_ownership

    async def fail(ticket):
        await install(ticket)
        entered.set()
        await resume.wait()
        raise OSError("initialization failed")

    registry.install_caller_ownership = fail
    first = asyncio.create_task(affinity.forward_caller_request(selected.routing_key, {}, "verified"))
    await asyncio.wait_for(entered.wait(), 5)
    second = asyncio.create_task(affinity.forward_caller_request(selected.routing_key, {}, "verified"))
    await asyncio.wait_for(waiting.wait(), 5)
    if cancel:
        first.cancel()
    else:
        resume.set()
    with pytest.raises(asyncio.CancelledError if cancel else CallerSessionError):
        await asyncio.wait_for(first, 5)
    with pytest.raises(CallerOwnershipLostError):
        await asyncio.wait_for(second, 5)
    assert not registry._caller_ownership
    assert not registry._callers
    assert not created
    assert redis.owner is None
    assert not original_lock.locked()
    registry.install_caller_ownership = install
    fresh = await affinity.forward_caller_request(selected.routing_key, {}, "verified")
    assert fresh.state is CallerOwnershipState.READY


@pytest.mark.asyncio
async def test_shared_lease_loss_prevents_queued_dispatch(routed_registry):
    """Queued operations recheck Redis after the active operation releases its lock."""
    affinity, registry, redis, created = routed_registry
    ticket = await affinity.forward_caller_request(binding().routing_key, {}, "verified")
    dispatched = []
    validated = asyncio.Event()
    validate = ticket.validator

    async def observe(ownership):
        await validate(ownership)
        validated.set()

    ticket.validator = observe

    async def queued():
        async with acquire(registry, ownership=ticket):
            dispatched.append(True)

    async with acquire(registry, ownership=ticket):
        validated.clear()
        task = asyncio.create_task(queued())
        await asyncio.wait_for(validated.wait(), 5)
        # The completed admission check reaches the held entry lock without another await.
        redis.owner, redis.generation = "remote", "two"
    with pytest.raises(CallerOwnershipLostError):
        await asyncio.wait_for(task, 5)
    assert not dispatched
    assert len(created) == 1
    assert not registry._callers


@pytest.mark.asyncio
async def test_revoked_forward_cannot_revive_generation_after_release_failure(routed_registry):
    """A delayed signed forward cannot resurrect a generation whose cleanup failed."""
    affinity, registry, redis, _ = routed_registry
    selected = binding()
    old = await affinity.forward_caller_request(selected.routing_key, {}, "verified")
    await affinity._revoke_caller_ticket(old)
    redis.fail_release = True
    await affinity._renew_caller_routes(redis)
    token = forwarded_caller_ownership.set((selected.routing_key, "local", old.generation))
    try:
        with pytest.raises(CallerOwnershipLostError):
            await affinity.forward_caller_request(selected.routing_key, {}, "verified")
    finally:
        forwarded_caller_ownership.reset(token)
    fresh = await affinity.forward_caller_request(selected.routing_key, {}, "verified")
    assert fresh.generation != old.generation
    assert fresh is registry._caller_ownership[selected.routing_key]


@pytest.mark.asyncio
async def test_delayed_heartbeat_does_not_revoke_new_generation(routed_registry):
    """An old heartbeat response cannot remove newer local authority or sessions."""
    affinity, registry, redis, _ = routed_registry
    selected = binding()
    old = await affinity.forward_caller_request(selected.routing_key, {}, "verified")
    entered, resume = asyncio.Event(), asyncio.Event()
    evaluate = redis.eval

    async def pause(script, *args):
        if "caller_renew_v1" in script:
            entered.set()
            await resume.wait()
            return 0
        return await evaluate(script, *args)

    redis.eval = pause
    task = asyncio.create_task(affinity._renew_caller_routes(redis))
    await asyncio.wait_for(entered.wait(), 5)
    old.revoke()
    fresh = await affinity.forward_caller_request(selected.routing_key, {}, "verified")
    async with acquire(registry, ownership=fresh) as upstream:
        resume.set()
        await asyncio.wait_for(task, 5)
        assert not upstream.is_closed
        assert fresh.state is CallerOwnershipState.READY
        assert affinity._caller_routes[selected.routing_key] is fresh


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ownership", [[], {"route": "wrong", "owner": "local", "generation": "one"}, {"route": "route", "owner": "other", "generation": "one"}, {"route": "route", "owner": "local", "generation": ""}]
)
async def test_signed_forward_rejects_invalid_ownership_fields(monkeypatch, ownership):
    """Even signed envelopes need matching route, owner, and generation before internal dispatch."""
    from mcpgateway.auth_context import FORWARD_SIG_FIELD, sign_redis_forward_envelope
    from mcpgateway.services import session_affinity as module

    monkeypatch.setattr(module, "get_worker_id", lambda: "local")
    dispatch = AsyncMock()
    monkeypatch.setattr(module, "post_rpc_in_process", dispatch)
    request = {"method": "tools/call", "params": {}, "auth_context": "verified", "mcp_session_id": "route", "caller_ownership": ownership}
    request[FORWARD_SIG_FIELD] = sign_redis_forward_envelope(request)
    result = await module.SessionAffinity()._execute_forwarded_request(request)
    assert result == {"error": {"code": -32000, "message": "Caller session ownership lost"}}
    dispatch.assert_not_awaited()
    assert forwarded_caller_ownership.get() is None


@pytest.mark.asyncio
async def test_signed_forward_carries_and_resets_generation_context(routed_registry, monkeypatch):
    """Verified generation authority reaches internal dispatch and cannot leak to another request."""
    import httpx

    from mcpgateway.auth_context import FORWARD_SIG_FIELD, sign_redis_forward_envelope
    from mcpgateway.services import session_affinity as module

    affinity, _, redis, _ = routed_registry
    selected = binding()
    ticket = await affinity.forward_caller_request(selected.routing_key, {}, "verified")

    async def dispatch(**kwargs):
        assert forwarded_caller_ownership.get() == (selected.routing_key, "local", ticket.generation)
        redis.generation = "new-generation"
        with pytest.raises(CallerOwnershipLostError):
            await affinity.forward_caller_request(selected.routing_key, {}, "verified")
        return httpx.Response(200, json={"error": {"code": -32000, "message": "Caller session ownership lost"}})

    monkeypatch.setattr(module, "post_rpc_in_process", dispatch)
    request = {
        "method": "tools/call",
        "params": {},
        "auth_context": "verified",
        "mcp_session_id": selected.routing_key,
        "caller_ownership": {"route": selected.routing_key, "owner": "local", "generation": ticket.generation},
    }
    request[FORWARD_SIG_FIELD] = sign_redis_forward_envelope(request)
    assert "error" in await affinity._execute_forwarded_request(request)
    assert forwarded_caller_ownership.get() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_forwarded_authority_cannot_fall_back_without_binding(monkeypatch, enabled):
    """Trusted forwarded ownership never turns into an unpinned local operation."""
    from mcpgateway.services import session_affinity as module

    monkeypatch.setattr(module.settings, "mcpgateway_session_affinity_enabled", enabled)
    token = forwarded_caller_ownership.set((binding().routing_key, "local", "one"))
    try:
        with pytest.raises(CallerOwnershipLostError):
            await module.forward_binding_operation(None, {}, "tools/call", {}, {})
    finally:
        forwarded_caller_ownership.reset(token)


@pytest.mark.asyncio
async def test_cancelled_queued_acquisition_releases_reservation(caller_registry):
    """Cancellation releases queued reservations without closing active state or leaking capacity."""
    registry, _ = caller_registry
    ticket = await ready_ticket(registry)
    admitted = asyncio.Event()
    validate = ticket.validator

    async def observe(ownership):
        await validate(ownership)
        admitted.set()

    ticket.validator = observe

    async def queued():
        async with acquire(registry, ownership=ticket):
            pytest.fail("cancelled waiter reached dispatch")

    async with acquire(registry, ownership=ticket) as upstream:
        admitted.clear()
        task = asyncio.create_task(queued())
        await asyncio.wait_for(admitted.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        entry = next(iter(registry._callers.values()))
        assert entry.users == 1
        assert not upstream.is_closed
    assert entry.users == 0
    assert entry.drained.is_set()
    await registry.evict_caller_route(binding().routing_key, generation=ticket.generation)
    assert not registry._callers
