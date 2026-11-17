# -*- coding: utf-8 -*-
"""Regression checks for caller-session review corrections."""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcpgateway.services import session_affinity as affinity_module
from mcpgateway.services.caller_session import CallerRoutingResult, CallerSessionError, resolve_caller_binding, SESSION_KEY_META
from mcpgateway.services.resource_service import ResourceService
from mcpgateway.services.upstream_session_registry import SessionLifecycle, TransportType, UpstreamSessionRegistry
from tests.unit.mcpgateway.services.test_export_service import export_service as _shared_export_service
from tests.unit.mcpgateway.services.test_export_service import mock_db as _shared_export_db
from tests.unit.mcpgateway.services.test_export_service import sample_gateway as _shared_gateway
from tests.unit.mcpgateway.services.test_sigv4_signing_paths import _sigv4_gateway
from tests.unit.mcpgateway.services.test_sigv4_signing_paths import TestResourceSigning as _ResourceSigning
from tests.unit.mcpgateway.services.test_tool_service_coverage import _make_gateway_payload, _make_tool_payload, _setup_cache_for_invoke
from tests.unit.mcpgateway.services.test_tool_service_coverage import tool_service as _shared_tool_service

export_service = _shared_export_service
mock_db = _shared_export_db
sample_gateway = _shared_gateway
tool_service = _shared_tool_service


def binding(key="a", identity="verified-caller"):
    """Resolve a binding using a simulated verified quota identity."""
    return resolve_caller_binding(caller_identity=identity, quota_identity=identity, server_id="server", downstream_session_id=None, meta={SESSION_KEY_META: key}, pin_sessions_by_caller=False)


@pytest.mark.asyncio
async def test_forwarded_origin_skips_execution_metrics(tool_service):
    """Forwarded origin skips execution metrics."""
    tp = _make_tool_payload(integration_type="MCP", request_type="STREAMABLEHTTP", gateway_id="gw-uuid-1", jsonpath_filter="")
    gp = _make_gateway_payload()
    metrics = MagicMock()
    response = CallerRoutingResult(result={"content": [{"type": "text", "text": "remote"}], "isError": False})
    with (
        _setup_cache_for_invoke(tp, gp),
        patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
        patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=None)),
        patch.object(tool_service, "_resolve_vault_auth_headers", AsyncMock(return_value=None)),
        patch("mcpgateway.services.tool_service.forward_binding_operation", AsyncMock(return_value=response)),
        patch("mcpgateway.services.tool_service.metrics_buffer", metrics),
        patch("mcpgateway.services.tool_service.global_config_cache") as cache,
    ):
        cache.get_passthrough_headers.return_value = []
        result = await tool_service.invoke_tool(MagicMock(), "test_tool", {}, request_headers={}, server_id="server")
    assert result.content[0].text == "remote"
    assert metrics.record_tool_metric.call_count == 0
    assert metrics.record_server_metric.call_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["sse", "streamablehttp"])
async def test_legacy_resource_session_does_not_pin_request_trace(transport):
    """Legacy resource session does not pin request trace."""
    created = []

    async def factory(req):
        """Create an isolated upstream session."""
        session = AsyncMock()
        session.read_resource.return_value = SimpleNamespace(contents=[SimpleNamespace(uri="test://r", text="ok", mimeType="text/plain")])
        created.append(req)
        return session, SessionLifecycle(owner_task=None, shutdown_event=None, client=None)

    registry = UpstreamSessionRegistry(session_factory=factory)
    traces = ["first"]
    try:
        with (
            patch("mcpgateway.services.resource_service._downstream_session_id_from_request", return_value="downstream"),
            patch("mcpgateway.services.resource_service.get_upstream_session_registry", return_value=registry),
            patch("mcpgateway.services.resource_service.inject_trace_context_headers", side_effect=lambda headers: {**headers, "traceparent": traces[0]}),
            patch("mcpgateway.services.resource_service.is_input_capture_enabled", return_value=False),
            patch("mcpgateway.services.resource_service.is_output_capture_enabled", return_value=False),
        ):
            for trace in ("first", "second"):
                traces[0] = trace
                await ResourceService().invoke_resource(
                    MagicMock(), "res-1", "test://r", resource_obj=_ResourceSigning._resource(), gateway_obj=_sigv4_gateway(transport=transport, auth_type=None, sigv4_config=None)
                )
        assert len(created) == 1
        assert "traceparent" not in created[0].headers
        assert created[0].request_headers is None
    finally:
        await registry.close_all()


