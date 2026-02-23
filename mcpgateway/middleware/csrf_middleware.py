# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/csrf_middleware.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

CSRF Protection Middleware for ContextForge.

This middleware validates CSRF tokens on state-changing requests to prevent
Cross-Site Request Forgery attacks.
"""

# Standard
import logging
from typing import Callable
from urllib.parse import urlparse

# Third-Party
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# First-Party
from mcpgateway.config import settings
from mcpgateway.services.csrf_service import get_csrf_service

logger = logging.getLogger(__name__)

# Safe HTTP methods that don't require CSRF protection
SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


class CSRFMiddleware(BaseHTTPMiddleware):
    """Middleware for CSRF token validation on state-changing requests.

    This middleware protects against Cross-Site Request Forgery attacks by:
    1. Validating CSRF tokens on non-safe HTTP methods
    2. Checking Referer/Origin headers when configured
    3. Exempting specific paths and Bearer token requests

    Examples:
        >>> middleware = CSRFMiddleware(None)
        >>> isinstance(middleware, CSRFMiddleware)
        True
        >>> # Test safe methods
        >>> "GET" in SAFE_METHODS
        True
        >>> "POST" in SAFE_METHODS
        False
        >>> # Test path matching
        >>> path = "/health"
        >>> exempt_paths = ["/health", "/metrics"]
        >>> path in exempt_paths
        True
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and validate CSRF token if required.

        Args:
            request: Incoming HTTP request
            call_next: Next middleware/handler in chain

        Returns:
            HTTP response or 403 error if CSRF validation fails

        Examples:
            >>> # Test CSRF validation logic
            >>> method = "POST"
            >>> method not in SAFE_METHODS
            True
            >>> # Test Bearer token detection
            >>> auth_header = "Bearer abc123"
            >>> auth_header.startswith("Bearer ")
            True
            >>> # Test origin parsing
            >>> from urllib.parse import urlparse
            >>> origin = "https://example.com"
            >>> parsed = urlparse(origin)
            >>> parsed.scheme
            'https'
            >>> parsed.netloc
            'example.com'
        """
        # 1. Skip if CSRF protection is disabled
        if not settings.csrf_enabled:
            return await call_next(request)

        # 2. Skip safe methods (GET, HEAD, OPTIONS, TRACE)
        if request.method in SAFE_METHODS:
            return await call_next(request)

        # 3. Skip exempt paths
        if request.url.path in settings.csrf_exempt_paths:
            return await call_next(request)

        # 4. Skip Bearer token requests (not vulnerable to CSRF)
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            return await call_next(request)

        # 5. Extract CSRF token from header
        csrf_token = request.headers.get(settings.csrf_token_name)
        if not csrf_token:
            logger.warning(f"CSRF token missing for {request.method} {request.url.path}")
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "CSRF token missing",
                    "code": "CSRF_TOKEN_MISSING"
                }
            )

        # 6. Get user_id and session_id from authenticated session
        user_id = None
        session_id = None

        # Try to get user from request.state (set by AuthContextMiddleware)
        if hasattr(request.state, "user") and request.state.user:
            user = request.state.user
            # EmailUser uses 'email' as primary key
            user_id = user.email if hasattr(user, "email") else str(user.id) if hasattr(user, "id") else None

        # Try to get session_id from cookies or headers
        session_id = request.cookies.get("session_id") or request.headers.get("X-Session-ID")

        # If no user context, we can't validate the token
        if not user_id:
            logger.warning(f"CSRF validation failed: no user context for {request.method} {request.url.path}")
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "CSRF token invalid",
                    "code": "CSRF_TOKEN_INVALID"
                }
            )

        # 7. Validate CSRF token
        csrf_service = get_csrf_service()
        if not csrf_service.validate_csrf_token(csrf_token, user_id, session_id):
            logger.warning(f"CSRF token validation failed for user {user_id}")
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "CSRF token invalid",
                    "code": "CSRF_TOKEN_INVALID"
                }
            )

        # 8. Check Referer/Origin if configured
        if settings.csrf_check_referer:
            referer = request.headers.get("referer") or request.headers.get("origin")

            # If header is present, validate it
            if referer:
                # Parse the referer/origin
                parsed_referer = urlparse(referer)
                referer_origin = f"{parsed_referer.scheme}://{parsed_referer.netloc}"

                # Get allowed origins
                app_domain = str(settings.app_domain)
                parsed_app = urlparse(app_domain)
                app_origin = f"{parsed_app.scheme}://{parsed_app.netloc}"

                allowed_origins = {app_origin}
                allowed_origins.update(settings.csrf_trusted_origins)

                # Check if referer matches allowed origins
                if referer_origin not in allowed_origins:
                    logger.warning(
                        f"CSRF referer check failed: {referer_origin} not in allowed origins for {request.method} {request.url.path}"
                    )
                    return JSONResponse(
                        status_code=403,
                        content={
                            "detail": "CSRF token invalid",
                            "code": "CSRF_TOKEN_INVALID"
                        }
                    )

        # 9. All checks passed, continue with request
        return await call_next(request)
