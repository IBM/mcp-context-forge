# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_gateway_service_reverse_proxy.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Internal reverse-proxy gateway registration tests.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from mcpgateway.db import Gateway as DbGateway
from mcpgateway.services.gateway_service import GatewayService, ReverseProxyGatewayRegistration, ReverseProxyGatewayScope


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
