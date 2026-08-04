# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/url_to_markdown_server/tests/test_server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for URL-to-Markdown MCP Server (FastMCP).
"""

import http.server
import socket
import ssl
import subprocess
import threading
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


@pytest.mark.asyncio
async def test_get_capabilities():
    """Test getting converter capabilities."""
    from url_to_markdown_server.server_fastmcp import converter

    result = converter.get_capabilities()

    assert "html_engines" in result
    assert "document_converters" in result
    assert "supported_formats" in result
    assert "features" in result


@pytest.mark.asyncio
async def test_convert_basic_html():
    """Test converting HTML content to markdown."""
    from url_to_markdown_server.server_fastmcp import converter

    html_content = """
    <html>
    <head><title>Test Page</title></head>
    <body>
        <h1>Main Title</h1>
        <p>This is a paragraph with <strong>bold text</strong> and <em>italic text</em>.</p>
        <ul>
            <li>First item</li>
            <li>Second item</li>
        </ul>
        <a href="https://example.com">External link</a>
    </body>
    </html>
    """

    result = await converter._convert_basic_html(html_content)

    if result.get("success"):
        markdown = result["markdown"]
        # Basic HTML conversion should preserve main content
        assert "Main Title" in markdown
        assert "bold text" in markdown
        assert "italic text" in markdown
        assert "First item" in markdown
        assert "example.com" in markdown
    else:
        # When dependencies are not available
        assert "error" in result


@pytest.mark.asyncio
async def test_convert_text_to_markdown():
    """Test converting plain text content."""
    from url_to_markdown_server.server_fastmcp import converter

    text_content = b"This is plain text content.\nWith multiple lines.\n\nAnd paragraphs."

    result = await converter._convert_text_to_markdown(text_content)

    assert result["success"] is True
    assert result["markdown"] == text_content.decode("utf-8")
    assert result["engine"] == "text"


def _fake_getaddrinfo(ip: str):
    """Build a fake ``socket.getaddrinfo``-shaped resolver for a fixed test IP."""

    def resolver(host: str, port: int) -> list[tuple[Any, ...]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port))]

    return resolver


class _MockStreamContext:
    """Async context manager mimicking ``httpx.AsyncClient.stream()``'s return value."""

    def __init__(self, response: MagicMock) -> None:
        self._response = response

    async def __aenter__(self) -> MagicMock:
        return self._response

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


@pytest.mark.asyncio
async def test_fetch_url_with_mock(monkeypatch):
    """Test fetching URL content through the pinned, streaming redirect loop."""
    from url_to_markdown_server.server_fastmcp import converter

    # No real DNS: example.com resolves to a fixed public test IP.
    monkeypatch.setattr(
        "url_to_markdown_server.ssrf._getaddrinfo", _fake_getaddrinfo("93.184.216.34")
    )

    html_content = b"<html><body><h1>Mocked Page</h1></body></html>"

    async def aiter_bytes():
        yield html_content

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "text/html"}
    mock_response.aiter_bytes = aiter_bytes
    mock_response.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.stream = MagicMock(return_value=_MockStreamContext(mock_response))
    # Simulates the default (no proxy configured) routing: every destination is
    # "pinned", not routed through a proxy mount.
    mock_client._transport_for_url = MagicMock(return_value=converter._pinned_transport)

    with patch.object(converter, "get_session", AsyncMock(return_value=mock_client)):
        result = await converter.fetch_url_content("https://example.com")

    assert result["success"] is True
    assert result["content"] == html_content
    assert result["content_type"] == "text/html"
    assert "example.com" in result["url"]
    mock_client.stream.assert_called_once()

    # The request URL stays the original hostname (not the resolved IP): the
    # actual pinned connect happens inside the transport's network backend via
    # the _pinned_ip contextvar, not by rewriting the request target - keeping
    # the request hostname-addressed is what lets HTTPX's connection pool, TLS
    # SNI, Host header, and cookie jar all stay correctly keyed by hostname
    # (see _PinnedNetworkBackend's docstring for why URL-embedded IP pinning
    # would instead let two hostnames sharing an IP share a TLS connection).
    call_args = mock_client.stream.call_args
    method, requested_url = call_args.args
    assert method == "GET"
    assert "example.com" in requested_url
    assert "93.184.216.34" not in requested_url
    assert "headers" not in call_args.kwargs
    assert "extensions" not in call_args.kwargs


