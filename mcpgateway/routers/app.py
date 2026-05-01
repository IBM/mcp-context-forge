"""React App API Router.

This module provides JSON API endpoints for the React client application,
including cookie-based authentication with CSRF protection and SPA serving.

Endpoints:
- POST /app/auth/login - Authenticate and set httpOnly cookie
- GET /app/auth/me - Get current user info from cookie
- POST /app/auth/logout - Clear authentication cookie
- GET /app/* - Serve React SPA (catch-all)
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from mcpgateway.auth import get_current_user_from_cookie
from mcpgateway.routers.email_auth import create_access_token
from mcpgateway.config import settings
from mcpgateway.db import get_db
from mcpgateway.schemas import EmailUserResponse
from mcpgateway.services.email_auth_service import EmailAuthService
from mcpgateway.utils.csrf import clear_csrf_cookie, generate_csrf_token, set_csrf_cookie, validate_csrf_token
from mcpgateway.utils.security_cookies import clear_auth_cookie, set_auth_cookie

logger = logging.getLogger(__name__)

# Main app router for auth endpoints
app_router = APIRouter(prefix="/app", tags=["app"])

# Separate router for SPA serving (no prefix, to handle /app/*)
app_spa_router = APIRouter(tags=["App UI"])


class LoginRequest(BaseModel):
    """Login request payload."""

    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    """Login response payload."""

    user: EmailUserResponse
    csrf_token: str


@app_router.post("/auth/login", response_model=LoginResponse)
async def auth_login(
    request: Request,
    response: Response,
    login_data: LoginRequest,
    db: Session = Depends(get_db),
) -> LoginResponse:
    """Authenticate user and set httpOnly cookie with CSRF token.

    This endpoint:
    1. Validates credentials via EmailAuthService
    2. Creates JWT access token
    3. Sets JWT in httpOnly cookie (XSS protection)
    4. Generates and sets CSRF token (CSRF protection)
    5. Returns user info and CSRF token for client storage

    Args:
        request: FastAPI request object
        response: FastAPI response object
        login_data: Email and password
        db: Database session

    Returns:
        LoginResponse: User info and CSRF token

    Raises:
        HTTPException: 401 if credentials invalid
        HTTPException: 500 if authentication service fails
    """
    try:
        # Authenticate user
        auth_service = EmailAuthService(db)
        user = await auth_service.authenticate_user(login_data.email, login_data.password)

        if not user:
            raise HTTPException(status_code=401, detail="Invalid email or password")

        # Create JWT token
        token, _ = await create_access_token(user)

        # Set JWT in httpOnly cookie
        set_auth_cookie(response, token)

        # Generate and set CSRF token
        csrf_token = generate_csrf_token()
        set_csrf_cookie(response, csrf_token)

        logger.info(f"User {user.email} authenticated successfully via /app/auth/login")

        # Return user info and CSRF token
        return LoginResponse(
            user=EmailUserResponse.from_email_user(user),
            csrf_token=csrf_token,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login failed for {login_data.email}: {e}")
        raise HTTPException(status_code=500, detail="Authentication failed")


@app_router.get("/auth/me", response_model=EmailUserResponse)
async def get_current_user(
    request: Request,
    user: Annotated[dict, Depends(get_current_user_from_cookie)],
    db: Session = Depends(get_db),
) -> EmailUserResponse:
    """Return current authenticated user from cookie.

    This endpoint validates the JWT cookie and returns user information.
    Used by React client to check authentication status on mount.

    Args:
        request: FastAPI request object
        user: Current user from cookie (injected by dependency)
        db: Database session

    Returns:
        EmailUserResponse: Current user information

    Raises:
        HTTPException: 401 if cookie invalid or missing
    """
    return EmailUserResponse(
        email=user["email"],
        full_name=user.get("full_name"),
        is_admin=user.get("is_admin", False),
        is_active=True,
        auth_provider="email",
        created_at=user.get("created_at"),
        last_login=None,
        email_verified=True,
        password_change_required=False,
        failed_login_attempts=0,
        locked_until=None,
        is_locked=False,
    )


@app_router.post("/auth/logout")
async def logout(
    request: Request,
    response: Response,
    user: Annotated[dict, Depends(get_current_user_from_cookie)],
) -> JSONResponse:
    """Clear authentication cookie and CSRF token.

    This endpoint:
    1. Validates CSRF token (prevents CSRF logout attacks)
    2. Clears JWT cookie
    3. Clears CSRF token cookie
    4. Returns success response

    Args:
        request: FastAPI request object
        response: FastAPI response object
        user: Current user from cookie (injected by dependency)

    Returns:
        JSONResponse: Success message

    Raises:
        HTTPException: 403 if CSRF token invalid
        HTTPException: 401 if not authenticated
    """
    # Validate CSRF token
    validate_csrf_token(request)

    # Clear cookies
    clear_auth_cookie(response)
    clear_csrf_cookie(response)

    logger.info(f"User {user['email']} logged out via /app/auth/logout")

    return JSONResponse(content={"message": "Logged out successfully"})


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
    """Serve the React SPA for all /app/* routes.

    Returns:
        FileResponse: The compiled React index.html

    Raises:
        HTTPException: 404 when the SPA has not been built yet
    """
    index = settings.static_dir / "app" / "index.html"
    if not index.exists():
        raise HTTPException(
            status_code=404,
            detail="React UI not built. Run: cd client && npm run build",
        )
    return FileResponse(str(index))
