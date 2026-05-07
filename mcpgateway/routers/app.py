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
from mcpgateway.services.email_auth_service import EmailAuthService
from mcpgateway.services.observability_service import ObservabilityService
from mcpgateway.services.token_blocklist_service import get_token_blocklist_service
from mcpgateway.utils.auth_errors import raise_auth_error
from mcpgateway.utils.csrf import clear_csrf_cookie, generate_csrf_token, require_csrf, set_csrf_cookie
from mcpgateway.utils.security_cookies import clear_auth_cookie, set_auth_cookie

logger = logging.getLogger(__name__)

# Module-level constants
JWT_COOKIE_PATH = "/"


def _validate_csrf_token_length() -> None:
    """Validate CSRF token length at startup.

    This is a security check performed at application startup to ensure
    CSRF tokens are generated with the correct length (32 bytes = 43 chars base64url).

    Token expiry synchronization between JWT and CSRF is validated by E2E tests
    (test_app_auth_token_expiry.py) which verify that both cookies have identical
    max_age values derived from settings.token_expiry.

    Raises:
        ValueError: If CSRF token length is misconfigured.
            This will cause application startup to fail (intentional fail-fast).
    """
    from mcpgateway.utils.csrf import CSRF_TOKEN_LENGTH

    # CSRF token length validation (security check)
    expected_csrf_length = 43  # 32 bytes base64url = 43 chars
    if CSRF_TOKEN_LENGTH != expected_csrf_length:
        raise ValueError(
            f"CSRF token length mismatch: expected {expected_csrf_length} chars, "
            f"got {CSRF_TOKEN_LENGTH}. This indicates a configuration error in csrf.py"
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
    csrf_token: str


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

        csrf_token = generate_csrf_token()
        set_csrf_cookie(response, csrf_token)

        logger.debug("User authenticated via cookie auth")

        return LoginResponse(
            user=EmailUserResponse.from_email_user(user),
            csrf_token=csrf_token,
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
    response: Response,
    _csrf: Annotated[None, Depends(require_csrf)],
    user_ctx: Annotated[tuple[EmailUser, str | None], Depends(get_current_user_from_cookie)],
) -> dict[str, str]:
    """Revoke JWT server-side and clear auth cookies.

    Security Flow:
        1. CSRF validation (via Depends) - prevents cross-site logout attacks
        2. Authentication check (via get_current_user_from_cookie)
        3. Server-side token revocation (best-effort)
        4. Cookie clearing (always succeeds)

    Token Revocation Pattern (Best-Effort):
        Token revocation is attempted but not required for logout success. This design
        prioritizes user experience and availability over strict revocation guarantees:

        Success Case:
            - Token added to blocklist (Redis/DB)
            - User immediately logged out client-side (cookies cleared)
            - Token rejected on subsequent requests (blocklist check)

        Failure Case (Redis/DB unavailable):
            - Revocation fails but logout succeeds (cookies still cleared)
            - User immediately logged out client-side
            - Token remains valid until natural expiry (settings.token_expiry)
            - Failure logged with correlation ID for monitoring/alerting
            - Metric recorded for observability (auth.token_revocation_failure)

        Rationale:
            - Logout must always succeed from user perspective (UX requirement)
            - Cookie clearing provides immediate client-side protection
            - Token TTL bounds exposure window (default: 20 minutes)
            - Monitoring/alerting enables operational response to blocklist outages
            - Alternative: Fail logout on revocation failure (poor UX, availability impact)

        Security Considerations:
            - Tokens without JTI cannot be revoked (logged as warning)
            - Short token_expiry (5-20 min recommended) limits exposure
            - Monitor auth.token_revocation_failure metric for blocklist health
            - Consider token_idle_timeout for additional protection

    Returns:
        dict: Success message with "message" key

    Raises:
        HTTPException: 401 if authentication fails
        HTTPException: 403 if CSRF validation fails
        HTTPException: 500 if internal error occurs
    """
    try:
        user, jti = user_ctx
        if jti:
            try:
                blocklist_service = get_token_blocklist_service()
                await asyncio.to_thread(blocklist_service.revoke_token, jti, user.email, "logout")
            except Exception as e:
                # Best-effort revocation: log but don't fail logout if blocklist is unavailable
                correlation_id = str(uuid.uuid4())
                logger.warning("Token revocation failed [%s]: %s", correlation_id, e, extra={"user_id": user.id})

                # Record metric for monitoring/alerting (only when observability is enabled)
                if settings.observability_enabled:
                    try:
                        _svc = ObservabilityService()
                        await asyncio.to_thread(
                            _svc.record_metric,
                            "auth.token_revocation_failure",
                            1,
                            metric_type="counter",
                            attributes={"user_id": str(user.id), "correlation_id": correlation_id, "error_type": type(e).__name__},
                        )
                    except Exception as metric_error:
                        logger.debug("Failed to record token revocation failure metric: %s", metric_error)
        else:
            logger.warning("Logout: token missing jti — server-side revocation skipped", extra={"user_id": user.id})

        clear_auth_cookie(response, path=JWT_COOKIE_PATH)
        clear_csrf_cookie(response)

        logger.debug("User logged out via cookie auth")

        return {"message": "Logged out successfully"}
    except HTTPException:
        raise
    except Exception as e:
        correlation_id = str(uuid.uuid4())
        logger.error("Logout failed [%s]: %s", correlation_id, e, exc_info=True)
        raise_auth_error("internal_error", "Logout failed", status_code=500, correlation_id=correlation_id)


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
