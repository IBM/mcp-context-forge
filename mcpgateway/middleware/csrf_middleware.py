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
from mcpgateway.utils.verify_credentials import verify_jwt_token_cached

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

        # 1b. Skip if auth is disabled (dev mode)
        if not getattr(settings, "auth_required", True):
            return await call_next(request)

        # 2. Skip safe methods (GET, HEAD, OPTIONS, TRACE)
        if request.method in SAFE_METHODS:
            return await call_next(request)

        # 3. Skip exempt paths (exact or prefix match)
        request_path = request.url.path
        for exempt_path in settings.csrf_exempt_paths:
            if request_path == exempt_path or request_path.startswith(exempt_path.rstrip("/") + "/"):
                return await call_next(request)

        # 4. Skip Bearer token requests (not vulnerable to CSRF)
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            return await call_next(request)

        # 5. Extract CSRF token from header or form field
        csrf_token = request.headers.get(settings.csrf_token_name)

        # If header is missing, try to parse form field (for classic HTML form submits)
        if not csrf_token:
            content_type = request.headers.get("content-type", "")

            # Parse application/x-www-form-urlencoded
            if "application/x-www-form-urlencoded" in content_type:
                try:
                    body = await request.body()
                    # Standard
                    from urllib.parse import parse_qs

                    form_data = parse_qs(body.decode("utf-8"))
                    csrf_token = form_data.get("csrf_token", [None])[0]
                except Exception as e:
                    logger.error(f"Failed to parse form data for CSRF token: {e}")

            # Parse multipart/form-data
            elif "multipart/form-data" in content_type:
                try:
                    async with request.form() as form:
                        csrf_token = form.get("csrf_token")
                except Exception as e:
                    logger.error(f"Failed to parse multipart form data for CSRF token: {e}")

        if not csrf_token:
            logger.warning(f"CSRF token missing for {request.method} {request.url.path}")
            return JSONResponse(status_code=403, content={"detail": "CSRF token missing", "code": "CSRF_TOKEN_MISSING"})

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

        # Fallback: derive user/session from a verified JWT when request.state
        # was not populated yet (middleware ordering or disabled auth-context).
        if not user_id or not session_id:
            raw_token = request.cookies.get("jwt_token") or request.cookies.get("access_token")
            if not raw_token:
                auth_header = request.headers.get("authorization", "")
                if auth_header.startswith("Bearer "):
                    raw_token = auth_header.split(" ", 1)[1].strip()

            if raw_token:
                try:
                    payload = await verify_jwt_token_cached(raw_token, request)
                    user_id = payload.get("sub") or payload.get("email") or payload.get("user", {}).get("email")
                    session_id = payload.get("jti")
                except Exception as exc:
                    logger.warning("CSRF fallback JWT verification failed for %s %s: %s", request.method, request.url.path, exc)

        # If no user context or session binding, we can't validate the token
        if not user_id or not session_id:
            logger.warning(f"CSRF validation failed: no user context for {request.method} {request.url.path}")
            return JSONResponse(status_code=403, content={"detail": "CSRF token invalid user_id and session_is do not match", "code": "CSRF_TOKEN_INVALID"})

        # 7. Double-submit cookie validation: compare cookie token with header/form token
        cookie_name = getattr(settings, "csrf_cookie_name", "csrf_token")
        cookie_token = request.cookies.get(cookie_name)

        if not cookie_token:
            logger.warning(f"CSRF cookie missing for {request.method} {request.url.path}")
            return JSONResponse(status_code=403, content={"detail": "CSRF token invalid, no cookie token", "code": "CSRF_TOKEN_INVALID"})

        # Constant-time comparison to prevent timing attacks
        # Standard
        import hmac

        if not hmac.compare_digest(csrf_token, cookie_token):
            logger.warning("CSRF double-submit validation failed: cookie and header/form tokens do not match")
            return JSONResponse(status_code=403, content={"detail": "CSRF token invalid, time issue", "code": "CSRF_TOKEN_INVALID"})

        # 8. Validate CSRF token HMAC
        csrf_service = get_csrf_service()
        if not csrf_service.validate_csrf_token(csrf_token, user_id, session_id):
            logger.warning(f"CSRF token HMAC validation failed for user {user_id}")
            return JSONResponse(status_code=403, content={"detail": "CSRF token invalid hmac issue", "code": "CSRF_TOKEN_INVALID"})

        # 9. Check Referer/Origin if configured (fail-closed: reject if missing)
        if settings.csrf_check_referer:
            referer = request.headers.get("referer") or request.headers.get("origin")

            # Fail closed: reject if header is missing
            if not referer:
                logger.warning(f"CSRF referer check failed: Referer/Origin header missing for {request.method} {request.url.path}")
                return JSONResponse(status_code=403, content={"detail": "CSRF token invalid origin header issue", "code": "CSRF_TOKEN_INVALID"})

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
                return JSONResponse(status_code=403, content={"detail": "CSRF token invalid allowed origin issue", "code": "CSRF_TOKEN_INVALID"})

        # 9. All checks passed, continue with request
        return await call_next(request)
