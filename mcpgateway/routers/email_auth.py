# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/email_auth.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Email Authentication Router.
This module provides FastAPI routes for email-based authentication
including login, registration, password management, and user profile endpoints.

Examples:
    >>> from fastapi import FastAPI
    >>> from mcpgateway.routers.email_auth import email_auth_router
    >>> app = FastAPI()
    >>> app.include_router(email_auth_router, prefix="/auth/email", tags=["Email Auth"])
    >>> isinstance(email_auth_router, APIRouter)
    True
"""

# Standard
from datetime import datetime, timedelta, UTC
from typing import List, Optional, Union

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.security import HTTPBearer
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.auth import get_current_user
from mcpgateway.config import settings
from mcpgateway.db import EmailUser, SessionLocal, utc_now
from mcpgateway.middleware.rbac import get_current_user_with_permissions, require_permission
from mcpgateway.schemas import (
    AdminCreateUserRequest,
    AdminUserUpdateRequest,
    AuthenticationResponse,
    AuthEventResponse,
    ChangePasswordRequest,
    CursorPaginatedUsersResponse,
    EmailLoginRequest,
    EmailUserResponse,
    ForgotPasswordRequest,
    PasswordResetTokenValidationResponse,
    PublicRegistrationRequest,
    ResetPasswordRequest,
    SuccessResponse,
)
from mcpgateway.services.email_auth_service import AuthenticationError, EmailAuthService, EmailValidationError, PasswordValidationError, UserExistsError
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.utils.create_jwt_token import create_jwt_token
from mcpgateway.utils.orjson_response import ORJSONResponse

# Initialize logging
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

# Create router
email_auth_router = APIRouter()

# Security scheme
bearer_scheme = HTTPBearer(auto_error=False)


def get_db():
    """Database dependency.

    Commits the transaction on successful completion to avoid implicit rollbacks
    for read-only operations. Rolls back explicitly on exception.

    Yields:
        Session: SQLAlchemy database session

    Raises:
        Exception: Re-raises any exception after rolling back the transaction.
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            try:
                db.invalidate()
            except Exception:
                pass  # nosec B110 - Best effort cleanup on connection failure
        raise
    finally:
        db.close()


def get_client_ip(request: Request) -> str:
    """Extract client IP address from request.

    Args:
        request: FastAPI request object

    Returns:
        str: Client IP address
    """
    # Check for X-Forwarded-For header (proxy/load balancer)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    # Check for X-Real-IP header
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip

    # Fall back to direct client IP
    return request.client.host if request.client else "unknown"


def get_user_agent(request: Request) -> str:
    """Extract user agent from request.

    Args:
        request: FastAPI request object

    Returns:
        str: User agent string
    """
    return request.headers.get("User-Agent", "unknown")


async def create_access_token(user: EmailUser, token_scopes: Optional[dict] = None, jti: Optional[str] = None) -> tuple[str, int]:
    """Create JWT access token for user with enhanced scoping.

    Args:
        user: EmailUser instance
        token_scopes: Optional token scoping information
        jti: Optional JWT ID for revocation tracking

    Returns:
        Tuple of (token_string, expires_in_seconds)
    """
    now = datetime.now(tz=UTC)
    expires_delta = timedelta(minutes=settings.token_expiry)
    expire = now + expires_delta

    # Create JWT payload — session token (teams resolved server-side at request time)
    payload = {
        # Standard JWT claims
        "sub": user.email,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "jti": jti or str(__import__("uuid").uuid4()),
        # User profile information
        "user": {
            "email": str(getattr(user, "email", "")),
            "full_name": str(getattr(user, "full_name", "")),
            "is_admin": bool(getattr(user, "is_admin", False)),
            "auth_provider": str(getattr(user, "auth_provider", "local")),
        },
        "token_use": "session",  # nosec B105 - token type marker, not a password
        # Token scoping (if provided)
        "scopes": token_scopes or {"server_id": None, "permissions": ["*"], "ip_restrictions": [], "time_restrictions": {}},
    }

    # Generate token using centralized token creation
    token = await create_jwt_token(payload)

    return token, int(expires_delta.total_seconds())


