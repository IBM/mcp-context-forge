# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/transports/rust_mcp_public_proxy.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

nginx-style reverse proxy to the Rust MCP public listener.

Use this when the gateway is the only public ingress (no nginx in front)
but you still want public ``/mcp`` traffic to bypass Python's transport
on the hot path. Routes to ``MCP_RUST_PUBLIC_LISTEN_HTTP`` (Rust's
authenticated public endpoint), not the trusted-internal
``MCP_RUST_LISTEN_HTTP`` that ``RustMCPRuntimeProxy`` uses.

Differences from ``RustMCPRuntimeProxy``
(``mcpgateway/transports/rust_mcp_runtime_proxy.py``):

- Forwards to the **public** listener (Rust calls back into Python for
  auth via ``/_internal/mcp/authenticate``), not the trusted-internal
  listener that assumes Python pre-authenticated.
- Adds ``X-Forwarded-{For,Proto,Host}``, RFC 7239 ``Forwarded``, and
  ``X-Real-IP`` — nginx-style — so Rust's auth path sees the original
  client info instead of ``127.0.0.1``.
- Preserves ``Authorization``, ``Cookie``, MCP session headers — this is
  a public hop, not a trusted-internal one.
- Does NOT inject ``x-contextforge-mcp-runtime``,
  ``X-ContextForge-Auth-Context``, or any other trust-marker headers.
- Streams both directions without buffering (SSE-friendly).

Registered with ``MCPIngressMount`` under the name ``"rust-public"``;
the selector picks it when ``settings.mcp_rust_ingress == "public"``.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
import logging
from typing import Awaitable, Callable, Optional

# Third-Party
import httpx
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

# First-Party
from mcpgateway.config import settings

logger = logging.getLogger(__name__)

# Hop-by-hop headers per RFC 7230 §6.1 — must not be forwarded by an
# intermediary. nginx strips these by default.
_HOP_BY_HOP_REQUEST = frozenset(
    {
        "host",
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "content-length",
    }
)
_HOP_BY_HOP_RESPONSE = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
    }
)
# Forwarded-chain headers are dropped from the inbound request and
# re-set unconditionally below. This is the no-nginx-in-front case: the
# immediate hop is the client, so we cannot trust any value they
# pre-populate. The set is intentionally a superset of the
# trusted-internal proxy's forwarded-chain set (it additionally drops
# ``x-real-ip`` because we re-derive it from the ASGI client info).
_FORWARDED_CHAIN_HEADERS = frozenset(
    {
        "forwarded",
        "x-forwarded-for",
        "x-forwarded-host",
        "x-forwarded-port",
        "x-forwarded-proto",
        "x-real-ip",
    }
)


def _format_forwarded_for(host: Optional[str], port: int) -> str:
    """Format an RFC 7239 ``for=`` directive value.

    Args:
        host: Client host (may be IPv4, IPv6, or ``None``).
        port: Client port; ``0`` is treated as "no port" because
            Starlette synthesizes ``0`` when ``request.client`` is
            unavailable, which is not a valid port number to advertise.

    Returns:
        A token suitable as the value of ``for=`` — ``unknown`` for
        absent clients, otherwise a quoted ``"ip[:port]"`` (with IPv6
        addresses bracketed per RFC 3986).
    """
    if not host:
        return "unknown"
    # IPv6 addresses contain colons and must be bracketed per RFC 3986;
    # detect already-bracketed input so a caller passing "[::1]" doesn't
    # end up with "[[::1]]".
    if ":" in host and not (host.startswith("[") and host.endswith("]")):
        address = f"[{host}]"
    else:
        address = host
    return f'"{address}:{port}"' if port else f'"{address}"'


def _build_forwarded_headers(request: Request) -> dict:
    """Construct the request headers Rust's public listener will see.

    Strips hop-by-hop and forwarded-chain headers from the inbound
    request, preserves auth / cookies / content-type / MCP session
    headers, then adds nginx-style forwarded metadata derived from the
    trusted ASGI ``request.client`` info. The forwarded-chain strip is
    a security control: this proxy is the first hop in the
    no-nginx-in-front deployment, so any client-supplied
    ``X-Forwarded-*`` or ``Forwarded`` value would let the caller spoof
    their own source IP to Rust's auth callback.

    Args:
        request: Incoming Starlette request.

    Returns:
        Dict of headers to send upstream.
    """
    forwarded: dict = {}
    for name, value in request.headers.items():
        lowered = name.lower()
        if lowered in _HOP_BY_HOP_REQUEST or lowered in _FORWARDED_CHAIN_HEADERS:
            continue
        forwarded[name] = value

    client_host = request.client.host if request.client else None
    client_port = request.client.port if request.client else 0
    host_header = request.headers.get("host", "")

    forwarded["X-Forwarded-For"] = client_host or "unknown"
    forwarded["X-Forwarded-Proto"] = request.url.scheme
    forwarded["X-Forwarded-Host"] = host_header
    forwarded["X-Real-IP"] = client_host or "unknown"
    forwarded["Forwarded"] = f'for={_format_forwarded_for(client_host, client_port)};proto={request.url.scheme};host="{host_header}"'
    return forwarded


