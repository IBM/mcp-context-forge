# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/transports/rust_mcp_runtime_grpc_proxy.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

gRPC-over-UDS proxy for the Rust MCP runtime sidecar (ADR-044).

Replaces the HTTP/JSON transport in ``rust_mcp_runtime_proxy.py`` with a
typed protobuf contract over a Unix Domain Socket.  The same Python auth and
path-rewrite middleware stays in front; only the Python → Rust IPC transport
changes.

Feature flag: enabled when ``MCP_RUST_GRPC_UDS`` is set to a socket path.
Falls back to the existing HTTP proxy when not configured.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
from typing import AsyncIterator

import grpc
import grpc.aio
import orjson
from starlette.types import Receive, Scope, Send

from mcpgateway.config import settings
from mcpgateway.transports.grpc_gen import mcp_runtime_pb2, mcp_runtime_pb2_grpc
from mcpgateway.transports.streamablehttp_transport import get_streamable_http_auth_context
from mcpgateway.utils.orjson_response import ORJSONResponse

logger = logging.getLogger(__name__)

_SERVER_ID_RE = re.compile(r"/servers/(?P<server_id>[a-fA-F0-9\-]+)/mcp/?$")
_CONTEXTFORGE_SERVER_ID_HEADER = "x-contextforge-server-id"
_CONTEXTFORGE_AUTH_CONTEXT_HEADER = "x-contextforge-auth-context"
_CONTEXTFORGE_AFFINITY_FORWARDED_HEADER = "x-contextforge-affinity-forwarded"