@pytest.mark.asyncio
async def test_cancelled_gate_waiter_preserves_other_waiters(monkeypatch):
    """Cancelled gate waiter preserves other waiters."""
    affinity = affinity_module.SessionAffinity()
    gate = affinity_module._CallerRouteGate()
    lock = asyncio.Lock()
    await lock.acquire()
    entered = 0
    both = asyncio.Event()

    class ObservedLock:
        """Provide controlled state for the regression."""

        async def __aenter__(self):
            """Observe gate contention before waiting for admission."""
            nonlocal entered
            entered += 1
            if entered == 2:
                both.set()
            await lock.acquire()

        async def __aexit__(self, *args):
            """Release the observed route gate."""
            lock.release()

    gate.lock = ObservedLock()
    route = binding().routing_key
    affinity._caller_gates[route] = gate
    redis = SimpleNamespace(eval=AsyncMock(return_value=["remote", "generation", 0, 300000]))
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=redis))
    first = asyncio.create_task(affinity.forward_caller_request(route, {}, "verified"))
    second = asyncio.create_task(affinity.forward_caller_request(route, {}, "verified"))
    await asyncio.wait_for(both.wait(), 5)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert gate.failures == 0
    redis = SimpleNamespace(eval=AsyncMock(return_value=["remote", "generation", 0, 300000]))
    with patch("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=redis)), patch.object(affinity, "_forward_rpc_to_worker", AsyncMock(return_value={"result": {}})):
        lock.release()
        assert await asyncio.wait_for(second, 5) == {"result": {}}


@pytest.mark.asyncio
async def test_expiry_does_not_block_unrelated_legacy_acquisition():
    """Expiry does not block unrelated legacy acquisition."""

    async def factory(req):
        """Create an isolated upstream session."""
        return MagicMock(), SessionLifecycle(owner_task=None, shutdown_event=None, client=None)

    registry = UpstreamSessionRegistry(session_factory=factory, caller_idle_timeout=600)
    async with registry.acquire_caller(binding=binding(), gateway_id="gateway", url="https://upstream/mcp", headers={}, transport_type=TransportType.STREAMABLE_HTTP):
        pass
    for entry in registry._callers.values():
        entry.last_used = time.monotonic() - 1000
    closing = asyncio.Event()
    resume = asyncio.Event()
    original = registry._close_session

    async def close(session):
        """Pause teardown at a controlled synchronization point."""
        closing.set()
        await resume.wait()
        await original(session)

    registry._close_session = close
    expiry = asyncio.create_task(registry.expire_callers())
    await asyncio.wait_for(closing.wait(), 5)
    assert not registry._global_lock.locked()

    async def acquire_legacy():
        """Execute an unrelated downstream acquisition while caller teardown is paused."""
        async with registry.acquire(downstream_session_id="unrelated-downstream", gateway_id="other-gateway", url="https://upstream/mcp", headers={}, transport_type=TransportType.STREAMABLE_HTTP):
            return True

    legacy = asyncio.create_task(acquire_legacy())
    assert await asyncio.wait_for(legacy, 5)
    async with registry.acquire_caller(binding=binding(identity="other-caller"), gateway_id="other-gateway", url="https://upstream/mcp", headers={}, transport_type=TransportType.STREAMABLE_HTTP):
        pass
    resume.set()
    await asyncio.wait_for(asyncio.gather(expiry, legacy), 5)
    await registry.close_all()


@pytest.mark.asyncio
async def test_s1_identity_quota_preserves_capacity_for_other_callers():
    """S1 identity quota preserves capacity for other callers."""

    async def factory(req):
        """Create an isolated upstream session."""
        return MagicMock(), SessionLifecycle(owner_task=None, shutdown_event=None, client=None)

    registry = UpstreamSessionRegistry(session_factory=factory, caller_max_bindings=3, caller_max_bindings_per_identity=1)

    async def use(selected):
        """Acquire and release one caller binding."""
        async with registry.acquire_caller(binding=selected, gateway_id="gateway", url="https://upstream/mcp", headers={}, transport_type=TransportType.STREAMABLE_HTTP):
            pass

    try:
        await use(binding("a"))
        with pytest.raises(CallerSessionError, match="quota exhausted"):
            await use(binding("b"))
        await use(binding("other", identity="another-caller"))
    finally:
        await registry.close_all()


@pytest.mark.asyncio
async def test_forwarding_records_one_execution_for_one_dispatch(tool_service):
    """Forwarding records one execution for one dispatch."""
    from tests.unit.mcpgateway.services.test_tool_service_coverage import TextContent, ToolResult

    tp = _make_tool_payload(integration_type="MCP", request_type="STREAMABLEHTTP", gateway_id="gw-uuid-1", jsonpath_filter="")
    gp = _make_gateway_payload()
    gp["pin_sessions_by_caller"] = True
    metrics = MagicMock()
    dispatch = AsyncMock(return_value=ToolResult(content=[TextContent(type="text", text="remote")], is_error=False))

    async def factory(req):
        """Create an isolated upstream session."""
        session = MagicMock()
        session.call_tool = dispatch
        return session, SessionLifecycle(owner_task=None, shutdown_event=None, client=None)

    registry = UpstreamSessionRegistry(session_factory=factory)
    context = {"is_authenticated": True, "caller_session_identity": "verified-caller", "email": "user@example.com"}
    origin = True

    async def forward(*args, **kwargs):
        """Dispatch through the real owner service before returning its response."""
        nonlocal origin
        if origin:
            origin = False
            owner = await tool_service.invoke_tool(MagicMock(), "test_tool", {}, request_headers={}, server_id="server", caller_auth_context=context)
            return CallerRoutingResult(result=owner.model_dump(by_alias=True))
        return CallerRoutingResult()

    try:
        with (
            _setup_cache_for_invoke(tp, gp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=None)),
            patch.object(tool_service, "_resolve_vault_auth_headers", AsyncMock(return_value=None)),
            patch("mcpgateway.services.tool_service.forward_binding_operation", side_effect=forward),
            patch("mcpgateway.services.tool_service.get_upstream_session_registry", return_value=registry),
            patch("mcpgateway.services.tool_service.settings.mcpgateway_session_affinity_enabled", False),
            patch("mcpgateway.services.tool_service.metrics_buffer", metrics),
            patch("mcpgateway.services.tool_service.global_config_cache") as cache,
        ):
            cache.get_passthrough_headers.return_value = []
            await tool_service.invoke_tool(MagicMock(), "test_tool", {}, request_headers={}, server_id="server", caller_auth_context=context)
        assert dispatch.await_count == 1
        assert metrics.record_tool_metric.call_count == 1
        assert metrics.record_server_metric.call_count == 1
    finally:
        await registry.close_all()


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [OSError("transient"), RuntimeError("transient")])
@pytest.mark.parametrize("transport,attempts", [("sse", 2), ("streamablehttp", 1)])
async def test_default_resource_retries_preserve_previous_attempt_count(error, transport, attempts):
    """Default sse retries preserve previous attempt count."""
    from contextlib import asynccontextmanager

    from mcpgateway.services.resource_service import ResourceError

    session = AsyncMock()
    session.read_resource.side_effect = [error, SimpleNamespace(contents=[SimpleNamespace(uri="test://r", text="ok", mimeType="text/plain")])]

    @asynccontextmanager
    async def proxy(**kwargs):
        """Provide controlled state for the regression."""
        yield SimpleNamespace(session=session)

    with (
        patch("mcpgateway.services.resource_service._downstream_session_id_from_request", return_value=None),
        patch("mcpgateway.services.resource_service.mcp_proxy_client", proxy),
        patch("mcpgateway.services.resource_service.is_input_capture_enabled", return_value=False),
        patch("mcpgateway.services.resource_service.is_output_capture_enabled", return_value=False),
    ):
        operation = ResourceService().invoke_resource(
            MagicMock(),
            "res-1",
            "test://r",
            resource_obj=_ResourceSigning._resource(),
            gateway_obj=_sigv4_gateway(transport=transport, auth_type=None, sigv4_config=None, pin_sessions_by_caller=False),
        )
        if attempts == 1:
            with pytest.raises(ResourceError):
                await operation
        else:
            assert await operation == "ok"
    assert session.read_resource.await_count == attempts