async def create_legacy_access_token(user: EmailUser) -> tuple[str, int]:
    """Create legacy JWT access token for backwards compatibility.

    Args:
        user: EmailUser instance

    Returns:
        Tuple of (token_string, expires_in_seconds)
    """
    now = datetime.now(tz=UTC)
    expires_delta = timedelta(minutes=settings.token_expiry)
    expire = now + expires_delta

    # Create simple JWT payload (original format) with primitives only
    payload = {
        "sub": str(getattr(user, "email", "")),
        "email": str(getattr(user, "email", "")),
        "full_name": str(getattr(user, "full_name", "")),
        "is_admin": bool(getattr(user, "is_admin", False)),
        "auth_provider": str(getattr(user, "auth_provider", "local")),
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }

    # Generate token using centralized token creation
    token = await create_jwt_token(payload)

    return token, int(expires_delta.total_seconds())


@email_auth_router.post("/login", response_model=AuthenticationResponse)
async def login(login_request: EmailLoginRequest, request: Request, db: Session = Depends(get_db)):
    """Authenticate user with email and password.

    Args:
        login_request: Login credentials
        request: FastAPI request object
        db: Database session

    Returns:
        AuthenticationResponse: Access token and user info

    Examples:
        >>> import asyncio
        >>> asyncio.iscoroutinefunction(login)
        True

    Raises:
        HTTPException: If authentication fails

    Examples:
        Request JSON:
            {
              "email": "user@example.com",
              "password": "secure_password"
            }
    """
    auth_service = EmailAuthService(db)
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)

    try:
        # Authenticate user
        user = await auth_service.authenticate_user(email=login_request.email, password=login_request.password, ip_address=ip_address, user_agent=user_agent)

        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

        # Password change enforcement respects master switch and individual toggles
        needs_password_change = False

        if settings.password_change_enforcement_enabled:
            # If flag is set on the user, always honor it (flag is cleared when password is changed)
            if getattr(user, "password_change_required", False):
                needs_password_change = True
                logger.debug("User %s has password_change_required flag set", login_request.email)

            # Enforce expiry-based password change if configured and not already required
            if not needs_password_change:
                try:
                    pwd_changed = getattr(user, "password_changed_at", None)
                    if isinstance(pwd_changed, datetime):
                        age_days = (utc_now() - pwd_changed).days
                        max_age = getattr(settings, "password_max_age_days", 90)
                        if age_days >= max_age:
                            needs_password_change = True
                            logger.debug("User %s password expired (%s days >= %s)", login_request.email, age_days, max_age)
                except Exception as exc:
                    logger.debug("Failed to evaluate password age for %s: %s", login_request.email, exc)

            # Detect default password on login if enabled
            if getattr(settings, "detect_default_password_on_login", True):
                # First-Party
                from mcpgateway.services.argon2_service import Argon2PasswordService

                password_service = Argon2PasswordService()
                is_using_default_password = await password_service.verify_password_async(settings.default_user_password.get_secret_value(), user.password_hash)  # nosec B105
                if is_using_default_password:
                    # Mark user for password change depending on configuration
                    if getattr(settings, "require_password_change_for_default_password", True):
                        user.password_change_required = True
                        needs_password_change = True
                        try:
                            db.commit()
                        except Exception as exc:  # log commit failures
                            logger.warning("Failed to commit password_change_required flag for %s: %s", login_request.email, exc)
                    else:
                        logger.info("User %s is using default password but enforcement is disabled", login_request.email)

        if needs_password_change:
            logger.info(f"Login blocked for {login_request.email}: password change required")
            return ORJSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"detail": "Password change required. Please change your password before continuing."},
                headers={"X-Password-Change-Required": "true"},
            )

        # Create access token
        access_token, expires_in = await create_access_token(user)

        # Return authentication response
        return AuthenticationResponse(
            access_token=access_token, token_type="bearer", expires_in=expires_in, user=EmailUserResponse.from_email_user(user)
        )  # nosec B106 - OAuth2 token type, not a password

    except HTTPException:
        raise  # Re-raise HTTP exceptions as-is (401, 403, etc.)
    except Exception as e:
        logger.error(f"Login error for {login_request.email}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Authentication service error")


