# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/correlation_id.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Correlation ID (Request ID) Middleware.

This middleware handles X-Correlation-ID HTTP headers and maps them to the internal
request_id used throughout the system for unified request tracing.

Key concept: HTTP X-Correlation-ID header → Internal request_id field (single ID for entire request flow)

The middleware automatically extracts or generates request IDs for every HTTP request,
stores them in context variables for async-safe propagation across services, and
injects them back into response headers for client-side correlation.

This enables end-to-end tracing: HTTP → Middleware → Services → Plugins → Logs (all with same request_id)

Implemented as pure ASGI middleware (no BaseHTTPMiddleware): the correlation ID only
needs the request headers and the response-start message, so responses stream
unbuffered without BaseHTTPMiddleware's per-request task-group overhead.
"""

# Standard
import logging

# Third-Party
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# First-Party
from mcpgateway.config import settings
from mcpgateway.utils.correlation_id import (
    clear_correlation_id,
    extract_correlation_id_from_headers,
    generate_correlation_id,
    set_correlation_id,
)

logger = logging.getLogger(__name__)


class CorrelationIDMiddleware:
    """Middleware for automatic request ID (correlation ID) handling.

    This middleware:
    1. Extracts request ID from X-Correlation-ID header in incoming requests
    2. Generates a new UUID if no correlation ID is present
    3. Stores the ID in context variables for the request lifecycle (used as request_id throughout system)
    4. Injects the request ID into X-Correlation-ID response header
    5. Cleans up context after request completion

    The request ID extracted/generated here becomes the unified request_id used in:
    - All log entries (request_id field)
    - GlobalContext.request_id (when plugins execute)
    - Service method calls for tracing
    - Database queries for request tracking

    Configuration is controlled via settings:
    - correlation_id_enabled: Enable/disable the middleware
    - correlation_id_header: Header name to use (default: X-Correlation-ID)
    - correlation_id_preserve: Whether to preserve incoming IDs (default: True)
    - correlation_id_response_header: Whether to add ID to responses (default: True)
    """

    def __init__(self, app: ASGIApp):
        """Initialize the correlation ID (request ID) middleware.

        Args:
            app: The ASGI application instance
        """
        self.app = app
        self.header_name = getattr(settings, "correlation_id_header", "X-Correlation-ID")
        self.preserve_incoming = getattr(settings, "correlation_id_preserve", True)
        self.add_to_response = getattr(settings, "correlation_id_response_header", True)

    def _resolve_correlation_id(self, scope: Scope) -> str:
        """Extract the incoming correlation ID from scope headers or generate one.

        Args:
            scope: The ASGI connection scope.

        Returns:
            The correlation ID to use for this request.
        """
        # Extract correlation ID from incoming request headers
        correlation_id = None
        if self.preserve_incoming:
            headers = {}
            for item in scope.get("headers") or []:
                if not isinstance(item, (tuple, list)) or len(item) != 2:
                    continue
                key, value = item
                if isinstance(key, (bytes, bytearray)) and isinstance(value, (bytes, bytearray)):
                    headers[key.decode("latin-1").lower()] = value.decode("latin-1")
            correlation_id = extract_correlation_id_from_headers(headers, self.header_name)

        # Generate new correlation ID if none was provided
        if not correlation_id:
            correlation_id = generate_correlation_id()
            logger.debug(f"Generated new correlation ID: {correlation_id}")
        else:
            logger.debug(f"Using client-provided correlation ID: {correlation_id}")

        return correlation_id

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Pure ASGI entry point — no BaseHTTPMiddleware task-group/body overhead.

        Resolves the correlation ID, stores it in the context variable for the
        request lifecycle, and injects it into the response-start headers.

        Args:
            scope: ASGI connection scope.
            receive: ASGI receive callable.
            send: ASGI send callable.
        """
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        correlation_id = self._resolve_correlation_id(scope)

        # Store correlation ID in context variable for this request
        # This makes it available to all downstream code (auth, services, plugins, logs)
        set_correlation_id(correlation_id)

        try:
            if not self.add_to_response:
                await self.app(scope, receive, send)
                return

            header_name = self.header_name.lower().encode("latin-1")
            header_value = correlation_id.encode("latin-1")

            async def send_with_correlation_id(message: Message) -> None:
                """Inject the correlation ID header into the response start, then forward."""
                if message.get("type") == "http.response.start":
                    headers = message.setdefault("headers", [])
                    # Starlette "set" semantics: replace any existing header of the same name
                    headers[:] = [(k, v) for k, v in headers if k.lower() != header_name]
                    headers.append((header_name, header_value))
                await send(message)

            await self.app(scope, receive, send_with_correlation_id)
        finally:
            # Clean up context after request completes
            # Note: ContextVar automatically cleans up, but explicit cleanup is good practice
            clear_correlation_id()
