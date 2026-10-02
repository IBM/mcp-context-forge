# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/ui_auth.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

UI authentication middleware for ContextForge: DocsAuthMiddleware (protects
/docs, /redoc, /openapi.json) and AdminAuthMiddleware (protects /admin/*).

Extracted from mcpgateway/main.py. Both are pure ASGI middleware;
main.py re-exports the classes so existing imports keep working.
"""

# Standard
import logging
from typing import Optional
import uuid

# Third-Party
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

# First-Party
from mcpgateway.auth import TokenValidationError, validate_token_user
from mcpgateway.common.validators import SecurityValidator
from mcpgateway.config import settings
from mcpgateway.db import SessionLocal
from mcpgateway.services.email_auth_service import EmailAuthService
from mcpgateway.services.permission_service import PermissionService
from mcpgateway.utils.orjson_response import ORJSONResponse
from mcpgateway.utils.paths import _normalize_scope_path, resolve_root_path
from mcpgateway.utils.verify_credentials import get_auth_header_value, is_proxy_auth_trust_active, require_docs_auth_override

logger = logging.getLogger(__name__)


class DocsAuthMiddleware:
    """
    Middleware to protect FastAPI's auto-generated documentation routes
    (/docs, /redoc, and /openapi.json) using Bearer token authentication.

    If a request to one of these paths is made without a valid token,
    the request is rejected with a 401 or 403 error.

    Note:
        OPTIONS requests are exempt from authentication to support CORS preflight
        as per RFC 7231 Section 4.3.7 (OPTIONS must not require authentication).

    Note:
        When DOCS_ALLOW_BASIC_AUTH is enabled, Basic Authentication
        is also accepted using BASIC_AUTH_USER and BASIC_AUTH_PASSWORD credentials.
    """

    def __init__(self, app):
        """Initialize the docs auth middleware.

        Args:
            app: The ASGI application to wrap.
        """
        self.app = app

    async def __call__(self, scope, receive, send):
        """Pure ASGI entry point — no BaseHTTPMiddleware task-group/body overhead.

        Args:
            scope (dict): The ASGI connection scope.
            receive (Callable): Awaitable that yields events from the client.
            send (Callable): Awaitable used to send events to the client.
        """
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        # Request(scope) is a thin wrapper (no body read).
        response = await self._check_docs_auth(Request(scope))
        if response is not None:
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)

    async def dispatch(self, request: Request, call_next):
        """
        Intercepts incoming requests to check if they are accessing protected documentation routes.
        If so, it requires a valid Bearer token; otherwise, it allows the request to proceed.

        BaseHTTPMiddleware-compatible entry point retained for tests and doctests.

        Args:
            request (Request): The incoming HTTP request.
            call_next (Callable): The function to call the next middleware or endpoint.

        Returns:
            Response: Either the standard route response or a 401/403 error response.

        Examples:
            >>> import asyncio
            >>> from unittest.mock import Mock, AsyncMock, patch
            >>> from fastapi import HTTPException
            >>> from fastapi.responses import JSONResponse
            >>>
            >>> # Test unprotected path - should pass through
            >>> middleware = DocsAuthMiddleware(None)
            >>> request = Mock()
            >>> request.url.path = "/api/tools"
            >>> request.scope = {"path": "/api/tools", "root_path": ""}
            >>> request.method = "GET"
            >>> request.headers.get.return_value = None
            >>> call_next = AsyncMock(return_value="response")
            >>>
            >>> result = asyncio.run(middleware.dispatch(request, call_next))
            >>> result
            'response'
            >>>
            >>> # Test that middleware checks protected paths
            >>> request.url.path = "/docs"
            >>> isinstance(middleware, DocsAuthMiddleware)
            True
        """
        response = await self._check_docs_auth(request)
        if response is not None:
            return response
        return await call_next(request)

    async def _check_docs_auth(self, request: Request) -> Optional[Response]:
        """Enforce Bearer-token authentication on protected documentation routes.

        Args:
            request (Request): The incoming HTTP request.

        Returns:
            A 401/403 error response when documentation authentication fails,
            or None to continue the request through the rest of the stack.
        """
        protected_paths = ["/docs", "/redoc", "/openapi.json"]

        # Allow OPTIONS requests to pass through for CORS preflight (RFC 7231)
        if request.method == "OPTIONS":
            return None

        # Get path from scope to handle root_path correctly
        scope_path = request.scope.get("path", request.url.path)
        root_path = resolve_root_path(request)
        scope_path = _normalize_scope_path(scope_path, root_path)

        is_protected = any(scope_path.startswith(p) for p in protected_paths)

        if is_protected:
            try:
                token = get_auth_header_value(request.headers)
                cookie_token = request.cookies.get("jwt_token")

                # Use dedicated docs authentication that bypasses global auth settings
                await require_docs_auth_override(token, cookie_token)
            except HTTPException as e:
                return ORJSONResponse(status_code=e.status_code, content={"detail": e.detail}, headers=e.headers if e.headers else None)

        # Proceed to next middleware or route
        return None


class AdminAuthMiddleware:
    """
    Middleware to protect Admin UI routes (/admin/*) requiring admin privileges.

    Exempts login-related paths and static assets:
    - /v1/admin/login - login page
    - /v1/admin/logout - logout action
    - /v1/admin/forgot-password - self-service password reset request page
    - /v1/admin/reset-password/* - self-service password reset completion page
    - /admin/static/* - static assets

    All other /admin/* routes require the user to be authenticated AND be an admin.
    Non-admin authenticated users receive a 403 Forbidden response.

    Note: This middleware respects the auth_required setting. When auth_required=False
    (typically in test environments), the middleware allows requests to pass through
    and relies on endpoint-level authentication which can be mocked in tests.
    """

    def __init__(self, app):
        """Initialize the admin auth middleware.

        Args:
            app: The ASGI application to wrap.
        """
        self.app = app

    # Public paths under /admin that do not require prior authentication.
    EXEMPT_PATHS = [
        "/v1/admin/login",
        "/v1/admin/logout",
        "/v1/admin/forgot-password",
        "/v1/admin/reset-password",
        "/admin/static",  # Legacy path
        "/v1/admin/static",  # Versioned path
    ]

    @staticmethod
    def _strip_v1(path: str) -> str:
        """Strip /v1 prefix from path for normalization.

        Args:
            path: Path to normalize.

        Returns:
            Path with /v1 prefix removed if present.

        Examples:
            >>> AdminAuthMiddleware._strip_v1("/v1/admin/login")
            '/admin/login'
            >>> AdminAuthMiddleware._strip_v1("/admin/login")
            '/admin/login'
        """
        return path[len("/v1") :] if path.startswith("/v1/") else path

    @staticmethod
    def _error_response(request: Request, root_path: str, status_code: int, detail: str, error_param: str = None):
        """Return appropriate error response based on request Accept header.

        Args:
            request: The incoming HTTP request.
            root_path: The root path prefix for the application.
            status_code: HTTP status code for JSON responses.
            detail: Error message detail.
            error_param: Optional error parameter for login redirect URL.

        Returns:
            Response with HX-Redirect for HTMX requests, RedirectResponse for HTML requests, ORJSONResponse for API requests.
        """
        accept_header = request.headers.get("accept", "")
        is_htmx = request.headers.get("hx-request") == "true"
        if "text/html" in accept_header or is_htmx:
            login_url = f"{root_path}/admin/login" if root_path else "/admin/login"
            if error_param:
                login_url = f"{login_url}?error={error_param}"
            if is_htmx:
                return Response(status_code=200, headers={"HX-Redirect": login_url})
            return RedirectResponse(url=login_url, status_code=302)
        return ORJSONResponse(status_code=status_code, content={"detail": detail})

    @staticmethod
    def _auth_error_param(detail: str) -> Optional[str]:
        """Map TokenValidationError detail to browser redirect error param."""
        normalized = (detail or "").lower()
        if "revoked" in normalized:
            return "token_revoked"
        if "disabled" in normalized:
            return "account_disabled"
        if "expired" in normalized or "idle timeout" in normalized:
            return "session_expired"
        return None

    async def __call__(self, scope, receive, send):
        """Pure ASGI entry point — no BaseHTTPMiddleware task-group/body overhead.

        Args:
            scope (dict): The ASGI connection scope.
            receive (Callable): Awaitable that yields events from the client.
            send (Callable): Awaitable used to send events to the client.
        """
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        # Request(scope) is a thin wrapper (no body read); request.state writes
        # land in scope["state"] and stay visible to downstream handlers.
        response = await self._check_admin_auth(Request(scope))
        if response is not None:
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)

    async def dispatch(self, request: Request, call_next):
        """
        Check admin privileges for admin routes.

        BaseHTTPMiddleware-compatible entry point retained for tests and doctests.

        Args:
            request (Request): The incoming HTTP request.
            call_next (Callable): The function to call the next middleware or endpoint.

        Returns:
            Response: Either the standard route response or a 401/403 error response.
        """
        response = await self._check_admin_auth(request)
        if response is not None:
            return response
        return await call_next(request)

    async def _check_admin_auth(self, request: Request) -> Optional[Response]:  # pylint: disable=too-many-return-statements
        """Verify admin status for protected admin routes.

        Args:
            request (Request): The incoming HTTP request.

        Returns:
            An error or redirect response when the request is denied, or None
            to continue the request through the rest of the stack.
        """
        # Skip admin auth check if auth is not required (e.g., test environments)
        # This allows tests to mock authentication at the dependency level
        if not settings.auth_required:
            return None

        # Get path from scope to handle root_path correctly
        scope_path = request.scope.get("path", request.url.path)
        root_path = resolve_root_path(request)
        scope_path = _normalize_scope_path(scope_path, root_path)

        # Allow OPTIONS requests for CORS preflight (RFC 7231)
        if request.method == "OPTIONS":
            return None

        # Check if this is an admin route (versioned /v1/admin/* or legacy /admin/*)
        is_admin_route = scope_path.startswith("/admin") or scope_path.startswith("/v1/admin")

        if not is_admin_route:
            return None

        # Normalize to unversioned path for exempt/permission checks so that
        # both direct (/v1/admin/login) and proxy-prefixed (/qa/gateway/admin/login)
        # paths are handled uniformly.
        check_path = self._strip_v1(scope_path)

        # Check if path is exempt (login, logout, static)
        is_exempt = any(check_path.startswith(self._strip_v1(p)) for p in self.EXEMPT_PATHS)
        if is_exempt:
            return None

        # For protected admin routes, verify admin status
        try:
            raw_token = None
            auth_user_email = None
            auth_user_is_admin = False

            auth_header = get_auth_header_value(request.headers)
            cookie_token = request.cookies.get("jwt_token") or request.cookies.get("access_token")

            # Preserve existing precedence: cookie first, then Authorization bearer.
            if cookie_token:
                raw_token = cookie_token
            elif auth_header:
                scheme, _, credentials_value = auth_header.partition(" ")
                if scheme.lower() == "bearer" and credentials_value:
                    raw_token = credentials_value.strip() or None

            if raw_token:
                try:
                    auth_user = await validate_token_user(request, raw_token)
                except TokenValidationError as exc:
                    logger.warning(
                        "Admin auth token validation failed: %s",
                        SecurityValidator.sanitize_log_message(str(exc.detail)),
                    )
                    return self._error_response(
                        request,
                        root_path,
                        exc.status_code,
                        exc.detail,
                        self._auth_error_param(exc.detail),
                    )

                auth_user_email = auth_user.email
                auth_user_is_admin = bool(auth_user.is_admin)

            elif is_proxy_auth_trust_active(settings):
                proxy_user = request.headers.get(settings.proxy_user_header)
                if proxy_user:
                    request.state.auth_method = "proxy"
                    auth_user_email = proxy_user

                    # Preserve existing proxy behavior: DB active/admin check,
                    # with platform-admin bootstrap when REQUIRE_USER_IN_DB=false.
                    with SessionLocal() as db:
                        auth_service = EmailAuthService(db)
                        proxy_db_user = await auth_service.get_user_by_email(proxy_user)

                        if not proxy_db_user:
                            platform_admin_email = getattr(settings, "platform_admin_email", "admin@example.com")
                            if not settings.require_user_in_db and proxy_user == platform_admin_email:
                                logger.info(
                                    "Platform admin bootstrap authentication for %s",
                                    SecurityValidator.sanitize_log_message(str(proxy_user)),
                                )
                                auth_user_is_admin = True
                            else:
                                return self._error_response(request, root_path, 401, "User not found")
                        else:
                            if not proxy_db_user.is_active:
                                logger.warning(
                                    "Admin access denied for disabled user: %s",
                                    SecurityValidator.sanitize_log_message(str(proxy_user)),
                                )
                                return self._error_response(request, root_path, 403, "Account is disabled", "account_disabled")
                            auth_user_is_admin = bool(proxy_db_user.is_admin)

            if not auth_user_email:
                return self._error_response(request, root_path, 401, "Authentication required")

            token_teams = getattr(request.state, "token_teams", None)

            # Preserve public-only denial invariant.
            if token_teams is not None and len(token_teams) == 0:
                logger.warning(
                    "Admin access denied for public-only token: %s",
                    SecurityValidator.sanitize_log_message(str(auth_user_email)),
                )
                return self._error_response(
                    request,
                    root_path,
                    403,
                    "Admin privileges required",
                    "admin_required",
                )

            # Validate optional team_id against token-visible teams.
            request_team_id = request.query_params.get("team_id")
            if request_team_id:
                try:
                    request_team_id = uuid.UUID(request_team_id).hex
                except (ValueError, AttributeError):
                    pass

            validated_team_id = request_team_id if token_teams and request_team_id and request_team_id in token_teams else None

            # validate_token_user already returned DB-authoritative is_admin,
            # including platform-admin bootstrap.
            if not auth_user_is_admin:
                with SessionLocal() as db:
                    permission_service = PermissionService(db)
                    has_admin_access = await permission_service.has_admin_permission(
                        auth_user_email,
                        team_id=validated_team_id,
                        token_teams=token_teams,
                    )

                if not has_admin_access:
                    logger.warning(
                        "Admin access denied for user without admin permissions: %s",
                        SecurityValidator.sanitize_log_message(str(auth_user_email)),
                    )
                    return self._error_response(
                        request,
                        root_path,
                        403,
                        "Admin privileges required",
                        "admin_required",
                    )

        except HTTPException as exc:
            return self._error_response(request, root_path, exc.status_code, exc.detail)
        except Exception as exc:
            logger.error("Admin auth middleware error: %s", exc)
            return ORJSONResponse(status_code=500, content={"detail": "Authentication error"})

        return None
