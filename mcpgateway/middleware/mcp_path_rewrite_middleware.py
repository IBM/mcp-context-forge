"""
mcp_path_rewrite_middleware.py

Middleware to rewrite MCP-related paths in HTTP requests.
"""

# First-Party
from mcpgateway.transports.streamablehttp_transport import (
    SessionManagerWrapper,
    streamable_http_auth,
)

# Initialize session manager for Streamable HTTP transport
streamable_http_session = SessionManagerWrapper()


class MCPPathRewriteMiddleware:
    """
    Supports requests like '/servers/<server_id>/mcp' by rewriting the path to '/mcp'.

    - Only rewrites paths ending with '/mcp' but not exactly '/mcp'.
    - Performs authentication before rewriting.
    - Passes rewritten requests to `streamable_http_session`.
    - All other requests are passed through without change.
    """

    def __init__(self, application):
        """
        Initialize the middleware with the ASGI application.

        Args:
            application (Callable): The next ASGI application in the middleware stack.
        """
        self.application = application

    async def __call__(self, scope, receive, send):
        """
        Intercept and potentially rewrite the incoming HTTP request path.

        Args:
            scope (dict): The ASGI connection scope.
            receive (Callable): Awaitable that yields events from the client.
            send (Callable): Awaitable used to send events to the client.

        Examples:
            >>> import asyncio
            >>> from unittest.mock import AsyncMock, patch
            >>>
            >>> # Test non-HTTP request passthrough
            >>> app_mock = AsyncMock()
            >>> middleware = MCPPathRewriteMiddleware(app_mock)
            >>> scope = {"type": "websocket", "path": "/ws"}
            >>> receive = AsyncMock()
            >>> send = AsyncMock()
            >>>
            >>> asyncio.run(middleware(scope, receive, send))
            >>> app_mock.assert_called_once_with(scope, receive, send)
            >>>
            >>> # Test path rewriting for /servers/123/mcp
            >>> app_mock.reset_mock()
            >>> scope = {"type": "http", "path": "/mcp"}
            >>> with patch('mcpgateway.transports.streamablehttp_transport.streamable_http_auth', return_value=True):
            ...     with patch.object(streamable_http_session, 'handle_streamable_http') as mock_handler:
            ...         asyncio.run(middleware(scope, receive, send))
            ...         scope["path"]
            '/mcp'
            >>>
            >>> # Test regular path (no rewrite)
            >>> scope = {"type": "http", "path": "/tools"}
            >>> with patch('mcpgateway.transports.streamablehttp_transport.streamable_http_auth', return_value=True):
            ...     asyncio.run(middleware(scope, receive, send))
            ...     scope["path"]
            '/tools'
        """

        # Only handle HTTP requests, HTTPS uses scope["type"] == "http" in ASGI
        if scope["type"] != "http":
            await self.application(scope, receive, send)
            return
        
        scope.setdefault("headers", [])

        # Call auth check first
        auth_ok = await streamable_http_auth(scope, receive, send)
        if not auth_ok:
            return

        original_path = scope.get("path", "")
        scope["modified_path"] = original_path
        if (original_path.endswith("/mcp") and original_path != "/mcp") or (original_path.endswith("/mcp/") and original_path != "/mcp/"):
            # Rewrite path so mounted app at /mcp handles it
            scope["path"] = "/mcp"
            await streamable_http_session.handle_streamable_http(scope, receive, send)
            return
        await self.application(scope, receive, send)