@pytest.mark.asyncio
async def test_expired_selected_entry_retires_without_capacity_pressure():
    """Expired selected entry retires without capacity pressure."""
    created = []

    async def factory(req):
        """Create an isolated upstream session."""
        session = MagicMock()
        created.append(session)
        return session, SessionLifecycle(owner_task=None, shutdown_event=None, client=None)

    registry = UpstreamSessionRegistry(session_factory=factory)

    async def use():
        """Acquire and release one caller binding."""
        async with registry.acquire_caller(binding=binding(), gateway_id="gateway", url="https://upstream/mcp", headers={}, transport_type=TransportType.STREAMABLE_HTTP):
            pass

    try:
        await use()
        next(iter(registry._callers.values())).last_used = time.monotonic() - 1000
        await use()
        assert len(created) == 2
        assert registry._caller_identity_counts == {"verified-caller": 1}
    finally:
        await registry.close_all()
    assert not registry._caller_identity_counts


@pytest.mark.asyncio
async def test_identity_quota_survives_token_server_and_gateway_changes():
    """Identity quota survives token server and gateway changes."""
    from mcpgateway.services.caller_session import verified_caller_identity, verified_quota_identity

    async def factory(req):
        """Create an isolated upstream session."""
        return MagicMock(), SessionLifecycle(owner_task=None, shutdown_event=None, client=None)

    registry = UpstreamSessionRegistry(session_factory=factory, caller_max_bindings=10, caller_max_bindings_per_identity=1)
    quota = verified_quota_identity("same@example.com", "issuer")

    def selected(token, server):
        """Resolve a token-specific binding with a stable quota identity."""
        return resolve_caller_binding(
            caller_identity=verified_caller_identity(token, "same@example.com", "issuer"),
            quota_identity=quota,
            server_id=server,
            downstream_session_id=None,
            meta={SESSION_KEY_META: token},
            pin_sessions_by_caller=False,
        )

    async def use(token, server, gateway):
        """Acquire and release one caller binding."""
        async with registry.acquire_caller(binding=selected(token, server), gateway_id=gateway, url="https://upstream/mcp", headers={}, transport_type=TransportType.STREAMABLE_HTTP):
            pass

    try:
        await use("first-token", "first-server", "first-gateway")
        with pytest.raises(CallerSessionError, match="quota exhausted"):
            await use("rotated-token", "other-server", "other-gateway")
        await registry.evict_gateway("first-gateway")
        assert not registry._caller_identity_counts
        await use("rotated-token", "other-server", "other-gateway")
    finally:
        await registry.close_all()
    assert not registry._caller_identity_counts


