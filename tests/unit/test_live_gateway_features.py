# -*- coding: utf-8 -*-
"""Location: ./tests/unit/test_live_gateway_features.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for the live-gateway feature probes.

The probes read feature state from the gateway under test instead of the
environment of the pytest process. This file sits directly under ``tests/unit/``
because its subject is test infrastructure.
"""

# Third-Party
import httpx
import pytest

# First-Party
from tests.live_gateway.helpers import gateway_features


@pytest.fixture(autouse=True)
def _clear_probe_cache():
    """Reset the probe caches so each test sees its own gateway answer."""
    gateway_features.gateway_accepts_modern_inbound.cache_clear()
    gateway_features.gateway_advertises_mcp_apps.cache_clear()
    yield
    gateway_features.gateway_accepts_modern_inbound.cache_clear()
    gateway_features.gateway_advertises_mcp_apps.cache_clear()


def _response(status: int, payload: dict | None = None) -> httpx.Response:
    return httpx.Response(status, json=payload or {}, request=httpx.Request("POST", "http://gateway/mcp/"))


class TestModernInbound:
    """Probe for ``MCP_INBOUND_PROTOCOL_MODE=auto``."""

    def test_accepted_discover_means_auto(self, monkeypatch):
        monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: _response(200))
        assert gateway_features.gateway_accepts_modern_inbound() is True

    def test_rejected_discover_means_legacy(self, monkeypatch):
        monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: _response(400))
        assert gateway_features.gateway_accepts_modern_inbound() is False

    def test_unreachable_gateway_is_not_modern(self, monkeypatch):
        def refuse(*args, **kwargs):
            raise httpx.ConnectError("refused")

        monkeypatch.setattr(httpx, "post", refuse)
        assert gateway_features.gateway_accepts_modern_inbound() is False

    def test_probe_sends_modern_revision_headers(self, monkeypatch):
        seen = {}

        def capture(url, headers, json, timeout):
            seen.update(headers=headers, body=json)
            return _response(200)

        monkeypatch.setattr(httpx, "post", capture)
        gateway_features.gateway_accepts_modern_inbound()
        assert seen["headers"]["MCP-Protocol-Version"] == "2026-07-28"
        assert seen["headers"]["Mcp-Method"] == "server/discover"
        assert seen["body"]["params"]["_meta"]["io.modelcontextprotocol/clientCapabilities"] == {}


class TestMcpApps:
    """Probe for ``MCPGATEWAY_MCP_APPS_ENABLED``."""

    def test_extension_listed_means_enabled(self, monkeypatch):
        payload = {"result": {"capabilities": {"extensions": {"io.modelcontextprotocol/ui": {}}}}}
        monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: _response(200, payload))
        assert gateway_features.gateway_advertises_mcp_apps() is True

    def test_missing_extension_means_disabled(self, monkeypatch):
        payload = {"result": {"capabilities": {"tools": {}}}}
        monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: _response(200, payload))
        assert gateway_features.gateway_advertises_mcp_apps() is False

    def test_error_status_means_disabled(self, monkeypatch):
        payload = {"result": {"capabilities": {"extensions": {"io.modelcontextprotocol/ui": {}}}}}
        monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: _response(401, payload))
        assert gateway_features.gateway_advertises_mcp_apps() is False

    def test_unreachable_gateway_is_disabled(self, monkeypatch):
        def refuse(*args, **kwargs):
            raise httpx.ConnectError("refused")

        monkeypatch.setattr(httpx, "post", refuse)
        assert gateway_features.gateway_advertises_mcp_apps() is False
