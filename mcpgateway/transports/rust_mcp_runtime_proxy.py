# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/transports/rust_mcp_runtime_proxy.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Experimental MCP transport proxy for the Rust runtime edge.

This module keeps Python auth/path-rewrite middleware in front of MCP traffic
while proxying MCP transport requests to the optional Rust runtime sidecar.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
import base64
import logging
import re
from urllib.parse import urlsplit, urlunsplit

# Third-Party
import httpx
import orjson
from starlette.types import Receive, Scope, Send

# First-Party
from mcpgateway.config import settings
from mcpgateway.services.http_client_service import get_http_client, get_http_limits
from mcpgateway.transports.streamablehttp_transport import get_streamable_http_auth_context
from mcpgateway.utils.orjson_response import ORJSONResponse

logger = logging.getLogger(__name__)

_SERVER_ID_RE = re.compile(r"/servers/(?P<server_id>[a-fA-F0-9\-]+)/mcp/?$")
_CONTEXTFORGE_SERVER_ID_HEADER = "x-contextforge-server-id"
_CONTEXTFORGE_AUTH_CONTEXT_HEADER = "x-contextforge-auth-context"
_CONTEXTFORGE_AFFINITY_FORWARDED_HEADER = "x-contextforge-affinity-forwarded"
_CLIENT_ERROR_DETAIL = "See server logs"
_REQUEST_HOP_BY_HOP_HEADERS = frozenset({"host", "content-length", "connection", "transfer-encoding", "keep-alive"})
_FORWARDED_CHAIN_HEADERS = frozenset({"forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-port", "x-forwarded-proto"})
_INTERNAL_ONLY_REQUEST_HEADERS = frozenset(
    {
        "x-forwarded-internally",
        "x-original-worker",
        "x-mcp-session-id",
        "x-contextforge-mcp-runtime",
        _CONTEXTFORGE_SERVER_ID_HEADER,
        _CONTEXTFORGE_AUTH_CONTEXT_HEADER,
        _CONTEXTFORGE_AFFINITY_FORWARDED_HEADER,
    }
)
_RESPONSE_HOP_BY_HOP_HEADERS = frozenset({"connection", "transfer-encoding", "keep-alive"})


