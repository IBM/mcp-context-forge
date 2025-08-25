# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/auth.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Authentication API Routes.
Provides authentication endpoints for multi-user support:
- User login and logout
- Token refresh and validation
- CSRF token generation
- Password management
"""

# Standard
import logging

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# First-Party
from mcpgateway.auth import get_current_user, get_current_user_optional, get_jwt_service, get_user_service
from mcpgateway.config import settings
from mcpgateway.db import User
from mcpgateway.schemas import (
    ChangePasswordRequest,
    CSRFTokenResponse,
    ErrorResponse,
    LoginRequest,
    LoginResponse,
    PasswordResetRequest,
    UserResponse,
)
from mcpgateway.services.jwt_service import JWTService
from mcpgateway.services.user_service import UserService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])
security = HTTPBearer(auto_error=False)


@router.post(
    "/login",
    response_model=LoginResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid credentials"},
        401: {"model": ErrorResponse, "description": "Authentication failed"},
        423: {"model": ErrorResponse, "description": "Account locked"},
    },
)
async def login(
    request: Request,
    response: Response,
    login_request: LoginRequest,
    user_service: UserService = Depends(get_user_service),
    jwt_service: JWTService = Depends(get_jwt_service),
):
    """
    User login endpoint.

    Authenticates user with username/password and returns JWT token.
    Supports both username and email login.
    """
    # Get client info for logging
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    # Authenticate user
    user = await user_service.authenticate_user(username=login_request.username, password=login_request.password, ip_address=client_ip, user_agent=user_agent)

    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    # Check if multi-user mode is enabled
    if not settings.multi_user_enabled:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Multi-user authentication is not enabled")

    # Create session
    session_hours = settings.session_timeout_hours
    if login_request.remember_me:
        session_hours = session_hours * 7  # Extended session for "remember me"

    session = await user_service.create_session(user=user, ip_address=client_ip, user_agent=user_agent, expires_in_hours=session_hours)

    # Create JWT token for API access
    token_data = await jwt_service.create_token(user=user, name=f"session-{session.id[:8]}", expires_in_days=session_hours // 24, description="Session-based login token")

    # Set secure HTTP-only cookie for web interface
    if settings.secure_cookies:
        response.set_cookie(
            key="session_token",
            value=session.session_token,
            max_age=session_hours * 3600,
            secure=True,
            httponly=True,
            samesite=settings.cookie_samesite,
        )

    # Generate CSRF token for cookie-based requests
    csrf_token = await jwt_service.generate_csrf_token()
    response.set_cookie(
        key=settings.csrf_token_name,
        value=csrf_token,
        max_age=session_hours * 3600,
        secure=settings.secure_cookies,
        httponly=False,  # Need to be accessible to JavaScript
        samesite=settings.cookie_samesite,
    )

    logger.info(f"User logged in: {user.username} from {client_ip}")

    return LoginResponse(access_token=token_data["token"], token_type="bearer", expires_in=session_hours * 3600, user=UserResponse.from_orm(user))


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user_optional),
    user_service: UserService = Depends(get_user_service),
):
    """
    User logout endpoint.

    Invalidates the current session and clears cookies.
    """
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    if current_user:
        # Log logout event
        await user_service._log_auth_event(event_type="logout", user_id=current_user.id, username=current_user.username, success=True, ip_address=client_ip, user_agent=user_agent)

        logger.info(f"User logged out: {current_user.username} from {client_ip}")

    # Clear cookies
    response.delete_cookie("session_token")
    response.delete_cookie(settings.csrf_token_name)

    return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """
    Get current user information.

    Returns the authenticated user's profile information.
    """
    return UserResponse.from_orm(current_user)


@router.post("/change-password")
async def change_password(
    request: Request,
    password_request: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    user_service: UserService = Depends(get_user_service),
):
    """
    Change user password.

    Requires current password for verification.
    """
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    await user_service.change_password(
        user_id=current_user.id,
        current_password=password_request.current_password,
        new_password=password_request.new_password,
        ip_address=client_ip,
        user_agent=user_agent,
    )

    return {"message": "Password changed successfully"}


@router.post("/forgot-password")
async def forgot_password(request: Request, password_reset: PasswordResetRequest, user_service: UserService = Depends(get_user_service)):
    """
    Request password reset.

    Sends password reset email if user exists.
    Always returns success to prevent email enumeration.
    """
    # Note: In a full implementation, this would:
    # 1. Generate a secure reset token
    # 2. Store it in the database with expiration
    # 3. Send email with reset link
    # 4. Provide reset confirmation endpoint

    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    # Check if user exists (but don't reveal this information)
    user = await user_service.get_user_by_email(password_reset.email)

    if user:
        await user_service._log_auth_event(
            event_type="password_reset_requested",
            user_id=user.id,
            username=user.username,
            success=True,
            ip_address=client_ip,
            user_agent=user_agent,
            details={"email": password_reset.email},
        )

        logger.info(f"Password reset requested for user: {user.username}")

    # Always return success to prevent email enumeration
    return {"message": "If the email address exists in our system, you will receive password reset instructions"}


@router.post("/refresh")
async def refresh_token(request: Request, current_user: User = Depends(get_current_user), jwt_service: JWTService = Depends(get_jwt_service)):
    """
    Refresh JWT token.

    Issues a new token with extended expiration.
    """
    client_ip = request.client.host if request.client else None

    # Create new token
    token_data = await jwt_service.create_token(
        user=current_user,
        name=f"refresh-{client_ip or 'unknown'}",
        expires_in_days=settings.token_default_expiry_days,
        description="Refreshed authentication token",
    )

    logger.info(f"Token refreshed for user: {current_user.username}")

    return {"access_token": token_data["token"], "token_type": "bearer", "expires_in": settings.token_default_expiry_days * 24 * 3600}


@router.get("/csrf-token", response_model=CSRFTokenResponse)
async def get_csrf_token(jwt_service: JWTService = Depends(get_jwt_service)):
    """
    Get CSRF token for form submissions.

    Returns a CSRF token for use in forms and AJAX requests.
    """
    csrf_token = await jwt_service.generate_csrf_token()

    return CSRFTokenResponse(csrf_token=csrf_token)


@router.post("/validate-token")
async def validate_token(request: Request, credentials: HTTPAuthorizationCredentials = Depends(security), jwt_service: JWTService = Depends(get_jwt_service)):
    """
    Validate JWT token.

    Checks if the provided token is valid and active.
    Returns user information if valid.
    """
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No token provided")

    try:
        payload = await jwt_service.verify_token(credentials.credentials, request)
        user_data = payload.get("user")

        return {"valid": True, "user": user_data, "expires_at": payload.get("exp"), "issued_at": payload.get("iat"), "token_id": payload.get("jti")}

    except HTTPException:
        return {"valid": False, "error": "Invalid or expired token"}


@router.get("/session-info")
async def get_session_info(request: Request, current_user: User = Depends(get_current_user_optional)):
    """
    Get current session information.

    Returns information about the current authentication session.
    """
    if not current_user:
        return {"authenticated": False, "user": None}

    # Get user's teams
    # First-Party
    from mcpgateway.auth import get_user_service

    user_service = get_user_service()
    teams = await user_service.get_user_teams(current_user.id)

    return {
        "authenticated": True,
        "user": UserResponse.from_orm(current_user),
        "teams": teams,
        "session_info": {"ip_address": request.client.host if request.client else None, "user_agent": request.headers.get("user-agent")},
    }


# Health check endpoint for authentication system
@router.get("/health")
async def auth_health_check():
    """
    Authentication system health check.

    Returns the status of the authentication system.
    """
    return {
        "status": "healthy",
        "multi_user_enabled": settings.multi_user_enabled,
        "legacy_auth_mode": settings.legacy_auth_mode,
        "auth_logging_enabled": settings.enable_auth_logging,
        "csrf_protection_enabled": True,
    }