@pytest.mark.asyncio
async def test_cancelled_expiry_keeps_retirement_and_reservations():
    """Cancelled expiry keeps retirement and reservations."""

    async def factory(req):
        """Create an isolated upstream session."""
        return MagicMock(), SessionLifecycle(owner_task=None, shutdown_event=None, client=None)

    registry = UpstreamSessionRegistry(session_factory=factory, caller_max_bindings=3, caller_max_bindings_per_identity=1)
    entered, resume = asyncio.Event(), asyncio.Event()
    original = registry._close_session

    async def close(upstream):
        """Pause teardown at a controlled synchronization point."""
        entered.set()
        await resume.wait()
        await original(upstream)

    try:
        async with registry.acquire_caller(binding=binding(), gateway_id="gateway", url="https://upstream/mcp", headers={}, transport_type=TransportType.STREAMABLE_HTTP):
            pass
        entry = next(iter(registry._callers.values()))
        entry.last_used = time.monotonic() - 1000
        registry._close_session = close
        task = asyncio.create_task(registry.expire_callers())
        await asyncio.wait_for(entered.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not entry.retirement.cancelled()
        assert registry._caller_identity_counts == {"verified-caller": 1}
        resume.set()
        await asyncio.wait_for(entry.retirement, 5)
        assert not registry._caller_identity_counts
        assert not registry._callers
    finally:
        resume.set()
        await registry.close_all()


@pytest.mark.asyncio
async def test_warm_acquisition_validates_shared_ownership_once():
    """Warm acquisition validates shared ownership once."""
    from tests.unit.mcpgateway.services.test_caller_session import ready_ticket

    async def factory(req):
        """Create an isolated upstream session."""
        return MagicMock(), SessionLifecycle(owner_task=None, shutdown_event=None, client=None)

    registry = UpstreamSessionRegistry(session_factory=factory)
    selected = binding()
    validator = AsyncMock()
    ticket = await ready_ticket(registry, selected, validator=validator)
    try:
        for _ in range(2):
            validator.reset_mock()
            async with registry.acquire_caller(binding=selected, ownership=ticket, gateway_id="gateway", url="https://upstream/mcp", headers={}, transport_type=TransportType.STREAMABLE_HTTP):
                pass
            validator.assert_awaited_once_with(ticket)
    finally:
        await registry.close_all()


@pytest.mark.asyncio
async def test_cancelled_ready_validation_does_not_revoke_ticket(monkeypatch):
    """Cancelled ready validation does not revoke ticket."""
    from mcpgateway.services.caller_session import CallerOwnershipState, CallerOwnershipTicket

    entered = asyncio.Event()

    async def evaluate(*args):
        """Pause a shared validation until request cancellation."""
        entered.set()
        await asyncio.Event().wait()

    redis = SimpleNamespace(eval=evaluate)
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=redis))
    affinity = affinity_module.SessionAffinity()
    ticket = CallerOwnershipTicket(binding().routing_key, "worker", "generation", time.monotonic() + 300, affinity._validate_caller_ticket, state=CallerOwnershipState.READY)
    task = asyncio.create_task(ticket.validate())
    await asyncio.wait_for(entered.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert ticket.state is CallerOwnershipState.READY


@pytest.mark.asyncio
async def test_forward_timeout_does_not_poison_route_gate(monkeypatch):
    """Forward timeout does not poison route gate."""
    route = binding().routing_key
    gate = affinity_module._CallerRouteGate()
    affinity = affinity_module.SessionAffinity()
    affinity._caller_gates[route] = gate
    redis = SimpleNamespace(eval=AsyncMock(return_value=["remote", "generation", 0, 300000]))
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=redis))
    with patch.object(affinity, "_forward_rpc_to_worker", AsyncMock(side_effect=TimeoutError)):
        with pytest.raises(CallerSessionError):
            await affinity.forward_caller_request(route, {}, "verified")
    assert gate.failures == 0
    with patch.object(affinity, "_forward_rpc_to_worker", AsyncMock(return_value={"result": {}})):
        assert await affinity.forward_caller_request(route, {}, "verified") == {"result": {}}