@email_auth_router.post("/register", response_model=AuthenticationResponse)
async def register(registration_request: PublicRegistrationRequest, request: Request, db: Session = Depends(get_db)):
    """Register a new user account.

    This endpoint is controlled by the PUBLIC_REGISTRATION_ENABLED setting.
    When disabled (default), returns 403 Forbidden and users can only be
    created by administrators via the admin API.

    Args:
        registration_request: Registration information (email, password, full_name only)
        request: FastAPI request object
        db: Database session

    Returns:
        AuthenticationResponse: Access token and user info

    Raises:
        HTTPException: If registration fails or is disabled

    Examples:
        Request JSON:
            {
              "email": "new@example.com",
              "password": "secure_password",
              "full_name": "New User"
            }
    """
    # Check if public registration is allowed
    if not settings.public_registration_enabled:
        logger.warning(f"Registration attempt rejected - public registration disabled: {registration_request.email}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Public registration is disabled. Please contact an administrator to create an account.",
        )

    auth_service = EmailAuthService(db)
    get_client_ip(request)
    get_user_agent(request)

    try:
        # Password is required by schema (str, not Optional) — Pydantic returns 422 if missing
        # Security-sensitive fields are hardcoded (not exposed on public schema)
        user = await auth_service.create_user(
            email=registration_request.email,
            password=registration_request.password,
            full_name=registration_request.full_name,
            is_admin=False,  # Regular users cannot self-register as admin
            is_active=True,  # Public registrations are always active
            password_change_required=False,  # No forced password change for self-registration
            auth_provider="local",
        )

        # Create access token
        access_token, expires_in = await create_access_token(user)

        logger.info(f"New user registered: {user.email}")

        return AuthenticationResponse(
            access_token=access_token, token_type="bearer", expires_in=expires_in, user=EmailUserResponse.from_email_user(user)
        )  # nosec B106 - OAuth2 token type, not a password

    except EmailValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except PasswordValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except UserExistsError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception as e:
        logger.error(f"Registration error for {registration_request.email}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Registration service error")


@email_auth_router.post("/change-password", response_model=SuccessResponse)
async def change_password(password_request: ChangePasswordRequest, request: Request, current_user: EmailUser = Depends(get_current_user), db: Session = Depends(get_db)):
    """Change user's password.

    Args:
        password_request: Old and new passwords
        request: FastAPI request object
        current_user: Currently authenticated user
        db: Database session

    Returns:
        SuccessResponse: Success confirmation

    Raises:
        HTTPException: If password change fails

    Examples:
        Request JSON (with Bearer token in Authorization header):
            {
              "old_password": "current_password",
              "new_password": "new_secure_password"
            }
    """
    auth_service = EmailAuthService(db)
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)

    try:
        # Change password
        success = await auth_service.change_password(
            email=current_user.email, old_password=password_request.old_password, new_password=password_request.new_password, ip_address=ip_address, user_agent=user_agent
        )

        if success:
            return SuccessResponse(success=True, message="Password changed successfully")
        else:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to change password")

    except AuthenticationError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    except PasswordValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Password change error for {current_user.email}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Password change service error")


