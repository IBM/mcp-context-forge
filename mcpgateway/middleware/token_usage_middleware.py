# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/token_usage_middleware.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Token Usage Logging Middleware.

This middleware logs API token usage for analytics and security monitoring.
It records each request made with an API token, including endpoint, method,
response time, and status code.

Examples:
    >>> from mcpgateway.middleware.token_usage_middleware import TokenUsageMiddleware  # doctest: +SKIP
    >>> app.add_middleware(TokenUsageMiddleware)  # doctest: +SKIP
"""

# Standard
import logging
import time
from typing import Callable

# Third-Party
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# First-Party
from mcpgateway.db import SessionLocal
from mcpgateway.middleware.path_filter import should_skip_auth_context
from mcpgateway.services.token_catalog_service import TokenCatalogService
from mcpgateway.utils.verify_credentials import verify_jwt_token_cached

logger = logging.getLogger(__name__)


class TokenUsageMiddleware(BaseHTTPMiddleware):
    """Middleware for logging API token usage.

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
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and log token usage if applicable.

        Args:
            request: Incoming HTTP request
            call_next: Next middleware/handler in chain

        Returns:
            HTTP response
        """
        # Skip for health checks and static files
        if should_skip_auth_context(request.url.path):
            return await call_next(request)

        # Record start time
        start_time = time.time()

        # Process request
        response = await call_next(request)

        # Calculate response time
        response_time_ms = int((time.time() - start_time) * 1000)

        # Only log if this was an API token request
        auth_method = getattr(request.state, "auth_method", None)
        if auth_method != "api_token":
            return response

        # Extract token information from request.state (populated during auth)
        # If not available, try to decode token
        jti = getattr(request.state, "jti", None)
        user_email = None
        
        # Try to get user email from request.state.user first
        if hasattr(request.state, "user") and request.state.user is not None:
            user_email = getattr(request.state.user, "email", None)
        
        # If we don't have JTI or email, we need to decode the token
        if not jti or not user_email:
            try:
                # Get token from Authorization header
                auth_header = request.headers.get("authorization")
                if not auth_header or not auth_header.startswith("Bearer "):
                    return response

                token = auth_header.replace("Bearer ", "")

                # Decode token to get JTI and user email
                try:
                    payload = await verify_jwt_token_cached(token, request)
                    jti = jti or payload.get("jti")
                    user_email = user_email or payload.get("sub") or payload.get("email")
                except Exception as decode_error:
                    logger.debug(f"Failed to decode token for usage logging: {decode_error}")
                    return response
            except Exception as e:
                logger.debug(f"Error extracting token information: {e}")
                return response

        if not jti or not user_email:
            logger.debug("Missing JTI or user_email for token usage logging")
            return response

        # Log token usage
        try:
            db = SessionLocal()
            try:
                token_service = TokenCatalogService(db)
                await token_service.log_token_usage(
                    jti=jti,
                    user_email=user_email,
                    endpoint=str(request.url.path),
                    method=request.method,
                    ip_address=request.client.host if request.client else None,
                    user_agent=request.headers.get("user-agent"),
                    status_code=response.status_code,
                    response_time_ms=response_time_ms,
                    blocked=False,
                    block_reason=None,
                )
                db.commit()
            except Exception as e:
                logger.debug(f"Failed to log token usage: {e}")
                db.rollback()
            finally:
                try:
                    db.close()
                except Exception as close_error:
                    logger.debug(f"Failed to close database session: {close_error}")
        except Exception as e:
            logger.debug(f"Error in token usage middleware: {e}")

        return response
