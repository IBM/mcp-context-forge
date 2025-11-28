# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/password_expiry_middleware.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Password Expiration Middleware for enforcing password policies.

This middleware checks if authenticated users have expired passwords
and redirects them appropriately or returns error responses.

Examples:
    >>> from mcpgateway.middleware.password_expiry_middleware import PasswordExpiryMiddleware  # doctest: +SKIP
    >>> app.add_middleware(PasswordExpiryMiddleware)  # doctest: +SKIP
"""

# Standard
import logging
from typing import Callable

# Third-Party
from fastapi import HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# First-Party
from mcpgateway.db import EmailUser

logger = logging.getLogger(__name__)


class PasswordExpiryMiddleware(BaseHTTPMiddleware):
    """Middleware for enforcing password expiration policies.

    This middleware checks if authenticated users have expired passwords
    and returns appropriate responses. It runs after authentication middleware
    has populated request.state.user.

    Behavior:
        - If user has expired password: Return 403 with password_expired flag
        - If user has password expiring soon: Add warning headers
        - Otherwise: Continue normally

    Excluded paths:
        - /auth/email/change-password (allow password changes)
        - /auth/email/login (allow login to show expiry message)
        - /auth/email/logout (allow logout)
        - Static assets and docs
    """

    # Paths that should be excluded from password expiry checks
    EXCLUDED_PATHS = {
        "/auth/email/change-password",
        "/auth/email/login",
        "/auth/email/logout",
        "/docs",
        "/openapi.json",
        "/redoc",
        "/favicon.ico"
    }

    def _is_excluded_path(self, path: str) -> bool:
        """Check if path should be excluded from password expiry checks.
        
        Args:
            path: Request path to check
            
        Returns:
            bool: True if path should be excluded
        """
        # Exact matches
        if path in self.EXCLUDED_PATHS:
            return True
            
        # Prefix matches for static assets
        excluded_prefixes = ["/static/", "/assets/", "/_next/"]
        for prefix in excluded_prefixes:
            if path.startswith(prefix):
                return True
                
        return False

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and check password expiration status.
        
        Args:
            request: Incoming HTTP request
            call_next: Next middleware/handler in chain
            
        Returns:
            Response: HTTP response, possibly with password expiry handling
        """
        # Skip password expiry checks for excluded paths
        if self._is_excluded_path(request.url.path):
            return await call_next(request)

        # Check if user is authenticated (set by AuthContextMiddleware)
        user: EmailUser = getattr(request.state, "user", None)
        
        if not user:
            # No authenticated user, continue normally
            return await call_next(request)

        try:
            # Check if password is expired
            if user.is_password_expired():
                logger.warning(f"Password expired for user {user.email}")
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={
                        "detail": "Your password has expired. Please change your password to continue.",
                        "password_expired": True,
                        "days_expired": abs(user.days_until_password_expires() or 0)
                    },
                    headers={"X-Password-Expired": "true"}
                )

            # Check if password is expiring soon (within 14 days)
            if user.is_password_expiring_soon(notification_days=14):
                days_until_expiry = user.days_until_password_expires()
                logger.info(f"Password expiring soon for user {user.email} ({days_until_expiry} days)")
                
                # Continue with request but add warning headers
                response = await call_next(request)
                response.headers["X-Password-Expiring"] = "true"
                response.headers["X-Days-Until-Expiry"] = str(days_until_expiry)
                return response

        except Exception as e:
            logger.error(f"Error checking password expiration for {user.email}: {e}")
            # Don't block request on errors, just log and continue
            
        # Password is valid, continue normally
        return await call_next(request)