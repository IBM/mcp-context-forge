# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/auth_middleware.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Authentication Middleware for early user context extraction.

This middleware extracts user information from JWT tokens early in the request
lifecycle and stores it in request.state.user for use by other middleware
(like ObservabilityMiddleware) and route handlers.

Examples:
    >>> from mcpgateway.middleware.auth_middleware import AuthContextMiddleware  # doctest: +SKIP
    >>> app.add_middleware(AuthContextMiddleware)  # doctest: +SKIP
"""

# Standard
import logging
from typing import Callable

# Third-Party
from fastapi.security import HTTPAuthorizationCredentials
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# First-Party
from mcpgateway.auth import get_current_user
from mcpgateway.config import settings
from mcpgateway.db import SessionLocal
from mcpgateway.services.security_logger import get_security_logger

logger = logging.getLogger(__name__)
security_logger = get_security_logger()


def _should_log_auth_success() -> bool:
    """Check if successful authentication should be logged based on settings.

    Returns:
        True if security_logging_level is "all", False otherwise.
    """
    return settings.security_logging_level == "all"


def _should_log_auth_failure() -> bool:
    """Check if failed authentication should be logged based on settings.

    Returns:
        True if security_logging_level is "all" or "failures_only", False for "high_severity".
    """
    # Log failures for "all" and "failures_only" levels, not for "high_severity"
    return settings.security_logging_level in ("all", "failures_only")


class AuthContextMiddleware(BaseHTTPMiddleware):
    """Middleware for extracting user authentication context early in request lifecycle.

    This middleware attempts to authenticate requests using JWT tokens from cookies
    or Authorization headers, and stores the user information in request.state.user
    for downstream middleware and handlers to use.

    Unlike route-level authentication dependencies, this runs for ALL requests,
    allowing middleware like ObservabilityMiddleware to access user context.

    Note:
        Authentication failures are silent - requests continue as unauthenticated.
        Route-level dependencies should still enforce authentication requirements.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and populate user context if authenticated.

        Args:
            request: Incoming HTTP request
            call_next: Next middleware/handler in chain

        Returns:
            HTTP response
        """
        # Skip for health checks and static files
        if request.url.path in ["/health", "/healthz", "/ready", "/metrics"] or request.url.path.startswith("/static/"):
            return await call_next(request)

        # Try to extract token from multiple sources
        token = None

        # 1. Try manual cookie reading
        if request.cookies:
            token = request.cookies.get("jwt_token") or request.cookies.get("access_token")

        # 2. Try Authorization header
        if not token:
            auth_header = request.headers.get("authorization")
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header.replace("Bearer ", "")

        # If no token found, continue without user context
        if not token:
            return await call_next(request)

        # Try to authenticate and populate user context
        db = None
        try:
            db = SessionLocal()
            credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
            # get_current_user now uses fresh DB sessions internally, no session needed here
            user = await get_current_user(credentials, request=request)

            # Note: EmailUser uses 'email' as primary key, not 'id'
            # User is already detached (created with fresh session that was closed)
            user_email = user.email
            user_id = user_email  # For EmailUser, email IS the ID

            # Store user in request state for downstream use
            request.state.user = user
            logger.info(f"✓ Authenticated user: {user_email if user_email else user_id}")

            # Log successful authentication (only if logging level is "all")
            if _should_log_auth_success():
                security_logger.log_authentication_attempt(
                    user_id=user_id,
                    user_email=user_email,
                    auth_method="bearer_token",
                    success=True,
                    client_ip=request.client.host if request.client else "unknown",
                    user_agent=request.headers.get("user-agent"),
                    db=db,
                )

        except Exception as e:
            # Silently fail - let route handlers enforce auth if needed
            logger.info(f"✗ Auth context extraction failed (continuing as anonymous): {e}")

            # Log failed authentication attempt (based on logging level)
            if _should_log_auth_failure():
                security_logger.log_authentication_attempt(
                    user_id="unknown",
                    user_email=None,
                    auth_method="bearer_token",
                    success=False,
                    client_ip=request.client.host if request.client else "unknown",
                    user_agent=request.headers.get("user-agent"),
                    failure_reason=str(e),
                    db=db if db else None,
                )

        finally:
            # Always close database session
            if db:
                try:
                    db.commit()  # End transaction cleanly (security_logger handles its own commits)
                    db.close()
                except Exception as close_error:
                    logger.debug(f"Failed to close database session: {close_error}")

        # Continue with request
        return await call_next(request)