def _start_tls_echo_server(cert: str, key: str) -> http.server.ThreadingHTTPServer:
    """Start a real, threaded HTTPS server on 127.0.0.1 that echoes the request's Host header.

    Threaded (not single-connection) so two concurrent client connections - one
    per hostname under test - can both be serviced without one blocking the other.
    """

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"  # keep-alive, so a reused connection is possible

        def do_GET(self) -> None:
            body = f"served Host={self.headers.get('Host')}".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            return

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_ctx.load_cert_chain(cert, key)
    httpd.socket = ssl_ctx.wrap_socket(httpd.socket, server_side=True)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


@pytest.mark.asyncio
async def test_fetch_url_does_not_reuse_connection_across_hostnames_sharing_an_ip(
    monkeypatch, tmp_path
):
    """Two hostnames pinned to the same IP must never share a pooled TLS connection.

    Regression guard for the GHSA-gv3m-3mvj-w6f2 review finding: pinning by
    rewriting the request URL to the resolved IP (the pre-fix approach) makes
    the IP the connection-pool origin, so once a connection to
    ``first.example`` is established and kept alive, a later request to
    ``second.example`` - resolved to the *same* IP - would be served over
    that already-established, already-authenticated-for-a-different-hostname
    connection without a new TLS handshake ever validating the second
    hostname's certificate. This spins up a real (loopback-only, no internet
    access) HTTPS server whose certificate only covers ``first.example``: a
    request to ``second.example`` must fail with a hostname-mismatch TLS
    error, proving a fresh, independently-validated connection was used
    rather than the pooled one.
    """
    from url_to_markdown_server.server_fastmcp import UrlToMarkdownConverter

    cert = str(tmp_path / "cert.pem")
    key = str(tmp_path / "key.pem")
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            key,
            "-out",
            cert,
            "-days",
            "1",
            "-nodes",
            "-subj",
            "/CN=first.example",
            "-addext",
            "subjectAltName=DNS:first.example",
        ],
        check=True,
        capture_output=True,
    )
    monkeypatch.setenv("SSL_CERT_FILE", cert)
    monkeypatch.setenv("MARKDOWN_ALLOW_LOCALHOST", "true")
    monkeypatch.setattr("url_to_markdown_server.ssrf._getaddrinfo", _fake_getaddrinfo("127.0.0.1"))

    httpd = _start_tls_echo_server(cert, key)
    port = httpd.server_port
    try:
        converter = UrlToMarkdownConverter()
        try:
            first = await converter.fetch_url_content(f"https://first.example:{port}/", timeout=5)
            assert first["success"] is True
            assert first["content"] == f"served Host=first.example:{port}".encode()

            second = await converter.fetch_url_content(f"https://second.example:{port}/", timeout=5)
            assert second["success"] is False
            assert "second.example" in second["error"]
        finally:
            if converter.session is not None:
                await converter.session.aclose()
    finally:
        httpd.shutdown()


def _clear_proxy_env(monkeypatch) -> None:
    """Drop any ambient proxy configuration so the test controls it entirely."""
    for base in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
        for name in (base, base.lower()):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("MARKDOWN_ALLOW_UNSAFE_PROXY_PINNING", raising=False)


def _proxy_urls(session) -> list[str]:
    """Collect the proxy URLs a client's mounted transports would connect through."""
    urls = []
    for transport in session._mounts.values():
        proxy_url = getattr(getattr(transport, "_pool", None), "_proxy_url", None)
        if proxy_url is not None:
            urls.append(str(proxy_url))
    return urls


@pytest.mark.asyncio
async def test_get_session_pins_connects_when_no_proxy_configured(monkeypatch):
    """With no proxy configured, the session must use the pinning transport."""
    from url_to_markdown_server.server_fastmcp import (
        UrlToMarkdownConverter,
        _PinnedNetworkBackend,
    )

    _clear_proxy_env(monkeypatch)

    converter = UrlToMarkdownConverter()
    session = await converter.get_session()
    try:
        assert session._transport is converter._pinned_transport
        backend = session._transport._pool._network_backend
        assert isinstance(backend, _PinnedNetworkBackend)
        assert _proxy_urls(session) == []
    finally:
        await session.aclose()