# Headers stripped before forwarding — mirrors rust_mcp_runtime_proxy.py
_REQUEST_HOP_BY_HOP = frozenset({"host", "content-length", "connection", "transfer-encoding", "keep-alive"})
_FORWARDED_CHAIN = frozenset({"forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-port", "x-forwarded-proto"})
_INTERNAL_ONLY = frozenset(
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

_CLIENT_ERROR_DETAIL = "See server logs"


class RustMCPRuntimeGrpcProxy:
    """Proxy MCP transport traffic to the Rust runtime via gRPC-over-UDS.

    Drop-in replacement for :class:`RustMCPRuntimeProxy` on the same ASGI
    interface.  Uses a typed protobuf contract instead of raw HTTP forwarding.
    """

    def __init__(self, python_fallback_app) -> None:
        """Initialise the proxy with the existing Python MCP transport fallback.

        Args:
            python_fallback_app: Python MCP transport app used when the gRPC
                channel is not configured or when the sidecar is unreachable.
        """
        self.python_fallback_app = python_fallback_app
        self._channel: grpc.aio.Channel | None = None
        self._stub: mcp_runtime_pb2_grpc.McpRuntimeStub | None = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # ASGI entry point
    # ------------------------------------------------------------------

    async def handle_streamable_http(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Route MCP requests to the Rust sidecar via gRPC and fall back to Python.

        Args:
            scope: Incoming ASGI scope.
            receive: ASGI receive callable.
            send: ASGI send callable.
        """
        if scope.get("type") != "http":
            await self.python_fallback_app(scope, receive, send)
            return

        method = str(scope.get("method", "GET")).upper()
        if method not in {"GET", "POST", "DELETE"}:
            await self.python_fallback_app(scope, receive, send)
            return

        try:
            stub = await self._get_stub()
            mcp_request = _build_mcp_request(scope, method, await _read_body(receive))

            if method == "GET":
                await self._handle_stream(stub, mcp_request, scope, receive, send)
            else:
                await self._handle_unary(stub, mcp_request, method, scope, receive, send)

        except grpc.aio.AioRpcError as exc:
            logger.error("gRPC Rust MCP runtime call failed: %s %s", exc.code(), exc.details())
            await _grpc_error_response(scope, receive, send)
        except Exception as exc:  # noqa: BLE001
            logger.error("gRPC Rust MCP runtime unexpected error: %s", exc)
            await _grpc_error_response(scope, receive, send)

    # ------------------------------------------------------------------
    # Unary: POST and DELETE
    # ------------------------------------------------------------------

    async def _handle_unary(
        self,
        stub: mcp_runtime_pb2_grpc.McpRuntimeStub,
        mcp_request: mcp_runtime_pb2.McpRequest,
        method: str,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if method == "DELETE":
            response: mcp_runtime_pb2.McpResponse = await stub.CloseSession(mcp_request)
        else:
            response = await stub.Invoke(mcp_request)

        headers = [(k.encode(), v.encode()) for k, v in response.headers.items()]
        await send({"type": "http.response.start", "status": response.status, "headers": headers})
        await send({"type": "http.response.body", "body": response.body, "more_body": False})

    # ------------------------------------------------------------------
    # Server-streaming: GET (SSE / live-stream / resume)
    # ------------------------------------------------------------------

    async def _handle_stream(
        self,
        stub: mcp_runtime_pb2_grpc.McpRuntimeStub,
        mcp_request: mcp_runtime_pb2.McpRequest,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        response_started = False
        async for chunk in stub.InvokeStream(mcp_request):
            if not response_started:
                # Emit headers on the first chunk
                await send(
                    {
                        "type": "http.response.start",
                        "status": chunk.error_status if chunk.error_status else 200,
                        "headers": [(b"content-type", b"text/event-stream"), (b"cache-control", b"no-cache")],
                    }
                )
                response_started = True

            if chunk.data:
                await send({"type": "http.response.body", "body": chunk.data, "more_body": not chunk.done})

            if chunk.done:
                break

        if not response_started:
            await send({"type": "http.response.start", "status": 200, "headers": []})

        await send({"type": "http.response.body", "body": b"", "more_body": False})

    # ------------------------------------------------------------------
    # Channel / stub management
    # ------------------------------------------------------------------

    async def _get_stub(self) -> mcp_runtime_pb2_grpc.McpRuntimeStub:
        """Return a cached gRPC stub connected to the Rust sidecar UDS socket.

        Returns:
            Async gRPC stub for ``McpRuntime``.

        Raises:
            RuntimeError: When ``MCP_RUST_GRPC_UDS`` is not configured.
        """
        uds_path = getattr(settings, "experimental_rust_mcp_runtime_grpc_uds", None)
        if not uds_path:
            raise RuntimeError("MCP_RUST_GRPC_UDS is not configured")

        if self._stub is not None:
            return self._stub

        async with self._lock:
            if self._stub is None:
                # grpc.aio supports unix:// URIs natively
                target = f"unix://{uds_path}"
                self._channel = grpc.aio.insecure_channel(target)
                self._stub = mcp_runtime_pb2_grpc.McpRuntimeStub(self._channel)
                logger.info("gRPC-over-UDS channel opened: %s", target)

        return self._stub


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _read_body(receive: Receive) -> bytes:
    """Read the full ASGI request body into memory.

    Args:
        receive: ASGI receive callable.

    Returns:
        Raw request body bytes.
    """
    chunks: list[bytes] = []
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            break
        if message["type"] != "http.request":
            continue
        body = message.get("body", b"")
        if body:
            chunks.append(body)
        if not message.get("more_body", False):
            break
    return b"".join(chunks)


def _extract_server_id(scope: Scope) -> str:
    modified_path = str(scope.get("modified_path") or scope.get("path") or "")
    match = _SERVER_ID_RE.search(modified_path)
    return match.group("server_id") if match else ""


def _extract_session_id(scope: Scope) -> str:
    for item in scope.get("headers") or []:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            continue
        name, value = item
        if isinstance(name, (bytes, bytearray)) and name.decode("latin-1").lower() == "mcp-session-id":
            return value.decode("latin-1") if isinstance(value, (bytes, bytearray)) else str(value)
    return ""


def _build_safe_headers(scope: Scope) -> dict[str, str]:
    headers: dict[str, str] = {}
    for item in scope.get("headers") or []:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            continue
        name, value = item
        if not isinstance(name, (bytes, bytearray)) or not isinstance(value, (bytes, bytearray)):
            continue
        header_name = name.decode("latin-1").lower()
        if header_name in _REQUEST_HOP_BY_HOP or header_name in _FORWARDED_CHAIN or header_name in _INTERNAL_ONLY:
            continue
        headers[header_name] = value.decode("latin-1")
    return headers


def _build_auth_context(scope: Scope) -> mcp_runtime_pb2.McpAuthContext | None:
    raw = get_streamable_http_auth_context()
    if not raw:
        return None
    encoded = base64.urlsafe_b64encode(orjson.dumps(raw)).decode("ascii").rstrip("=")
    return mcp_runtime_pb2.McpAuthContext(encoded=encoded, expires_at_epoch_ms=0)


def _is_affinity_forwarded(scope: Scope) -> bool:
    client = scope.get("client")
    client_host = client[0] if isinstance(client, (tuple, list)) and client else None
    from_loopback = client_host in ("127.0.0.1", "::1")
    if not from_loopback:
        return False
    for item in scope.get("headers") or []:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            continue
        name, value = item
        if (
            isinstance(name, (bytes, bytearray))
            and name.decode("latin-1").lower() == "x-forwarded-internally"
            and isinstance(value, (bytes, bytearray))
            and value.decode("latin-1") == "true"
        ):
            return True
    return False


def _build_mcp_request(scope: Scope, method: str, body: bytes) -> mcp_runtime_pb2.McpRequest:
    path = str(scope.get("path") or "/mcp/")
    query_string = scope.get("query_string", b"")
    query = query_string.decode("latin-1") if isinstance(query_string, (bytes, bytearray)) else str(query_string or "")

    auth_ctx = _build_auth_context(scope)

    return mcp_runtime_pb2.McpRequest(
        method=method,
        path=path,
        query=query,
        body=body,
        headers=_build_safe_headers(scope),
        server_id=_extract_server_id(scope),
        auth_context=auth_ctx,
        affinity_forwarded=_is_affinity_forwarded(scope),
        session_id=_extract_session_id(scope),
    )


async def _grpc_error_response(scope: Scope, receive: Receive, send: Send) -> None:
    error_response = ORJSONResponse(
        status_code=502,
        content={
            "jsonrpc": "2.0",
            "id": None,
            "error": {
                "code": -32000,
                "message": "Rust MCP runtime gRPC transport unavailable",
                "data": _CLIENT_ERROR_DETAIL,
            },
        },
    )
    await error_response(scope, receive, send)