class RustMCPRuntimeProxy:
    """Proxy MCP transport traffic to the experimental Rust runtime."""

    def __init__(self, python_fallback_app) -> None:
        """Initialize the proxy with the existing Python MCP transport fallback.

        Args:
            python_fallback_app: Python MCP transport app used when Rust cannot handle
                the request.
        """
        self.python_fallback_app = python_fallback_app
        self._uds_client: httpx.AsyncClient | None = None
        self._uds_client_lock = asyncio.Lock()

    async def handle_streamable_http(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Route MCP transport requests to the Rust runtime and preserve Python fallback for others.

        Args:
            scope: Incoming ASGI scope.
            receive: ASGI receive callable.
            send: ASGI send callable.
        """
        if scope.get("type") != "http":
            logger.debug("Rust MCP runtime deferring to Python fallback: scope type %r is not 'http'", scope.get("type"))
            await self.python_fallback_app(scope, receive, send)
            return

        method = str(scope.get("method", "GET")).upper()
        if method not in {"GET", "POST", "DELETE"}:
            logger.debug("Rust MCP runtime deferring to Python fallback: HTTP method %r is not supported", method)
            await self.python_fallback_app(scope, receive, send)
            return

        target_url = _build_runtime_mcp_url(scope)
        headers = _build_forward_headers(scope)
        timeout = httpx.Timeout(settings.experimental_rust_mcp_runtime_timeout_seconds)

        try:
            client = await self._get_runtime_client()
            async with client.stream(
                method,
                target_url,
                content=_stream_request_body(receive) if method == "POST" else b"",
                headers=headers,
                timeout=timeout,
                follow_redirects=False,
            ) as response:
                await send(
                    {
                        "type": "http.response.start",
                        "status": response.status_code,
                        "headers": [(name, value) for name, value in response.headers.raw if name.decode("latin-1").lower() not in _RESPONSE_HOP_BY_HOP_HEADERS],
                    }
                )
                async for chunk in response.aiter_bytes():
                    if chunk:
                        await send({"type": "http.response.body", "body": chunk, "more_body": True})
                await send({"type": "http.response.body", "body": b"", "more_body": False})
        except httpx.HTTPError as exc:
            logger.error("Experimental Rust MCP runtime request failed: %s", exc)
            error_response = ORJSONResponse(
                status_code=502,
                content={
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32000,
                        "message": "Experimental Rust MCP runtime unavailable",
                        "data": _CLIENT_ERROR_DETAIL,
                    },
                },
            )
            await error_response(scope, receive, send)
            return

    async def _get_runtime_client(self) -> httpx.AsyncClient:
        """Return the client used for Python -> Rust runtime proxying.

        Returns:
            An async HTTP client configured for either UDS or loopback HTTP.
        """
        uds_path = settings.experimental_rust_mcp_runtime_uds
        if not uds_path:
            return await get_http_client()

        if self._uds_client is not None:
            return self._uds_client

        async with self._uds_client_lock:
            if self._uds_client is None:
                self._uds_client = httpx.AsyncClient(
                    transport=httpx.AsyncHTTPTransport(uds=uds_path),
                    limits=get_http_limits(),
                    timeout=httpx.Timeout(settings.experimental_rust_mcp_runtime_timeout_seconds),
                    follow_redirects=False,
                )
            return self._uds_client


async def _stream_request_body(receive: Receive):
    """Yield ASGI request body chunks without buffering the full request.

    Args:
        receive: ASGI receive callable for the current request.

    Yields:
        Raw request body chunks as they arrive from the client.
    """
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            return
        if message["type"] != "http.request":
            continue
        body = message.get("body", b"")
        if body:
            yield body
        if not message.get("more_body", False):
            return


def _extract_server_id_from_scope(scope: Scope) -> str | None:
    """Extract server_id when the mounted MCP path came from /servers/<id>/mcp.

    Args:
        scope: Incoming ASGI scope.

    Returns:
        The matched server id, or ``None`` when the request is not server-scoped.
    """
    modified_path = str(scope.get("modified_path") or scope.get("path") or "")
    match = _SERVER_ID_RE.search(modified_path)
    return match.group("server_id") if match else None


def _build_runtime_mcp_url(scope: Scope) -> str:
    """Build the target Rust runtime /mcp URL, preserving the query string.

    Args:
        scope: Incoming ASGI scope.

    Returns:
        Absolute URL for the Rust sidecar MCP endpoint.
    """
    base = urlsplit(settings.experimental_rust_mcp_runtime_url)
    query_string = scope.get("query_string", b"")
    query = query_string.decode("latin-1") if isinstance(query_string, (bytes, bytearray)) else str(query_string or "")
    base_path = base.path.rstrip("/")
    if not base_path:
        target_path = "/mcp/"
    elif base_path.endswith("/mcp"):
        target_path = f"{base_path}/"
    else:
        target_path = f"{base_path}/mcp/"
    merged_query = "&".join(part for part in (base.query, query) if part)
    return urlunsplit((base.scheme, base.netloc, target_path, merged_query, ""))


def _build_forward_headers(scope: Scope) -> list[tuple[str, str]]:
    """Forward request headers needed by the Rust runtime while stripping internal-only headers.

    Args:
        scope: Incoming ASGI scope.

    Returns:
        Header tuples safe to forward to the Rust sidecar.
    """
    headers: list[tuple[str, str]] = []
    for item in scope.get("headers") or []:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            continue
        name, value = item
        if not isinstance(name, (bytes, bytearray)) or not isinstance(value, (bytes, bytearray)):
            continue
        header_name = name.decode("latin-1").lower()
        if header_name in _REQUEST_HOP_BY_HOP_HEADERS or header_name in _FORWARDED_CHAIN_HEADERS or header_name in _INTERNAL_ONLY_REQUEST_HEADERS:
            continue
        headers.append((header_name, value.decode("latin-1")))

    server_id = _extract_server_id_from_scope(scope)
    if server_id:
        headers.append((_CONTEXTFORGE_SERVER_ID_HEADER, server_id))

    auth_context = _build_forwarded_auth_context_header()
    if auth_context is not None:
        headers.append((_CONTEXTFORGE_AUTH_CONTEXT_HEADER, auth_context))

    client = scope.get("client")
    client_host = client[0] if isinstance(client, (tuple, list)) and client else None
    from_loopback = client_host in ("127.0.0.1", "::1")
    incoming_headers = {
        name.decode("latin-1").lower(): value.decode("latin-1")
        for item in scope.get("headers") or []
        if isinstance(item, (tuple, list)) and len(item) == 2
        for name, value in [item]
        if isinstance(name, (bytes, bytearray)) and isinstance(value, (bytes, bytearray))
    }
    if from_loopback and incoming_headers.get("x-forwarded-internally") == "true":
        headers.append((_CONTEXTFORGE_AFFINITY_FORWARDED_HEADER, "rust"))

    return headers


def _build_forwarded_auth_context_header() -> str | None:
    """Serialize the authenticated MCP context for the trusted internal Python dispatcher.

    Returns:
        Base64url-encoded auth context for trusted internal forwarding, or ``None``
        when no MCP auth context is available.
    """
    auth_context = get_streamable_http_auth_context()
    if not auth_context:
        return None
    encoded = base64.urlsafe_b64encode(orjson.dumps(auth_context)).decode("ascii")
    return encoded.rstrip("=")