@email_auth_router.post("/forgot-password", response_model=SuccessResponse)
async def forgot_password(reset_request: ForgotPasswordRequest, request: Request, db: Session = Depends(get_db)):
    """Request a one-time password reset token via email.

    Args:
        reset_request: Forgot-password request payload.
        request: Incoming HTTP request.
        db: Database session dependency.

    Returns:
        SuccessResponse: Generic success response to avoid account enumeration.

    Raises:
        HTTPException: If password reset is disabled or the request is rate limited.
    """
    if not getattr(settings, "password_reset_enabled", True):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Password reset is disabled")

    auth_service = EmailAuthService(db)
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)

    result = await auth_service.request_password_reset(email=reset_request.email, ip_address=ip_address, user_agent=user_agent)
    if result.rate_limited:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many requests. Please try again later.")

    return SuccessResponse(success=True, message="If this email is registered, you will receive a reset link.")


@email_auth_router.get("/reset-password/{token}", response_model=PasswordResetTokenValidationResponse)
async def validate_password_reset_token(token: str, request: Request, db: Session = Depends(get_db)):
    """Validate a password reset token before submitting a new password.

    Args:
        token: One-time reset token.
        request: Incoming HTTP request.
        db: Database session dependency.

    Returns:
        PasswordResetTokenValidationResponse: Token validity and expiration data.

    Raises:
        HTTPException: If password reset is disabled or token validation fails.
    """
    if not getattr(settings, "password_reset_enabled", True):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Password reset is disabled")

    auth_service = EmailAuthService(db)
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)

    try:
        reset_token = await auth_service.validate_password_reset_token(token=token, ip_address=ip_address, user_agent=user_agent)
        return PasswordResetTokenValidationResponse(valid=True, message="Reset token is valid", expires_at=reset_token.expires_at)
    except AuthenticationError as exc:
        detail = str(exc)
        if "expired" in detail.lower():
            raise HTTPException(status_code=status.HTTP_410_GONE, detail=detail)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


@email_auth_router.post("/reset-password/{token}", response_model=SuccessResponse)
async def complete_password_reset(token: str, reset_request: ResetPasswordRequest, request: Request, db: Session = Depends(get_db)):
    """Complete password reset with a valid one-time token.

    Args:
        token: One-time reset token.
        reset_request: Reset-password payload with new credentials.
        request: Incoming HTTP request.
        db: Database session dependency.

    Returns:
        SuccessResponse: Password reset completion status.

    Raises:
        HTTPException: If password reset is disabled or reset validation fails.
    """
    if not getattr(settings, "password_reset_enabled", True):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Password reset is disabled")

    auth_service = EmailAuthService(db)
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)

    try:
        await auth_service.reset_password_with_token(token=token, new_password=reset_request.new_password, ip_address=ip_address, user_agent=user_agent)
        return SuccessResponse(success=True, message="Password reset successful. Please sign in with your new password.")
    except AuthenticationError as exc:
        detail = str(exc)
        if "expired" in detail.lower():
            raise HTTPException(status_code=status.HTTP_410_GONE, detail=detail)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
    except PasswordValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@email_auth_router.get("/me", response_model=EmailUserResponse)
async def get_current_user_profile(current_user: EmailUser = Depends(get_current_user)):
    """Get current user's profile information.

    Args:
        current_user: Currently authenticated user

    Returns:
        EmailUserResponse: User profile information

    Raises:
        HTTPException: If user authentication fails

    Examples:
        >>> # GET /auth/email/me
        >>> # Headers: Authorization: Bearer <token>
    """
    return EmailUserResponse.from_email_user(current_user)


