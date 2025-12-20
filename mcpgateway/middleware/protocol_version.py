# -*- coding: utf-8 -*-
"""Middleware to validate MCP-Protocol-Version header per MCP spec 2025-06-18."""

# Standard
import logging
from typing import Callable

# Third-Party
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

# First-Party
from mcpgateway.utils.orjson_response import ORJSONResponse

logger = logging.getLogger(__name__)

# MCP Protocol Versions (per MCP specification)
SUPPORTED_PROTOCOL_VERSIONS = ["2024-11-05", "2025-03-26", "2025-06-18"]
DEFAULT_PROTOCOL_VERSION = "2025-03-26"  # Per spec, default for backwards compatibility


class MCPProtocolVersionMiddleware(BaseHTTPMiddleware):
    """
    Validates MCP-Protocol-Version header per MCP spec 2025-06-18.

    Per the MCP specification (basic/transports.mdx):
    - Clients MUST include MCP-Protocol-Version header on all HTTP requests
    - If not provided, server SHOULD assume 2025-03-26 for backwards compatibility
    - If unsupported version provided, server MUST respond with 400 Bad Request
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Validate MCP-Protocol-Version header for MCP protocol endpoints.

        Args:
            request: The incoming HTTP request
            call_next: The next middleware or route handler in the chain

        Returns:
            Response: Either a 400 error for invalid protocol versions or the result of call_next
        """
        path = request.url.path

        # Skip validation for non-MCP endpoints (admin UI, health, openapi, etc.)
        if not self._is_mcp_endpoint(path):
            return await call_next(request)

        # Get the protocol version from headers (case-insensitive)
        protocol_version = request.headers.get("mcp-protocol-version")

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

        # Store validated version in request state for use by handlers
        request.state.mcp_protocol_version = protocol_version

        return await call_next(request)

    def _is_mcp_endpoint(self, path: str) -> bool:
        """
        Check if path is an MCP protocol endpoint that requires version validation.

        MCP protocol endpoints include:
        - /rpc (main JSON-RPC endpoint)
        - /servers/*/sse (Server-Sent Events transport)
        - /servers/*/ws (WebSocket transport)

        Non-MCP endpoints (admin, health, openapi, etc.) are excluded.

        Args:
            path: The request URL path to check

        Returns:
            bool: True if path is an MCP protocol endpoint, False otherwise
        """
        # Exact match for main RPC endpoint
        if path in ("/rpc", "/"):
            return True

        # Prefix matches for SSE/WebSocket/Server endpoints
        if path.startswith("/servers/") and (path.endswith("/sse") or path.endswith("/ws")):
            return True

        return False
