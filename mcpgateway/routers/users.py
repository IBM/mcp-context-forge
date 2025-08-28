# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/users.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

User Management API Routes.
Provides user management endpoints for administrators:
- User CRUD operations
- User activation/deactivation
- User statistics and reporting
- Authentication event logs
"""

# Standard
import logging
from typing import Optional

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.auth import get_current_user, get_db, get_user_service, require_admin
from mcpgateway.db import AuthEvent, User
from mcpgateway.schemas import (
    AuthEventListResponse,
    AuthEventResponse,
    ErrorResponse,
    UserCreate,
    UserListResponse,
    UserProfileResponse,
    UserResponse,
    UserStatsResponse,
    UserUpdate,
)
from mcpgateway.services.user_service import UserService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["User Management"])


@router.post(
    "/",
    response_model=UserResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Validation error"},
        409: {"model": ErrorResponse, "description": "User already exists"},
        403: {"model": ErrorResponse, "description": "Admin privileges required"},
    },
)
@router.post("", include_in_schema=False)  # Support both /users and /users/
async def create_user(request: Request, user_data: UserCreate, current_user: User = Depends(require_admin), user_service: UserService = Depends(get_user_service)):
    """
    Create a new user.

    Requires admin privileges. Creates a new user with the specified details.
    """
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    user = await user_service.create_user(
        username=user_data.username,
        password=user_data.password,
        email=user_data.email,
        full_name=user_data.full_name,
        is_admin=user_data.is_admin,
        created_by=current_user.id,
        ip_address=client_ip,
        user_agent=user_agent,
    )

    logger.info(f"User created by admin {current_user.username}: {user.username}")
    return UserResponse.from_orm(user)


@router.get("/", response_model=UserListResponse, responses={403: {"model": ErrorResponse, "description": "Admin privileges required"}})
@router.get("", include_in_schema=False)  # Support both /users and /users/
async def list_users(
    current_user: User = Depends(require_admin),
    user_service: UserService = Depends(get_user_service),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(50, ge=1, le=100, description="Maximum number of records to return"),
    search: Optional[str] = Query(None, description="Search term for username, email, or full name"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
):
    """
    List users with optional filtering.

    Requires admin privileges. Returns paginated list of users.
    """
    users = await user_service.list_users(skip=skip, limit=limit, search=search, is_active=is_active)

    # Get total count for pagination
    # In a real implementation, you'd want a more efficient count query
    total_users = await user_service.list_users(search=search, is_active=is_active)
    total = len(total_users)

    return UserListResponse(users=[UserResponse.from_orm(user) for user in users], total=total, page=(skip // limit) + 1, per_page=limit)


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    responses={
        404: {"model": ErrorResponse, "description": "User not found"},
        403: {"model": ErrorResponse, "description": "Admin privileges required"},
    },
)
async def get_user(user_id: str, current_user: User = Depends(require_admin), user_service: UserService = Depends(get_user_service)):
    """
    Get user by ID.

    Requires admin privileges. Returns detailed user information.
    """
    user = await user_service.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    return UserResponse.from_orm(user)


@router.put(
    "/{user_id}",
    response_model=UserResponse,
    responses={
        404: {"model": ErrorResponse, "description": "User not found"},
        409: {"model": ErrorResponse, "description": "Email already exists"},
        403: {"model": ErrorResponse, "description": "Admin privileges required"},
    },
)
async def update_user(
    user_id: str,
    request: Request,
    user_updates: UserUpdate,
    current_user: User = Depends(require_admin),
    user_service: UserService = Depends(get_user_service),
):
    """
    Update user information.

    Requires admin privileges. Updates the specified user's information.
    """
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    user = await user_service.update_user(
        user_id=user_id,
        email=user_updates.email,
        full_name=user_updates.full_name,
        is_active=user_updates.is_active,
        is_admin=user_updates.is_admin,
        updated_by=current_user.id,
        ip_address=client_ip,
        user_agent=user_agent,
    )

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    logger.info(f"User updated by admin {current_user.username}: {user.username}")
    return UserResponse.from_orm(user)


@router.delete(
    "/{user_id}",
    responses={
        404: {"model": ErrorResponse, "description": "User not found"},
        403: {"model": ErrorResponse, "description": "Admin privileges required"},
        400: {"model": ErrorResponse, "description": "Cannot delete own account"},
    },
)
async def delete_user(
    user_id: str,
    request: Request,
    current_user: User = Depends(require_admin),
    user_service: UserService = Depends(get_user_service),
    db: Session = Depends(get_db),
):
    """
    Delete user account.

    Requires admin privileges. Permanently deletes the user account.
    Cannot delete own account.
    """
    if user_id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete your own account")

    user = await user_service.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    # Log the deletion before deleting
    await user_service._log_auth_event(
        event_type="user_deleted",
        user_id=current_user.id,
        username=current_user.username,
        success=True,
        ip_address=client_ip,
        user_agent=user_agent,
        details={"deleted_user_id": user_id, "deleted_username": user.username},
    )

    # Delete the user
    db.delete(user)
    db.commit()

    logger.warning(f"User deleted by admin {current_user.username}: {user.username}")
    return {"message": f"User {user.username} deleted successfully"}


@router.post(
    "/{user_id}/activate",
    response_model=UserResponse,
    responses={
        404: {"model": ErrorResponse, "description": "User not found"},
        403: {"model": ErrorResponse, "description": "Admin privileges required"},
    },
)
async def activate_user(user_id: str, request: Request, current_user: User = Depends(require_admin), user_service: UserService = Depends(get_user_service)):
    """
    Activate user account.

    Requires admin privileges. Activates a deactivated user account.
    """
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    user = await user_service.update_user(user_id=user_id, is_active=True, updated_by=current_user.id, ip_address=client_ip, user_agent=user_agent)

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    logger.info(f"User activated by admin {current_user.username}: {user.username}")
    return UserResponse.from_orm(user)


@router.post(
    "/{user_id}/deactivate",
    response_model=UserResponse,
    responses={
        404: {"model": ErrorResponse, "description": "User not found"},
        403: {"model": ErrorResponse, "description": "Admin privileges required"},
        400: {"model": ErrorResponse, "description": "Cannot deactivate own account"},
    },
)
async def deactivate_user(user_id: str, request: Request, current_user: User = Depends(require_admin), user_service: UserService = Depends(get_user_service)):
    """
    Deactivate user account.

    Requires admin privileges. Deactivates a user account.
    Cannot deactivate own account.
    """
    if user_id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot deactivate your own account")

    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    user = await user_service.update_user(user_id=user_id, is_active=False, updated_by=current_user.id, ip_address=client_ip, user_agent=user_agent)

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    logger.info(f"User deactivated by admin {current_user.username}: {user.username}")
    return UserResponse.from_orm(user)


@router.get(
    "/{user_id}/profile",
    response_model=UserProfileResponse,
    responses={
        404: {"model": ErrorResponse, "description": "User not found"},
        403: {"model": ErrorResponse, "description": "Admin privileges required"},
    },
)
async def get_user_profile(user_id: str, current_user: User = Depends(require_admin), user_service: UserService = Depends(get_user_service), db: Session = Depends(get_db)):
    """
    Get detailed user profile.

    Requires admin privileges. Returns comprehensive user information
    including team memberships, token counts, and security information.
    """
    user = await user_service.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Get user's teams
    teams = await user_service.get_user_teams(user_id)

    # Get active token count
    # First-Party
    from mcpgateway.db import ApiToken

    active_tokens = db.query(ApiToken).filter(ApiToken.user_id == user_id, ApiToken.is_active.is_(True)).count()

    # Get last login IP
    last_auth_event = db.query(AuthEvent).filter(AuthEvent.user_id == user_id, AuthEvent.event_type == "login_success").order_by(AuthEvent.timestamp.desc()).first()

    last_login_ip = last_auth_event.ip_address if last_auth_event else None

    # Check if account is locked
    # First-Party
    from mcpgateway.db import utc_now

    account_locked = user.locked_until and user.locked_until > utc_now()

    return UserProfileResponse(user=UserResponse.from_orm(user), teams=teams, active_tokens=active_tokens, last_login_ip=last_login_ip, account_locked=account_locked)


@router.get(
    "/{user_id}/auth-events",
    response_model=AuthEventListResponse,
    responses={
        404: {"model": ErrorResponse, "description": "User not found"},
        403: {"model": ErrorResponse, "description": "Admin privileges required"},
    },
)
async def get_user_auth_events(
    user_id: str,
    current_user: User = Depends(require_admin),
    user_service: UserService = Depends(get_user_service),
    db: Session = Depends(get_db),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(50, ge=1, le=100, description="Maximum number of records to return"),
    event_type: Optional[str] = Query(None, description="Filter by event type"),
):
    """
    Get authentication events for a user.

    Requires admin privileges. Returns paginated list of authentication
    events for the specified user.
    """
    user = await user_service.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Query auth events
    query = db.query(AuthEvent).filter(AuthEvent.user_id == user_id)

    if event_type:
        query = query.filter(AuthEvent.event_type == event_type)

    # Get total count
    total = query.count()

    # Get paginated results
    events = query.order_by(AuthEvent.timestamp.desc()).offset(skip).limit(limit).all()

    return AuthEventListResponse(events=[AuthEventResponse.from_orm(event) for event in events], total=total, page=(skip // limit) + 1, per_page=limit)


@router.get("/stats/overview", response_model=UserStatsResponse, responses={403: {"model": ErrorResponse, "description": "Admin privileges required"}})
async def get_user_statistics(current_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """
    Get user statistics overview.

    Requires admin privileges. Returns comprehensive statistics
    about users, teams, and authentication activity.
    """
    # Standard
    from datetime import timedelta

    # First-Party
    from mcpgateway.db import ApiToken, Team, utc_now

    # Total users
    total_users = db.query(User).count()

    # Active users
    active_users = db.query(User).filter(User.is_active.is_(True)).count()

    # Admin users
    admin_users = db.query(User).filter(User.is_admin.is_(True)).count()

    # New users in last 30 days
    thirty_days_ago = utc_now() - timedelta(days=30)
    new_users_last_30_days = db.query(User).filter(User.created_at >= thirty_days_ago).count()

    # Total teams
    total_teams = db.query(Team).count()

    # Total active API tokens
    total_api_tokens = db.query(ApiToken).filter(ApiToken.is_active.is_(True)).count()

    # Login events in last 24 hours
    twenty_four_hours_ago = utc_now() - timedelta(hours=24)
    login_events_last_24h = db.query(AuthEvent).filter(AuthEvent.event_type == "login_success", AuthEvent.timestamp >= twenty_four_hours_ago).count()

    return UserStatsResponse(
        total_users=total_users,
        active_users=active_users,
        admin_users=admin_users,
        new_users_last_30_days=new_users_last_30_days,
        total_teams=total_teams,
        total_api_tokens=total_api_tokens,
        login_events_last_24h=login_events_last_24h,
    )


# Self-service endpoints (users can manage their own profile)


@router.get("/me/profile", response_model=UserProfileResponse)
async def get_my_profile(current_user: User = Depends(get_current_user), user_service: UserService = Depends(get_user_service), db: Session = Depends(get_db)):
    """
    Get current user's profile.

    Returns comprehensive profile information for the authenticated user.
    """
    # Get user's teams
    teams = await user_service.get_user_teams(current_user.id)

    # Get active token count
    # First-Party
    from mcpgateway.db import ApiToken

    active_tokens = db.query(ApiToken).filter(ApiToken.user_id == current_user.id, ApiToken.is_active.is_(True)).count()

    # Get last login IP
    last_auth_event = db.query(AuthEvent).filter(AuthEvent.user_id == current_user.id, AuthEvent.event_type == "login_success").order_by(AuthEvent.timestamp.desc()).first()

    last_login_ip = last_auth_event.ip_address if last_auth_event else None

    # Check if account is locked
    # First-Party
    from mcpgateway.db import utc_now

    account_locked = current_user.locked_until and current_user.locked_until > utc_now()

    return UserProfileResponse(user=UserResponse.from_orm(current_user), teams=teams, active_tokens=active_tokens, last_login_ip=last_login_ip, account_locked=account_locked)


@router.put("/me", response_model=UserResponse)
async def update_my_profile(request: Request, user_updates: UserUpdate, current_user: User = Depends(get_current_user), user_service: UserService = Depends(get_user_service)):
    """
    Update current user's profile.

    Users can update their own email and full name.
    Admin status and active status can only be changed by admins.
    """
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    # Users cannot change their own admin/active status
    if not current_user.is_admin:
        user_updates.is_admin = None
        user_updates.is_active = None

    user = await user_service.update_user(
        user_id=current_user.id,
        email=user_updates.email,
        full_name=user_updates.full_name,
        is_active=user_updates.is_active,
        is_admin=user_updates.is_admin,
        updated_by=current_user.id,
        ip_address=client_ip,
        user_agent=user_agent,
    )

    logger.info(f"User updated own profile: {current_user.username}")
    return UserResponse.from_orm(user)
