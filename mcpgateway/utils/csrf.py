"""CSRF protection utilities for cookie-based authentication.

Implements synchronizer token pattern with httpOnly cookies for secure
cross-site request forgery protection.
"""

import secrets
from typing import Optional

from fastapi import HTTPException, Request, Response

from mcpgateway.config import settings


def generate_csrf_token() -> str:
    """Generate cryptographically secure CSRF token.

    Returns:
        str: URL-safe random token (32 bytes = 43 characters base64)
    """
    return secrets.token_urlsafe(32)


def set_csrf_cookie(response: Response, token: str) -> None:
    """Set CSRF token in httpOnly cookie.

    Args:
        response: FastAPI Response object
        token: CSRF token to set

    Note:
        Cookie is httpOnly for security, but token must also be sent
        in X-CSRF-Token header for validation (double-submit pattern).
    """
    response.set_cookie(
        key="csrf_token",
        value=token,
        httponly=True,
        secure=(settings.environment == "production") or settings.secure_cookies,
        samesite="strict",
        path="/app/auth",
        max_age=settings.token_expiry * 60,  # Match JWT expiration
    )


def get_csrf_token_from_cookie(request: Request) -> Optional[str]:
    """Extract CSRF token from cookie.

    Args:
        request: FastAPI Request object

    Returns:
        Optional[str]: CSRF token if present, None otherwise
    """
    return request.cookies.get("csrf_token")


def get_csrf_token_from_header(request: Request) -> Optional[str]:
    """Extract CSRF token from X-CSRF-Token header.

    Args:
        request: FastAPI Request object

    Returns:
        Optional[str]: CSRF token if present, None otherwise
    """
    return request.headers.get("X-CSRF-Token")


def validate_csrf_token(request: Request) -> None:
    """Validate CSRF token from cookie and header match.

    Implements synchronizer token pattern:
    1. Token stored in httpOnly cookie (not accessible to JS)
    2. Same token sent in X-CSRF-Token header (accessible to JS)
    3. Server validates both match

    Args:
        request: FastAPI Request object

    Raises:
        HTTPException: 403 if token missing or invalid

    Note:
        This protects against CSRF attacks because:
        - Attacker can't read httpOnly cookie via JS
        - Attacker can't set custom headers in cross-origin requests
        - Both must match for validation to pass
    """
    cookie_token = get_csrf_token_from_cookie(request)
    header_token = get_csrf_token_from_header(request)

    if not cookie_token:
        raise HTTPException(status_code=403, detail="CSRF token missing from cookie")

    if not header_token:
        raise HTTPException(status_code=403, detail="CSRF token missing from header")

    if not secrets.compare_digest(cookie_token, header_token):
        raise HTTPException(status_code=403, detail="CSRF token mismatch")


def clear_csrf_cookie(response: Response) -> None:
    """Clear CSRF token cookie.

    Args:
        response: FastAPI Response object
    """
    response.delete_cookie(key="csrf_token", path="/app/auth")
