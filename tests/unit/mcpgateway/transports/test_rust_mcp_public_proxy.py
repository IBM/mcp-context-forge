# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/transports/test_rust_mcp_public_proxy.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for ``mcpgateway.transports.rust_mcp_public_proxy``.

The public proxy is the no-nginx-in-front ingress: it forwards client
traffic to Rust's authenticated public listener with nginx-style
forwarded headers, so Rust's ``/_internal/mcp/authenticate`` callback
sees the original client info instead of ``127.0.0.1``. These tests pin
the security-critical behavior (XFF spoof rejection, auth header
preservation), the streaming contract (close-on-exit), and the error
path mappings.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
from typing import Callable, List, Optional

# Third-Party
import httpx
import pytest

try:
    # Pragmatic test seam: MockTransport returns a fully-buffered Response
    # whose stream is already consumed; AsyncIteratorByteStream is the
    # smallest public-API equivalent for crafting a streamable Response.
    # No public alternative exists in current httpx; revisit if/when
    # httpx exposes a stable streaming-response helper.
    from httpx._content import AsyncIteratorByteStream  # noqa: PLC2701 — see comment above
except ImportError as exc:  # pragma: no cover — surfaces a future httpx refactor
    raise RuntimeError("test_rust_mcp_public_proxy depends on httpx._content.AsyncIteratorByteStream; " "httpx may have moved this private symbol — pin httpx or update the import.") from exc

# First-Party
from mcpgateway.transports.rust_mcp_public_proxy import (
    RustMCPPublicProxyApp,
    _build_forwarded_headers,
    _format_forwarded_for,
    build_rust_public_proxy_app,
)

# ---------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------


def _make_scope(
    *,
    method: str = "POST",
    path: str = "/mcp",
    headers: Optional[List[tuple]] = None,
    client: Optional[tuple] = ("198.51.100.7", 50001),
    scheme: str = "http",
) -> dict:
    """Build a minimal HTTP ASGI scope for the proxy under test."""
    base_headers = [(b"host", b"gateway.example:4444")]
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "scheme": scheme,
        "headers": base_headers + (headers or []),
        "server": ("gateway.example", 4444),
        "client": client,
    }


def _make_receive(body: bytes = b"") -> Callable:
    """Return a single-body ASGI receive callable that disconnects after the body."""
    sent = {"done": False}

    async def receive() -> dict:
        if sent["done"]:
            return {"type": "http.disconnect"}
        sent["done"] = True
        return {"type": "http.request", "body": body, "more_body": False}

    return receive


class _SendCollector:
    """ASGI ``send`` callable that records every message for assertions."""

    def __init__(self) -> None:
        self.messages: List[dict] = []

    async def __call__(self, message: dict) -> None:
        self.messages.append(message)

    @property
    def status(self) -> Optional[int]:
        for msg in self.messages:
            if msg.get("type") == "http.response.start":
                return msg["status"]
        return None

    @property
    def body(self) -> bytes:
        return b"".join(msg.get("body", b"") for msg in self.messages if msg.get("type") == "http.response.body")

    @property
    def headers(self) -> dict:
        for msg in self.messages:
            if msg.get("type") == "http.response.start":
                return {name.decode("latin-1").lower(): value.decode("latin-1") for name, value in msg["headers"]}
        return {}


def _make_proxy(handler: Callable[[httpx.Request], httpx.Response]) -> RustMCPPublicProxyApp:
    """Build a proxy whose lazily-cached client is wired to an httpx MockTransport."""
    proxy = RustMCPPublicProxyApp(upstream_url="http://upstream.test")
    # Pre-seed the lazy client so _get_client returns ours unchanged.
    proxy._client = httpx.AsyncClient(  # noqa: SLF001 — test seam
        base_url="http://upstream.test",
        transport=httpx.MockTransport(handler),
    )
    return proxy


def _streaming_response(status: int, body: bytes, headers: Optional[dict] = None) -> httpx.Response:
    """Construct an httpx.Response whose body is a real async stream.

    ``MockTransport`` returns a fully-buffered ``httpx.Response`` whose
    stream is already consumed, so calling ``aiter_raw()`` afterwards
    raises ``StreamConsumed``. Wrapping the bytes in
    ``AsyncIteratorByteStream`` keeps the response streamable and
    matches what real upstreams produce when the proxy calls
    ``client.send(..., stream=True)``.
    """

    async def _gen():
        yield body

    return httpx.Response(status, stream=AsyncIteratorByteStream(_gen()), headers=headers or {})


