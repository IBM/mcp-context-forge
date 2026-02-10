# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/compression.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

SSE-Aware Compression Middleware for MCP Gateway.

This module wraps starlette-compress to skip compression for Server-Sent Events (SSE)
responses, which should not be compressed as it can break streaming behavior.
"""

# Third-Party
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette_compress import CompressMiddleware

# First-Party
from mcpgateway.config import settings


class SSEAwareCompressMiddleware:
    """
    Compression middleware that skips compression for SSE responses on /mcp paths.

    Server-Sent Events (text/event-stream) responses should not be compressed
    because compression can buffer the stream and break real-time delivery.
    When json_response_enabled=False (SSE mode), this middleware bypasses
    compression for /mcp endpoints.

    When json_response_enabled=True (default), all responses including /mcp
    are compressed normally since they return JSON, not SSE streams.

    Examples:
        >>> from unittest.mock import AsyncMock
        >>> app = AsyncMock()
        >>> middleware = SSEAwareCompressMiddleware(app, minimum_size=500)
        >>> isinstance(middleware, SSEAwareCompressMiddleware)
        True
        >>> middleware.app is app
        True

        >>> # Test path matching logic
        >>> def is_mcp_path(path):
        ...     return path == "/mcp" or path == "/mcp/" or path.endswith("/mcp") or path.endswith("/mcp/")
        >>> is_mcp_path("/mcp")
        True
        >>> is_mcp_path("/mcp/")
        True
        >>> is_mcp_path("/servers/123/mcp")
        True
        >>> is_mcp_path("/servers/123/mcp/")
        True
        >>> is_mcp_path("/tools")
        False
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        minimum_size: int = 500,
        gzip_level: int = 6,
        brotli_quality: int = 4,
        zstd_level: int = 3,
    ) -> None:
        """
        Initialize the SSE-aware compression middleware.

        Args:
            app: The ASGI application to wrap.
            minimum_size: Minimum response size to compress (bytes).
            gzip_level: GZip compression level (1-9).
            brotli_quality: Brotli compression quality (0-11).
            zstd_level: Zstandard compression level.

        Example:
            >>> from unittest.mock import AsyncMock
            >>> app = AsyncMock()
            >>> middleware = SSEAwareCompressMiddleware(app, minimum_size=1000)
            >>> middleware.minimum_size
            1000
        """
        self.app = app
        self.minimum_size = minimum_size
        self.gzip_level = gzip_level
        self.brotli_quality = brotli_quality
        self.zstd_level = zstd_level

        # Create the underlying compression middleware
        self.compress_app = CompressMiddleware(
            app,
            minimum_size=minimum_size,
            gzip_level=gzip_level,
            brotli_quality=brotli_quality,
            zstd_level=zstd_level,
        )

    def _is_mcp_path(self, path: str) -> bool:
        """Check if the path is an MCP endpoint.

        Args:
            path: The request path to check.

        Returns:
            True if the path is an MCP endpoint, False otherwise.
        """
        return path == "/mcp" or path == "/mcp/" or path.endswith("/mcp") or path.endswith("/mcp/")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """
        Process the ASGI request, skipping compression for SSE responses.

        When json_response_enabled=False (SSE mode), MCP paths bypass compression
        to prevent buffering of streaming responses.

        Args:
            scope: The ASGI connection scope.
            receive: The ASGI receive callable.
            send: The ASGI send callable.

        Example:
            >>> import asyncio
            >>> from unittest.mock import AsyncMock, patch
            >>> app = AsyncMock()
            >>> middleware = SSEAwareCompressMiddleware(app)
            >>> # Non-HTTP requests pass through to compress middleware
            >>> scope = {"type": "websocket"}
            >>> asyncio.run(middleware(scope, AsyncMock(), AsyncMock()))
        """
        if scope["type"] != "http":
            # Non-HTTP requests (websocket, lifespan) go through compression
            await self.compress_app(scope, receive, send)
            return

        path = scope.get("path", "")

        # When SSE mode is enabled (json_response_enabled=False), skip compression
        # for MCP paths to prevent buffering of streaming responses
        if not settings.json_response_enabled and self._is_mcp_path(path):
            # SSE mode for MCP - bypass compression entirely
            await self.app(scope, receive, send)
            return

        # For all other requests (including MCP in JSON mode), use compression
        await self.compress_app(scope, receive, send)
