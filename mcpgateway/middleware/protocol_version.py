# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/protocol_version.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Middleware to validate MCP-Protocol-Version header for MCP HTTP endpoints.
"""

# Standard
import logging
from typing import Callable

# Third-Party
from fastapi import Request, Response
from mcp_types.version import HANDSHAKE_PROTOCOL_VERSIONS, LATEST_HANDSHAKE_VERSION, LATEST_PROTOCOL_VERSION
from mcp_types.version import SUPPORTED_PROTOCOL_VERSIONS as MCP_SUPPORTED_PROTOCOL_VERSIONS
from starlette.middleware.base import BaseHTTPMiddleware

# First-Party
from mcpgateway.utils.orjson_response import ORJSONResponse
from mcpgateway.utils.paths import replace_api_path_alias

logger = logging.getLogger(__name__)

# MCP protocol versions are sourced from the MCP SDK to stay aligned with schema.ts.
SUPPORTED_PROTOCOL_VERSIONS = list(MCP_SUPPORTED_PROTOCOL_VERSIONS)
# Default to the latest protocol for this implementation.
DEFAULT_PROTOCOL_VERSION = LATEST_PROTOCOL_VERSION


class MCPProtocolVersionMiddleware(BaseHTTPMiddleware):
    """
    Validates MCP-Protocol-Version header on MCP protocol HTTP endpoints.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Validate MCP-Protocol-Version header for MCP protocol endpoints.

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

            MCP endpoints default to the latest handshake version (legacy mode is the default):

            >>> from mcp_types.version import LATEST_HANDSHAKE_VERSION
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
            >>> req.state.mcp_protocol_version == LATEST_HANDSHAKE_VERSION
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
        path = request.url.path

        # Skip validation for non-MCP endpoints (admin UI, health, openapi, etc.)
        if not self._is_mcp_endpoint(path):
            return await call_next(request)

        # Get the protocol version from headers (case-insensitive)
        protocol_version = request.headers.get("mcp-protocol-version")

        # Resolve accepted versions based on inbound protocol mode
        # Import here to avoid circular import at module level
        from mcpgateway.config import settings  # pylint: disable=import-outside-toplevel

        if settings.mcp_inbound_protocol_mode == "legacy":
            accepted_versions = HANDSHAKE_PROTOCOL_VERSIONS
            default_version = LATEST_HANDSHAKE_VERSION
        else:
            accepted_versions = SUPPORTED_PROTOCOL_VERSIONS
            default_version = DEFAULT_PROTOCOL_VERSION

        # If no protocol version provided, assume default version (backwards compatibility)
        if protocol_version is None:
            protocol_version = default_version
            logger.debug("No MCP-Protocol-Version header, assuming %s", default_version)

        # Validate protocol version
        if protocol_version not in accepted_versions:
            supported = ", ".join(accepted_versions)
            logger.warning("Unsupported protocol version: %s", protocol_version)
            return ORJSONResponse(
                status_code=400,
                content={"error": "Bad Request", "message": f"Unsupported protocol version: {protocol_version}. Supported versions: {supported}"},
            )

        # Store validated version in request state for use by handlers
        request.state.mcp_protocol_version = protocol_version

        return await call_next(request)

    def _is_mcp_endpoint(self, path: str) -> bool:
        """
        Check if path is an MCP protocol endpoint that requires version validation.

        MCP protocol endpoints include:
        - /mcp and /mcp/ (Streamable HTTP transport)
        - /rpc and /rpc/ (gateway JSON-RPC endpoint)
        - /servers/*/sse (SSE transport)
        - /servers/*/ws (WebSocket transport)
        - /v1/virtual-servers/*/sse (versioned SSE transport alias)
        - /v1/virtual-servers/*/ws (versioned WebSocket transport alias)

        Non-MCP endpoints (admin, health, openapi, etc.) are excluded.

        Args:
            path: The request URL path to check

        Returns:
            bool: True if path is an MCP protocol endpoint, False otherwise
        """
        path = replace_api_path_alias(path)

        # Exact match for main RPC endpoint
        if path in ("/mcp", "/mcp/", "/rpc", "/rpc/"):
            return True

        # Prefix matches for SSE/WebSocket/Server endpoints
        if path.startswith("/servers/") and (path.endswith("/sse") or path.endswith("/ws")):
            return True

        return False
