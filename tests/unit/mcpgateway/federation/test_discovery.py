# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/federation/test_discovery.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti
"""

# Standard
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
from zeroconf import ServiceStateChange

# First-Party
import mcpgateway.federation.discovery as discovery


class DummySettings:
    app_name = "test-app"
    port = 12345
    federation_timeout = 5
    skip_ssl_verify = True
    federation_discovery = False
    federation_peers = []
    basic_auth_user = "user"
    basic_auth_password = "pass"
    # HTTPX connection pool settings
    httpx_max_connections = 100
    httpx_max_keepalive_connections = 50
    httpx_keepalive_expiry = 30.0


@patch("mcpgateway.federation.discovery.settings", new=DummySettings)
def test_get_local_addresses_returns_list():
    service = discovery.LocalDiscoveryService()
    addresses = service._get_local_addresses()
    assert isinstance(addresses, list)
    assert all(isinstance(addr, str) for addr in addresses)
    assert addresses  # Should not be empty


@pytest.mark.asyncio
@patch("mcpgateway.federation.discovery.settings", new=DummySettings)
@patch.object(discovery.DiscoveryService, "_get_gateway_info", new_callable=AsyncMock)
async def test_add_peer_valid_url(mock_get_info):
    mock_get_info.return_value = MagicMock()
    service = discovery.DiscoveryService()
    url = "http://peer1:1234"
    added = await service.add_peer(url, source="test")
    assert added is True
    assert url in service._discovered_peers


@pytest.mark.asyncio
@patch("mcpgateway.federation.discovery.settings", new=DummySettings)
@patch.object(discovery.DiscoveryService, "_get_gateway_info", new_callable=AsyncMock)
async def test_add_peer_invalid_url(mock_get_info):
    service = discovery.DiscoveryService()
    url = "not-a-url"
    added = await service.add_peer(url, source="test")
    assert added is False
    assert url not in service._discovered_peers


@patch("mcpgateway.federation.discovery.settings", new=DummySettings)
def test_get_discovered_peers_empty():
    service = discovery.DiscoveryService()
    assert service.get_discovered_peers() == []


@pytest.mark.asyncio
@patch("mcpgateway.federation.discovery.settings", new=DummySettings)
@patch.object(discovery.DiscoveryService, "_get_gateway_info", new_callable=AsyncMock)
async def test_remove_peer(mock_get_info):
    mock_get_info.return_value = MagicMock()
    service = discovery.DiscoveryService()
    url = "http://peer2:5678"
    await service.add_peer(url, source="test")
    assert url in service._discovered_peers
    await service.remove_peer(url)
    assert url not in service._discovered_peers


@pytest.mark.asyncio
@patch("mcpgateway.federation.discovery.settings", new=DummySettings)
@patch.object(discovery.DiscoveryService, "_get_gateway_info", new_callable=AsyncMock)
async def test_refresh_peer_success(mock_get_info):
    mock_get_info.return_value = MagicMock()
    service = discovery.DiscoveryService()
    url = "http://peer3:9999"
    await service.add_peer(url, source="test")
    refreshed = await service.refresh_peer(url)
    assert refreshed is True


@pytest.mark.asyncio
@patch("mcpgateway.federation.discovery.settings", new=DummySettings)
async def test_refresh_peer_not_found():
    service = discovery.DiscoveryService()
    refreshed = await service.refresh_peer("http://notfound:1")
    assert refreshed is False


@patch("mcpgateway.federation.discovery.settings", new=DummySettings)
def test_get_auth_headers():
    service = discovery.DiscoveryService()
    headers = service._get_auth_headers()
    assert "Authorization" in headers
    assert "X-API-Key" in headers
    assert headers["Authorization"].startswith("Basic ")


@patch("mcpgateway.federation.discovery.settings", new=DummySettings)
def test_get_local_addresses_fallback(monkeypatch):
    service = discovery.LocalDiscoveryService()

    def raise_exc(*a, **kw):
        raise Exception("fail")

    monkeypatch.setattr("socket.getaddrinfo", raise_exc)
    addresses = service._get_local_addresses()
    assert addresses == ["127.0.0.1"]


@pytest.mark.asyncio
@patch("mcpgateway.federation.discovery.settings", new=DummySettings)
@patch.object(discovery.DiscoveryService, "_get_gateway_info", new_callable=AsyncMock)
async def test_add_peer_gateway_info_fails(mock_get_info):
    mock_get_info.side_effect = Exception("fail")
    service = discovery.DiscoveryService()
    url = "http://peer4:1234"
    added = await service.add_peer(url, source="test")
    assert added is False
    assert url not in service._discovered_peers


@pytest.mark.asyncio
@patch("mcpgateway.federation.discovery.settings", new=DummySettings)
async def test_remove_peer_not_existing():
    service = discovery.DiscoveryService()
    url = "http://notfound:2"
    await service.remove_peer(url)  # Should not raise
    assert url not in service._discovered_peers


@pytest.mark.asyncio
@patch("mcpgateway.federation.discovery.settings", new=DummySettings)
async def test_on_service_state_change_added(monkeypatch):
    service = discovery.DiscoveryService()

    class DummyInfo:
        addresses = [b"\x7f\x00\x00\x01"]
        port = 1234
        properties = {b"name": b"peer"}

    async def get_info(*a, **k):
        return DummyInfo()

    monkeypatch.setattr(service, "add_peer", AsyncMock())
    zeroconf = MagicMock()
    zeroconf.async_get_service_info = get_info
    await service._on_service_state_change(zeroconf, "_mcp._tcp.local.", "peer", discovery.ServiceStateChange.Added)
    service.add_peer.assert_awaited()


@pytest.mark.asyncio
@patch("mcpgateway.federation.discovery.settings", new=DummySettings)
async def test_on_service_state_change_no_info(monkeypatch):
    service = discovery.DiscoveryService()

    async def get_info(*a, **k):
        return None

    zeroconf = MagicMock()
    zeroconf.async_get_service_info = get_info
    # Should not raise
    await service._on_service_state_change(zeroconf, "_mcp._tcp.local.", "peer", discovery.ServiceStateChange.Added)


@pytest.mark.asyncio
@patch("mcpgateway.federation.discovery.settings", new=DummySettings)
async def test_on_service_state_change_exception(monkeypatch):
    service = discovery.DiscoveryService()

    class DummyInfo:
        addresses = [b"\x7f\x00\x00\x01"]
        port = 1234
        properties = {b"name": b"peer"}

    async def get_info(*a, **k):
        return DummyInfo()

    zeroconf = MagicMock()
    zeroconf.async_get_service_info = get_info
    monkeypatch.setattr(service, "add_peer", AsyncMock(side_effect=Exception("fail")))
    # Should not raise
    await service._on_service_state_change(zeroconf, "_mcp._tcp.local.", "peer", discovery.ServiceStateChange.Added)


@pytest.mark.asyncio
@patch("mcpgateway.federation.discovery.settings", new=DummySettings)
async def test_exchange_peers_success(monkeypatch):
    service = discovery.DiscoveryService()
    url = "http://peer5:1234"
    service._discovered_peers[url] = MagicMock()
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = [{"url": "http://peer6:1234", "name": "peer6"}]
    service._http_client.get = AsyncMock(return_value=response)
    monkeypatch.setattr(service, "add_peer", AsyncMock())
    await service._exchange_peers()
    service._http_client.get.assert_awaited()
    service.add_peer.assert_awaited_with("http://peer6:1234", source="exchange", name="peer6")


@pytest.mark.asyncio
@patch("mcpgateway.federation.discovery.settings", new=DummySettings)
async def test_exchange_peers_exception(monkeypatch):
    service = discovery.DiscoveryService()
    url = "http://peer7:1234"
    service._discovered_peers[url] = MagicMock()
    service._http_client.get = AsyncMock(side_effect=Exception("fail"))
    # Should not raise
    await service._exchange_peers()


@pytest.mark.asyncio
@patch("mcpgateway.federation.discovery.settings", new=DummySettings)
async def test_cleanup_loop_one_stale(monkeypatch):
    service = discovery.DiscoveryService()
    url = "http://peer8:1234"
    peer = MagicMock()
    peer.last_seen = datetime.now(timezone.utc) - timedelta(minutes=11)
    service._discovered_peers[url] = peer
    monkeypatch.setattr(asyncio, "sleep", AsyncMock(side_effect=Exception("break")))
    monkeypatch.setattr(service, "remove_peer", AsyncMock())
    try:
        await service._cleanup_loop()
    except Exception:
        pass
    service.remove_peer.assert_awaited_with(url)


@pytest.mark.asyncio
@patch("mcpgateway.federation.discovery.settings", new=DummySettings)
async def test_refresh_loop(monkeypatch):
    service = discovery.DiscoveryService()
    url = "http://peer9:1234"
    service._discovered_peers[url] = MagicMock()
    monkeypatch.setattr(service, "refresh_peer", AsyncMock())
    monkeypatch.setattr(service, "_exchange_peers", AsyncMock())
    monkeypatch.setattr(asyncio, "sleep", AsyncMock(side_effect=Exception("break")))
    try:
        await service._refresh_loop()
    except Exception:
        pass
    service.refresh_peer.assert_awaited_with(url)
    service._exchange_peers.assert_awaited()


@pytest.mark.asyncio
@patch("mcpgateway.federation.discovery.settings", new=DummySettings)
async def test_start_and_stop(monkeypatch):
    service = discovery.DiscoveryService()
    monkeypatch.setattr(service, "_cleanup_loop", AsyncMock())
    monkeypatch.setattr(service, "_refresh_loop", AsyncMock())
    monkeypatch.setattr(service, "add_peer", AsyncMock())
    DummySettings.federation_discovery = False
    DummySettings.federation_peers = ["http://peer10:1234"]
    await service.start()
    await service.stop()
    DummySettings.federation_peers = []


@pytest.mark.asyncio
@patch("mcpgateway.federation.discovery.settings", new=DummySettings)
async def test_on_service_state_change_not_added():
    service = discovery.DiscoveryService()
    zeroconf = MagicMock()
    # Should do nothing and not raise
    await service._on_service_state_change(zeroconf, "_mcp._tcp.local.", "peer", ServiceStateChange.Removed)


@pytest.mark.asyncio
@patch("mcpgateway.federation.discovery.settings", new=DummySettings)
async def test_on_service_state_change_no_addresses(monkeypatch):
    service = discovery.DiscoveryService()

    class DummyInfo:
        addresses = []
        port = 1234
        properties = {b"name": b"peer"}

    async def get_info(*a, **k):
        return DummyInfo()

    zeroconf = MagicMock()
    zeroconf.async_get_service_info = get_info
    # Should not call add_peer
    monkeypatch.setattr(service, "add_peer", AsyncMock())
    await service._on_service_state_change(zeroconf, "_mcp._tcp.local.", "peer", ServiceStateChange.Added)
    service.add_peer.assert_not_awaited()


@pytest.mark.asyncio
@patch("mcpgateway.federation.discovery.settings", new=DummySettings)
async def test_get_gateway_info_protocol_version_mismatch(monkeypatch):
    service = discovery.DiscoveryService()
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {"protocol_version": "WRONG", "capabilities": {}}
    service._http_client.post = AsyncMock(return_value=response)
    with pytest.raises(ValueError):
        await service._get_gateway_info("http://peer11:1234")


@pytest.mark.asyncio
@patch("mcpgateway.federation.discovery.settings", new=DummySettings)
async def test_cleanup_loop_exception(monkeypatch):
    service = discovery.DiscoveryService()
    monkeypatch.setattr(asyncio, "sleep", AsyncMock(side_effect=Exception("break")))

    def raise_exc(*a, **k):
        raise Exception("fail")

    monkeypatch.setattr(service, "remove_peer", AsyncMock(side_effect=raise_exc))
    url = "http://peer12:1234"
    peer = MagicMock()
    peer.last_seen = datetime.now(timezone.utc) - timedelta(minutes=11)
    service._discovered_peers[url] = peer
    try:
        await service._cleanup_loop()
    except Exception:
        pass
    # Should log error, not raise


@pytest.mark.asyncio
@patch("mcpgateway.federation.discovery.settings", new=DummySettings)
async def test_refresh_loop_exception(monkeypatch):
    service = discovery.DiscoveryService()
    monkeypatch.setattr(asyncio, "sleep", AsyncMock(side_effect=Exception("break")))
    monkeypatch.setattr(service, "refresh_peer", AsyncMock(side_effect=Exception("fail")))
    monkeypatch.setattr(service, "_exchange_peers", AsyncMock(side_effect=Exception("fail")))
    url = "http://peer13:1234"
    service._discovered_peers[url] = MagicMock()
    try:
        await service._refresh_loop()
    except Exception:
        pass
    # Should log error, not raise


@pytest.mark.asyncio
@patch("mcpgateway.federation.discovery.settings", new=DummySettings)
async def test_start_exception(monkeypatch):
    service = discovery.DiscoveryService()
    DummySettings.federation_discovery = True

    class DummyZeroconf:
        async def async_register_service(self, *a, **k):
            raise Exception("fail")

    monkeypatch.setattr(discovery, "AsyncZeroconf", lambda: DummyZeroconf())
    with pytest.raises(Exception):
        await service.start()
    DummySettings.federation_discovery = False


def test_stop_exceptions(monkeypatch):
    service = discovery.DiscoveryService()

    # Simulate browser and zeroconf present
    class DummyBrowser:
        async def async_cancel(self):
            pass  # Do not raise

    class DummyZeroconf:
        async def async_unregister_service(self, *a, **k):
            pass  # Do not raise

        async def async_close(self):
            pass  # Do not raise

    monkeypatch.setattr(service, "_browser", DummyBrowser())
    monkeypatch.setattr(service, "_zeroconf", DummyZeroconf())

    # Patch http client close to NOT raise
    service._http_client.aclose = AsyncMock(return_value=None)

    # Should not raise
    asyncio.run(service.stop())
