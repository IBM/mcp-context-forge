# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/correlation_id.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: MCP Gateway Contributors

Correlation ID (Request ID) Middleware.

This middleware handles X-Correlation-ID HTTP headers and maps them to the internal
request_id used throughout the system for unified request tracing.

Key concept: HTTP X-Correlation-ID header → Internal request_id field (single ID for entire request flow)

The middleware automatically extracts or generates request IDs for every HTTP request,
stores them in context variables for async-safe propagation across services, and
injects them back into response headers for client-side correlation.

This enables end-to-end tracing: HTTP → Middleware → Services → Plugins → Logs (all with same request_id)
"""

# Standard
import logging
from typing import Callable

# Third-Party
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

# First-Party
from mcpgateway.config import settings
from mcpgateway.utils.correlation_id import (
    clear_correlation_id,
    extract_correlation_id_from_headers,
    generate_correlation_id,
    set_correlation_id,
)

logger = logging.getLogger(__name__)


class CorrelationIDMiddleware(BaseHTTPMiddleware):
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

    def __init__(self, app):
        """Initialize the correlation ID (request ID) middleware.

        Args:
            app: The FastAPI application instance
        """
        super().__init__(app)
        self.header_name = getattr(settings, "correlation_id_header", "X-Correlation-ID")
        self.preserve_incoming = getattr(settings, "correlation_id_preserve", True)
        self.add_to_response = getattr(settings, "correlation_id_response_header", True)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process the request and manage request ID (correlation ID) lifecycle.

        Extracts or generates a request ID, stores it in context variables for use throughout
        the request lifecycle (becomes request_id in logs, services, plugins), and injects
        it back into the X-Correlation-ID response header.

        Args:
            request: The incoming HTTP request
            call_next: The next middleware or route handler

        Returns:
            Response: The HTTP response with correlation ID header added
        """
        # Extract correlation ID from incoming request headers
        correlation_id = None
        if self.preserve_incoming:
            correlation_id = extract_correlation_id_from_headers(dict(request.headers), self.header_name)

        # Generate new correlation ID if none was provided
        if not correlation_id:
            correlation_id = generate_correlation_id()
            logger.debug(f"Generated new correlation ID: {correlation_id}")
        else:
            logger.debug(f"Using client-provided correlation ID: {correlation_id}")

        # Store correlation ID in context variable for this request
        # This makes it available to all downstream code (auth, services, plugins, logs)
        set_correlation_id(correlation_id)

        try:
            # Process the request
            response = await call_next(request)

            # Add correlation ID to response headers if enabled
            if self.add_to_response:
                response.headers[self.header_name] = correlation_id

            return response

        finally:
            # Clean up context after request completes
            # Note: ContextVar automatically cleans up, but explicit cleanup is good practice
            clear_correlation_id()
