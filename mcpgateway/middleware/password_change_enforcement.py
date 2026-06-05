# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/password_change_enforcement.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Password Change Enforcement Middleware.

This middleware enforces mandatory password changes for users with the
password_change_required flag set. It prevents bypassing the password
change requirement by directly navigating to admin routes.

Security Design:
- Only enforces on /admin/* routes (scoped to admin UI)
- Exempts password change and logout endpoints
- Only applies to session tokens (not API tokens)
- Runs after authentication (has access to user context)
"""

# Standard
import logging
from typing import Optional

# Third-Party
from fastapi import Request
from fastapi.responses import RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import EmailUser

logger = logging.getLogger(__name__)


class PasswordChangeEnforcementMiddleware(BaseHTTPMiddleware):
    """Middleware to enforce mandatory password changes.

    This middleware checks if an authenticated user has the password_change_required
    flag set and redirects them to the password change page if they attempt to
    access any admin route (except exempt paths).

    The middleware only enforces password changes for:
    - Admin UI routes (/admin/*)
    - Session-based authentication (not API tokens)
    - When password_change_enforcement_enabled is True

    Exempt paths (always allowed):
    - /admin/change-password-required (the password change page itself)
    - /admin/login (login page)
    - /auth/email/change-password (password change API endpoint)
    - /auth/email/logout (logout endpoint)
    """

    # Paths that are always allowed even when password change is required
    EXEMPT_PATHS = frozenset(
        {
            "/admin/change-password-required",
            "/admin/login",
            "/auth/email/change-password",
            "/auth/email/logout",
        }
    )

    def __init__(self, app: ASGIApp):
        """Initialize the password change enforcement middleware.

        Args:
            app: The ASGI application
        """
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        """Process request and enforce password change if required.

        Args:
            request: The incoming request
            call_next: The next middleware/handler in the chain

        Returns:
            The response from the application or a redirect to password change page
        """
        # Skip enforcement if feature is disabled
        if not settings.password_change_enforcement_enabled:
            return await call_next(request)

        # Only enforce on /admin/* routes (scoped to admin UI)
        if not request.url.path.startswith("/admin"):
            return await call_next(request)

        # Skip exempt paths (password change page, login, logout)
        if request.url.path in self.EXEMPT_PATHS:
            return await call_next(request)

        # Get user from request state (set by get_current_user dependency)
        user: Optional[EmailUser] = getattr(request.state, "user", None)
        if not user:
            # No authenticated user - let the request proceed
            # (authentication will be handled by route dependencies)
            return await call_next(request)

        # Only enforce for session tokens (not API tokens)
        # API tokens are used for programmatic access and should not be blocked
        auth_method = getattr(request.state, "auth_method", "jwt")
        if auth_method == "api_token":
            logger.debug(
                "Skipping password change enforcement for API token (user: %s)",
                getattr(user, "email", "unknown"),
            )
            return await call_next(request)

        # Check if password change is required
        password_change_required = getattr(user, "password_change_required", False)
        if password_change_required:
            user_email = getattr(user, "email", "unknown")
            logger.info(
                "Blocking access to %s for user %s: password change required",
                request.url.path,
                user_email,
            )

            # Redirect to password change page
            # Use 303 See Other to ensure GET request after POST
            return RedirectResponse(
                url="/admin/change-password-required",
                status_code=303,
            )

        # Password change not required - proceed with request
        return await call_next(request)
