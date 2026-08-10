# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/csrf_middleware.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

CSRF Protection Middleware for ContextForge.

This middleware validates CSRF tokens on state-changing requests to prevent
Cross-Site Request Forgery attacks.

Implemented as pure ASGI middleware (no BaseHTTPMiddleware): validation only
needs request headers, cookies, and scope state — the body is never consumed,
so there is nothing to replay downstream, and pass-through responses stream
unbuffered.
"""

# Standard
import hmac
import logging
from typing import Any, Callable, Optional
from urllib.parse import urlparse

# Third-Party
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# First-Party
from mcpgateway.auth_context import get_jwt_user_email_from_payload
from mcpgateway.config import settings
from mcpgateway.services.csrf_service import get_csrf_service
from mcpgateway.utils.verify_credentials import get_auth_header_value, is_proxy_auth_trust_active, verify_jwt_token_cached

logger = logging.getLogger(__name__)

# Safe HTTP methods that don't require CSRF protection
SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


def _extract_bearer_token(auth_header: str) -> str | None:
    """Return a bearer token from an auth header, accepting scheme case-insensitively."""
    scheme, separator, token = auth_header.partition(" ")
    if separator and scheme.lower() == "bearer" and token.strip():
        return token.strip()
    return None


class CSRFMiddleware:
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

    def __init__(self, app: Any) -> None:
        """Initialize the CSRF middleware.

        Args:
            app: The ASGI application to wrap.
        """
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        """Pure ASGI entry point — no BaseHTTPMiddleware task-group/body overhead.

        Args:
            scope: ASGI connection scope.
            receive: ASGI receive callable.
            send: ASGI send callable.
        """
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        # Request(scope) is a thin wrapper (no body read); request.state reads
        # scope["state"], populated by upstream middleware as usual.
        rejection = await self._validate_request(Request(scope))
        if rejection is not None:
            await rejection(scope, receive, send)
            return

        await self.app(scope, receive, send)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """BaseHTTPMiddleware-compatible entry point retained for tests and doctests.

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
        rejection = await self._validate_request(request)
        if rejection is not None:
            return rejection
        return await call_next(request)

    async def _validate_request(self, request: Request) -> Optional[Response]:
        """Validate the CSRF token when the request requires protection.

        Args:
            request: Incoming HTTP request.

        Returns:
            A 403 JSON response when validation fails, or None to let the
            request continue through the stack.
        """
        # 1. Skip if CSRF protection is disabled
        if not settings.csrf_enabled:
            return None

        # 1b. Skip if auth is disabled (dev mode)
        if not getattr(settings, "auth_required", True):
            return None

        # 2. Skip safe methods (GET, HEAD, OPTIONS, TRACE)
        if request.method in SAFE_METHODS:
            return None

        # 3. Skip exempt paths (exact or prefix match)
        request_path = request.url.path
        for exempt_path in settings.csrf_exempt_paths:
            if request_path == exempt_path or request_path.startswith(exempt_path.rstrip("/") + "/"):
                return None

        # 4. Skip Bearer token requests (not vulnerable to CSRF)
        auth_header = get_auth_header_value(request.headers) or ""
        if _extract_bearer_token(auth_header):
            return None

        # 4b. Skip requests that carry no credentials at all. CSRF only defends against
        # ambient cookie-borne credentials; a request with no Authorization header and no
        # auth cookie has nothing for CSRF to protect. Let the auth layer produce the
        # correct 401 instead of a misleading 403 CSRF error.
        #
        # Exception: trusted-proxy-header auth is still ambient (the identity comes from
        # the proxy's own session cookie, injected as a header) so it must not fall
        # through here.
        has_auth_cookie = bool(request.cookies.get("jwt_token") or request.cookies.get("access_token"))
        has_proxy_identity = is_proxy_auth_trust_active(settings) and bool(request.headers.get(settings.proxy_user_header))
        if not auth_header and not has_auth_cookie and not has_proxy_identity:
            return None

        # 5. Extract CSRF token from header. The request body is never consumed
        # (pure ASGI: no BaseHTTPMiddleware replay problem to work around).
        csrf_token = request.headers.get(settings.csrf_token_name)

        if not csrf_token:
            logger.warning(f"CSRF token missing for {request.method} {request.url.path}")
            return JSONResponse(status_code=403, content={"detail": "CSRF validation failed", "code": "CSRF_TOKEN_INVALID"})

        # 6. Get user_id and session_id from authenticated session
        user_id = None
        session_id = None

        # Try to get user from request.state (set by AuthContextMiddleware)
        if hasattr(request.state, "user") and request.state.user:
            user = request.state.user
            # EmailUser uses 'email' as primary key
            user_id = user.email if hasattr(user, "email") else str(user.id) if hasattr(user, "id") else None

        # Bind CSRF tokens to the verified JWT session (jti) when available
        session_id = getattr(request.state, "jti", None)

        # Fallback: derive whichever of user_id/session_id request.state didn't
        # already populate (middleware ordering, disabled auth-context, or a
        # local/session login for which request.state.jti is never set — see
        # auth.py's _set_auth_method_from_payload). Only fill in the missing
        # piece; never clobber a user_id already resolved from
        # request.state.user.email above, or every session-cookie request
        # would silently re-resolve identity to the JWT `sub` (EmailUser.id)
        # instead of the email CSRFMiddleware is supposed to bind to.
        if not user_id or not session_id:
            raw_token = request.cookies.get("jwt_token") or request.cookies.get("access_token")
            if not raw_token:
                auth_header = get_auth_header_value(request.headers) or ""
                raw_token = _extract_bearer_token(auth_header)

            if raw_token:
                try:
                    payload = await verify_jwt_token_cached(raw_token, request)
                    if not user_id:
                        user_id = get_jwt_user_email_from_payload(payload)
                    if not session_id:
                        session_id = payload.get("jti")
                except Exception as exc:
                    logger.warning("CSRF fallback JWT verification failed for %s %s: %s", request.method, request.url.path, exc)

        # If no user context or session binding, we can't validate the token
        if not user_id or not session_id:
            logger.warning(f"CSRF validation failed: no user context for {request.method} {request.url.path}")
            return JSONResponse(status_code=403, content={"detail": "CSRF validation failed", "code": "CSRF_TOKEN_INVALID"})

        # 7. Double-submit cookie validation: compare cookie token with header/form token
        cookie_name = getattr(settings, "csrf_cookie_name", "mcpgateway_csrf_token")
        cookie_token = request.cookies.get(cookie_name)

        if not cookie_token:
            logger.warning(f"CSRF cookie missing for {request.method} {request.url.path}")
            return JSONResponse(status_code=403, content={"detail": "CSRF validation failed", "code": "CSRF_TOKEN_INVALID"})

        # Constant-time comparison to prevent timing attacks
        if not hmac.compare_digest(csrf_token, cookie_token):
            logger.warning("CSRF double-submit validation failed: cookie and header/form tokens do not match")
            return JSONResponse(status_code=403, content={"detail": "CSRF validation failed", "code": "CSRF_TOKEN_INVALID"})

        # 8. Validate CSRF token HMAC
        csrf_service = get_csrf_service()
        if not csrf_service.validate_csrf_token(csrf_token, user_id, session_id):
            logger.warning(f"CSRF token HMAC validation failed for user {user_id}")
            return JSONResponse(status_code=403, content={"detail": "CSRF validation failed", "code": "CSRF_TOKEN_INVALID"})

        # 9. Check Referer/Origin if configured (fail-closed: reject if missing)
        if settings.csrf_check_referer:
            referer = request.headers.get("referer") or request.headers.get("origin")

            # Fail closed: reject if header is missing
            if not referer:
                logger.warning(f"CSRF referer check failed: Referer/Origin header missing for {request.method} {request.url.path}")
                return JSONResponse(status_code=403, content={"detail": "CSRF validation failed", "code": "CSRF_TOKEN_INVALID"})

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
                logger.warning(f"CSRF referer check failed: {referer_origin} not in allowed origins for {request.method} {request.url.path}")
                return JSONResponse(status_code=403, content={"detail": "CSRF validation failed", "code": "CSRF_TOKEN_INVALID"})

        # 10. All checks passed, continue with request
        return None
