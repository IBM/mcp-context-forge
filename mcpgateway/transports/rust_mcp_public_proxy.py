# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/transports/rust_mcp_public_proxy.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

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


def _build_forwarded_headers(request: Request) -> dict:
    """Construct the request headers Rust's public listener will see.

    Strips hop-by-hop headers, preserves auth / cookies / content-type /
    MCP session headers, and adds nginx-style forwarded metadata so
    Rust's auth callback sees the original client.

    Args:
        request: Incoming Starlette request.

    Returns:
        Dict of headers to send upstream.
    """
    forwarded: dict = {}
    for name, value in request.headers.items():
        if name.lower() in _HOP_BY_HOP_REQUEST:
            continue
        forwarded[name] = value

    client_host = request.client.host if request.client else "unknown"
    client_port = request.client.port if request.client else 0

    existing_xff = request.headers.get("x-forwarded-for", "")
    forwarded["X-Forwarded-For"] = f"{existing_xff}, {client_host}".lstrip(", ") if existing_xff else client_host
    forwarded["X-Forwarded-Proto"] = request.url.scheme
    forwarded["X-Forwarded-Host"] = request.headers.get("host", "")
    forwarded["X-Real-IP"] = client_host
    forwarded["Forwarded"] = f'for="{client_host}:{client_port}";' f"proto={request.url.scheme};" f'host={request.headers.get("host", "")}'
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
        client = await self._get_client()
        upstream_path = scope.get("path", "/")
        headers = _build_forwarded_headers(request)

        try:
            upstream_request = client.build_request(
                method=request.method,
                url=upstream_path,
                headers=headers,
                params=request.query_params,
                content=request.stream(),
            )
            upstream_response = await client.send(upstream_request, stream=True)
        except httpx.HTTPError as exc:
            logger.error("rust-public ingress: upstream request to %s failed: %s", upstream_path, exc)
            error_response = Response(
                status_code=502,
                content=b"Rust MCP public ingress unavailable",
                media_type="text/plain",
            )
            await error_response(scope, receive, send)
            return

        response_headers = {name: value for name, value in upstream_response.headers.items() if name.lower() not in _HOP_BY_HOP_RESPONSE}

        async def _body_iter():
            """Stream the upstream response body chunk-by-chunk and close on exit."""
            try:
                async for chunk in upstream_response.aiter_raw():
                    yield chunk
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