@pytest.mark.asyncio
async def test_get_session_honors_env_proxy(monkeypatch):
    """A configured egress proxy must be honored (mounted), not silently bypassed.

    HTTPX only auto-loads HTTP_PROXY/HTTPS_PROXY/ALL_PROXY when it builds its own
    transport (``allow_env_proxies = trust_env and transport is None``), so
    unconditionally passing the pinned transport would drop the operator's proxy
    and send requests direct - defeating an egress proxy that may exist precisely
    to filter or audit outbound traffic. The mount is built unconditionally here;
    whether ``fetch_url_content()`` is actually allowed to use it for a given
    destination is a separate, later gate (see the fetch-level opt-in tests below).
    """
    from url_to_markdown_server.server_fastmcp import (
        UrlToMarkdownConverter,
        _PinnedNetworkBackend,
    )

    _clear_proxy_env(monkeypatch)
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.internal:3128")
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.internal:3128")

    converter = UrlToMarkdownConverter()
    session = await converter.get_session()
    try:
        proxies = _proxy_urls(session)
        assert proxies, "session must mount the configured egress proxy"
        assert all("proxy.internal" in url for url in proxies)
        proxy_transport = session._transport_for_url(httpx.URL("https://example.com/"))
        assert proxy_transport is not converter._pinned_transport
        assert not isinstance(proxy_transport._pool._network_backend, _PinnedNetworkBackend)
    finally:
        await session.aclose()


@pytest.mark.asyncio
async def test_get_session_keeps_pinning_for_no_proxy_destination(monkeypatch):
    """A NO_PROXY-excluded destination must keep IP pinning even when a proxy is set.

    Regression guard for the GHSA-gv3m-3mvj-w6f2 follow-up review: configuring
    HTTP_PROXY previously disabled connect-time pinning globally, so a NO_PROXY host
    - which never touches the proxy at all - went out with no DNS-rebinding
    protection whatsoever, defeating the guard for a destination the proxy plays no
    part in securing.
    """
    from url_to_markdown_server.server_fastmcp import (
        UrlToMarkdownConverter,
        _PinnedNetworkBackend,
    )

    _clear_proxy_env(monkeypatch)
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.internal:3128")
    monkeypatch.setenv("NO_PROXY", "excluded.example")

    converter = UrlToMarkdownConverter()
    session = await converter.get_session()
    try:
        excluded_transport = session._transport_for_url(httpx.URL("http://excluded.example/"))
        assert excluded_transport is converter._pinned_transport
        assert isinstance(excluded_transport._pool._network_backend, _PinnedNetworkBackend)

        proxied_transport = session._transport_for_url(httpx.URL("http://other.example/"))
        assert proxied_transport is not converter._pinned_transport
    finally:
        await session.aclose()