class RustMCPPublicProxyApp:
    """ASGI app that reverse-proxies public MCP requests to Rust's public listener.

    Holds a single long-lived ``httpx.AsyncClient`` per app instance for
    connection pooling; constructed lazily on first request so module
    import doesn't trigger any I/O.
    """

    def __init__(self, *, upstream_url: Optional[str] = None) -> None:
        """Initialize the proxy.

        Args:
            upstream_url: Base URL for the Rust public listener. Defaults
                to ``settings.mcp_rust_public_proxy_upstream``
                (default ``http://127.0.0.1:8787``, matching
                ``MCP_RUST_PUBLIC_LISTEN_HTTP=0.0.0.0:8787`` from
                ``docker-entrypoint.sh``).
        """
        self._upstream_url = upstream_url or settings.mcp_rust_public_proxy_upstream
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazily build the long-lived ``httpx.AsyncClient`` for upstream forwarding.

        Returns:
            The cached client (constructed on first call).
        """
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._upstream_url,
                timeout=httpx.Timeout(
                    connect=5.0,
                    read=None,  # SSE streams are long-lived; no read timeout
                    write=30.0,
                    pool=5.0,
                ),
                limits=httpx.Limits(
                    max_keepalive_connections=64,
                    max_connections=256,
                    keepalive_expiry=30.0,
                ),
                follow_redirects=False,
                http2=False,  # Rust public listener is HTTP/1.1
            )
        return self._client

    async def __call__(self, scope: dict, receive: Callable[[], Awaitable[dict]], send: Callable[[dict], Awaitable[None]]) -> None:
        """ASGI entry point.

        Args:
            scope: ASGI scope.
            receive: ASGI receive callable.
            send: ASGI send callable.
        """
        if scope.get("type") != "http":
            # Non-HTTP scopes (lifespan, websocket) aren't handled here.
            # MCP uses streamable HTTP today; if a future version adds
            # WebSocket-on-/mcp, route those through a different ingress.
            response = Response(status_code=404, content=b"Not found", media_type="text/plain")
            await response(scope, receive, send)
            return

        request = Request(scope, receive)
        upstream_path = scope.get("path", "/")
        method = request.method

        # asyncio.CancelledError is BaseException in 3.8+ — neither the
        # httpx.HTTPError nor the bare ``Exception`` arms below will swallow
        # a client-disconnect cancel; it propagates out naturally.
        try:
            client = await self._get_client()
            headers = _build_forwarded_headers(request)
            upstream_request = client.build_request(
                method=method,
                url=upstream_path,
                headers=headers,
                params=request.query_params,
                content=request.stream(),
            )
            upstream_response = await client.send(upstream_request, stream=True)
        except httpx.HTTPError as exc:
            logger.error(
                "rust-public ingress: upstream %s %s failed (%s): %s",
                method,
                upstream_path,
                type(exc).__name__,
                exc,
            )
            error_response = Response(
                status_code=502,
                content=b"Rust MCP public ingress unavailable",
                media_type="text/plain",
            )
            await error_response(scope, receive, send)
            return
        except Exception:  # pylint: disable=broad-except
            # Defensive catch-all: anything else (RuntimeError, SSLError
            # subclasses outside HTTPError, etc.) becomes a 500 with a
            # logged stack trace, so silent 500s never reach the client
            # without a server-side breadcrumb.
            logger.exception(
                "rust-public ingress: unexpected error preparing upstream %s %s",
                method,
                upstream_path,
            )
            error_response = Response(
                status_code=500,
                content=b"Rust MCP public ingress error",
                media_type="text/plain",
            )
            await error_response(scope, receive, send)
            return

        # Auth-relevant or server-error upstream statuses get a warning so
        # ops can spot a flood of 401s after a credential rotation, or a
        # cascading 503, without raising the log level globally.
        if upstream_response.status_code >= 500 or upstream_response.status_code in (401, 403):
            logger.warning(
                "rust-public ingress: upstream %s %s returned %d",
                method,
                upstream_path,
                upstream_response.status_code,
            )

        response_headers = {name: value for name, value in upstream_response.headers.items() if name.lower() not in _HOP_BY_HOP_RESPONSE}

        async def _body_iter():
            """Stream the upstream response body and close the upstream connection on exit.

            The ``finally`` returns the connection to the pool whether
            iteration completes normally, the client disconnects
            (``CancelledError``), or upstream errors mid-stream. Errors
            other than cancellation are logged with the upstream context
            so a mid-SSE Rust crash leaves a breadcrumb instead of just
            a generic Starlette 500.
            """
            try:
                async for chunk in upstream_response.aiter_raw():
                    yield chunk
            except asyncio.CancelledError:
                logger.debug(
                    "rust-public ingress: client disconnected mid-stream from upstream %s %s",
                    method,
                    upstream_path,
                )
                raise
            except Exception:  # pylint: disable=broad-except
                logger.exception(
                    "rust-public ingress: error streaming body from upstream %s %s",
                    method,
                    upstream_path,
                )
                raise
            finally:
                await upstream_response.aclose()

        streaming_response = StreamingResponse(
            _body_iter(),
            status_code=upstream_response.status_code,
            headers=response_headers,
            media_type=upstream_response.headers.get("content-type"),
        )
        await streaming_response(scope, receive, send)


def build_rust_public_proxy_app(*, upstream_url: Optional[str] = None) -> RustMCPPublicProxyApp:
    """Factory for the public-listener ingress app.

    Args:
        upstream_url: Optional override for the Rust public listener URL.
            If ``None``, reads ``settings.mcp_rust_public_proxy_upstream``.

    Returns:
        A :class:`RustMCPPublicProxyApp` ready to register with
        :class:`MCPIngressMount` under the name ``"rust-public"``.
    """
    return RustMCPPublicProxyApp(upstream_url=upstream_url)