@pytest.mark.asyncio
async def test_script_cache_is_per_redis_client():
    """Script cache is per redis client."""

    class Client:
        """Provide controlled state for the regression."""

        def __init__(self):
            """Initialize the controlled client."""
            self.registered = []

        def register_script(self, script):
            """Register one callable ownership script."""
            self.registered.append(script)

            async def execute(**kwargs):
                """Return the supplied script argument."""
                return kwargs["args"][0]

            return execute

    affinity = affinity_module.SessionAffinity()
    first, second = Client(), Client()
    assert await affinity._caller_eval(first, "script", 1, "key", "value") == "value"
    assert await affinity._caller_eval(first, "script", 1, "key", "next") == "next"
    assert await affinity._caller_eval(second, "script", 1, "key", "reconnected") == "reconnected"
    assert first.registered == second.registered == ["script"]


def test_rejection_events_are_bounded_and_identifier_free(caplog):
    """Rejection events are bounded and identifier free."""
    from mcpgateway.services import caller_session

    caller_session._CALLER_EVENT_TIMES.clear()
    with caplog.at_level("WARNING", logger="mcpgateway.services.caller_session"):
        for _ in range(10):
            caller_session.log_caller_event("caller_session_quota_rejected")
    assert len(caplog.records) == 1
    assert caplog.records[0].event == "caller_session_quota_rejected"
    assert "verified-caller" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", [True, False])