@pytest.mark.asyncio
async def test_fetch_url_blocks_dns_rebind_on_no_proxy_destination(monkeypatch):
    """Live DNS-rebinding attempt against a NO_PROXY destination must fail closed.

    Regression guard for the same follow-up finding, exercised end-to-end: a real
    local "victim" service stands in for an internal target. The hostname resolves
    to a public IP the first time (passing validation) and to the victim's real,
    internal address on every later lookup - the DNS-rebinding pattern. Before the
    fix, a configured proxy disabled pinning for this NO_PROXY host too, so the
    raw connect re-resolved the hostname and reached the victim directly. After the
    fix the pinned connect uses the address already validated and must time out
    instead, and the victim must never be reached.
    """
    from url_to_markdown_server.server_fastmcp import UrlToMarkdownConverter

    rebind_host = "rebind.example"
    hits = {"n": 0}

    class Victim(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            hits["n"] += 1
            body = b"internal-secret"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            return

    httpd = http.server.HTTPServer(("127.0.0.1", 0), Victim)
    port = httpd.server_port
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    real_getaddrinfo = socket.getaddrinfo
    lookups = {"n": 0}

    def rebinding_getaddrinfo(host, port_arg, *args, **kwargs):
        name = host.decode("ascii") if isinstance(host, (bytes, bytearray)) else host
        if name == rebind_host:
            lookups["n"] += 1
            ip = "93.184.216.34" if lookups["n"] == 1 else "127.0.0.1"
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port_arg))]
        return real_getaddrinfo(host, port_arg, *args, **kwargs)

    # Patching socket.getaddrinfo directly (rather than the ssrf._getaddrinfo seam)
    # exercises both call sites that matter here: ssrf.py's validation-time lookup
    # (call #1, sees the public IP) and httpcore/anyio's raw connect-time lookup on
    # the unpinned proxy path (call #2, sees the rebound internal IP) - the same two
    # DNS lookups a real attacker-controlled DNS-rebinding server would answer
    # differently.
    monkeypatch.setattr(socket, "getaddrinfo", rebinding_getaddrinfo)
    _clear_proxy_env(monkeypatch)
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("NO_PROXY", rebind_host)

    try:
        converter = UrlToMarkdownConverter()
        try:
            result = await converter.fetch_url_content(f"http://{rebind_host}:{port}/", timeout=3)
        finally:
            if converter.session is not None:
                await converter.session.aclose()
    finally:
        httpd.shutdown()

    assert result["success"] is False
    assert hits["n"] == 0, "the victim service must never be reached once pinning is enforced"


@pytest.mark.asyncio
async def test_fetch_url_rejects_proxy_matched_destination_without_opt_in(monkeypatch):
    """A proxy-matched destination must be refused outright, contacting neither proxy nor target.

    Regression guard for the third GHSA-gv3m-3mvj-w6f2 follow-up review: falling back to
    a direct (pinned) connection for a proxy-matched destination closed the DNS-rebinding
    gap, but silently bypassing the configured proxy that way is its own kind of control
    bypass - operators may rely on that proxy for audit logging, DLP, or destination
    allowlisting the server has no other way to enforce. Without an explicit
    MARKDOWN_ALLOW_UNSAFE_PROXY_PINNING opt-in, such a destination must now be blocked
    before any network I/O at all: this uses a DNS-rebinding hostname (public IP on the
    first lookup, "victim" IP on every later one) to prove the destination is unreachable
    even under an active rebinding attempt, and a stub "proxy" to prove it is never
    contacted either - neither must see a single connection.
    """
    from url_to_markdown_server.server_fastmcp import UrlToMarkdownConverter

    rebind_host = "rebind-via-proxy.example"
    victim_hits = {"n": 0}
    proxy_hits = {"n": 0}

    def _make_counting_server(hits: dict[str, int]) -> http.server.HTTPServer:
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                hits["n"] += 1
                body = b"internal-secret"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args: object) -> None:
                return

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server

    victim = _make_counting_server(victim_hits)
    proxy = _make_counting_server(proxy_hits)

    real_getaddrinfo = socket.getaddrinfo

    def rebinding_getaddrinfo(host, port_arg, *args, **kwargs):
        name = host.decode("ascii") if isinstance(host, (bytes, bytearray)) else host
        if name == rebind_host:
            ip = "93.184.216.34" if not hasattr(rebinding_getaddrinfo, "_hit") else "127.0.0.1"
            rebinding_getaddrinfo._hit = True
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port_arg))]
        return real_getaddrinfo(host, port_arg, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", rebinding_getaddrinfo)
    _clear_proxy_env(monkeypatch)
    # rebind_host is deliberately NOT in NO_PROXY: it must be one of the destinations
    # the proxy would otherwise handle.
    monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{proxy.server_port}")

    try:
        converter = UrlToMarkdownConverter()
        try:
            result = await converter.fetch_url_content(
                f"http://{rebind_host}:{victim.server_port}/", timeout=3
            )
        finally:
            if converter.session is not None:
                await converter.session.aclose()
    finally:
        victim.shutdown()
        proxy.shutdown()

    assert result == {"success": False, "error": "URL is not allowed"}
    assert victim_hits["n"] == 0, "the destination must never be reached without the opt-in"
    assert proxy_hits["n"] == 0, "the proxy must never be contacted without the opt-in either"


@pytest.mark.asyncio
async def test_fetch_url_allows_proxy_matched_destination_with_opt_in(monkeypatch):
    """With the explicit opt-in, a proxy-matched (unpinned) destination is still fetched.

    Companion to the rejection test above: MARKDOWN_ALLOW_UNSAFE_PROXY_PINNING is the
    documented escape hatch for operators who need the proxy honored even though its
    connect cannot be pinned end-to-end. Proves the opt-in results in a normal fetch
    rather than an unconditional block.
    """
    from url_to_markdown_server.server_fastmcp import converter

    monkeypatch.setenv("MARKDOWN_ALLOW_UNSAFE_PROXY_PINNING", "true")
    monkeypatch.setattr(
        "url_to_markdown_server.ssrf._getaddrinfo", _fake_getaddrinfo("93.184.216.34")
    )

    html_content = b"<html><body>hi</body></html>"

    async def aiter_bytes():
        yield html_content

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "text/html"}
    mock_response.aiter_bytes = aiter_bytes
    mock_response.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.stream = MagicMock(return_value=_MockStreamContext(mock_response))
    # Not the real pinned transport: simulates a destination that matched a
    # configured proxy mount rather than falling through to the pinned default.
    mock_client._transport_for_url = MagicMock(return_value=object())

    with patch.object(converter, "get_session", AsyncMock(return_value=mock_client)):
        result = await converter.fetch_url_content("https://example.com")

    assert result["success"] is True
    assert result["content"] == html_content
    mock_client.stream.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_url_blocks_redirect_to_internal_target(monkeypatch):
    """A redirect to a blocked internal address must be re-validated and blocked.

    Regression guard for hoisting validate_url() above the retry loop: if only the
    first hop were validated, this redirect to the cloud metadata address would be
    followed silently instead of being blocked.
    """
    from url_to_markdown_server.server_fastmcp import converter

    monkeypatch.setattr(
        "url_to_markdown_server.ssrf._getaddrinfo", _fake_getaddrinfo("93.184.216.34")
    )

    mock_response = MagicMock()
    mock_response.status_code = 302
    mock_response.headers = {"location": "http://169.254.169.254/"}

    mock_client = MagicMock()
    mock_client.stream = MagicMock(return_value=_MockStreamContext(mock_response))
    mock_client._transport_for_url = MagicMock(return_value=converter._pinned_transport)

    with patch.object(converter, "get_session", AsyncMock(return_value=mock_client)):
        result = await converter.fetch_url_content("https://example.com")

    assert result == {"success": False, "error": "URL is not allowed"}
    # The blocked second hop must never actually connect.
    assert mock_client.stream.call_count <= 1


