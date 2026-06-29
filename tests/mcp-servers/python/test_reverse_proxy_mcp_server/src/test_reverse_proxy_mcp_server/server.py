#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/test_reverse_proxy_mcp_server/src/test_reverse_proxy_mcp_server/server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Test MCP Server for Reverse Proxy Multi-Transport

A minimal test server supporting multiple transports (stdio, HTTP, SSE) for testing
reverse proxy functionality with streamable HTTP and SSE transports.
"""

import logging
import sys
from typing import Any

from fastmcp import FastMCP
from pydantic import Field

# Configure logging to stderr to avoid MCP protocol interference
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger(__name__)

# Create FastMCP server instance with custom ASGI app to log headers
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class HeaderLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware to log all incoming HTTP request headers."""

    async def dispatch(self, request: Request, call_next):
        logger.info("=" * 80)
        logger.info("INCOMING REQUEST HEADERS:")
        for header_name, header_value in request.headers.items():
            # Mask sensitive values but show they exist
            if header_name.lower() in ("authorization", "x-api-key", "cookie"):
                masked_value = f"{header_value[:10]}..." if len(header_value) > 10 else "***"
                logger.info(f"  {header_name}: {masked_value} (masked)")
            else:
                logger.info(f"  {header_name}: {header_value}")
        logger.info("=" * 80)

        response = await call_next(request)
        return response


mcp = FastMCP(name="test-reverse-proxy-mcp-server", version="0.1.0")


@mcp.tool(description="Echo back the input message")
async def echo(
    message: str = Field(..., description="Message to echo back"),
) -> dict[str, Any]:
    """Echo back the input message."""
    logger.info(f"Echo tool called with message: {message}")
    return {
        "success": True,
        "message": message,
        "length": len(message),
    }


@mcp.tool(description="Get server information")
async def get_server_info() -> dict[str, Any]:
    """Get information about the test server."""
    logger.info("Get server info tool called")
    return {
        "success": True,
        "name": "test-reverse-proxy-mcp-server",
        "version": "0.1.0",
        "supported_transports": ["stdio", "http", "sse"],
        "description": "Test MCP server for reverse proxy multi-transport testing",
    }


def main():
    """Main entry point for the FastMCP server."""
    import argparse

    parser = argparse.ArgumentParser(description="Test Reverse Proxy MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http", "sse"],
        default="stdio",
        help="Transport mode (stdio, http, or sse)",
    )
    parser.add_argument("--host", default="0.0.0.0", help="HTTP/SSE host")
    parser.add_argument("--port", type=int, default=9020, help="HTTP/SSE port")

    args = parser.parse_args()

    if args.transport == "http":
        logger.info(f"Starting Test Reverse Proxy MCP Server on HTTP at {args.host}:{args.port}")
        # Add header logging middleware
        mcp.run(
            transport="http",
            host=args.host,
            port=args.port,
            middleware=[Middleware(HeaderLoggingMiddleware)]
        )
    elif args.transport == "sse":
        logger.info(f"Starting Test Reverse Proxy MCP Server on SSE at {args.host}:{args.port}")
        # Add header logging middleware for SSE transport
        mcp.run(
            transport="sse",
            host=args.host,
            port=args.port,
            middleware=[Middleware(HeaderLoggingMiddleware)]
        )
    else:
        logger.info("Starting Test Reverse Proxy MCP Server on stdio")
        mcp.run()


if __name__ == "__main__":
    main()