@email_auth_router.get("/events", response_model=list[AuthEventResponse])
async def get_auth_events(limit: int = 50, offset: int = 0, current_user: EmailUser = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get authentication events for the current user.

    Args:
        limit: Maximum number of events to return
        offset: Number of events to skip
        current_user: Currently authenticated user
        db: Database session

    Returns:
        List[AuthEventResponse]: Authentication events

    Raises:
        HTTPException: If user authentication fails

    Examples:
        >>> # GET /auth/email/events?limit=10&offset=0
        >>> # Headers: Authorization: Bearer <token>
    """
    auth_service = EmailAuthService(db)

    try:
        events = await auth_service.get_auth_events(email=current_user.email, limit=limit, offset=offset)

        return [AuthEventResponse.model_validate(event) for event in events]

    except Exception as e:
        logger.error(f"Error getting auth events for {current_user.email}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve authentication events")


# Admin-only endpoints
@email_auth_router.get("/admin/users", response_model=Union[CursorPaginatedUsersResponse, List[EmailUserResponse]])
@require_permission("admin.user_management")
async def list_users(
    cursor: Optional[str] = Query(None, description="Pagination cursor for fetching the next set of results"),
    limit: Optional[int] = Query(
        None,
        ge=0,
        le=settings.pagination_max_page_size,
        description="Maximum number of users to return. 0 means all (no limit). Default uses pagination_default_page_size.",
    ),
    include_pagination: bool = Query(False, description="Include cursor pagination metadata in response"),
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> Union[CursorPaginatedUsersResponse, List[EmailUserResponse]]:
    """List all users (admin only) with cursor-based pagination support.

    Args:
        cursor: Pagination cursor for fetching the next set of results
        limit: Maximum number of users to return. Use 0 for all users (no limit).
            If not specified, uses pagination_default_page_size (default: 50).
        include_pagination: Whether to include cursor pagination metadata in the response (default: false)
        current_user_ctx: Currently authenticated user context with permissions
        db: Database session

    Returns:
        CursorPaginatedUsersResponse with users and nextCursor if include_pagination=true, or
        List of users if include_pagination=false

    Raises:
        HTTPException: If user is not admin

    Examples:
        >>> # Cursor-based with pagination: GET /auth/email/admin/users?cursor=eyJlbWFpbCI6Li4ufQ&include_pagination=true
        >>> # Simple list: GET /auth/email/admin/users
        >>> # Headers: Authorization: Bearer <admin_token>
    """
    auth_service = EmailAuthService(db)

    try:
        result = await auth_service.list_users(cursor=cursor, limit=limit)
        user_responses = [EmailUserResponse.from_email_user(user) for user in result.data]

        if include_pagination:
            return CursorPaginatedUsersResponse(users=user_responses, next_cursor=result.next_cursor)

        return user_responses

    except Exception as e:
        logger.error(f"Error listing users: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve user list")


@email_auth_router.get("/admin/events", response_model=list[AuthEventResponse])
@require_permission("admin.user_management")
async def list_all_auth_events(limit: int = 100, offset: int = 0, user_email: Optional[str] = None, current_user_ctx: dict = Depends(get_current_user_with_permissions), db: Session = Depends(get_db)):
    """List authentication events for all users (admin only).

    Args:
        limit: Maximum number of events to return
        offset: Number of events to skip
        user_email: Filter events by specific user email
        current_user_ctx: Currently authenticated user context with permissions
        db: Database session

    Returns:
        List[AuthEventResponse]: Authentication events

    Raises:
        HTTPException: If user is not admin

    Examples:
        >>> # GET /auth/email/admin/events?limit=50&user_email=user@example.com
        >>> # Headers: Authorization: Bearer <admin_token>
    """
    auth_service = EmailAuthService(db)

    try:
        events = await auth_service.get_auth_events(email=user_email, limit=limit, offset=offset)

        return [AuthEventResponse.model_validate(event) for event in events]

    except Exception as e:
        logger.error(f"Error getting auth events: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve authentication events")


@email_auth_router.post("/admin/users", response_model=EmailUserResponse, status_code=status.HTTP_201_CREATED)
@require_permission("admin.user_management")
async def create_user(user_request: AdminCreateUserRequest, current_user_ctx: dict = Depends(get_current_user_with_permissions), db: Session = Depends(get_db)):
    """Create a new user account (admin only).

    Args:
        user_request: User creation information
        current_user_ctx: Currently authenticated user context with permissions
        db: Database session

    Returns:
        EmailUserResponse: Created user information

    Raises:
        HTTPException: If user creation fails

    Examples:
        Request JSON:
            {
              "email": "newuser@example.com",
              "password": "secure_password",
              "full_name": "New User",
              "is_admin": false
            }
    """
    auth_service = EmailAuthService(db)

    try:
        # Password is required by schema (str, not Optional) — Pydantic returns 422 if missing
        # Create new user with all fields from request
        user = await auth_service.create_user(
            email=user_request.email,
            password=user_request.password,
            full_name=user_request.full_name,
            is_admin=user_request.is_admin,
            is_active=user_request.is_active,
            password_change_required=user_request.password_change_required,
            auth_provider="local",
            granted_by=current_user_ctx.get("email"),
        )

        # If the user was created with the default password, optionally force password change
        if (
            settings.password_change_enforcement_enabled
            and getattr(settings, "require_password_change_for_default_password", True)
            and user_request.password == settings.default_user_password.get_secret_value()
        ):  # nosec B105
            user.password_change_required = True
            db.commit()

        logger.info(f"Admin {current_user_ctx['email']} created user: {user.email}")

        db.commit()
        db.close()
        return EmailUserResponse.from_email_user(user)

    except EmailValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except PasswordValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except UserExistsError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception as e:
        logger.error(f"Admin user creation error: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="User creation failed")


@email_auth_router.get("/admin/users/{user_email}", response_model=EmailUserResponse)
@require_permission("admin.user_management")
async def get_user(user_email: str, current_user_ctx: dict = Depends(get_current_user_with_permissions), db: Session = Depends(get_db)):
    """Get user by email (admin only).

    Args:
        user_email: Email of user to retrieve
        current_user_ctx: Currently authenticated user context with permissions
        db: Database session

    Returns:
        EmailUserResponse: User information

    Raises:
        HTTPException: If user not found
    """
    auth_service = EmailAuthService(db)

    try:
        user = await auth_service.get_user_by_email(user_email)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        return EmailUserResponse.from_email_user(user)

    except HTTPException:
        raise  # Re-raise HTTP exceptions as-is (401, 403, 404, etc.)
    except Exception as e:
        logger.error(f"Error retrieving user {user_email}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve user")


@email_auth_router.patch("/admin/users/{user_email}", response_model=EmailUserResponse)
@require_permission("admin.user_management")
async def update_user(user_email: str, user_request: AdminUserUpdateRequest, current_user_ctx: dict = Depends(get_current_user_with_permissions), db: Session = Depends(get_db)):
    """Update user information (admin only).

    Args:
        user_email: Email of user to update
        user_request: Updated user information
        current_user_ctx: Currently authenticated user context with permissions
        db: Database session

    Returns:
        EmailUserResponse: Updated user information

    Raises:
        HTTPException: If user not found or update fails
    """
    return await update_user_delegate(user_email, user_request, current_user_ctx, db)


# ----------------------> [#2754] remove after Sun, 16 Aug 2026 23:59:59 UTC and replace update_user as dirrected in the docstring of update_user_delegate
@email_auth_router.put("/admin/users/{user_email}", response_model=EmailUserResponse, deprecated=True)
@require_permission("admin.user_management")
async def update_user_deprecated(
    user_email: str, user_request: AdminUserUpdateRequest, response: Response, current_user_ctx: dict = Depends(get_current_user_with_permissions), db: Session = Depends(get_db)
):
    """Update user information (admin only). Deprecated: use PATCH instead.

    Args:
        user_email: Email of user to update
        user_request: Updated user information
        current_user_ctx: Currently authenticated user context with permissions
        db: Database session
        response: FastAPI Response object to manipulate the headers

    Returns:
        EmailUserResponse: Updated user information

    Raises:
        HTTPException: If user not found or update fails
    """
    result = await update_user_delegate(user_email, user_request, current_user_ctx, db)
    deprecation_date = "@" + str(int(datetime(2026, 2, 24, 23, 59, 59).timestamp()))
    response.headers["Deprecation"] = deprecation_date
    response.headers["Sunset"] = "Sun, 16 Aug 2026 23:59:59 UTC"
    return result


async def update_user_delegate(user_email: str, user_request: AdminUserUpdateRequest, current_user_ctx: dict, db: Session):
    """Update user information. Common function for both update_user and update_user_depreciated.
    Helps in reducing duplicate code and consistent behaviour. Move this entire code back to update_user after
    Sun, 16 Aug 2026 23:59:59 UTC.

    Args:
        user_email: Email of user to update
        user_request: Updated user information
        current_user_ctx: Currently authenticated user context with permissions
        db: Database session

    Returns:
        EmailUserResponse: Updated user information

    Raises:
        HTTPException: If user not found or update fails
    """
    auth_service = EmailAuthService(db)

    try:
        user = await auth_service.update_user(
            email=user_email,
            full_name=user_request.full_name,
            is_admin=user_request.is_admin,
            is_active=user_request.is_active,
            password_change_required=user_request.password_change_required,
            password=user_request.password,
            admin_origin_source="api",
        )

        logger.info(f"Admin {current_user_ctx['email']} updated user: {user.email}")

        result = EmailUserResponse.from_email_user(user)
        return result

    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)
    except PasswordValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating user {user_email}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update user")
# -------------------------->


@email_auth_router.delete("/admin/users/{user_email}", response_model=SuccessResponse)
@require_permission("admin.user_management")
async def delete_user(user_email: str, current_user_ctx: dict = Depends(get_current_user_with_permissions), db: Session = Depends(get_db)):
    """Delete/deactivate user (admin only).

    Args:
        user_email: Email of user to delete
        current_user_ctx: Currently authenticated user context with permissions
        db: Database session

    Returns:
        SuccessResponse: Success confirmation

    Raises:
        HTTPException: If user not found or deletion fails
    """
    auth_service = EmailAuthService(db)

    try:
        # Prevent admin from deleting themselves
        if user_email == current_user_ctx["email"]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete your own account")

        # Prevent deleting the last active admin user
        if await auth_service.is_last_active_admin(user_email):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete the last remaining admin user")

        # Hard delete using auth service
        await auth_service.delete_user(user_email)

        logger.info(f"Admin {current_user_ctx['email']} deleted user: {user_email}")

        db.commit()
        db.close()
        return SuccessResponse(success=True, message=f"User {user_email} has been deleted")

    except HTTPException:
        raise  # Re-raise HTTP exceptions as-is (401, 403, 404, etc.)
    except Exception as e:
        logger.error(f"Error deleting user {user_email}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete user")


@email_auth_router.post("/admin/users/{user_email}/unlock", response_model=SuccessResponse)
@require_permission("admin.user_management")
async def unlock_user(user_email: str, current_user_ctx: dict = Depends(get_current_user_with_permissions), db: Session = Depends(get_db)):
    """Unlock a user account by clearing lockout state and failed login counter.

    Args:
        user_email: Email address of the user to unlock.
        current_user_ctx: Authenticated admin context.
        db: Database session dependency.

    Returns:
        SuccessResponse: Unlock operation result.

    Raises:
        HTTPException: If user is missing or unlock operation fails.
    """
    auth_service = EmailAuthService(db)

    try:
        await auth_service.unlock_user_account(email=user_email, unlocked_by=current_user_ctx.get("email"))
        return SuccessResponse(success=True, message=f"User {user_email} has been unlocked")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        logger.error("Failed to unlock user %s: %s", user_email, exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to unlock user")
