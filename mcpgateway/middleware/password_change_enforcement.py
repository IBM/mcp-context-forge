# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/password_change_enforcement.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Password Change Enforcement Middleware.

This middleware enforces mandatory password changes for users with the
password_change_required flag set. It prevents bypassing the password
change requirement by directly navigating to admin routes.

Security Design:
- Only enforces on /admin/* routes (scoped to admin UI)
- Exempts password change and logout endpoints
- Only applies to session tokens (not API tokens)
- Runs after authentication (has access to user context)

Implemented as pure ASGI middleware (no BaseHTTPMiddleware): the enforcement
logic only needs the request path and scope state, and the redirect deny is
sent directly, so pass-through responses stream unbuffered.
"""

# Standard
import logging
from typing import Callable, Optional

# Third-Party
from fastapi import Request
from fastapi.responses import RedirectResponse
from starlette.types import ASGIApp

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import EmailUser

logger = logging.getLogger(__name__)


class PasswordChangeEnforcementMiddleware:
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
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        """Process request and enforce password change if required.

        Pure ASGI entry point — no BaseHTTPMiddleware task-group/body overhead.

        Args:
            scope: ASGI connection scope.
            receive: ASGI receive callable.
            send: ASGI send callable.
        """
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        # Skip enforcement if feature is disabled
        if not settings.password_change_enforcement_enabled:
            await self.app(scope, receive, send)
            return

        # Request(scope) is a thin wrapper (no body read); request.state reads
        # scope["state"], where AuthContextMiddleware populated the user.
        request = Request(scope)

        # Only enforce on /admin/* routes (scoped to admin UI)
        if not request.url.path.startswith("/admin"):
            await self.app(scope, receive, send)
            return

        # Skip exempt paths (password change page, login, logout)
        if request.url.path in self.EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return

        # Get user from request state (set by get_current_user dependency)
        user: Optional[EmailUser] = getattr(request.state, "user", None)
        if not user:
            # No authenticated user - let the request proceed
            # (authentication will be handled by route dependencies)
            await self.app(scope, receive, send)
            return

        # Only enforce for session tokens (not API tokens)
        # API tokens are used for programmatic access and should not be blocked
        auth_method = getattr(request.state, "auth_method", "jwt")
        if auth_method == "api_token":
            logger.debug(
                "Skipping password change enforcement for API token (user: %s)",
                getattr(user, "email", "unknown"),
            )
            await self.app(scope, receive, send)
            return

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
            response = RedirectResponse(
                url="/admin/change-password-required",
                status_code=303,
            )
            await response(scope, receive, send)
            return

        # Password change not required - proceed with request
        await self.app(scope, receive, send)
