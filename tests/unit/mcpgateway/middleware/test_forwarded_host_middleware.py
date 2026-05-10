# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/middleware/test_forwarded_host_middleware.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

Unit tests for ForwardedHostMiddleware.
"""

# Third-Party
import pytest

# First-Party
from mcpgateway.middleware.forwarded_host import ForwardedHostMiddleware


def _make_scope(
    *,
    host: str = "internal-gw:4444",
    server: tuple = ("internal-gw", 4444),
    scheme: str = "http",
    scope_type: str = "http",
) -> dict:
    """Build a minimal ASGI scope for testing."""
    headers = [(b"host", host.encode("latin1"))]
    return {
        "type": scope_type,
        "scheme": scheme,
        "server": server,
        "headers": headers,
        "path": "/admin",
        "query_string": b"",
    }


def _add_header(scope: dict, name: str, value: str) -> dict:
    """Add a header to an ASGI scope."""
    scope["headers"].append((name.lower().encode("latin1"), value.encode("latin1")))
    return scope


async def _capture_app(scope, receive, send):
    """A no-op ASGI app that records the scope it received."""
    scope["_captured"] = True


class TestForwardedHostMiddleware:
    """Tests for X-Forwarded-Host header rewriting."""

    @pytest.mark.asyncio
    async def test_no_forwarded_host_passthrough(self):
        """Without X-Forwarded-Host, scope is unchanged."""
        scope = _make_scope()
        original_server = scope["server"]
        original_headers = list(scope["headers"])

        mw = ForwardedHostMiddleware(_capture_app)
        await mw(scope, None, None)

        assert scope["server"] == original_server
        host_values = [v for k, v in scope["headers"] if k == b"host"]
        assert host_values == [h for _, h in original_headers if _ == b"host"]

    @pytest.mark.asyncio
    async def test_simple_hostname(self):
        """X-Forwarded-Host with a plain hostname rewrites host and server."""
        scope = _make_scope(scheme="https")
        _add_header(scope, "x-forwarded-host", "proxy.example.com")

        mw = ForwardedHostMiddleware(_capture_app)
        await mw(scope, None, None)

        assert scope["server"] == ("proxy.example.com", 443)
        host_values = [v.decode() for k, v in scope["headers"] if k == b"host"]
        assert host_values == ["proxy.example.com"]

    @pytest.mark.asyncio
    async def test_hostname_with_port(self):
        """X-Forwarded-Host with host:port rewrites both."""
        scope = _make_scope(scheme="https")
        _add_header(scope, "x-forwarded-host", "proxy.example.com:8443")

        mw = ForwardedHostMiddleware(_capture_app)
        await mw(scope, None, None)

        assert scope["server"] == ("proxy.example.com", 8443)
        host_values = [v.decode() for k, v in scope["headers"] if k == b"host"]
        assert host_values == ["proxy.example.com:8443"]

    @pytest.mark.asyncio
    async def test_http_default_port(self):
        """HTTP scheme defaults to port 80 in scope['server']."""
        scope = _make_scope(scheme="http")
        _add_header(scope, "x-forwarded-host", "proxy.example.com")

        mw = ForwardedHostMiddleware(_capture_app)
        await mw(scope, None, None)

        assert scope["server"] == ("proxy.example.com", 80)

    @pytest.mark.asyncio
    async def test_https_default_port(self):
        """HTTPS scheme defaults to port 443 in scope['server']."""
        scope = _make_scope(scheme="https")
        _add_header(scope, "x-forwarded-host", "proxy.example.com")

        mw = ForwardedHostMiddleware(_capture_app)
        await mw(scope, None, None)

        assert scope["server"] == ("proxy.example.com", 443)

    @pytest.mark.asyncio
    async def test_wss_default_port(self):
        """WSS scheme defaults to port 443 in scope['server']."""
        scope = _make_scope(scheme="wss", scope_type="websocket")
        _add_header(scope, "x-forwarded-host", "proxy.example.com")

        mw = ForwardedHostMiddleware(_capture_app)
        await mw(scope, None, None)

        assert scope["server"] == ("proxy.example.com", 443)

    @pytest.mark.asyncio
    async def test_ws_default_port(self):
        """WS scheme defaults to port 80 in scope['server']."""
        scope = _make_scope(scheme="ws", scope_type="websocket")
        _add_header(scope, "x-forwarded-host", "proxy.example.com")

        mw = ForwardedHostMiddleware(_capture_app)
        await mw(scope, None, None)

        assert scope["server"] == ("proxy.example.com", 80)

    @pytest.mark.asyncio
    async def test_ipv6_without_port(self):
        """Bracketed IPv6 address without port; server is unbracketed."""
        scope = _make_scope(scheme="https")
        _add_header(scope, "x-forwarded-host", "[2001:db8::1]")

        mw = ForwardedHostMiddleware(_capture_app)
        await mw(scope, None, None)

        assert scope["server"] == ("2001:db8::1", 443)
        host_values = [v.decode() for k, v in scope["headers"] if k == b"host"]
        assert host_values == ["[2001:db8::1]"]

    @pytest.mark.asyncio
    async def test_ipv6_with_port(self):
        """Bracketed IPv6 address with port; server is unbracketed."""
        scope = _make_scope(scheme="https")
        _add_header(scope, "x-forwarded-host", "[2001:db8::1]:8080")

        mw = ForwardedHostMiddleware(_capture_app)
        await mw(scope, None, None)

        assert scope["server"] == ("2001:db8::1", 8080)
        host_values = [v.decode() for k, v in scope["headers"] if k == b"host"]
        assert host_values == ["[2001:db8::1]:8080"]

    @pytest.mark.asyncio
    async def test_ipv6_unbracketed_without_port(self):
        """Unbracketed IPv6 without port is treated as a literal host."""
        scope = _make_scope(scheme="https")
        _add_header(scope, "x-forwarded-host", "2001:db8::1")

        mw = ForwardedHostMiddleware(_capture_app)
        await mw(scope, None, None)

        assert scope["server"] == ("2001:db8::1", 443)
        host_values = [v.decode() for k, v in scope["headers"] if k == b"host"]
        assert host_values == ["2001:db8::1"]

    @pytest.mark.asyncio
    async def test_empty_forwarded_host_ignored(self):
        """Empty X-Forwarded-Host is ignored."""
        scope = _make_scope()
        original_server = scope["server"]
        _add_header(scope, "x-forwarded-host", "")

        mw = ForwardedHostMiddleware(_capture_app)
        await mw(scope, None, None)

        assert scope["server"] == original_server

    @pytest.mark.asyncio
    async def test_whitespace_only_forwarded_host_ignored(self):
        """Whitespace-only X-Forwarded-Host is ignored."""
        scope = _make_scope()
        original_server = scope["server"]
        _add_header(scope, "x-forwarded-host", "   ")

        mw = ForwardedHostMiddleware(_capture_app)
        await mw(scope, None, None)

        assert scope["server"] == original_server

    @pytest.mark.asyncio
    async def test_comma_separated_takes_first(self):
        """Comma-separated X-Forwarded-Host takes the first (leftmost) value."""
        scope = _make_scope(scheme="https")
        _add_header(scope, "x-forwarded-host", "first-proxy.com, second-proxy.com")

        mw = ForwardedHostMiddleware(_capture_app)
        await mw(scope, None, None)

        assert scope["server"] == ("first-proxy.com", 443)
        host_values = [v.decode() for k, v in scope["headers"] if k == b"host"]
        assert host_values == ["first-proxy.com"]

    @pytest.mark.asyncio
    async def test_lifespan_scope_passthrough(self):
        """Lifespan events are passed through without modification."""
        scope = {"type": "lifespan"}

        mw = ForwardedHostMiddleware(_capture_app)
        await mw(scope, None, None)

        assert "server" not in scope

    @pytest.mark.asyncio
    async def test_replaces_existing_host_header(self):
        """Ensures the original host header is replaced, not duplicated."""
        scope = _make_scope(host="internal:4444", scheme="https")
        _add_header(scope, "x-forwarded-host", "external.com")

        mw = ForwardedHostMiddleware(_capture_app)
        await mw(scope, None, None)

        host_entries = [(k, v) for k, v in scope["headers"] if k == b"host"]
        assert len(host_entries) == 1
        assert host_entries[0][1] == b"external.com"

    @pytest.mark.asyncio
    async def test_invalid_port_ignored(self):
        """Non-numeric port causes the header to be ignored entirely."""
        scope = _make_scope(scheme="https")
        original_server = scope["server"]
        _add_header(scope, "x-forwarded-host", "proxy.example.com:notaport")

        mw = ForwardedHostMiddleware(_capture_app)
        await mw(scope, None, None)

        assert scope["server"] == original_server
        host_values = [v.decode() for k, v in scope["headers"] if k == b"host"]
        assert host_values == ["internal-gw:4444"]

    @pytest.mark.asyncio
    async def test_out_of_range_port_ignored(self):
        """Port outside 1-65535 causes the header to be ignored entirely."""
        scope = _make_scope(scheme="https")
        original_server = scope["server"]
        _add_header(scope, "x-forwarded-host", "proxy.example.com:99999")

        mw = ForwardedHostMiddleware(_capture_app)
        await mw(scope, None, None)

        assert scope["server"] == original_server

    @pytest.mark.asyncio
    async def test_path_in_host_ignored(self):
        """Host value containing '/' is rejected."""
        scope = _make_scope()
        original_server = scope["server"]
        _add_header(scope, "x-forwarded-host", "evil.com/path")

        mw = ForwardedHostMiddleware(_capture_app)
        await mw(scope, None, None)

        assert scope["server"] == original_server

    @pytest.mark.asyncio
    async def test_duplicate_headers_first_wins(self):
        """When multiple X-Forwarded-Host headers are present, the first wins."""
        scope = _make_scope(scheme="https")
        # Add two headers; the first (client-facing) should win.
        _add_header(scope, "x-forwarded-host", "first-proxy.com")
        _add_header(scope, "x-forwarded-host", "last-proxy.com")

        mw = ForwardedHostMiddleware(_capture_app)
        await mw(scope, None, None)

        assert scope["server"] == ("first-proxy.com", 443)
        host_values = [v.decode() for k, v in scope["headers"] if k == b"host"]
        assert host_values == ["first-proxy.com"]

    @pytest.mark.asyncio
    async def test_malformed_bracketed_ipv6_ignored(self):
        """Bracketed IPv6 missing closing ']' is rejected."""
        scope = _make_scope()
        original_server = scope["server"]
        _add_header(scope, "x-forwarded-host", "[2001:db8::1")

        mw = ForwardedHostMiddleware(_capture_app)
        await mw(scope, None, None)

        assert scope["server"] == original_server

    @pytest.mark.asyncio
    async def test_empty_bracketed_host_ignored(self):
        """Empty brackets '[]' result in empty host and are rejected."""
        scope = _make_scope()
        original_server = scope["server"]
        _add_header(scope, "x-forwarded-host", "[]")

        mw = ForwardedHostMiddleware(_capture_app)
        await mw(scope, None, None)

        assert scope["server"] == original_server

    @pytest.mark.asyncio
    async def test_empty_host_with_port_ignored(self):
        """Host value ':443' with empty host is rejected."""
        scope = _make_scope()
        original_server = scope["server"]
        _add_header(scope, "x-forwarded-host", ":443")

        mw = ForwardedHostMiddleware(_capture_app)
        await mw(scope, None, None)

        assert scope["server"] == original_server

    @pytest.mark.asyncio
    async def test_plus_sign_in_port_ignored(self):
        """Port with leading '+' is rejected as invalid."""
        scope = _make_scope()
        original_server = scope["server"]
        _add_header(scope, "x-forwarded-host", "example.com:+443")

        mw = ForwardedHostMiddleware(_capture_app)
        await mw(scope, None, None)

        assert scope["server"] == original_server

    @pytest.mark.asyncio
    async def test_whitespace_in_forwarded_host_ignored(self):
        """X-Forwarded-Host containing an embedded space is rejected."""
        scope = _make_scope()
        original_server = scope["server"]
        _add_header(scope, "x-forwarded-host", "evil.com/path with space")

        mw = ForwardedHostMiddleware(_capture_app)
        await mw(scope, None, None)

        assert scope["server"] == original_server

    @pytest.mark.asyncio
    async def test_bracketed_ipv6_with_trailing_junk_ignored(self):
        """Bracketed IPv6 with extra colons (last not after ]) is rejected."""
        scope = _make_scope()
        original_server = scope["server"]
        _add_header(scope, "x-forwarded-host", "[::1]:8080:extra")

        mw = ForwardedHostMiddleware(_capture_app)
        await mw(scope, None, None)

        assert scope["server"] == original_server

    @pytest.mark.asyncio
    async def test_bracketed_ipv6_with_non_digit_port_ignored(self):
        """Bracketed IPv6 with an alphabetic port is rejected."""
        scope = _make_scope()
        original_server = scope["server"]
        _add_header(scope, "x-forwarded-host", "[::1]:abc")

        mw = ForwardedHostMiddleware(_capture_app)
        await mw(scope, None, None)

        assert scope["server"] == original_server