@pytest.mark.asyncio
async def test_fetch_url_aborts_streaming_when_content_exceeds_max_size(monkeypatch):
    """The streamed size cap must abort mid-stream, not after fully buffering the response.

    Regression guard for the README's security claim ("Content is streamed and
    aborted as soon as it exceeds the configured maximum - never fully
    buffered before the limit is enforced"): asserts both that the streaming
    abort branch returns the expected error, and that not every chunk the
    mock could produce was actually pulled before the abort happened.
    """
    from url_to_markdown_server import server_fastmcp
    from url_to_markdown_server.server_fastmcp import converter

    monkeypatch.setattr(server_fastmcp, "MAX_CONTENT_SIZE", 10)
    monkeypatch.setattr(
        "url_to_markdown_server.ssrf._getaddrinfo", _fake_getaddrinfo("93.184.216.34")
    )

    chunks_pulled = 0

    async def aiter_bytes():
        nonlocal chunks_pulled
        # 5 chunks of 5 bytes = 25 bytes total, well over the 10-byte cap. If
        # the loop buffered everything before checking the cap, all 5 would
        # be pulled; the abort must happen well before that.
        for _ in range(5):
            chunks_pulled += 1
            yield b"aaaaa"

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "text/plain"}
    mock_response.aiter_bytes = aiter_bytes
    mock_response.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.stream = MagicMock(return_value=_MockStreamContext(mock_response))
    mock_client._transport_for_url = MagicMock(return_value=converter._pinned_transport)

    with patch.object(converter, "get_session", AsyncMock(return_value=mock_client)):
        result = await converter.fetch_url_content("https://example.com")

    assert result == {
        "success": False,
        "error": "Content too large: exceeded 10 bytes while streaming",
    }
    assert chunks_pulled < 5, "abort must happen mid-stream, not after consuming every chunk"