# ---------------------------------------------------------------------
# _format_forwarded_for — pure function, RFC 7239 §6.3 conformance
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "host,port,expected",
    [
        ("198.51.100.7", 50001, '"198.51.100.7:50001"'),
        ("198.51.100.7", 0, '"198.51.100.7"'),
        ("2001:db8::1", 8080, '"[2001:db8::1]:8080"'),
        ("2001:db8::1", 0, '"[2001:db8::1]"'),
        # Defensive: callers passing already-bracketed IPv6 must not
        # end up double-bracketed.
        ("[2001:db8::1]", 8080, '"[2001:db8::1]:8080"'),
        ("[2001:db8::1]", 0, '"[2001:db8::1]"'),
        (None, 50001, "unknown"),
        ("", 50001, "unknown"),
    ],
)
def test_format_forwarded_for(host: Optional[str], port: int, expected: str) -> None:
    """Known clients are quoted (with IPv6 bracketed exactly once); absent clients become ``unknown`` without a synthetic ``:0``."""
    assert _format_forwarded_for(host, port) == expected


# ---------------------------------------------------------------------
# _build_forwarded_headers — security-critical
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_forwarded_headers_drops_client_supplied_chain() -> None:
    """Client-supplied X-Forwarded-* / Forwarded / X-Real-IP must NOT survive into the upstream request."""
    # Third-Party
    from starlette.requests import Request

    scope = _make_scope(
        headers=[
            (b"x-forwarded-for", b"10.0.0.1, evil.example"),
            (b"x-forwarded-proto", b"https"),
            (b"x-forwarded-host", b"attacker.example"),
            (b"x-forwarded-port", b"443"),
            (b"x-real-ip", b"10.0.0.1"),
            (b"forwarded", b"for=10.0.0.1;proto=https;host=attacker.example"),
        ],
    )
    request = Request(scope, _make_receive())

    headers = _build_forwarded_headers(request)

    # Real ASGI client info wins; the spoofed leftmost IP is gone.
    assert headers["X-Forwarded-For"] == "198.51.100.7"
    assert headers["X-Real-IP"] == "198.51.100.7"
    assert headers["X-Forwarded-Proto"] == "http"
    assert headers["X-Forwarded-Host"] == "gateway.example:4444"
    # The attacker's ``for=10.0.0.1`` must not be reflected anywhere.
    assert "10.0.0.1" not in headers["Forwarded"]
    assert "attacker.example" not in headers["Forwarded"]
    assert headers["Forwarded"] == 'for="198.51.100.7:50001";proto=http;host="gateway.example:4444"'


@pytest.mark.asyncio
async def test_build_forwarded_headers_strips_hop_by_hop_and_preserves_auth() -> None:
    """Hop-by-hop headers are dropped; Authorization and Cookie pass through."""
    # Third-Party
    from starlette.requests import Request

    scope = _make_scope(
        headers=[
            (b"connection", b"close"),
            (b"keep-alive", b"timeout=5"),
            (b"transfer-encoding", b"chunked"),
            (b"content-length", b"42"),
            (b"upgrade", b"h2c"),
            (b"proxy-authorization", b"Basic blah"),
            (b"authorization", b"Bearer good-token"),
            (b"cookie", b"session=abc"),
            (b"content-type", b"application/json"),
            (b"mcp-session-id", b"session-1"),
        ],
    )
    request = Request(scope, _make_receive())

    headers = _build_forwarded_headers(request)

    # Hop-by-hop: gone.
    assert "connection" not in {k.lower() for k in headers}
    assert "keep-alive" not in {k.lower() for k in headers}
    assert "transfer-encoding" not in {k.lower() for k in headers}
    assert "content-length" not in {k.lower() for k in headers}
    assert "upgrade" not in {k.lower() for k in headers}
    assert "proxy-authorization" not in {k.lower() for k in headers}
    assert "host" not in {k.lower() for k in headers}
    # Application headers and credentials: preserved.
    assert headers["authorization"] == "Bearer good-token"
    assert headers["cookie"] == "session=abc"
    assert headers["content-type"] == "application/json"
    assert headers["mcp-session-id"] == "session-1"


