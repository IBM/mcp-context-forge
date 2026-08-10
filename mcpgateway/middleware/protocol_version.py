# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/protocol_version.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Middleware to validate MCP-Protocol-Version header for MCP HTTP endpoints.

Implemented as pure ASGI middleware (no BaseHTTPMiddleware): validation only
needs the request path and headers, so requests avoid BaseHTTPMiddleware's
task-group and body-streaming overhead, and the 400 short-circuit response
is sent directly.
"""

# Standard
import logging
from typing import Any, Callable, Dict, Optional

# Third-Party
from fastapi import Request, Response
from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS as MCP_SUPPORTED_PROTOCOL_VERSIONS
from mcp.types import LATEST_PROTOCOL_VERSION
from starlette.datastructures import Headers

# First-Party
from mcpgateway.utils.orjson_response import ORJSONResponse

logger = logging.getLogger(__name__)

# MCP protocol versions are sourced from the MCP SDK to stay aligned with schema.ts.
SUPPORTED_PROTOCOL_VERSIONS = list(MCP_SUPPORTED_PROTOCOL_VERSIONS)
# Default to the latest protocol for this implementation.
DEFAULT_PROTOCOL_VERSION = LATEST_PROTOCOL_VERSION


class MCPProtocolVersionMiddleware:
    """
    Validates MCP-Protocol-Version header on MCP protocol HTTP endpoints.
    """

    def __init__(self, app: Any) -> None:
        """Initialize the middleware.

        Args:
            app: The ASGI application to wrap
        """
        self.app = app

    def _validate(self, scope: Dict[str, Any]) -> Optional[Response]:
        """Validate the MCP-Protocol-Version header for an HTTP scope.

        Sets ``mcp_protocol_version`` into the scope state (visible downstream
        as ``request.state.mcp_protocol_version``) when the version is valid.

        Args:
            scope: The ASGI connection scope (also a Request's ``.scope``).

        Returns:
            None to pass the request through, or a 400 response when the
            protocol version is unsupported.
        """
        path = scope.get("path", "")

        # Skip validation for non-MCP endpoints (admin UI, health, openapi, etc.)
        if not self._is_mcp_endpoint(path):
            return None

        # Get the protocol version from headers (case-insensitive)
        protocol_version = Headers(raw=scope.get("headers") or []).get("mcp-protocol-version")

        # If no protocol version provided, assume default version (backwards compatibility)
        if protocol_version is None:
            protocol_version = DEFAULT_PROTOCOL_VERSION
            logger.debug(f"No MCP-Protocol-Version header, assuming {DEFAULT_PROTOCOL_VERSION}")

        # Validate protocol version
        if protocol_version not in SUPPORTED_PROTOCOL_VERSIONS:
            supported = ", ".join(SUPPORTED_PROTOCOL_VERSIONS)
            logger.warning(f"Unsupported protocol version: {protocol_version}")
            return ORJSONResponse(
                status_code=400,
                content={"error": "Bad Request", "message": f"Unsupported protocol version: {protocol_version}. Supported versions: {supported}"},
            )

        # Store validated version in request state for use by handlers.
        # Starlette's request.state is backed by scope["state"]; assigning here
        # keeps handlers working without constructing a Request.
        scope.setdefault("state", {})["mcp_protocol_version"] = protocol_version
        return None

    async def __call__(self, scope: Dict[str, Any], receive: Callable, send: Callable) -> None:
        """Pure ASGI entry point — no BaseHTTPMiddleware task-group/body overhead.

        Args:
            scope: ASGI connection scope.
            receive: ASGI receive callable.
            send: ASGI send callable.
        """
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        rejection = self._validate(scope)
        if rejection is not None:
            await rejection(scope, receive, send)
            return

        await self.app(scope, receive, send)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """BaseHTTPMiddleware-compatible entry point retained for tests and doctests.

        Shares its validation logic with ``__call__`` via ``_validate``.

        Args:
            request: The incoming HTTP request
            call_next: The next middleware or route handler in the chain

        Returns:
            Response: Either a 400 error for invalid protocol versions or the result of call_next

        Examples:
            Non-MCP endpoints are bypassed:

            >>> import asyncio
            >>> from starlette.requests import Request
            >>> from starlette.responses import Response
            >>> from mcpgateway.middleware.protocol_version import MCPProtocolVersionMiddleware
            >>> async def call_next(req): return Response("ok", media_type="text/plain")
            >>> scope = {
            ...     "type": "http",
            ...     "asgi": {"version": "3.0"},
            ...     "method": "GET",
            ...     "path": "/health",
            ...     "raw_path": b"/health",
            ...     "query_string": b"",
            ...     "headers": [],
            ...     "client": ("testclient", 50000),
            ...     "server": ("testserver", 80),
            ...     "scheme": "http",
            ... }
            >>> resp = asyncio.run(MCPProtocolVersionMiddleware(app=None).dispatch(Request(scope), call_next))
            >>> resp.status_code
            200

            MCP endpoints default the version when the header is missing:

            >>> from mcpgateway.middleware.protocol_version import DEFAULT_PROTOCOL_VERSION
            >>> scope_rpc = {
            ...     "type": "http",
            ...     "asgi": {"version": "3.0"},
            ...     "method": "POST",
            ...     "path": "/rpc",
            ...     "raw_path": b"/rpc",
            ...     "query_string": b"",
            ...     "headers": [],
            ...     "client": ("testclient", 50000),
            ...     "server": ("testserver", 80),
            ...     "scheme": "http",
            ... }
            >>> req = Request(scope_rpc)
            >>> _ = asyncio.run(MCPProtocolVersionMiddleware(app=None).dispatch(req, call_next))
            >>> req.state.mcp_protocol_version == DEFAULT_PROTOCOL_VERSION
            True

            Unsupported versions return `400`:

            >>> bad_scope = {
            ...     "type": "http",
            ...     "asgi": {"version": "3.0"},
            ...     "method": "POST",
            ...     "path": "/rpc",
            ...     "raw_path": b"/rpc",
            ...     "query_string": b"",
            ...     "headers": [(b"mcp-protocol-version", b"bad")],
            ...     "client": ("testclient", 50000),
            ...     "server": ("testserver", 80),
            ...     "scheme": "http",
            ... }
            >>> bad_resp = asyncio.run(MCPProtocolVersionMiddleware(app=None).dispatch(Request(bad_scope), call_next))
            >>> (bad_resp.status_code, b"Unsupported protocol version: bad" in bad_resp.body)
            (400, True)
        """
        rejection = self._validate(request.scope)
        if rejection is not None:
            return rejection
        return await call_next(request)

    def _is_mcp_endpoint(self, path: str) -> bool:
        """
        Check if path is an MCP protocol endpoint that requires version validation.

        MCP protocol endpoints include:
        - /mcp and /mcp/ (Streamable HTTP transport)
        - /rpc and /rpc/ (gateway JSON-RPC endpoint)
        - /servers/*/sse (SSE transport)
        - /servers/*/ws (WebSocket transport)

        Non-MCP endpoints (admin, health, openapi, etc.) are excluded.

        Args:
            path: The request URL path to check

        Returns:
            bool: True if path is an MCP protocol endpoint, False otherwise
        """
        # Exact match for main RPC endpoint
        if path in ("/mcp", "/mcp/", "/rpc", "/rpc/"):
            return True

        # Prefix matches for SSE/WebSocket/Server endpoints
        if path.startswith("/servers/") and (path.endswith("/sse") or path.endswith("/ws")):
            return True

        return False
