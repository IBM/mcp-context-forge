# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/http_auth_sessions.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Prakhar Singh

HTTP Auth Session Management Router

This module provides REST API endpoints for managing HTTP authentication sessions
"""

# Standard
from typing import Any, Dict, Generator, Optional
import uuid

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import EmailStr, ValidationError
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.admin import enforce_admin_csrf
from mcpgateway.db import HttpAuthSession, SessionLocal
from mcpgateway.middleware.rbac import get_current_user_with_permissions, require_permission
from mcpgateway.schemas import (
    HttpAuthSessionListResponse,
    HttpAuthSessionResponse,
    HttpAuthSessionTerminateResponse,
)
from mcpgateway.services.http_auth_session_service import HttpAuthSessionService
from mcpgateway.services.logging_service import LoggingService

# Initialize logging
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

# Create routers - separate user and admin endpoints
router_user = APIRouter(prefix="/auth/sessions", tags=["HTTP Auth Sessions - User"])
router_admin = APIRouter(prefix="/admin/sessions", tags=["HTTP Auth Sessions - Admin"])

# For backward compatibility, keep the old router but mark as deprecated
router = router_user


def get_db() -> Generator[Session, None, None]:
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


def validate_session_id(session_id: str) -> None:
    """Validate that session_id is a valid UUID format.

    Args:
        session_id: Session ID to validate

    Raises:
        HTTPException: If session_id is not a valid UUID format
    """
    try:
        uuid.UUID(session_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid session ID format. Must be a valid UUID.",
        ) from e


def get_current_session_id(request: Request) -> Optional[str]:
    """Extract current session ID from JWT token.

    Args:
        request: FastAPI request object

    Returns:
        Session ID from JWT jti claim, or None if not present
    """
    # The session ID is stored in the JWT's jti (JWT ID) claim
    # This is set during login in admin.py
    user = request.state.user if hasattr(request.state, "user") else None
    if user and hasattr(user, "jti"):
        return user.jti
    return None


# ============================================================================
# Phase 6: User Self-Service Endpoints
# ============================================================================


@router_user.get("/me", response_model=HttpAuthSessionListResponse)
async def list_my_sessions(
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> HttpAuthSessionListResponse:
    """List all active sessions for the current user.

    Phase 6: User self-service endpoint. Users can view their own sessions
    to monitor active logins and detect unauthorized access.

    Requires: Authentication only (no specific permissions needed)

    Args:
        request: FastAPI request object
        user: Authenticated user from JWT
        db: Database session

    Returns:
        HttpAuthSessionListResponse: List of user's active sessions

    Raises:
        HTTPException: If session retrieval fails
    """
    try:
        session_service = HttpAuthSessionService(db)
        user_email = user.get("email", "unknown")
        sessions = await session_service.list_user_sessions(user_email)

        # Get current session ID to mark it
        current_session_id = get_current_session_id(request)

        # Convert to response models
        session_responses = []
        for session in sessions:
            session_responses.append(
                HttpAuthSessionResponse(
                    session_id=session.session_id,
                    user_email=session.user_email,
                    created_at=session.created_at,
                    last_activity=session.last_activity,
                    ip_address=session.ip_address,
                    user_agent=session.user_agent,
                    device_info=session.device_info,
                    is_current=(session.session_id == current_session_id),
                )
            )

        user_email = user.get("email", "unknown")
        return HttpAuthSessionListResponse(
            sessions=session_responses,
            total_count=len(session_responses),
            user_email=user_email,
        )

    except Exception as e:
        user_email = user.get("email", "unknown")
        logger.error(f"Failed to list sessions for user {user_email}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve sessions",
        ) from e


@router_user.delete("/me/{session_id}", response_model=HttpAuthSessionTerminateResponse)
async def terminate_my_session(
    session_id: str,
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
    _csrf: None = Depends(enforce_admin_csrf),
) -> HttpAuthSessionTerminateResponse:
    """Terminate one of the current user's sessions.

    CSRF Protection: This endpoint requires CSRF token validation for browser-based
    requests to prevent cross-site request forgery attacks. API clients using
    Bearer tokens are exempt from CSRF validation.

    Phase 6: User self-service endpoint. Users can terminate their own sessions
    (e.g., logout from other devices). Cannot terminate the current session.

    Requires: Authentication only (no specific permissions needed)

    Args:
        session_id: Session ID to terminate
        request: FastAPI request object
        user: Authenticated user from JWT
        db: Database session

    Returns:
        HttpAuthSessionTerminateResponse: Termination result

    Raises:
        HTTPException: If session not found, not owned by user, or is current session
    """
    # Validate UUID format
    validate_session_id(session_id)

    try:
        # Verify session belongs to current user
        session = db.query(HttpAuthSession).filter(HttpAuthSession.session_id == session_id).first()

        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found",
            )

        # Verify session belongs to current user
        user_email = user.get("email", "unknown")
        if session.user_email != user_email:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot terminate another user's session",
            )

        # Prevent terminating current session
        current_session_id = get_current_session_id(request)
        if session_id == current_session_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot terminate current session. Use logout instead.",
            )

        # Terminate session
        session_service = HttpAuthSessionService(db)
        success = await session_service.terminate_session(session_id, reason="user_revoke")

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found or already terminated",
            )

        user_email = user.get("email", "unknown")
        logger.info(
            f"User {user_email} terminated their session {session_id}",
            extra={"user_email": user_email, "session_id": session_id},
        )

        return HttpAuthSessionTerminateResponse(
            success=True,
            session_id=session_id,
            message="Session terminated successfully",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to terminate session {session_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to terminate session",
        ) from e


# ============================================================================
# Phase 5: Admin Session Management Endpoints
# ============================================================================


@router_admin.get("", response_model=HttpAuthSessionListResponse)
@require_permission("sessions.read")
async def list_all_sessions(
    user_email: Optional[str] = Query(None, description="Filter sessions by this user's email address"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(50, ge=1, le=100, description="Number of sessions per page (max 100)"),
    user: Dict[str, Any] = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> HttpAuthSessionListResponse:
    """List all active HTTP auth sessions (admin only) with pagination.

    Phase 5: Admin endpoint for viewing all sessions across all users.
    Requires 'sessions.read' permission.

    Supports pagination to handle large numbers of sessions efficiently.
    Results are ordered by last_activity (most recent first).

    Note: total_count is computed on every request. For very large tables,
    consider caching this value or making it optional.

    Args:
        user_email: Optional filter - show only sessions for this specific user
        page: Page number (1-indexed, default: 1)
        page_size: Number of sessions per page (1-100, default: 50)
        user: Current authenticated admin user
        db: Database session

    Returns:
        HttpAuthSessionListResponse: Paginated list of active sessions

    Raises:
        HTTPException: If session retrieval fails
    """
    try:
        # Third-Party
        from sqlalchemy import desc
        from sqlalchemy import func as sql_func

        # Validate user_email parameter if provided (security: prevent SQL injection)
        if user_email:
            try:
                # Use Pydantic's EmailStr for validation
                # Third-Party
                from pydantic import TypeAdapter

                email_validator = TypeAdapter(EmailStr)
                email_validator.validate_python(user_email)
            except ValidationError as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid email format: {user_email}",
                ) from e

        # Build base query (lazy - not executed yet)
        query = db.query(HttpAuthSession)

        # Build filter conditions separately for reuse in count query
        filter_conditions = []
        if user_email:
            filter_conditions.append(HttpAuthSession.user_email == user_email)

        # Apply filters to query
        if filter_conditions:
            query = query.filter(*filter_conditions)

        # Get total count using the same filter conditions
        # More robust than extracting whereclause - rebuilds filters explicitly
        count_query = db.query(sql_func.count(HttpAuthSession.session_id))  # pylint: disable=not-callable  # SQLAlchemy func is callable
        if filter_conditions:
            count_query = count_query.filter(*filter_conditions)
        total_count = count_query.scalar() or 0

        # Order by last_activity (most recent first) - only for data query, not count
        query = query.order_by(desc(HttpAuthSession.last_activity))

        # Apply pagination (still lazy - adds OFFSET and LIMIT to query)
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)

        # Execute query and fetch results
        sessions = query.all()

        # Convert to response models
        session_responses = []
        for session in sessions:
            session_responses.append(
                HttpAuthSessionResponse(
                    session_id=session.session_id,
                    user_email=session.user_email,
                    created_at=session.created_at,
                    last_activity=session.last_activity,
                    ip_address=session.ip_address,
                    user_agent=session.user_agent,
                    device_info=session.device_info,
                    is_current=False,  # Admin view doesn't mark current session
                )
            )

        # Get user email from dict (get_current_user_with_permissions returns dict)
        admin_email = user.get("email", "unknown")

        logger.info(
            f"Admin {admin_email} listed sessions (page {page}/{(total_count + page_size - 1) // page_size})" + (f" for user {user_email}" if user_email else ""),
            extra={
                "admin_email": admin_email,
                "filter_user": user_email,
                "page": page,
                "page_size": page_size,
                "total_count": total_count,
                "returned_count": len(session_responses),
            },
        )

        return HttpAuthSessionListResponse(
            sessions=session_responses,
            total_count=total_count,  # Total count across all pages
            user_email=user_email,
        )

    except Exception as e:
        logger.error(f"Failed to list sessions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve sessions",
        ) from e


@router_admin.get("/{session_id}", response_model=HttpAuthSessionResponse)
@require_permission("sessions.read")
async def get_session_details(
    session_id: str,
    user: Dict[str, Any] = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> HttpAuthSessionResponse:
    """Get details of a specific session (admin only).

    Phase 5: Admin endpoint for viewing detailed information about a specific session.
    Useful for security investigations and audit purposes.
    Requires 'sessions.read' permission.

    Args:
        session_id: Session identifier
        user: Current authenticated admin user
        db: Database session

    Returns:
        HttpAuthSessionResponse: Detailed session information

    Raises:
        HTTPException: If session not found or retrieval fails
    """
    # Validate UUID format
    validate_session_id(session_id)

    try:
        session = db.query(HttpAuthSession).filter(HttpAuthSession.session_id == session_id).first()

        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found",
            )

        admin_email = user.get("email", "unknown")
        logger.info(
            f"Admin {admin_email} retrieved session details for {session_id}",
            extra={"admin_email": admin_email, "session_id": session_id, "target_user": session.user_email},
        )

        return HttpAuthSessionResponse(
            session_id=session.session_id,
            user_email=session.user_email,
            created_at=session.created_at,
            last_activity=session.last_activity,
            ip_address=session.ip_address,
            user_agent=session.user_agent,
            device_info=session.device_info,
            is_current=False,  # Admin view doesn't mark current session
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to retrieve session {session_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve session details",
        ) from e


@router_admin.delete("/{session_id}", response_model=HttpAuthSessionTerminateResponse)
@require_permission("sessions.terminate")
async def admin_terminate_session(
    session_id: str,
    reason: Optional[str] = Query("admin_revoke", description="Reason for termination"),
    user: Dict[str, Any] = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
    _csrf: None = Depends(enforce_admin_csrf),
) -> HttpAuthSessionTerminateResponse:
    """Terminate any user's session (admin only).

    CSRF Protection: This endpoint requires CSRF token validation for browser-based
    requests to prevent cross-site request forgery attacks. API clients using
    Bearer tokens are exempt from CSRF validation.

    Phase 5: Admin endpoint for terminating any session.
    Requires 'sessions.terminate' permission.

    Args:
        session_id: Session ID to terminate
        reason: Reason for termination
        user: Current authenticated admin user
        db: Database session

    Returns:
        HttpAuthSessionTerminateResponse: Termination result

    Raises:
        HTTPException: If session not found or termination fails
    """
    # Validate UUID format
    validate_session_id(session_id)

    try:
        # Get session info for logging
        session = db.query(HttpAuthSession).filter(HttpAuthSession.session_id == session_id).first()

        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found",
            )

        target_user_email = session.user_email

        # Terminate session
        session_service = HttpAuthSessionService(db)
        success = await session_service.terminate_session(session_id, reason=reason)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found or already terminated",
            )

        admin_email = user.get("email", "unknown")
        logger.info(
            f"Admin {admin_email} terminated session {session_id} for user {target_user_email}",
            extra={
                "admin_email": admin_email,
                "target_user": target_user_email,
                "session_id": session_id,
                "reason": reason,
            },
        )

        return HttpAuthSessionTerminateResponse(
            success=True,
            session_id=session_id,
            message=f"Session terminated successfully (reason: {reason})",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to terminate session {session_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to terminate session",
        ) from e


@router_admin.get("/user/{user_email}", response_model=HttpAuthSessionListResponse)
@require_permission("sessions.read")
async def list_user_sessions_admin(
    user_email: str,
    user: Dict[str, Any] = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> HttpAuthSessionListResponse:
    """List all sessions for a specific user (admin only).

    Phase 5: Admin endpoint for viewing a specific user's sessions.
    Requires 'sessions.read' permission.

    Args:
        user_email: Email of user to list sessions for
        user: Current authenticated admin user
        db: Database session

    Returns:
        HttpAuthSessionListResponse: List of user's active sessions

    Raises:
        HTTPException: If session retrieval fails
    """
    try:
        session_service = HttpAuthSessionService(db)
        sessions = await session_service.list_user_sessions(user_email)

        # Convert to response models
        session_responses = []
        for session in sessions:
            session_responses.append(
                HttpAuthSessionResponse(
                    session_id=session.session_id,
                    user_email=session.user_email,
                    created_at=session.created_at,
                    last_activity=session.last_activity,
                    ip_address=session.ip_address,
                    user_agent=session.user_agent,
                    device_info=session.device_info,
                    is_current=False,
                )
            )

        admin_email = user.get("email", "unknown")
        logger.info(
            f"Admin {admin_email} listed sessions for user {user_email}",
            extra={"admin_email": admin_email, "target_user": user_email, "count": len(session_responses)},
        )

        return HttpAuthSessionListResponse(
            sessions=session_responses,
            total_count=len(session_responses),
            user_email=user_email,
        )

    except Exception as e:
        logger.error(f"Failed to list sessions for user {user_email}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve sessions",
        ) from e