async def test_caller_pinning_export_import_round_trip(export_service, mock_db, sample_gateway, flag):
    """Gateway exports and import schemas preserve both explicit caller-pinning values."""
    from mcpgateway.services.import_service import ImportService

    sample_gateway.pin_sessions_by_caller = flag
    with patch.object(export_service, "_fetch_all_gateways", AsyncMock(return_value=[sample_gateway])):
        exported = await export_service._export_gateways(mock_db, None, False)
    assert exported[0]["pin_sessions_by_caller"] is flag
    importer = ImportService()
    assert importer._convert_to_gateway_create(exported[0]).pin_sessions_by_caller is flag
    assert importer._convert_to_gateway_update(exported[0]).pin_sessions_by_caller is flag
    exported[0].pop("pin_sessions_by_caller")
    assert importer._convert_to_gateway_create(exported[0]).pin_sessions_by_caller is False
    assert importer._convert_to_gateway_update(exported[0]).pin_sessions_by_caller is None


@pytest.mark.parametrize("authenticated", [False, None])
def test_anonymous_context_cannot_supply_quota_authority(authenticated):
    """Anonymous context cannot mint quota authority through client-like ownership fields."""
    from mcpgateway.services.caller_session import quota_identity_from_context

    assert quota_identity_from_context({"is_authenticated": authenticated, "caller_quota_identity": "forged"}) is None


def test_missing_verified_quota_authority_fails_closed():
    """A session identity alone cannot create an unaccounted caller binding."""
    with pytest.raises(CallerSessionError, match="identity unavailable"):
        resolve_caller_binding(caller_identity="token", server_id="server", downstream_session_id=None, meta={SESSION_KEY_META: "key"}, pin_sessions_by_caller=True)


