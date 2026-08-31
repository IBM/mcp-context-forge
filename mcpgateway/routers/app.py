"""React App API Router.

This module provides JSON API endpoints for the React client application,
including cookie-based authentication with CSRF protection and SPA serving.

Endpoints:
- POST /app/auth/login - Authenticate and set httpOnly cookie
- GET /app/auth/me - Get current user info from cookie
- POST /app/auth/logout - Clear authentication cookie
- GET /app/* - Serve React SPA (catch-all)
"""

import asyncio
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from mcpgateway.admin import rate_limit
from mcpgateway.auth import get_current_user_from_cookie
from mcpgateway.config import settings
from mcpgateway.db import EmailUser, get_db
from mcpgateway.routers.email_auth import create_access_token
from mcpgateway.schemas import EmailUserResponse
from mcpgateway.services.csrf_service import CSRF_TOKEN_LENGTH, clear_csrf_cookie, get_csrf_service
from mcpgateway.services.email_auth_service import EmailAuthService
from mcpgateway.services.observability_service import ObservabilityService
from mcpgateway.services.token_blocklist_service import get_token_blocklist_service
from mcpgateway.utils.auth_errors import raise_auth_error
from mcpgateway.utils.security_cookies import clear_auth_cookie, set_auth_cookie

logger = logging.getLogger(__name__)

# Module-level constants
JWT_COOKIE_PATH = "/"


def _validate_csrf_token_length() -> None:
    """Validate CSRF token length at startup.
    This is a security check performed at application startup to ensure
    CSRF tokens are generated with the correct length.
    Token expiry synchronization between JWT and CSRF is validated by E2E tests
    (test_app_auth_token_expiry.py) which verify that both cookies have identical
    max_age values derived from settings.token_expiry.
    Raises:
        ValueError: If CSRF token length is misconfigured.
            This will cause application startup to fail (intentional fail-fast).
    """
    expected_csrf_length = 64  # HMAC-SHA256 hex digest = 64 chars
    if CSRF_TOKEN_LENGTH != expected_csrf_length:
        raise ValueError(
            f"CSRF token length mismatch: expected {expected_csrf_length} chars, "
            f"got {CSRF_TOKEN_LENGTH}. This indicates a configuration error in csrf_service.py"
        )
    logger.debug("CSRF token length validation passed: %d chars", CSRF_TOKEN_LENGTH)


# Run validation at module import time (fail-fast before app startup)
_validate_csrf_token_length()

# Main app router for auth endpoints
app_router = APIRouter(prefix="/app", tags=["app"])

# Separate router for SPA serving (no prefix, to handle /app/*)
app_spa_router = APIRouter(tags=["App UI"])


class LoginRequest(BaseModel):
    """Login request payload."""

    email: EmailStr
    password: str = Field(..., min_length=settings.password_min_length, max_length=256)


class LoginResponse(BaseModel):
    """Login response payload."""

    user: EmailUserResponse
    mcpgateway_csrf_token: str


@app_router.post("/auth/login", response_model=LoginResponse)
@rate_limit(10)  # 10 requests per minute to prevent credential stuffing
async def auth_login(
    request: Request,
    response: Response,
    login_data: LoginRequest,
    db: Annotated[Session, Depends(get_db)],
) -> LoginResponse:
    """Authenticate user and set httpOnly JWT cookie plus CSRF token.

    Rate limited to 10 requests per minute per IP to prevent credential stuffing attacks.
    Per-user account lockout is handled by EmailAuthService.

    Args:
        request: FastAPI request object
        response: FastAPI response object for setting cookies
        login_data: Login credentials (email and password)
        db: Database session

    Returns:
        LoginResponse: User profile and CSRF token

    Raises:
        HTTPException: 401 if authentication fails
        HTTPException: 429 if rate limit exceeded
        HTTPException: 500 if internal error occurs
    """
    try:
        auth_service = EmailAuthService(db)

        user = await auth_service.authenticate_user(login_data.email, login_data.password)

        if not user:
            raise_auth_error("authentication_failed", "Invalid email or password")

        token, _ = await create_access_token(user)
        set_auth_cookie(response, token, path=JWT_COOKIE_PATH)

        # Generate HMAC-bound CSRF token (64-char) matching middleware expectations
        # Extract jti from token payload for session binding
        from mcpgateway.config import settings
        from mcpgateway.services.csrf_service import set_csrf_cookie
        from mcpgateway.utils.verify_credentials import verify_jwt_token_cached

        payload = await verify_jwt_token_cached(token, request)
        session_id = payload.get("jti", "")
        user_sub = payload.get("sub", user.email)
        csrf_service = get_csrf_service()
        csrf_token = csrf_service.generate_csrf_token(user_id=user_sub, session_id=session_id)
        set_csrf_cookie(response, csrf_token, settings)

        logger.debug("User authenticated via cookie auth")

        return LoginResponse(
            user=EmailUserResponse.from_email_user(user),
            mcpgateway_csrf_token=csrf_token,
        )

    except HTTPException:
        raise
    except Exception as e:
        correlation_id = str(uuid.uuid4())
        logger.error("Login failed [%s]: %s", correlation_id, e, exc_info=True)
        raise_auth_error("internal_error", "Authentication failed", status_code=500, correlation_id=correlation_id)