@pytest.mark.asyncio
async def test_fetch_url_too_many_redirects(monkeypatch):
    """A redirect chain that never terminates must stop after MAX_REDIRECT_HOPS re-validated hops.

    Regression guard for the loop's off-by-one: the range is
    ``MAX_REDIRECT_HOPS + 1`` so an initial request plus MAX_REDIRECT_HOPS
    redirects are attempted (11 total for the default of 10) before giving up.
    """
    from url_to_markdown_server import server_fastmcp
    from url_to_markdown_server.server_fastmcp import converter

    monkeypatch.setattr(
        "url_to_markdown_server.ssrf._getaddrinfo", _fake_getaddrinfo("93.184.216.34")
    )

    mock_response = MagicMock()
    mock_response.status_code = 302
    mock_response.headers = {"location": "https://example.com/next"}

    mock_client = MagicMock()
    mock_client.stream = MagicMock(return_value=_MockStreamContext(mock_response))
    mock_client._transport_for_url = MagicMock(return_value=converter._pinned_transport)

    with patch.object(converter, "get_session", AsyncMock(return_value=mock_client)):
        result = await converter.fetch_url_content("https://example.com")

    assert result == {
        "success": False,
        "error": f"Too many redirects (max {server_fastmcp.MAX_REDIRECT_HOPS})",
    }
    assert mock_client.stream.call_count == server_fastmcp.MAX_REDIRECT_HOPS + 1


@pytest.mark.asyncio
async def test_convert_document_to_markdown():
    """Test document conversion capabilities check."""
    from url_to_markdown_server.server_fastmcp import converter

    # Test with a simple text document
    text_content = b"Simple text document"
    result = await converter.convert_document_to_markdown(text_content, "text/plain")

    assert result["success"] is True
    assert result["markdown"] == "Simple text document"


@pytest.mark.asyncio
async def test_capabilities():
    """Test that converter capabilities are properly initialized."""
    from url_to_markdown_server.server_fastmcp import converter

    # Check that converter is properly initialized
    assert hasattr(converter, "html_engines")
    assert hasattr(converter, "document_converters")
    assert isinstance(converter.html_engines, dict)
    assert isinstance(converter.document_converters, dict)

    # Get capabilities
    caps = converter.get_capabilities()
    assert "text/plain" in caps["supported_formats"]["text"]
    assert "Batch processing" in caps["features"]


@pytest.mark.asyncio
async def test_batch_convert_rejects_too_many_urls():
    """Test that batch_convert rejects a call with more than 50 URLs before the tool body runs."""
    from fastmcp.exceptions import ValidationError

    from url_to_markdown_server.server_fastmcp import mcp

    tool = await mcp.get_tool("batch_convert")
    urls = [f"https://example.com/{i}" for i in range(51)]

    with pytest.raises(ValidationError):
        await tool.run({"urls": urls})


@pytest.mark.asyncio
@pytest.mark.parametrize("max_concurrent", [0, -1])
async def test_batch_convert_rejects_non_positive_max_concurrent(max_concurrent):
    """max_concurrent=0 builds asyncio.Semaphore(0), which hangs every task forever;
    reject zero and negative values before batch_convert() starts."""
    from fastmcp.exceptions import ValidationError

    from url_to_markdown_server.server_fastmcp import mcp

    tool = await mcp.get_tool("batch_convert")

    with pytest.raises(ValidationError):
        await tool.run({"urls": ["https://example.com/"], "max_concurrent": max_concurrent})


@pytest.mark.asyncio
async def test_pinned_network_backend_delegates_unix_socket_and_sleep():
    """connect_unix_socket() and sleep() are plain pass-throughs.

    Neither is exercised by this server's own request path (no unix sockets, no
    httpcore retry backoff triggered in tests), but both are part of the
    httpcore.AsyncNetworkBackend protocol _PinnedNetworkBackend implements, so
    they must still delegate correctly to the wrapped backend/asyncio.
    """
    from url_to_markdown_server.server_fastmcp import _PinnedNetworkBackend

    backend = _PinnedNetworkBackend()
    fake_stream = MagicMock()
    backend._backend = MagicMock()
    backend._backend.connect_unix_socket = AsyncMock(return_value=fake_stream)

    result = await backend.connect_unix_socket("/tmp/example.sock", timeout=5, socket_options=None)

    assert result is fake_stream
    backend._backend.connect_unix_socket.assert_called_once_with(
        "/tmp/example.sock", timeout=5, socket_options=None
    )

    await backend.sleep(0)  # delegates to asyncio.sleep(); completing is the assertion