def test_identity_quota_configuration_rejects_zero():
    """Identity quota configuration requires a positive reservation limit."""
    from pydantic import ValidationError

    from mcpgateway.config import Settings

    with pytest.raises(ValidationError):
        Settings(mcp_caller_session_max_bindings_per_identity=0)


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["remote execution failed", "forwarding timed out"])
async def test_forwarding_errors_finish_spans_without_execution_metrics(tool_service, message):
    """Remote failures finish the origin span without claiming another local execution."""
    metrics = MagicMock()
    span_context = MagicMock()

    async def fail(*args, **kwargs):
        """Mark remote ownership before raising its forwarding failure."""
        kwargs["on_forward"]()
        raise CallerSessionError(message)

    with (
        _setup_cache_for_invoke(_make_tool_payload(integration_type="MCP", request_type="STREAMABLEHTTP", gateway_id="gw-uuid-1", jsonpath_filter=""), _make_gateway_payload()),
        patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
        patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=None)),
        patch.object(tool_service, "_resolve_vault_auth_headers", AsyncMock(return_value=None)),
        patch("mcpgateway.services.tool_service.forward_binding_operation", side_effect=fail),
        patch("mcpgateway.services.tool_service.metrics_buffer", metrics),
        patch("mcpgateway.services.tool_service.create_span", return_value=span_context),
        patch("mcpgateway.services.tool_service.global_config_cache") as cache,
    ):
        cache.get_passthrough_headers.return_value = []
        with pytest.raises(CallerSessionError, match=message):
            await tool_service.invoke_tool(MagicMock(), "test_tool", {}, request_headers={}, server_id="server")
    metrics.record_tool_metric.assert_not_called()
    metrics.record_server_metric.assert_not_called()
    assert span_context.__exit__.called


def test_nested_execution_scopes_reset_after_errors():
    """Nested forwarding cannot mark a parent execution or leak ownership to another request."""
    from mcpgateway.services.caller_session import caller_execution_scope, mark_caller_execution_forwarded

    with caller_execution_scope() as parent:
        with caller_execution_scope() as child:
            mark_caller_execution_forwarded()
            assert child.forwarded
            assert not parent.forwarded
        with pytest.raises(RuntimeError):
            with caller_execution_scope():
                mark_caller_execution_forwarded()
                raise RuntimeError("nested request failed")
        assert not parent.forwarded
        mark_caller_execution_forwarded()
        assert parent.forwarded
    with caller_execution_scope() as fresh:
        assert not fresh.forwarded


def test_missing_principal_keeps_default_authentication_behavior():
    """Identity-less verified contexts keep default dispatch but cannot establish caller bindings."""
    from mcpgateway.services.caller_session import quota_identity_from_context

    quota = quota_identity_from_context({"is_authenticated": True})
    assert quota is None
    assert resolve_caller_binding(caller_identity="verified-token", quota_identity=quota, server_id=None, downstream_session_id=None, meta=None, pin_sessions_by_caller=False) is None
    with pytest.raises(CallerSessionError, match="identity unavailable"):
        resolve_caller_binding(caller_identity="verified-token", quota_identity=quota, server_id=None, downstream_session_id=None, meta=None, pin_sessions_by_caller=True)


@pytest.mark.asyncio
async def test_shutdown_rejects_inflight_creation_and_releases_quota():
    """Shutdown rejects unfinished caller creation and releases its session and reservations."""
    entered, resume = asyncio.Event(), asyncio.Event()

    async def factory(req):
        """Pause construction until registry shutdown completes."""
        entered.set()
        await resume.wait()
        return MagicMock(), SessionLifecycle(owner_task=None, shutdown_event=None, client=None)

    registry = UpstreamSessionRegistry(session_factory=factory)

    async def acquire():
        """Reject dispatch when shutdown overtakes connection construction."""
        async with registry.acquire_caller(binding=binding(), gateway_id="gateway", url="https://upstream/mcp", headers={}, transport_type=TransportType.STREAMABLE_HTTP):
            pytest.fail("shutdown admitted a new caller dispatch")

    task = asyncio.create_task(acquire())
    try:
        await asyncio.wait_for(entered.wait(), 5)
        await registry.close_all()
        resume.set()
        with pytest.raises(CallerSessionError, match="registry is closing"):
            await asyncio.wait_for(task, 5)
        assert not registry._callers
        assert not registry._caller_identity_counts
        assert registry.snapshot().active_sessions == 0
    finally:
        resume.set()
        await asyncio.gather(task, return_exceptions=True)
        await registry.close_all()
