# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_gateway_service_reverse_proxy.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Internal reverse-proxy gateway registration tests.
"""

from types import SimpleNamespace
from datetime import datetime, timezone
from contextlib import nullcontext
from unittest.mock import AsyncMock, MagicMock

import pytest

from mcpgateway.db import Gateway as DbGateway
from mcpgateway.services.gateway_service import GatewayService, ReverseProxyGatewayRegistration, ReverseProxyGatewayScope
from mcpgateway.services.reverse_proxy_sessions import ConnectionId, LocalSessionId, ReverseProxyEviction, ReverseProxySessionManager, StableGatewayId


@pytest.mark.asyncio
async def test_internal_reverse_proxy_registration_persists_without_network_initialization(test_db, monkeypatch):
    # Given
    service = GatewayService()
    service._initialize_gateway_with_timeout = AsyncMock()
    service._notify_gateway_added = AsyncMock()
    registry_cache = SimpleNamespace(invalidate_gateways=AsyncMock())
    tool_cache = SimpleNamespace(invalidate_gateway=AsyncMock())
    monkeypatch.setattr("mcpgateway.services.gateway_service._get_registry_cache", lambda: registry_cache)
    monkeypatch.setattr("mcpgateway.services.gateway_service._get_tool_lookup_cache", lambda: tool_cache)
    monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", SimpleNamespace(invalidate_tags=AsyncMock()))
    monkeypatch.setattr("mcpgateway.services.gateway_service.audit_trail", MagicMock(log_action=MagicMock()))
    monkeypatch.setattr("mcpgateway.services.gateway_service.structured_logger", MagicMock(log=MagicMock()))
    registration = ReverseProxyGatewayRegistration(
        stable_id="831ca569cfa55f89bf5a80720d32ef25",  # pragma: allowlist secret
        name="proxied-alpha",
        description="Local alpha server",
        owner_email="owner@example.com",
        scope=ReverseProxyGatewayScope(team_id=None, visibility="public"),
    )

    # When
    result = await service.register_reverse_proxy_gateway(test_db, registration)

    # Then
    persisted = test_db.get(DbGateway, registration.stable_id)
    assert result.id == registration.stable_id
    assert persisted is not None
    assert persisted.transport == "PROXIED"
    assert persisted.url == f"reverse-proxy://catalog/{registration.stable_id}"
    assert persisted.created_via == "reverse_proxy"
    assert persisted.enabled is True
    assert persisted.reachable is True
    assert persisted.owner_email == "owner@example.com"
    assert persisted.visibility == "public"
    service._initialize_gateway_with_timeout.assert_not_awaited()
    service._notify_gateway_added.assert_awaited_once()
    registry_cache.invalidate_gateways.assert_awaited_once()
    tool_cache.invalidate_gateway.assert_awaited_once_with(registration.stable_id)


@pytest.mark.asyncio
async def test_internal_reverse_proxy_registration_reconciles_matching_gateway(test_db, monkeypatch):
    # Given
    service = GatewayService()
    service._notify_gateway_added = AsyncMock()
    monkeypatch.setattr("mcpgateway.services.gateway_service._get_registry_cache", lambda: SimpleNamespace(invalidate_gateways=AsyncMock()))
    monkeypatch.setattr("mcpgateway.services.gateway_service._get_tool_lookup_cache", lambda: SimpleNamespace(invalidate_gateway=AsyncMock()))
    monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", SimpleNamespace(invalidate_tags=AsyncMock()))
    registration = ReverseProxyGatewayRegistration(
        stable_id="23bffbef515258d184d3421c95215c72",  # pragma: allowlist secret
        name="proxied-reconnect",
        description=None,
        owner_email="owner@example.com",
        scope=ReverseProxyGatewayScope(team_id=None, visibility="public"),
    )

    # When
    first = await service.register_reverse_proxy_gateway(test_db, registration)
    second = await service.register_reverse_proxy_gateway(test_db, registration)

    # Then
    assert first.id == second.id
    assert test_db.query(DbGateway).filter(DbGateway.id == registration.stable_id).count() == 1
    service._notify_gateway_added.assert_awaited_once()


@pytest.mark.asyncio
async def test_mark_reverse_proxy_gateway_unreachable_requires_internal_authority(test_db, monkeypatch):
    """Only transport-plus-server-provenance rows are updated; catalog rows remain present."""
    seen_at = datetime(2026, 8, 13, 12, tzinfo=timezone.utc)
    internal = DbGateway(id="internal-proxied", name="internal", slug="internal", url="reverse-proxy://catalog/internal", transport="PROXIED", created_via="reverse_proxy", reachable=True, capabilities={})
    forged = DbGateway(id="forged-proxied", name="forged", slug="forged", url="reverse-proxy://catalog/forged", transport="PROXIED", created_via="api", reachable=True, capabilities={})
    test_db.add_all([internal, forged])
    test_db.commit()
    monkeypatch.setattr("mcpgateway.services.gateway_service.fresh_db_session", lambda: nullcontext(test_db))

    manager = ReverseProxySessionManager()
    evictions = tuple(ReverseProxyEviction(StableGatewayId(gateway_id), ConnectionId("old")) for gateway_id in (internal.id, forged.id))
    await GatewayService().mark_reverse_proxy_gateways_unreachable(manager, evictions, seen_at=seen_at)

    assert test_db.get(DbGateway, internal.id) is internal
    assert internal.reachable is False
    assert internal.last_seen is not None
    assert internal.last_seen.replace(tzinfo=timezone.utc) == seen_at
    assert forged.reachable is True


@pytest.mark.asyncio
async def test_unreachable_commit_invalidates_gateway_registry_cache(test_db, monkeypatch):
    """A successful reachability commit invalidates cached gateway reads."""
    gateway = DbGateway(id="cached-proxied", name="cached", slug="cached", url="reverse-proxy://catalog/cached", transport="PROXIED", created_via="reverse_proxy", reachable=True, capabilities={})
    test_db.add(gateway)
    test_db.commit()
    cache = SimpleNamespace(invalidate_gateways=AsyncMock())
    monkeypatch.setattr("mcpgateway.services.gateway_service.fresh_db_session", lambda: nullcontext(test_db))
    monkeypatch.setattr("mcpgateway.services.gateway_service._get_registry_cache", lambda: cache)

    manager = ReverseProxySessionManager()
    eviction = ReverseProxyEviction(StableGatewayId(gateway.id), ConnectionId("old"))
    await GatewayService().mark_reverse_proxy_gateways_unreachable(manager, (eviction,), seen_at=datetime.now(tz=timezone.utc))

    cache.invalidate_gateways.assert_awaited_once()


@pytest.mark.asyncio
async def test_unreachable_batch_continues_after_persistence_failure_and_invalidates_once(monkeypatch):
    # Given
    gateways = [
        SimpleNamespace(transport="PROXIED", created_via="reverse_proxy", reachable=True, last_seen=None)
        for _ in range(3)
    ]
    failure = RuntimeError("second persistence failed")
    sessions = []
    for index, gateway in enumerate(gateways):
        session = MagicMock()
        session.get.return_value = gateway
        if index == 1:
            session.commit.side_effect = failure
        sessions.append(session)
    session_contexts = iter(nullcontext(session) for session in sessions)
    cache = SimpleNamespace(invalidate_gateways=AsyncMock())
    monkeypatch.setattr("mcpgateway.services.gateway_service.fresh_db_session", lambda: next(session_contexts))
    monkeypatch.setattr("mcpgateway.services.gateway_service._get_registry_cache", lambda: cache)
    evictions = tuple(ReverseProxyEviction(StableGatewayId(f"proxied-{index}"), ConnectionId("old")) for index in range(3))

    # When
    with pytest.raises(RuntimeError) as captured:
        await GatewayService().mark_reverse_proxy_gateways_unreachable(
            ReverseProxySessionManager(),
            evictions,
            seen_at=datetime(2026, 8, 13, 12, tzinfo=timezone.utc),
        )

    # Then
    assert captured.value is failure
    assert [session.commit.call_count for session in sessions] == [1, 1, 1]
    assert gateways[0].reachable is False
    assert gateways[2].reachable is False
    cache.invalidate_gateways.assert_awaited_once()


@pytest.mark.asyncio
async def test_unreachable_persistence_skips_live_replacement(test_db, monkeypatch):
    """An old generation cannot overwrite reachability after a replacement promotion."""
    gateway = DbGateway(id="replacement-proxied", name="replacement", slug="replacement", url="reverse-proxy://catalog/replacement", transport="PROXIED", created_via="reverse_proxy", reachable=True, capabilities={})
    test_db.add(gateway)
    test_db.commit()
    manager = ReverseProxySessionManager()
    replacement = await manager.connect(MagicMock(), LocalSessionId("replacement"))
    stable_id = StableGatewayId(gateway.id)
    await manager.promote_stable_id(stable_id, replacement.connection_id)
    monkeypatch.setattr("mcpgateway.services.gateway_service.fresh_db_session", lambda: nullcontext(test_db))
    cache = SimpleNamespace(invalidate_gateways=AsyncMock())
    monkeypatch.setattr("mcpgateway.services.gateway_service._get_registry_cache", lambda: cache)

    await GatewayService().mark_reverse_proxy_gateways_unreachable(
        manager,
        (ReverseProxyEviction(stable_id, ConnectionId("old-generation")),),
        seen_at=datetime.now(tz=timezone.utc),
    )

    assert gateway.reachable is True
    cache.invalidate_gateways.assert_not_awaited()


@pytest.mark.asyncio
async def test_unreachable_persistence_requires_distributed_owner_absence(test_db, monkeypatch):
    """A replacement Redis generation prevents an old worker from persisting unreachable."""
    gateway = DbGateway(id="distributed-replacement", name="replacement", slug="distributed-replacement", url="reverse-proxy://catalog/distributed-replacement", transport="PROXIED", created_via="reverse_proxy", reachable=True, capabilities={})
    test_db.add(gateway)
    test_db.commit()
    monkeypatch.setattr("mcpgateway.services.gateway_service.fresh_db_session", lambda: nullcontext(test_db))
    cache = SimpleNamespace(invalidate_gateways=AsyncMock())
    monkeypatch.setattr("mcpgateway.services.gateway_service._get_registry_cache", lambda: cache)
    authority_check = AsyncMock(return_value=False)
    eviction = ReverseProxyEviction(StableGatewayId(gateway.id), ConnectionId("old-generation"))

    await GatewayService().mark_reverse_proxy_gateways_unreachable(
        ReverseProxySessionManager(),
        (eviction,),
        seen_at=datetime.now(tz=timezone.utc),
        authority_check=authority_check,
    )

    authority_check.assert_awaited_once_with(eviction)
    assert gateway.reachable is True
    cache.invalidate_gateways.assert_not_awaited()