@app_router.get("/auth/me", response_model=EmailUserResponse)
async def get_me(
    user_ctx: Annotated[tuple[EmailUser, str | None], Depends(get_current_user_from_cookie)],
) -> EmailUserResponse:
    """Return current authenticated user from cookie.

    Returns:
        EmailUserResponse: Current user profile data

    Raises:
        HTTPException: 401 if authentication fails (no valid cookie)
        HTTPException: 500 if internal error occurs
    """
    user, _ = user_ctx
    return EmailUserResponse.from_email_user(user)


@app_router.post("/auth/logout")
async def logout(
    request: Request,
    response: Response,
) -> dict[str, str]:
    """Clear auth cookies and revoke JWT server-side (best-effort).

    Cookie clearing always succeeds regardless of auth or revocation state.
    This endpoint is CSRF-exempt so that logout works even when the CSRF token
    has expired or is missing (e.g., after a long idle session).

    Token revocation is best-effort: if the blocklist is unavailable, cookies
    are still cleared and the token expires naturally (settings.token_expiry).

    Returns:
        dict: Success message with "message" key
    """
    # Always clear cookies first — regardless of what follows.
    clear_auth_cookie(response, path=JWT_COOKIE_PATH)
    clear_csrf_cookie(response, settings)

    # Best-effort: revoke the JWT so it cannot be reused before natural expiry.
    raw_token = request.cookies.get("jwt_token")
    if raw_token:
        try:
            from mcpgateway.utils.verify_credentials import verify_jwt_token_cached

            payload = await verify_jwt_token_cached(raw_token, request)
            jti = payload.get("jti")
            user_email = payload.get("email") or payload.get("sub", "unknown")
            if jti:
                blocklist_service = get_token_blocklist_service()
                await asyncio.to_thread(blocklist_service.revoke_token, jti, user_email, "logout")
            else:
                logger.warning("Logout: token missing jti — server-side revocation skipped")
        except Exception as e:
            correlation_id = str(uuid.uuid4())
            logger.warning("Logout revocation failed [%s]: %s", correlation_id, e)

            if settings.observability_enabled:
                try:
                    _svc = ObservabilityService()
                    await asyncio.to_thread(
                        _svc.record_metric,
                        "auth.token_revocation_failure",
                        1,
                        metric_type="counter",
                        attributes={"correlation_id": correlation_id, "error_type": type(e).__name__},
                    )
                except Exception as metric_error:
                    logger.debug("Failed to record token revocation failure metric: %s", metric_error)

    logger.debug("User logged out via cookie auth")
    return {"message": "Logged out successfully"}


# ---------------------------------------------------------------------------
# React SPA — /app catch-all
#
# Served on a SEPARATE router (no /admin prefix, no CSRF dependency) so that
# /app/login and all other client-side routes are reachable at their intended
# paths.  Auth is NOT enforced here: the HTML is public; access control is
# handled by the React AuthGuard (client-side) and by each API endpoint
# (server-side).  This follows the standard SPA deployment pattern.
# ---------------------------------------------------------------------------


@app_spa_router.get("/app", include_in_schema=False)
@app_spa_router.get("/app/{path:path}", include_in_schema=False)
async def app_spa(_request: Request) -> FileResponse:
    """Serve the React SPA for all /app/* routes."""
    index = settings.static_dir / "app" / "index.html"
    if not index.exists():
        raise HTTPException(
            status_code=404,
            detail="React UI not built. Run: cd client && npm run build",
        )
    return FileResponse(str(index))
