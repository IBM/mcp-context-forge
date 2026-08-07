# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_mcp_origin_validation.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for MCP Streamable HTTP Origin validation (DNS rebinding protection).

Covers:
  - Settings.mcp_transport_security_settings property
  - Settings._parse_mcp_allowed_origins / _parse_mcp_allowed_hosts validators
  - SessionManagerWrapper receiving correct TransportSecuritySettings
  - HTTP 403 on invalid / unapproved Origin, for POST / GET / DELETE
  - HTTP pass-through on absent Origin and allowlisted Origin
  - null Origin blocked unless explicitly listed
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import pytest

from mcpgateway.config import Settings
from mcpgateway.transports import streamablehttp_transport as tr
from mcpgateway.transports.streamablehttp_transport import SessionManagerWrapper


# ---------------------------------------------------------------------------
# Helpers shared across tests
# ---------------------------------------------------------------------------


def _make_scope(path: str, headers: list[tuple[bytes, bytes]], method: str = "POST") -> dict[str, Any]:
    """Minimal ASGI HTTP scope for the session-manager wrapper."""
    return {
        "type": "http",
        "method": method,
        "path": path,
        "modified_path": path,
        "headers": headers,
        "scheme": "http",
        "server": ("localhost", 4444),
        "client": ("127.0.0.1", 0),
        "query_string": b"",
    }


def _make_receive(body: bytes = b"{}"):
    """Single-message async receive."""
    called = False

    async def receive():
        nonlocal called
        if not called:
            called = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    return receive


def _make_send_collector():
    """Return (send_fn, messages_list)."""
    messages: list[dict] = []

    async def send(msg: dict) -> None:
        messages.append(msg)

    return send, messages


# ---------------------------------------------------------------------------
# Settings.mcp_transport_security_settings property
# ---------------------------------------------------------------------------


class TestMcpTransportSecuritySettingsProperty:
    """Unit tests for Settings.mcp_transport_security_settings."""

    def test_returns_transport_security_settings_type(self):
        """Property must return a TransportSecuritySettings instance."""
        from mcp.server.transport_security import TransportSecuritySettings

        s = Settings(allowed_origins={"http://localhost:4444"})
        ts = s.mcp_transport_security_settings
        assert isinstance(ts, TransportSecuritySettings)

    def test_dns_rebinding_always_enabled(self):
        """enable_dns_rebinding_protection must always be True."""
        s = Settings(allowed_origins={"http://localhost:4444"})
        assert s.mcp_transport_security_settings.enable_dns_rebinding_protection is True

    def test_fallback_to_allowed_origins_when_mcp_allowed_origins_is_none(self):
        """When mcp_allowed_origins is not set, allowed_origins is used."""
        s = Settings(mcp_allowed_origins=None, allowed_origins={"http://localhost:4444", "http://localhost:3000"})
        ts = s.mcp_transport_security_settings
        assert set(ts.allowed_origins) == {"http://localhost:4444", "http://localhost:3000"}

    def test_explicit_mcp_allowed_origins_overrides_allowed_origins(self):
        """When mcp_allowed_origins is set it takes precedence over allowed_origins."""
        s = Settings(
            mcp_allowed_origins={"https://custom.example.com"},
            allowed_origins={"http://localhost:4444"},
        )
        ts = s.mcp_transport_security_settings
        assert ts.allowed_origins == ["https://custom.example.com"]
        assert "http://localhost:4444" not in ts.allowed_origins

    def test_empty_mcp_allowed_origins_means_no_origin_permitted(self):
        """Explicit empty set → allowed_origins=[] → every present Origin rejected."""
        s = Settings(mcp_allowed_origins=set(), allowed_origins={"http://localhost:4444"})
        ts = s.mcp_transport_security_settings
        assert ts.allowed_origins == []

    def test_derived_hosts_include_app_domain_and_loopback(self):
        """Without explicit mcp_allowed_hosts the derived list covers localhost variants."""
        s = Settings(app_domain="http://localhost:4444", mcp_allowed_hosts=[])
        ts = s.mcp_transport_security_settings
        assert any("localhost" in h for h in ts.allowed_hosts)

    def test_explicit_mcp_allowed_hosts_used_verbatim(self):
        """When mcp_allowed_hosts is set the list is passed through unchanged."""
        s = Settings(mcp_allowed_hosts=["mcp.example.com:443", "mcp.example.com"])
        ts = s.mcp_transport_security_settings
        assert ts.allowed_hosts == ["mcp.example.com:443", "mcp.example.com"]


