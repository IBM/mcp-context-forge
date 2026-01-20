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
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPBearer
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.auth import get_current_user
from mcpgateway.config import settings
from mcpgateway.db import EmailUser, SessionLocal, utc_now
from mcpgateway.middleware.rbac import get_current_user_with_permissions, require_permission
from mcpgateway.schemas import (
    AuthenticationResponse,
    AuthEventResponse,
    ChangePasswordRequest,
    CursorPaginatedUsersResponse,
    EmailLoginRequest,
    EmailRegistrationRequest,
    EmailUserResponse,
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

    # Get user's teams for namespace information (ensure safe access)
    try:
        teams = user.get_teams() if callable(getattr(user, "get_teams", None)) else []
    except Exception:
        teams = []

    # Normalize teams into JSON-serializable primitives
    safe_teams = []
    for team in teams or []:
        try:
            safe_teams.append(
                {
                    "id": str(getattr(team, "id", None)) if getattr(team, "id", None) is not None else None,
                    "name": str(getattr(team, "name", "")),
                    "slug": str(getattr(team, "slug", "")),
                    "is_personal": bool(getattr(team, "is_personal", False)),
                    "role": str(next((m.role for m in getattr(user, "team_memberships", []) if getattr(m, "team_id", None) == getattr(team, "id", None)), "member")),
                }
            )
        except Exception:
            # Fallback to a string representation if anything goes wrong
            try:
                safe_teams.append({"id": None, "name": str(team), "slug": str(team), "is_personal": False, "role": "member"})
            except Exception:
                safe_teams.append({"id": None, "name": "", "slug": "", "is_personal": False, "role": "member"})

    # Create enhanced JWT payload with team and namespace information
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
        # Namespace access (backwards compatible)
        "namespaces": [f"user:{getattr(user, 'email', '')}", *[f"team:{t.get('slug', '')}" for t in safe_teams], "public"],
        # Token scoping (if provided)
        "scopes": token_scopes or {"server_id": None, "permissions": ["*"], "ip_restrictions": [], "time_restrictions": {}},
    }

    # For admin users: omit "teams" key entirely to enable unrestricted access bypass
    # For regular users: include teams for proper team-based scoping
    if not bool(getattr(user, "is_admin", False)):
        # Use only team IDs for the "teams" claim to match /tokens behavior
        payload["teams"] = [t["id"] for t in safe_teams if t.get("id")]

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
                is_using_default_password = password_service.verify_password(settings.default_user_password.get_secret_value(), user.password_hash)  # nosec B105
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
async def register(registration_request: EmailRegistrationRequest, request: Request, db: Session = Depends(get_db)):
    """Register a new user account.

    Args:
        registration_request: Registration information
        request: FastAPI request object
        db: Database session

    Returns:
        AuthenticationResponse: Access token and user info

    Raises:
        HTTPException: If registration fails

    Examples:
        Request JSON:
            {
              "email": "new@example.com",
              "password": "secure_password",
              "full_name": "New User"
            }
    """
    auth_service = EmailAuthService(db)
    get_client_ip(request)
    get_user_agent(request)

    try:
        # Create new user
        user = await auth_service.create_user(
            email=registration_request.email,
            password=registration_request.password,
            full_name=registration_request.full_name,
            is_admin=False,  # Regular users cannot self-register as admin
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
) -> Union[CursorPaginatedUsersResponse, List[EmailUserResponse]]:
    """List all users (admin only) with cursor-based pagination support.

    Args:
        cursor: Pagination cursor for fetching the next set of results
        limit: Maximum number of users to return. Use 0 for all users (no limit).
            If not specified, uses pagination_default_page_size (default: 50).
        include_pagination: Whether to include cursor pagination metadata in the response (default: false)
        current_user_ctx: Currently authenticated user context with permissions

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

    db = current_user_ctx["db"]
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
async def list_all_auth_events(limit: int = 100, offset: int = 0, user_email: Optional[str] = None, current_user_ctx: dict = Depends(get_current_user_with_permissions)):
    """List authentication events for all users (admin only).

    Args:
        limit: Maximum number of events to return
        offset: Number of events to skip
        user_email: Filter events by specific user email
        current_user_ctx: Currently authenticated user context with permissions

    Returns:
        List[AuthEventResponse]: Authentication events

    Raises:
        HTTPException: If user is not admin

    Examples:
        >>> # GET /auth/email/admin/events?limit=50&user_email=user@example.com
        >>> # Headers: Authorization: Bearer <admin_token>
    """

    db = current_user_ctx["db"]
    auth_service = EmailAuthService(db)

    try:
        events = await auth_service.get_auth_events(email=user_email, limit=limit, offset=offset)

        return [AuthEventResponse.model_validate(event) for event in events]

    except Exception as e:
        logger.error(f"Error getting auth events: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve authentication events")


@email_auth_router.post("/admin/users", response_model=EmailUserResponse, status_code=status.HTTP_201_CREATED)
@require_permission("admin.user_management")
async def create_user(user_request: EmailRegistrationRequest, current_user_ctx: dict = Depends(get_current_user_with_permissions)):
    """Create a new user account (admin only).

    Args:
        user_request: User creation information
        current_user_ctx: Currently authenticated user context with permissions

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
    db = current_user_ctx["db"]
    auth_service = EmailAuthService(db)

    try:
        # Create new user with admin privileges
        user = await auth_service.create_user(
            email=user_request.email,
            password=user_request.password,
            full_name=user_request.full_name,
            is_admin=user_request.is_admin,
            auth_provider="local",
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
async def get_user(user_email: str, current_user_ctx: dict = Depends(get_current_user_with_permissions)):
    """Get user by email (admin only).

    Args:
        user_email: Email of user to retrieve
        current_user_ctx: Currently authenticated user context with permissions

    Returns:
        EmailUserResponse: User information

    Raises:
        HTTPException: If user not found
    """
    db = current_user_ctx["db"]
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


@email_auth_router.put("/admin/users/{user_email}", response_model=EmailUserResponse)
@require_permission("admin.user_management")
async def update_user(user_email: str, user_request: EmailRegistrationRequest, current_user_ctx: dict = Depends(get_current_user_with_permissions)):
    """Update user information (admin only).

    Args:
        user_email: Email of user to update
        user_request: Updated user information
        current_user_ctx: Currently authenticated user context with permissions

    Returns:
        EmailUserResponse: Updated user information

    Raises:
        HTTPException: If user not found or update fails
    """
    db = current_user_ctx["db"]
    auth_service = EmailAuthService(db)

    try:
        # Get existing user
        user = await auth_service.get_user_by_email(user_email)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        # Update user fields
        user.full_name = user_request.full_name
        user.is_admin = getattr(user_request, "is_admin", user.is_admin)

        # Update password if provided
        if user_request.password:
            # For admin updates, we need to directly update the password hash
            # since we don't have the old password to verify
            # First-Party
            from mcpgateway.services.argon2_service import Argon2PasswordService

            password_service = Argon2PasswordService()

            # Validate the new password meets requirements
            auth_service.validate_password(user_request.password)

            # Update password hash directly
            user.password_hash = password_service.hash_password(user_request.password)
            user.password_change_required = False  # Clear password change requirement
            user.password_changed_at = utc_now()  # Update password change timestamp

        db.commit()
        db.refresh(user)

        logger.info(f"Admin {current_user_ctx['email']} updated user: {user.email}")

        return EmailUserResponse.from_email_user(user)

    except HTTPException:
        raise  # Re-raise HTTP exceptions as-is (401, 403, 404, etc.)
    except Exception as e:
        logger.error(f"Error updating user {user_email}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update user")


@email_auth_router.delete("/admin/users/{user_email}", response_model=SuccessResponse)
@require_permission("admin.user_management")
async def delete_user(user_email: str, current_user_ctx: dict = Depends(get_current_user_with_permissions)):
    """Delete/deactivate user (admin only).

    Args:
        user_email: Email of user to delete
        current_user_ctx: Currently authenticated user context with permissions

    Returns:
        SuccessResponse: Success confirmation

    Raises:
        HTTPException: If user not found or deletion fails
    """
    db = current_user_ctx["db"]
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

        return SuccessResponse(success=True, message=f"User {user_email} has been deleted")

    except HTTPException:
        raise  # Re-raise HTTP exceptions as-is (401, 403, 404, etc.)
    except Exception as e:
        logger.error(f"Error deleting user {user_email}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete user")
