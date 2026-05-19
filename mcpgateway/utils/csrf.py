"""CSRF protection utilities for cookie-based authentication.

Implements double-submit cookie pattern: CSRF token set in a non-httpOnly
cookie (so JS can read it after page refresh) and validated against the
X-CSRF-Token request header. The JWT session cookie remains httpOnly.

Token Expiry Coupling:
    CSRF and JWT tokens share the same expiry (settings.token_expiry * 60 seconds).
    This coupling is intentional to prevent auth/CSRF desynchronization:

    - Both cookies expire simultaneously
    - Token refresh (if implemented) must renew both cookies together
    - Prevents edge case: valid JWT with expired CSRF (or vice versa)

    Implementation notes:
    - JWT expiry: Set in create_access_token() via exp claim
    - CSRF expiry: Set in set_csrf_cookie() via max_age parameter
    - Both use settings.token_expiry as single source of truth
    - Default: 60 minutes (configurable via TOKEN_EXPIRY env var)
"""

import math
import secrets
from typing import Optional

from fastapi import Request, Response

from mcpgateway.config import settings
from mcpgateway.utils.auth_errors import raise_auth_error

# CSRF token generation constants
CSRF_TOKEN_BYTES = 32  # 32 bytes = 256 bits (OWASP recommendation)
CSRF_TOKEN_LENGTH = math.ceil(CSRF_TOKEN_BYTES * 4 / 3)  # URL-safe base64 without padding


def generate_csrf_token() -> str:
    """Generate cryptographically secure CSRF token.

    Returns:
        str: URL-safe random token (32 bytes = 43 characters base64)
    """
    return secrets.token_urlsafe(CSRF_TOKEN_BYTES)


def set_csrf_cookie(response: Response, token: str) -> None:
    """Set CSRF token in a non-httpOnly cookie so JS can read it after page refresh.

    Expiry matches token_expiry so CSRF and JWT cookies stay in sync. If a
    token-refresh endpoint is added later, both cookies must be renewed together.

    Security properties:
    - max_age: Synchronized with JWT expiry (settings.token_expiry * 60)
    - httponly: False (JS must read token for X-CSRF-Token header)
    - secure: True in production (HTTPS only)
    - samesite: strict (prevents CSRF attacks)
    - path: /app (scoped to React client routes)
    """
    response.set_cookie(
        key="csrf_token",
        value=token,
        httponly=False,  # JS must read for X-CSRF-Token header (double-submit pattern)
        secure=(settings.environment == "production") or settings.secure_cookies,  # HTTPS only in prod
        samesite="strict",  # Prevents CSRF attacks (no cross-site requests)
        path="/",  # Application-wide scope to match jwt_token cookie
        max_age=settings.token_expiry * 60,  # Synchronized with JWT expiry
    )


def get_csrf_token_from_cookie(request: Request) -> Optional[str]:
    """Extract CSRF token from cookie."""
    return request.cookies.get("csrf_token")


def get_csrf_token_from_header(request: Request) -> Optional[str]:
    """Extract CSRF token from X-CSRF-Token header."""
    return request.headers.get("X-CSRF-Token")


def validate_csrf_token(request: Request) -> None:
    """Validate CSRF token: cookie value must match X-CSRF-Token header.

    Cross-origin attackers cannot set custom headers, so a matching
    cookie+header pair proves the request originates from the same site.

    Security: Validates token length before comparison to prevent DoS via oversized tokens.
    """
    cookie_token = get_csrf_token_from_cookie(request)
    header_token = get_csrf_token_from_header(request)

    if not cookie_token:
        raise_auth_error("csrf_missing_cookie", "CSRF token missing from cookie", status_code=403)

    if not header_token:
        raise_auth_error("csrf_missing_header", "CSRF token missing from header", status_code=403)

    # Validate token format and length to prevent DoS
    if len(cookie_token) != CSRF_TOKEN_LENGTH:
        raise_auth_error("csrf_invalid_format", "Invalid CSRF token format", status_code=403)

    if len(header_token) != CSRF_TOKEN_LENGTH:
        raise_auth_error("csrf_invalid_format", "Invalid CSRF token format", status_code=403)

    if not secrets.compare_digest(cookie_token, header_token):
        raise_auth_error("csrf_mismatch", "CSRF token mismatch", status_code=403)


def require_csrf(request: Request) -> None:
    """FastAPI dependency: validate CSRF token before handler body executes."""
    validate_csrf_token(request)


def clear_csrf_cookie(response: Response) -> None:
    """Clear CSRF token cookie."""
    response.delete_cookie(
        key="csrf_token",
        path="/",
        samesite="strict",
        secure=(settings.environment == "production") or settings.secure_cookies,
    )
