# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/token_usage_middleware.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Token Usage Logging Middleware.

This middleware logs API token usage for analytics and security monitoring.
It records each request made with an API token, including endpoint, method,
response time, and status code.

Note: Implemented as raw ASGI middleware (not BaseHTTPMiddleware) to avoid
response body buffering issues with streaming responses.

Examples:
    >>> from mcpgateway.middleware.token_usage_middleware import TokenUsageMiddleware  # doctest: +SKIP
    >>> app.add_middleware(TokenUsageMiddleware)  # doctest: +SKIP
"""

# Standard
import logging
import time

# Third-Party
from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

# First-Party
from mcpgateway.db import fresh_db_session
from mcpgateway.middleware.path_filter import should_skip_auth_context
from mcpgateway.services.token_catalog_service import TokenCatalogService
from mcpgateway.utils.verify_credentials import verify_jwt_token_cached

logger = logging.getLogger(__name__)


class TokenUsageMiddleware:
    """Raw ASGI middleware for logging API token usage.

    This middleware tracks when API tokens are used, recording details like:
    - Endpoint accessed
    - HTTP method
    - Response status code
    - Response time
    - Client IP and user agent

    This data is used for security auditing, usage analytics, and detecting
    anomalous token usage patterns.

    Note:
        Only logs usage for requests authenticated with API tokens (identified
        by request.state.auth_method == "api_token").

        Implemented as raw ASGI middleware to avoid BaseHTTPMiddleware issues:
        - BaseHTTPMiddleware buffers entire response bodies (problematic for streaming)
        - Raw ASGI middleware streams responses efficiently
    """

    def __init__(self, app: ASGIApp) -> None:
        """Initialize middleware.

        Args:
            app: ASGI application to wrap
        """
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Process ASGI request.

        Args:
            scope: ASGI scope dict
            receive: Receive callable
            send: Send callable
        """
        # Only process HTTP requests
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Skip health checks and static files
        path = scope.get("path", "")
        if should_skip_auth_context(path):
            await self.app(scope, receive, send)
            return

        # Record start time
        start_time = time.time()

        # Capture response status
        status_code = 200  # Default

        async def send_wrapper(message: dict) -> None:
            """Wrap send to capture response status.

            Args:
                message: ASGI message dict containing response data
            """
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        # Process request
        await self.app(scope, receive, send_wrapper)

        # Calculate response time
        response_time_ms = round((time.time() - start_time) * 1000)

        # Only log if this was an API token request
        state = scope.get("state", {})
        auth_method = state.get("auth_method") if state else None

        if auth_method != "api_token":
            return

        # Extract token information from scope state
        jti = state.get("jti") if state else None
        user = state.get("user") if state else None
        user_email = getattr(user, "email", None) if user else None

        # If we don't have JTI or email, try to decode the token
        if not jti or not user_email:
            try:
                # Get token from Authorization header
                headers = Headers(scope=scope)
                auth_header = headers.get("authorization")
                if not auth_header or not auth_header.startswith("Bearer "):
                    return

                token = auth_header.replace("Bearer ", "")

                # Decode token to get JTI and user email
                # Note: We need to create a minimal Request-like object
                request = Request(scope, receive)
                try:
                    payload = await verify_jwt_token_cached(token, request)
                    jti = jti or payload.get("jti")
                    user_email = user_email or payload.get("sub") or payload.get("email")
                except Exception as decode_error:
                    logger.debug(f"Failed to decode token for usage logging: {decode_error}")
                    return
            except Exception as e:
                logger.debug(f"Error extracting token information: {e}")
                return

        if not jti or not user_email:
            logger.debug("Missing JTI or user_email for token usage logging")
            return

        # Log token usage
        try:
            with fresh_db_session() as db:
                token_service = TokenCatalogService(db)
                # Get client IP
                client = scope.get("client")
                ip_address = client[0] if client else None

                # Get user agent
                headers = Headers(scope=scope)
                user_agent = headers.get("user-agent")

                # Log usage
                await token_service.log_token_usage(
                    jti=jti,
                    user_email=user_email,
                    endpoint=path,
                    method=scope.get("method", "GET"),
                    ip_address=ip_address,
                    user_agent=user_agent,
                    status_code=status_code,
                    response_time_ms=response_time_ms,
                    blocked=False,
                    block_reason=None,
                )
        except Exception as e:
            logger.debug(f"Failed to log token usage: {e}")