# ---------------------------------------------------------------------------
# Settings._parse_mcp_allowed_origins validator
# ---------------------------------------------------------------------------


class TestParseMcpAllowedOriginsValidator:
    """Unit tests for Settings._parse_mcp_allowed_origins."""

    def test_none_returns_none(self):
        """None input must come back as None (not-set sentinel)."""
        assert Settings._parse_mcp_allowed_origins(None) is None

    def test_json_array_string(self):
        result = Settings._parse_mcp_allowed_origins('["http://localhost:4444","https://example.com"]')
        assert result == {"http://localhost:4444", "https://example.com"}

    def test_csv_string(self):
        result = Settings._parse_mcp_allowed_origins("http://a.com, http://b.com")
        assert result == {"http://a.com", "http://b.com"}

    def test_empty_json_array(self):
        result = Settings._parse_mcp_allowed_origins("[]")
        assert result == set()

    def test_set_passthrough(self):
        result = Settings._parse_mcp_allowed_origins({"http://a.com"})
        assert result == {"http://a.com"}

    def test_list_passthrough(self):
        result = Settings._parse_mcp_allowed_origins(["http://a.com", "http://b.com"])
        assert result == {"http://a.com", "http://b.com"}


# ---------------------------------------------------------------------------
# Settings._parse_mcp_allowed_hosts validator
# ---------------------------------------------------------------------------


class TestParseMcpAllowedHostsValidator:
    """Unit tests for Settings._parse_mcp_allowed_hosts."""

    def test_empty_list_returns_empty(self):
        assert Settings._parse_mcp_allowed_hosts([]) == []

    def test_json_array_string(self):
        result = Settings._parse_mcp_allowed_hosts('["localhost:4444","mcp.example.com"]')
        assert result == ["localhost:4444", "mcp.example.com"]

    def test_csv_string(self):
        result = Settings._parse_mcp_allowed_hosts("localhost:4444, mcp.example.com")
        assert result == ["localhost:4444", "mcp.example.com"]

    def test_list_passthrough(self):
        result = Settings._parse_mcp_allowed_hosts(["localhost:4444"])
        assert result == ["localhost:4444"]

    def test_non_list_non_string_returns_empty(self):
        result = Settings._parse_mcp_allowed_hosts(None)
        assert result == []


# ---------------------------------------------------------------------------
# SessionManagerWrapper passes security_settings to StreamableHTTPSessionManager
# ---------------------------------------------------------------------------


class TestSessionManagerWrapperSecuritySettings:
    """Verify that SessionManagerWrapper forwards security_settings to the SDK manager."""

    def test_session_manager_constructed_with_security_settings(self, monkeypatch):
        """StreamableHTTPSessionManager must receive a security_settings kwarg."""
        captured: dict[str, Any] = {}

        class FakeManager:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            @asynccontextmanager
            async def run(self):
                yield self

        monkeypatch.setattr(tr, "StreamableHTTPSessionManager", FakeManager)
        SessionManagerWrapper()

        assert "security_settings" in captured, "security_settings must be passed to StreamableHTTPSessionManager"

    def test_security_settings_has_protection_enabled(self, monkeypatch):
        """The forwarded security_settings must have dns rebinding protection on."""
        from mcp.server.transport_security import TransportSecuritySettings

        captured: dict[str, Any] = {}

        class FakeManager:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            @asynccontextmanager
            async def run(self):
                yield self

        monkeypatch.setattr(tr, "StreamableHTTPSessionManager", FakeManager)
        monkeypatch.setattr(tr.settings, "allowed_origins", {"http://localhost:4444"})
        monkeypatch.setattr(tr.settings, "mcp_allowed_origins", None)
        monkeypatch.setattr(tr.settings, "mcp_allowed_hosts", [])
        SessionManagerWrapper()

        ts = captured["security_settings"]
        assert isinstance(ts, TransportSecuritySettings)
        assert ts.enable_dns_rebinding_protection is True