@pytest.mark.asyncio
async def test_build_forwarded_headers_unknown_client_emits_for_unknown() -> None:
    """When ``request.client`` is None, Forwarded uses ``for=unknown`` (no synthetic ``:0``)."""
    # Third-Party
    from starlette.requests import Request

    scope = _make_scope(client=None)
    request = Request(scope, _make_receive())

    headers = _build_forwarded_headers(request)

    assert headers["X-Forwarded-For"] == "unknown"
    assert headers["X-Real-IP"] == "unknown"
    assert headers["Forwarded"].startswith("for=unknown;")
    # No bogus ":0" port snuck in.
    assert ":0" not in headers["Forwarded"]


# ---------------------------------------------------------------------
# Proxy ASGI behavior
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_proxy_forwards_request_and_streams_response() -> None:
    """A successful round-trip: status, body, content-type all passed through."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        return _streaming_response(200, b"hello-from-rust", {"content-type": "text/plain"})

    proxy = _make_proxy(handler)
    send = _SendCollector()

    await proxy(_make_scope(method="POST", path="/mcp"), _make_receive(b"payload"), send)

    assert send.status == 200
    assert send.body == b"hello-from-rust"
    assert send.headers.get("content-type") == "text/plain"
    assert captured["method"] == "POST"
    assert captured["url"].endswith("/mcp")


@pytest.mark.asyncio
async def test_proxy_passes_through_auth_failures_unchanged() -> None:
    """A 401 from upstream reaches the client unmodified — the proxy does not synthesize 200/502."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return _streaming_response(401, b"who are you", {"www-authenticate": "Bearer"})

    proxy = _make_proxy(handler)
    send = _SendCollector()

    await proxy(_make_scope(), _make_receive(), send)

    assert send.status == 401
    assert send.body == b"who are you"
    assert send.headers.get("www-authenticate") == "Bearer"


