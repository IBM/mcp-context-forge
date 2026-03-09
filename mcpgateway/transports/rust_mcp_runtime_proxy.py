# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/transports/rust_mcp_runtime_proxy.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Experimental MCP transport proxy for the Rust runtime edge.

This module keeps Python auth/path-rewrite middleware in front of MCP traffic
while proxying POST JSON-RPC calls to the optional Rust runtime sidecar.
Non-POST requests continue to use the existing Python streamable HTTP handler so
that current session-management semantics remain available while the Rust edge
is still transport-focused.
"""

# Future
from __future__ import annotations

# Standard
import logging
import re
from urllib.parse import urlsplit, urlunsplit

# Third-Party
import httpx
from starlette.types import Receive, Scope, Send

# First-Party
from mcpgateway.config import settings
from mcpgateway.services.http_client_service import get_http_client
from mcpgateway.utils.orjson_response import ORJSONResponse

logger = logging.getLogger(__name__)

_SERVER_ID_RE = re.compile(r"/servers/(?P<server_id>[a-fA-F0-9\-]+)/mcp/?$")
_CONTEXTFORGE_SERVER_ID_HEADER = "x-contextforge-server-id"
_REQUEST_HOP_BY_HOP_HEADERS = frozenset({"host", "content-length", "connection", "transfer-encoding", "keep-alive"})
_INTERNAL_ONLY_REQUEST_HEADERS = frozenset({"x-forwarded-internally", "x-mcp-session-id", "x-contextforge-mcp-runtime", _CONTEXTFORGE_SERVER_ID_HEADER})
_RESPONSE_HOP_BY_HOP_HEADERS = frozenset({"connection", "transfer-encoding", "keep-alive"})


class RustMCPRuntimeProxy:
    """Proxy POST MCP traffic to the experimental Rust runtime."""

    def __init__(self, python_fallback_app) -> None:
        """Initialize the proxy with the existing Python MCP transport fallback."""
        self.python_fallback_app = python_fallback_app

    async def handle_streamable_http(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Route POST requests to the Rust runtime and preserve Python fallback for others."""
        if scope.get("type") != "http":
            await self.python_fallback_app(scope, receive, send)
            return

        method = str(scope.get("method", "GET")).upper()
        if method != "POST":
            await self.python_fallback_app(scope, receive, send)
            return

        target_url = _build_runtime_mcp_url(scope)
        headers = _build_forward_headers(scope)
        timeout = httpx.Timeout(settings.experimental_rust_mcp_runtime_timeout_seconds)

        try:
            client = await get_http_client()
            async with client.stream(
                "POST",
                target_url,
                content=_stream_request_body(receive),
                headers=headers,
                timeout=timeout,
            ) as response:
                await send(
                    {
                        "type": "http.response.start",
                        "status": response.status_code,
                        "headers": [
                            (name, value)
                            for name, value in response.headers.raw
                            if name.decode("latin-1").lower() not in _RESPONSE_HOP_BY_HOP_HEADERS
                        ],
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
                        "data": str(exc),
                    },
                },
            )
            await error_response(scope, receive, send)
            return


async def _stream_request_body(receive: Receive):
    """Yield ASGI request body chunks without buffering the full request."""
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
    """Extract server_id when the mounted MCP path came from /servers/<id>/mcp."""
    modified_path = str(scope.get("modified_path") or scope.get("path") or "")
    match = _SERVER_ID_RE.search(modified_path)
    return match.group("server_id") if match else None


def _build_runtime_mcp_url(scope: Scope) -> str:
    """Build the target Rust runtime /mcp URL, preserving the query string."""
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
    """Forward request headers needed by the Rust runtime while stripping internal-only headers."""
    headers: list[tuple[str, str]] = []
    for item in scope.get("headers") or []:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            continue
        name, value = item
        if not isinstance(name, (bytes, bytearray)) or not isinstance(value, (bytes, bytearray)):
            continue
        header_name = name.decode("latin-1").lower()
        if header_name in _REQUEST_HOP_BY_HOP_HEADERS or header_name in _INTERNAL_ONLY_REQUEST_HEADERS:
            continue
        headers.append((header_name, value.decode("latin-1")))

    server_id = _extract_server_id_from_scope(scope)
    if server_id:
        headers.append((_CONTEXTFORGE_SERVER_ID_HEADER, server_id))
    return headers
