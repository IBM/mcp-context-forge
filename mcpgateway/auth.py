# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/auth.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Authentication and Authorization Module.
Provides authentication middleware and dependencies for multi-user support:
- JWT token validation
- User authentication dependencies
- CSRF protection
- Legacy authentication support
- Permission checking
"""

# Standard
import logging
from typing import Optional

# Third-Party
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import SessionLocal, User
from mcpgateway.services.jwt_service import JWTService
from mcpgateway.services.user_service import UserService

logger = logging.getLogger(__name__)

# Security scheme for OpenAPI documentation
security = HTTPBearer(auto_error=False)


def get_db():
    """Database dependency.

    Yields:
        Session: SQLAlchemy database session
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_jwt_service(db: Session = Depends(get_db)):
    """Get JWT service dependency.

    Args:
        db: Database session dependency

    Returns:
        JWTService: JWT service instance
    """
    return JWTService(db)


def get_user_service(db: Session = Depends(get_db)):
    """Get user service dependency.

    Args:
        db: Database session dependency

    Returns:
        UserService: User service instance
    """
    return UserService(db)


async def get_current_user_optional(request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security), jwt_service: JWTService = Depends(get_jwt_service)) -> Optional[User]:
    """
    Get current user from JWT token (optional - doesn't raise error if no token).

    Args:
        request: FastAPI request object
        credentials: HTTP Bearer credentials
        jwt_service: JWT service for token validation

    Returns:
        User object if valid token provided, None otherwise
    """
    if not credentials:
        return None

    try:
        payload = await jwt_service.verify_token(credentials.credentials, request)
        return payload.get("user")
    except HTTPException:
        return None


async def get_current_user(request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security), jwt_service: JWTService = Depends(get_jwt_service)) -> User:
    """
    Get current user from JWT token (required).

    Args:
        request: FastAPI request object
        credentials: HTTP Bearer credentials
        jwt_service: JWT service for token validation

    Returns:
        User object

    Raises:
        HTTPException: If no valid token provided
    """
    if not settings.multi_user_enabled:
        # Legacy mode - return a mock admin user
        if settings.legacy_auth_mode:
            return _create_legacy_admin_user()

    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required", headers={"WWW-Authenticate": "Bearer"})

    try:
        payload = await jwt_service.verify_token(credentials.credentials, request)
        user_data = payload.get("user")

        if not user_data:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

        # Convert dict back to User object
        user = User(
            id=user_data["id"],
            username=user_data["username"],
            email=user_data.get("email"),
            full_name=user_data.get("full_name"),
            is_admin=user_data.get("is_admin", False),
            is_active=user_data.get("is_active", True),
        )

        return user

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in authentication: {e}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication failed")


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """
    Require admin privileges.

    Args:
        current_user: Current authenticated user

    Returns:
        User object

    Raises:
        HTTPException: If user is not admin
    """
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required")

    return current_user


async def require_active_user(current_user: User = Depends(get_current_user)) -> User:
    """
    Require active user account.

    Args:
        current_user: Current authenticated user

    Returns:
        User object

    Raises:
        HTTPException: If user is not active
    """
    if not current_user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is not active")

    return current_user


async def check_resource_access(
    user: User,
    resource_user_id: Optional[str],
    resource_scope_type: str = "global",
    resource_scope_team_id: Optional[str] = None,
    user_service: UserService = None,
) -> bool:
    """
    Check if user has access to a resource based on scope.

    Args:
        user: Current user
        resource_user_id: Owner of the resource
        resource_scope_type: Scope type (private, team, global)
        resource_scope_team_id: Team ID if team-scoped
        user_service: User service for team membership checks

    Returns:
        True if user has access
    """
    # Admin users can access everything
    if user.is_admin:
        return True

    # Global resources are accessible to everyone
    if resource_scope_type == "global":
        return True

    # Private resources - only owner can access
    if resource_scope_type == "private":
        return resource_user_id == user.id

    # Team resources - check team membership
    if resource_scope_type == "team" and resource_scope_team_id:
        if user_service:
            user_teams = await user_service.get_user_teams(user.id)
            team_ids = [team["id"] for team in user_teams]
            return resource_scope_team_id in team_ids

    return False


def require_resource_access(user: User = Depends(get_current_user), user_service: UserService = Depends(get_user_service)):
    """
    Dependency factory for resource access checking.

    Args:
        user: Current authenticated user
        user_service: User service for team membership checks

    Returns:
        function: Function that can check access to a specific resource
    """

    async def check_access(resource_user_id: Optional[str], resource_scope_type: str = "global", resource_scope_team_id: Optional[str] = None) -> bool:
        """
        Check access to a specific resource.

        Args:
            resource_user_id: Owner of the resource
            resource_scope_type: Scope type (private, team, global)
            resource_scope_team_id: Team ID if team-scoped

        Returns:
            bool: True if user has access
        """
        return await check_resource_access(
            user=user,
            resource_user_id=resource_user_id,
            resource_scope_type=resource_scope_type,
            resource_scope_team_id=resource_scope_team_id,
            user_service=user_service,
        )

    return check_access


async def validate_csrf_token(request: Request, current_user: User = Depends(get_current_user)) -> User:
    """
    Validate CSRF token for cookie-based authentication.

    Args:
        request: FastAPI request object
        current_user: Current authenticated user

    Returns:
        User object

    Raises:
        HTTPException: If CSRF validation fails
    """
    # Skip CSRF validation for bearer token authentication
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return current_user

    # For cookie-based auth, require CSRF token
    csrf_token = request.headers.get(settings.csrf_header_name)
    csrf_cookie = request.cookies.get(settings.csrf_token_name)

    if not csrf_token or not csrf_cookie or csrf_token != csrf_cookie:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token validation failed")

    return current_user


def _create_legacy_admin_user() -> User:
    """Create a legacy admin user for backward compatibility.

    Returns:
        User: Mock admin user for legacy mode
    """
    return User(
        id="legacy-admin",
        username=settings.basic_auth_user,
        email=None,
        full_name="Legacy Admin User",
        is_admin=True,
        is_active=True,
        password_hash="",
    )  # Not used in legacy mode


# Scoped access dependencies for different resources
class ScopeFilter:
    """Utility class for scope-based filtering."""

    @staticmethod
    def for_user(user: User, include_team: bool = True, include_global: bool = True):
        """
        Create scope filter conditions for a user.

        Note: This is a placeholder for future RBAC implementation.
        Currently returns a simple condition based on user access.

        Args:
            user: Current user
            include_team: Include team-scoped resources
            include_global: Include global resources

        Returns:
            str: Simple filter description (placeholder)
        """
        # Placeholder implementation - will be replaced with proper SQLAlchemy filters
        # when RBAC is implemented
        conditions = []

        if user.is_admin:
            conditions.append("admin_access")
        else:
            conditions.append("user_access")

        if include_team:
            conditions.append("team_access")

        if include_global:
            conditions.append("global_access")

        return "filter_conditions: " + ", ".join(conditions)


# Legacy authentication compatibility
async def get_current_user_legacy_compatible(
    request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security), jwt_service: JWTService = Depends(get_jwt_service)
) -> Optional[User]:
    """
    Get current user with legacy compatibility.
    Falls back to legacy auth if multi-user is disabled.

    Args:
        request: FastAPI request object
        credentials: HTTP Bearer credentials
        jwt_service: JWT service for token validation

    Returns:
        Optional[User]: User object if authenticated, None otherwise
    """
    if not settings.multi_user_enabled or settings.legacy_auth_mode:
        return _create_legacy_admin_user()

    return await get_current_user_optional(request, credentials, jwt_service)