@pytest.mark.asyncio
async def test_proxy_strips_hop_by_hop_response_headers() -> None:
    """``Transfer-Encoding`` / ``Connection`` from upstream must not propagate downstream."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return _streaming_response(
            200,
            b"ok",
            {
                "content-type": "application/json",
                "connection": "close",
                # httpx normally manages transfer-encoding itself; assert
                # that any hop-by-hop survivor is filtered by us.
                "keep-alive": "timeout=5",
            },
        )

    proxy = _make_proxy(handler)
    send = _SendCollector()

    await proxy(_make_scope(), _make_receive(), send)

    # Hop-by-hop response headers are absent downstream.
    assert "connection" not in send.headers
    assert "keep-alive" not in send.headers
    assert "transfer-encoding" not in send.headers
    # Application headers survive.
    assert send.headers.get("content-type") == "application/json"


@pytest.mark.asyncio
async def test_proxy_returns_502_on_upstream_httpx_error(caplog) -> None:
    """An ``httpx.HTTPError`` from the upstream call becomes a logged 502."""

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("upstream down")

    proxy = _make_proxy(handler)
    send = _SendCollector()
    caplog.set_level("ERROR", logger="mcpgateway.transports.rust_mcp_public_proxy")

    await proxy(_make_scope(), _make_receive(), send)

    assert send.status == 502
    assert b"unavailable" in send.body
    assert any("rust-public ingress" in rec.message and "ConnectError" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_proxy_returns_500_on_unexpected_exception(caplog) -> None:
    """A non-HTTPError exception during forwarding becomes a logged 500 instead of leaking."""

    def handler(_request: httpx.Request) -> httpx.Response:
        raise RuntimeError("unexpected internal failure")

    proxy = _make_proxy(handler)
    send = _SendCollector()
    caplog.set_level("ERROR", logger="mcpgateway.transports.rust_mcp_public_proxy")

    await proxy(_make_scope(), _make_receive(), send)

    assert send.status == 500
    assert any("unexpected error" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_proxy_re_raises_cancelled_error_during_send() -> None:
    """asyncio.CancelledError from the upstream send must propagate, not be swallowed as 502/500.

    Since CancelledError is BaseException in Python 3.8+, neither the
    httpx.HTTPError nor the broad ``except Exception`` arm catches it —
    it propagates naturally out of __call__. This test pins that
    contract so a future refactor that widens the catch (e.g. to
    BaseException) doesn't accidentally mask client disconnects as
    bogus 502 responses.
    """

    def handler(_request: httpx.Request) -> httpx.Response:
        raise asyncio.CancelledError()

    proxy = _make_proxy(handler)
    send = _SendCollector()

    with pytest.raises(asyncio.CancelledError):
        await proxy(_make_scope(), _make_receive(), send)

    # No 502/500 was sent — the cancel propagated before any response.
    assert send.messages == []


@pytest.mark.asyncio
async def test_body_iter_logs_exception_on_mid_stream_non_cancel_error(caplog) -> None:
    """A non-cancellation exception mid-stream takes the broad ``except Exception`` arm and logs with traceback."""

    async def _exploding_stream():
        yield b"first-chunk"
        raise RuntimeError("upstream-died-mid-stream")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=AsyncIteratorByteStream(_exploding_stream()), headers={"content-type": "text/event-stream"})

    proxy = _make_proxy(handler)
    send = _SendCollector()
    caplog.set_level("ERROR", logger="mcpgateway.transports.rust_mcp_public_proxy")

    # Don't assert on raise/no-raise — depends on Starlette's task-group behavior.
    try:
        await proxy(_make_scope(), _make_receive(), send)
    except RuntimeError:
        pass

    error_records = [r for r in caplog.records if r.levelname == "ERROR"]
    assert any("error streaming body" in rec.message and "upstream-died-mid-stream" in (rec.exc_text or "") for rec in error_records), [(r.message, r.exc_text) for r in error_records]


@pytest.mark.asyncio
async def test_body_iter_logs_debug_on_mid_stream_cancellation(caplog) -> None:
    """asyncio.CancelledError raised mid-stream takes the dedicated debug-log branch in _body_iter.

    Asserting the debug log fires proves the dedicated ``except
    asyncio.CancelledError`` arm was taken (vs. the broader
    ``except Exception`` arm, which uses ``logger.exception`` and would
    spam stack traces for every client tab close on an SSE stream).
    Whether Starlette then propagates the cancel or surfaces it as a
    silent client disconnect is its own concern — we test the proxy's
    contract, not Starlette's.
    """

    async def _exploding_stream():
        yield b"first-chunk"
        raise asyncio.CancelledError()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=AsyncIteratorByteStream(_exploding_stream()), headers={"content-type": "text/event-stream"})

    proxy = _make_proxy(handler)
    send = _SendCollector()
    caplog.set_level("DEBUG", logger="mcpgateway.transports.rust_mcp_public_proxy")

    # Don't assert raise/no-raise — depends on Starlette's task-group behavior.
    try:
        await proxy(_make_scope(), _make_receive(), send)
    except asyncio.CancelledError:
        pass

    debug_msgs = [r.message for r in caplog.records if r.levelname == "DEBUG"]
    assert any("client disconnected mid-stream" in msg for msg in debug_msgs), debug_msgs
    # And the log must NOT include a stack-trace-bearing "exception" record from the broad Exception arm.
    error_msgs = [r.message for r in caplog.records if r.levelname == "ERROR"]
    assert not any("error streaming body" in msg for msg in error_msgs), error_msgs


@pytest.mark.parametrize("status", [401, 403, 500, 503])
@pytest.mark.asyncio
async def test_proxy_logs_warning_on_auth_relevant_upstream_status(status: int, caplog) -> None:
    """Upstream 401/403/5xx statuses each get a warning so a flood after a credential rotation or backend outage is visible."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return _streaming_response(status, b"")

    proxy = _make_proxy(handler)
    send = _SendCollector()
    caplog.set_level("WARNING", logger="mcpgateway.transports.rust_mcp_public_proxy")

    await proxy(_make_scope(), _make_receive(), send)

    assert send.status == status
    assert any(f"returned {status}" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_proxy_returns_404_on_non_http_scope() -> None:
    """Lifespan / websocket scopes are not handled here and return 404 immediately."""
    proxy = _make_proxy(lambda _r: httpx.Response(200))
    send = _SendCollector()

    async def _no_receive() -> dict:
        return {"type": "lifespan.startup"}

    await proxy({"type": "lifespan"}, _no_receive, send)

    assert send.status == 404


@pytest.mark.asyncio
async def test_proxy_does_not_forward_client_supplied_xff() -> None:
    """End-to-end: client sets X-Forwarded-For; upstream sees only the trusted ASGI client info."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        return _streaming_response(200, b"ok")

    proxy = _make_proxy(handler)
    send = _SendCollector()

    scope = _make_scope(
        headers=[
            (b"x-forwarded-for", b"10.0.0.1"),
            (b"x-real-ip", b"10.0.0.1"),
            (b"forwarded", b"for=10.0.0.1"),
        ],
    )
    await proxy(scope, _make_receive(), send)

    assert captured["headers"]["x-forwarded-for"] == "198.51.100.7"
    assert captured["headers"]["x-real-ip"] == "198.51.100.7"
    assert "10.0.0.1" not in captured["headers"]["forwarded"]


# ---------------------------------------------------------------------
# Lazy client lifecycle
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_client_constructs_lazily_and_reuses() -> None:
    """First request constructs the AsyncClient; subsequent requests reuse it."""
    proxy = RustMCPPublicProxyApp(upstream_url="http://upstream.test")
    assert proxy._client is None  # noqa: SLF001 — verifying no I/O at construction

    client_a = await proxy._get_client()  # noqa: SLF001
    client_b = await proxy._get_client()  # noqa: SLF001

    assert client_a is client_b
    await client_a.aclose()


def test_factory_returns_proxy_instance() -> None:
    """``build_rust_public_proxy_app`` exposes the same constructor surface for the mount registry."""
    app = build_rust_public_proxy_app(upstream_url="http://upstream.test")
    assert isinstance(app, RustMCPPublicProxyApp)


# ---------------------------------------------------------------------
# Streaming contract
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_response_body_streams_multiple_chunks() -> None:
    """Multi-chunk SSE-style responses are forwarded chunk-by-chunk."""
    chunks = [b"event: tick\n", b"data: 1\n\n", b"event: tick\n", b"data: 2\n\n"]

    def handler(_request: httpx.Request) -> httpx.Response:
        async def _stream():
            for chunk in chunks:
                yield chunk

        return httpx.Response(200, stream=AsyncIteratorByteStream(_stream()), headers={"content-type": "text/event-stream"})

    proxy = _make_proxy(handler)
    send = _SendCollector()

    await proxy(_make_scope(method="GET", path="/mcp"), _make_receive(), send)

    assert send.status == 200
    assert send.body == b"".join(chunks)
    assert send.headers.get("content-type") == "text/event-stream"


@pytest.mark.asyncio
async def test_response_body_aclose_called_after_normal_completion() -> None:
    """The upstream response is closed after streaming completes — tested by proxying through an interceptor."""
    closed: List[bool] = []

    class _AcloseSpy(httpx.AsyncClient):
        """AsyncClient subclass that records aclose() on every response it sends."""

        async def send(self, request, **kwargs):  # type: ignore[override]
            response = await super().send(request, **kwargs)
            original_aclose = response.aclose

            async def _spy_aclose() -> None:
                closed.append(True)
                await original_aclose()

            response.aclose = _spy_aclose  # type: ignore[method-assign]
            return response

    proxy = RustMCPPublicProxyApp(upstream_url="http://upstream.test")
    proxy._client = _AcloseSpy(  # noqa: SLF001
        base_url="http://upstream.test",
        transport=httpx.MockTransport(lambda _r: _streaming_response(200, b"streamed-body")),
    )
    send = _SendCollector()

    await proxy(_make_scope(), _make_receive(), send)

    assert send.body == b"streamed-body"
    # aclose is idempotent and may be called by both _body_iter's finally
    # and Starlette's StreamingResponse cleanup; we only care that it
    # ran at least once so the upstream connection returns to the pool.
    assert closed, "upstream response must be closed after _body_iter exits"

    await proxy._client.aclose()  # noqa: SLF001
