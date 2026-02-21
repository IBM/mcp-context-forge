# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/ldap_auth.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

LDAP Authentication Router.
This module provides FastAPI routes for LDAP bind authentication,
directory sync triggers, and LDAP connection status.

Examples:
    >>> from fastapi import FastAPI
    >>> from mcpgateway.routers.ldap_auth import ldap_router
    >>> app = FastAPI()
    >>> app.include_router(ldap_router, tags=["LDAP Authentication"])
    >>> isinstance(ldap_router, APIRouter)
    True
"""

# Standard
from typing import Optional

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.auth import get_current_user
from mcpgateway.config import settings
from mcpgateway.db import EmailUser, SessionLocal, utc_now
from mcpgateway.middleware.rbac import require_permission
from mcpgateway.schemas import AuthenticationResponse, EmailUserResponse, LdapLoginRequest, LdapStatusResponse, LdapSyncResponse
from mcpgateway.services.ldap_service import LdapBindError, LdapConnectionError, LdapService
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.utils.orjson_response import ORJSONResponse

# Initialize logging
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

# Create router
ldap_router = APIRouter(prefix="/auth/ldap", tags=["LDAP Authentication"])

# Security scheme
bearer_scheme = HTTPBearer(auto_error=False)


def get_db():
    """Database dependency.

    Yields:
        Session: SQLAlchemy database session
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
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip
    return request.client.host if request.client else "unknown"


@ldap_router.post("/login", response_model=AuthenticationResponse)
async def ldap_login(login_request: LdapLoginRequest, request: Request, db: Session = Depends(get_db)):
    """Authenticate user via LDAP simple bind.

    Performs LDAP bind authentication and issues a JWT session token.
    If the user doesn't exist in the gateway, they are auto-provisioned
    from the LDAP directory entry (when ldap_auto_create_users is enabled).

    Args:
        login_request: LDAP login credentials (username + password)
        request: FastAPI request object
        db: Database session

    Returns:
        AuthenticationResponse: Access token and user info

    Raises:
        HTTPException: 401 if credentials invalid, 503 if LDAP unreachable

    Examples:
        >>> import asyncio
        >>> asyncio.iscoroutinefunction(ldap_login)
        True
    """
    ip_address = get_client_ip(request)
    ldap_service = LdapService(db)

    try:
        ldap_entry = ldap_service.authenticate(login_request.username, login_request.password)
    except LdapConnectionError as exc:
        logger.error("LDAP server unreachable during login: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LDAP server is unreachable. Please try again later.",
        )

    if not ldap_entry:
        logger.info("LDAP login failed for user %s from %s", login_request.username, ip_address)
        # Track failed attempt if user exists in gateway
        try:
            from mcpgateway.services.email_auth_service import EmailAuthService  # pylint: disable=import-outside-toplevel

            auth_svc = EmailAuthService(db)
            # Try email lookup by common patterns (uid@domain or direct email)
            domain_parts = [p.split("=")[1] for p in settings.ldap_base_dn.split(",") if "=" in p]
            domain = ".".join(domain_parts) if domain_parts else "ldap.local"
            candidate_email = f"{login_request.username}@{domain}".lower()
            existing = await auth_svc.get_user_by_email(candidate_email)
            if existing and existing.auth_provider == "ldap":
                existing.increment_failed_attempts()
                db.commit()
        except Exception:
            pass  # nosec B110 - Best effort lockout tracking
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid LDAP credentials",
        )

    # Get or create the gateway user from the LDAP entry
    user = await ldap_service.get_or_create_user(ldap_entry)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="LDAP user auto-provisioning is disabled. Contact your administrator.",
        )

    # Check account lockout
    if user.is_account_locked():
        logger.info("LDAP login rejected for locked account: %s", user.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is locked due to too many failed login attempts. Try again later.",
        )

    # Successful login: reset failed attempts and update last login
    user.reset_failed_attempts()
    user.last_login = utc_now()
    try:
        db.commit()
    except Exception:
        pass  # nosec B110 - Non-critical update

    # Log auth event
    try:
        # First-Party
        from mcpgateway.db import EmailAuthEvent

        event = EmailAuthEvent(
            user_email=user.email,
            event_type="ldap_login",
            ip_address=ip_address,
            user_agent=request.headers.get("User-Agent", "unknown"),
            details=f"LDAP bind login from DN: {ldap_entry.dn}",
        )
        db.add(event)
        db.commit()
    except Exception as exc:
        logger.debug("Failed to log LDAP auth event: %s", exc)

    # Create JWT access token
    # First-Party
    from mcpgateway.routers.email_auth import create_access_token

    access_token, expires_in = await create_access_token(user)

    logger.info("LDAP login successful: %s (uid: %s)", user.email, ldap_entry.uid)

    return AuthenticationResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=expires_in,
        user=EmailUserResponse.from_email_user(user),
    )  # nosec B106 - OAuth2 token type


@ldap_router.get("/status", response_model=LdapStatusResponse)
async def ldap_status(current_user: EmailUser = Depends(get_current_user)):
    """Check LDAP connection status.

    Requires admin privileges. Returns whether the LDAP server is reachable
    and current configuration details.

    Args:
        current_user: Authenticated admin user (from JWT)

    Returns:
        LdapStatusResponse: LDAP connection status

    Raises:
        HTTPException: 403 if not admin

    Examples:
        >>> import asyncio
        >>> asyncio.iscoroutinefunction(ldap_status)
        True
    """
    if not getattr(current_user, "is_admin", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required to view LDAP status",
        )

    db = SessionLocal()
    try:
        ldap_service = LdapService(db)
        connected, error = ldap_service.check_connection()

        last_sync_str = None
        if LdapService._last_sync_at:
            last_sync_str = LdapService._last_sync_at.isoformat()

        # Sanitize error message to avoid leaking internal details
        sanitized_error = "Connection failed" if error else None

        return LdapStatusResponse(
            connected=connected,
            server_uri=settings.ldap_uri,
            base_dn=settings.ldap_base_dn,
            sync_enabled=settings.ldap_sync_enabled,
            last_sync_at=last_sync_str,
            error=sanitized_error,
        )
    finally:
        db.close()


@ldap_router.post("/sync", response_model=LdapSyncResponse)
async def ldap_sync(current_user: EmailUser = Depends(get_current_user), db: Session = Depends(get_db)):
    """Trigger an LDAP directory sync.

    Requires admin privileges. Imports users and groups from the LDAP
    directory into the gateway database.

    Args:
        current_user: Authenticated admin user
        db: Database session

    Returns:
        LdapSyncResponse: Sync results with counts

    Raises:
        HTTPException: 403 if not admin, 503 if LDAP unreachable

    Examples:
        >>> import asyncio
        >>> asyncio.iscoroutinefunction(ldap_sync)
        True
    """
    if not getattr(current_user, "is_admin", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required to trigger LDAP sync",
        )

    ldap_service = LdapService(db)
    try:
        result = await ldap_service.sync_directory()
    except LdapConnectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"LDAP server unreachable: {exc}",
        )

    return LdapSyncResponse(
        users_synced=result.users_synced,
        groups_synced=result.groups_synced,
        users_removed=result.users_removed,
        groups_removed=result.groups_removed,
        errors=result.errors,
    )