def test_environment_proxy_mounts_fails_closed_on_httpx_error(monkeypatch):
    """If httpx's private get_environment_proxies() ever goes away, fail closed.

    Returning None (rather than raising, which would crash session creation, or an
    empty map, which reads the same as "no proxy configured" but for the wrong
    reason) is treated by get_session() as "no proxy configured": every
    destination stays on the pinned transport.
    """
    from url_to_markdown_server import server_fastmcp

    def boom():
        raise RuntimeError("get_environment_proxies removed")

    monkeypatch.setattr("httpx._utils.get_environment_proxies", boom)

    assert server_fastmcp._environment_proxy_mounts() is None


@pytest.mark.asyncio
async def test_fetch_url_redirect_missing_location_header(monkeypatch):
    """A redirect response without a Location header must fail cleanly, not crash."""
    from url_to_markdown_server.server_fastmcp import converter

    monkeypatch.setattr(
        "url_to_markdown_server.ssrf._getaddrinfo", _fake_getaddrinfo("93.184.216.34")
    )

    mock_response = MagicMock()
    mock_response.status_code = 302
    mock_response.headers = {}

    mock_client = MagicMock()
    mock_client.stream = MagicMock(return_value=_MockStreamContext(mock_response))
    mock_client._transport_for_url = MagicMock(return_value=converter._pinned_transport)

    with patch.object(converter, "get_session", AsyncMock(return_value=mock_client)):
        result = await converter.fetch_url_content("https://example.com")

    assert result["success"] is False
    assert result["error"] == "Redirect missing Location header"


@pytest.mark.asyncio
async def test_fetch_url_rejects_declared_content_length_over_max(monkeypatch):
    """A Content-Length declaring more than MAX_CONTENT_SIZE is rejected before reading the body."""
    from url_to_markdown_server import server_fastmcp
    from url_to_markdown_server.server_fastmcp import converter

    monkeypatch.setattr(
        "url_to_markdown_server.ssrf._getaddrinfo", _fake_getaddrinfo("93.184.216.34")
    )
    monkeypatch.setattr(server_fastmcp, "MAX_CONTENT_SIZE", 10)

    async def aiter_bytes():
        yield b"unused"

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "text/html", "content-length": "999"}
    mock_response.aiter_bytes = aiter_bytes
    mock_response.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.stream = MagicMock(return_value=_MockStreamContext(mock_response))
    mock_client._transport_for_url = MagicMock(return_value=converter._pinned_transport)

    with patch.object(converter, "get_session", AsyncMock(return_value=mock_client)):
        result = await converter.fetch_url_content("https://example.com")

    assert result["success"] is False
    assert "Content too large" in result["error"]
    assert "999 bytes" in result["error"]


@pytest.mark.asyncio
async def test_fetch_url_reports_http_status_error(monkeypatch):
    """A non-redirect error status (e.g. 404) surfaces as a clean error, not a raw exception."""
    from url_to_markdown_server.server_fastmcp import converter

    monkeypatch.setattr(
        "url_to_markdown_server.ssrf._getaddrinfo", _fake_getaddrinfo("93.184.216.34")
    )

    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.headers = {}
    mock_response.reason_phrase = "Not Found"
    mock_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError("Not Found", request=MagicMock(), response=mock_response)
    )

    mock_client = MagicMock()
    mock_client.stream = MagicMock(return_value=_MockStreamContext(mock_response))
    mock_client._transport_for_url = MagicMock(return_value=converter._pinned_transport)

    with patch.object(converter, "get_session", AsyncMock(return_value=mock_client)):
        result = await converter.fetch_url_content("https://example.com")

    assert result["success"] is False
    assert result["error"] == "HTTP 404: Not Found"