# ---------------------------------------------------------------------------
# Transport-layer Origin enforcement — 403 / pass-through
# ---------------------------------------------------------------------------


class TestOriginEnforcement:
    """Test that the SDK transport rejects bad Origins before session creation."""

    @staticmethod
    def _make_wrapper_with_sdk_security(monkeypatch, allowed_origins: list[str], allowed_hosts: list[str]):
        """Return an initialised SessionManagerWrapper using real SDK security logic."""
        from mcp.server.transport_security import TransportSecuritySettings

        ts = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_origins=allowed_origins,
            allowed_hosts=allowed_hosts,
        )

        # Patch the LazySettingsWrapper instance directly so that
        # SessionManagerWrapper.__init__ reads the pre-built TransportSecuritySettings.
        # Setting an instance attribute on LazySettingsWrapper shadows its __getattr__
        # delegation, so no property patching on the wrapper class is needed.
        monkeypatch.setattr(tr.settings, "mcp_transport_security_settings", ts)

        # Use real StreamableHTTPSessionManager (it applies TransportSecurityMiddleware)
        return SessionManagerWrapper()

    @pytest.mark.asyncio
    async def test_absent_origin_is_accepted(self, monkeypatch):
        """No Origin header → SDK must not reject the request."""
        wrapper = self._make_wrapper_with_sdk_security(
            monkeypatch,
            allowed_origins=["http://localhost:4444"],
            allowed_hosts=["localhost:4444", "localhost"],
        )
        await wrapper.initialize()

        send, messages = _make_send_collector()
        scope = _make_scope(
            "/mcp",
            headers=[
                (b"host", b"localhost:4444"),
                (b"content-type", b"application/json"),
            ],
            method="POST",
        )

        # The SDK will proceed past security validation and hit its session logic;
        # we only care that no 403 is sent at the security layer.
        try:
            await wrapper.handle_streamable_http(scope, _make_receive(), send)
        except Exception:  # noqa: BLE001 — session logic may raise; security rejection would have sent a response
            pass

        status_codes = [m.get("status") for m in messages if m.get("type") == "http.response.start"]
        assert 403 not in status_codes, f"Absent Origin must not produce 403; got statuses={status_codes}"

        await wrapper.shutdown()

    @pytest.mark.asyncio
    async def test_allowlisted_origin_is_accepted(self, monkeypatch):
        """An Origin in the allowlist must not be rejected with 403."""
        wrapper = self._make_wrapper_with_sdk_security(
            monkeypatch,
            allowed_origins=["http://localhost:4444"],
            allowed_hosts=["localhost:4444", "localhost"],
        )
        await wrapper.initialize()

        send, messages = _make_send_collector()
        scope = _make_scope(
            "/mcp",
            headers=[
                (b"host", b"localhost:4444"),
                (b"origin", b"http://localhost:4444"),
                (b"content-type", b"application/json"),
            ],
            method="POST",
        )

        try:
            await wrapper.handle_streamable_http(scope, _make_receive(), send)
        except Exception:  # noqa: BLE001
            pass

        status_codes = [m.get("status") for m in messages if m.get("type") == "http.response.start"]
        assert 403 not in status_codes, f"Allowlisted Origin must not produce 403; got statuses={status_codes}"

        await wrapper.shutdown()

    @pytest.mark.asyncio
    async def test_unapproved_origin_returns_403_on_post(self, monkeypatch):
        """An Origin not in the allowlist must produce HTTP 403 on POST."""
        wrapper = self._make_wrapper_with_sdk_security(
            monkeypatch,
            allowed_origins=["http://localhost:4444"],
            allowed_hosts=["localhost:4444", "localhost"],
        )
        await wrapper.initialize()

        send, messages = _make_send_collector()
        scope = _make_scope(
            "/mcp",
            headers=[
                (b"host", b"localhost:4444"),
                (b"origin", b"https://attacker.invalid"),
                (b"content-type", b"application/json"),
            ],
            method="POST",
        )

        await wrapper.handle_streamable_http(scope, _make_receive(), send)

        status_codes = [m.get("status") for m in messages if m.get("type") == "http.response.start"]
        assert 403 in status_codes, f"Unapproved Origin on POST must produce 403; got statuses={status_codes}"

        await wrapper.shutdown()

    @pytest.mark.asyncio
    async def test_unapproved_origin_returns_403_on_get(self):
        """An Origin not in the allowlist must produce HTTP 403 on GET.

        Tests the SDK's StreamableHTTPServerTransport directly, which is the
        layer that ContextForge delegates to via StreamableHTTPSessionManager.
        This validates the security mechanism we enable by passing security_settings.
        """
        from mcp.server.streamable_http import StreamableHTTPServerTransport
        from mcp.server.transport_security import TransportSecuritySettings

        ts = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_origins=["http://localhost:4444"],
            allowed_hosts=["localhost:4444", "localhost"],
        )
        transport = StreamableHTTPServerTransport(
            mcp_session_id="test-session-abc",
            security_settings=ts,
        )

        send, messages = _make_send_collector()
        scope = _make_scope(
            "/mcp",
            headers=[
                (b"host", b"localhost:4444"),
                (b"origin", b"https://attacker.invalid"),
            ],
            method="GET",
        )

        await transport.handle_request(scope, _make_receive(), send)

        status_codes = [m.get("status") for m in messages if m.get("type") == "http.response.start"]
        assert 403 in status_codes, f"Unapproved Origin on GET must produce 403 at SDK level; got statuses={status_codes}"

    @pytest.mark.asyncio
    async def test_unapproved_origin_returns_403_on_delete(self, monkeypatch):
        """An Origin not in the allowlist must produce HTTP 403 on DELETE."""
        wrapper = self._make_wrapper_with_sdk_security(
            monkeypatch,
            allowed_origins=["http://localhost:4444"],
            allowed_hosts=["localhost:4444", "localhost"],
        )
        await wrapper.initialize()

        send, messages = _make_send_collector()
        scope = _make_scope(
            "/mcp",
            headers=[
                (b"host", b"localhost:4444"),
                (b"origin", b"https://attacker.invalid"),
            ],
            method="DELETE",
        )

        await wrapper.handle_streamable_http(scope, _make_receive(), send)

        status_codes = [m.get("status") for m in messages if m.get("type") == "http.response.start"]
        assert 403 in status_codes, f"Unapproved Origin on DELETE must produce 403; got statuses={status_codes}"

        await wrapper.shutdown()

    @pytest.mark.asyncio
    async def test_null_origin_returns_403(self, monkeypatch):
        """The string 'null' as Origin must be rejected unless explicitly allowlisted."""
        wrapper = self._make_wrapper_with_sdk_security(
            monkeypatch,
            allowed_origins=["http://localhost:4444"],
            allowed_hosts=["localhost:4444", "localhost"],
        )
        await wrapper.initialize()

        send, messages = _make_send_collector()
        scope = _make_scope(
            "/mcp",
            headers=[
                (b"host", b"localhost:4444"),
                (b"origin", b"null"),
                (b"content-type", b"application/json"),
            ],
            method="POST",
        )

        await wrapper.handle_streamable_http(scope, _make_receive(), send)

        status_codes = [m.get("status") for m in messages if m.get("type") == "http.response.start"]
        assert 403 in status_codes, f"'null' Origin must produce 403; got statuses={status_codes}"

        await wrapper.shutdown()

    @pytest.mark.asyncio
    async def test_empty_allowlist_rejects_every_present_origin(self, monkeypatch):
        """When mcp_allowed_origins=[] every present Origin must be rejected."""
        wrapper = self._make_wrapper_with_sdk_security(
            monkeypatch,
            allowed_origins=[],  # empty — reject all present Origins
            allowed_hosts=["localhost:4444", "localhost"],
        )
        await wrapper.initialize()

        send, messages = _make_send_collector()
        scope = _make_scope(
            "/mcp",
            headers=[
                (b"host", b"localhost:4444"),
                (b"origin", b"http://localhost:4444"),
                (b"content-type", b"application/json"),
            ],
            method="POST",
        )

        await wrapper.handle_streamable_http(scope, _make_receive(), send)

        status_codes = [m.get("status") for m in messages if m.get("type") == "http.response.start"]
        assert 403 in status_codes, f"Empty allowlist must reject any present Origin; got statuses={status_codes}"

        await wrapper.shutdown()
