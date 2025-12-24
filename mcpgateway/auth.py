# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/auth.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Shared authentication utilities.

This module provides common authentication functions that can be shared
across different parts of the application without creating circular imports.
"""

# Standard
import asyncio
from datetime import datetime, timezone
import hashlib
import logging
from typing import Any, Dict, Generator, Never, Optional
import uuid

# Third-Party
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import EmailUser, fresh_db_session, SessionLocal
from mcpgateway.plugins.framework import get_plugin_manager, GlobalContext, HttpAuthResolveUserPayload, HttpHeaderPayload, HttpHookType, PluginViolationError
from mcpgateway.utils.correlation_id import get_correlation_id
from mcpgateway.utils.verify_credentials import verify_jwt_token

# Security scheme
security = HTTPBearer(auto_error=False)


def _log_auth_event(
    logger: logging.Logger,
    message: str,
    level: int = logging.INFO,
    user_id: Optional[str] = None,
    auth_method: Optional[str] = None,
    auth_success: bool = False,
    security_event: Optional[str] = None,
    security_severity: str = "low",
    **extra_context,
) -> None:
    """Log authentication event with structured context and request_id.

    This helper creates structured log records that include request_id from the
    correlation ID context, enabling end-to-end tracing of authentication flows.

    Args:
        logger: Logger instance to use
        message: Log message
        level: Log level (default: INFO)
        user_id: User identifier
        auth_method: Authentication method used (jwt, api_token, etc.)
        auth_success: Whether authentication succeeded
        security_event: Type of security event (authentication, authorization, etc.)
        security_severity: Severity level (low, medium, high, critical)
        **extra_context: Additional context fields
    """
    # Get request_id from correlation ID context
    request_id = get_correlation_id()

    # Build structured log record
    extra = {
        "request_id": request_id,
        "entity_type": "auth",
        "auth_success": auth_success,
        "security_event": security_event or "authentication",
        "security_severity": security_severity,
    }

    if user_id:
        extra["user_id"] = user_id
    if auth_method:
        extra["auth_method"] = auth_method

    # Add any additional context
    extra.update(extra_context)

    # Log with structured context
    logger.log(level, message, extra=extra)


def get_db() -> Generator[Session, Never, None]:
    """Database dependency.

    Commits the transaction on successful completion to avoid implicit rollbacks
    for read-only operations. Rolls back explicitly on exception.

    Yields:
        Session: SQLAlchemy database session

    Raises:
        Exception: Re-raises any exception after rolling back the transaction.

    Examples:
        >>> db_gen = get_db()
        >>> db = next(db_gen)
        >>> hasattr(db, 'query')
        True
        >>> hasattr(db, 'close')
        True
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _get_personal_team_sync(user_email: str) -> Optional[str]:
    """Synchronous helper to get user's personal team using a fresh DB session.

    This runs in a thread pool to avoid blocking the event loop.

    Args:
        user_email: The user's email address.

    Returns:
        The personal team ID, or None if not found.
    """
    with fresh_db_session() as db:
        # Third-Party
        from sqlalchemy import select  # pylint: disable=import-outside-toplevel

        # First-Party
        from mcpgateway.db import EmailTeam, EmailTeamMember  # pylint: disable=import-outside-toplevel

        result = db.execute(select(EmailTeam).join(EmailTeamMember).where(EmailTeamMember.user_email == user_email, EmailTeam.is_personal.is_(True)))
        personal_team = result.scalar_one_or_none()
        return personal_team.id if personal_team else None


async def get_team_from_token(payload: Dict[str, Any]) -> Optional[str]:
    """
    Extract the team ID from an authentication token payload. If the token does
    not include a team, the user's personal team is retrieved from the database.

    This function uses a short-lived database session to avoid holding connections
    during slow downstream operations (like HTTP calls).

    This function behaves as follows:

    1. If `payload["teams"]` exists and is non-empty:
       Returns the first team ID from that list.

    2. If no teams are present in the payload:
       Fetches the user's teams (using `payload["sub"]` as the user email) and
       returns the ID of the personal team, if one exists.

    Args:
        payload (Dict[str, Any]):
            The token payload. Expected fields:
            - "sub" (str): The user's unique identifier (email).
            - "teams" (List[str], optional): List containing team ID.

    Returns:
        Optional[str]:
            The resolved team ID. Returns `None` if no team can be determined
            either from the payload or from the database.

    Examples:
        >>> import asyncio
        >>> # --- Case 1: Token has team ---
        >>> payload = {"sub": "user@example.com", "teams": ["team_456"]}
        >>> asyncio.run(get_team_from_token(payload))
        'team_456'
    """
    team_id = payload.get("teams")[0] if payload.get("teams") else None
    if isinstance(team_id, dict):
        team_id = team_id.get("id")
    user_email = payload.get("sub")

    # If no team found in token, get user's personal team using fresh DB session
    if not team_id and user_email:
        try:
            team_id = await asyncio.to_thread(_get_personal_team_sync, user_email)
        except Exception as e:
            logging.getLogger(__name__).warning(f"Failed to get personal team for {user_email}: {e}")
            team_id = None

    return team_id


def _check_token_revoked_sync(jti: str) -> bool:
    """Synchronous helper to check if a token is revoked.

    This runs in a thread pool to avoid blocking the event loop.

    Args:
        jti: The JWT ID to check.

    Returns:
        True if the token is revoked, False otherwise.
    """
    with fresh_db_session() as db:
        # Third-Party
        from sqlalchemy import select  # pylint: disable=import-outside-toplevel

        # First-Party
        from mcpgateway.db import TokenRevocation  # pylint: disable=import-outside-toplevel

        result = db.execute(select(TokenRevocation).where(TokenRevocation.jti == jti))
        return result.scalar_one_or_none() is not None


def _lookup_api_token_sync(token_hash: str) -> Optional[Dict[str, Any]]:
    """Synchronous helper to look up an API token by hash.

    This runs in a thread pool to avoid blocking the event loop.

    Args:
        token_hash: SHA256 hash of the API token.

    Returns:
        Dict with token info if found and active, None otherwise.
    """
    with fresh_db_session() as db:
        # Third-Party
        from sqlalchemy import select  # pylint: disable=import-outside-toplevel

        # First-Party
        from mcpgateway.db import EmailApiToken, utc_now  # pylint: disable=import-outside-toplevel

        result = db.execute(select(EmailApiToken).where(EmailApiToken.token_hash == token_hash, EmailApiToken.is_active.is_(True)))
        api_token = result.scalar_one_or_none()

        if api_token:
            # Check expiration
            if api_token.expires_at and api_token.expires_at < datetime.now(timezone.utc):
                return {"expired": True}

            # Check revocation
            # First-Party
            from mcpgateway.db import TokenRevocation  # pylint: disable=import-outside-toplevel

            revoke_result = db.execute(select(TokenRevocation).where(TokenRevocation.jti == api_token.jti))
            if revoke_result.scalar_one_or_none() is not None:
                return {"revoked": True}

            # Update last_used timestamp
            api_token.last_used = utc_now()
            db.commit()

            return {
                "user_email": api_token.user_email,
                "jti": api_token.jti,
            }
        return None


def _get_user_by_email_sync(email: str) -> Optional[EmailUser]:
    """Synchronous helper to get user by email.

    This runs in a thread pool to avoid blocking the event loop.

    Args:
        email: The user's email address.

    Returns:
        EmailUser if found, None otherwise.
    """
    with fresh_db_session() as db:
        # Third-Party
        from sqlalchemy import select  # pylint: disable=import-outside-toplevel

        result = db.execute(select(EmailUser).where(EmailUser.email == email))
        user = result.scalar_one_or_none()
        if user:
            # Detach from session and return a copy of attributes
            # since the session will be closed
            return EmailUser(
                email=user.email,
                password_hash=user.password_hash,
                full_name=user.full_name,
                is_admin=user.is_admin,
                is_active=user.is_active,
                email_verified_at=user.email_verified_at,
                created_at=user.created_at,
                updated_at=user.updated_at,
            )
        return None


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    request: Optional[object] = None,
) -> EmailUser:
    """Get current authenticated user from JWT token with revocation checking.

    Supports plugin-based custom authentication via HTTP_AUTH_RESOLVE_USER hook.

    Args:
        credentials: HTTP authorization credentials
        request: Optional request object for plugin hooks

    Returns:
        EmailUser: Authenticated user

    Raises:
        HTTPException: If authentication fails
    """
    logger = logging.getLogger(__name__)

    # NEW: Custom authentication hook - allows plugins to provide alternative auth
    # This hook is invoked BEFORE standard JWT/API token validation
    try:
        # Get plugin manager singleton
        plugin_manager = get_plugin_manager()

        if plugin_manager:
            # Extract client information
            client_host = None
            client_port = None
            if request and hasattr(request, "client") and request.client:
                client_host = request.client.host
                client_port = request.client.port

            # Serialize credentials for plugin
            credentials_dict = None
            if credentials:
                credentials_dict = {
                    "scheme": credentials.scheme,
                    "credentials": credentials.credentials,
                }

            # Extract headers from request
            # Note: Middleware modifies request.scope["headers"], so request.headers
            # will automatically reflect any modifications made by HTTP_PRE_REQUEST hooks
            headers = {}
            if request and hasattr(request, "headers"):
                headers = dict(request.headers)

            # Get request ID from correlation ID context (set by CorrelationIDMiddleware)
            request_id = get_correlation_id()
            if not request_id:
                # Fallback chain for safety
                if request and hasattr(request, "state") and hasattr(request.state, "request_id"):
                    request_id = request.state.request_id
                else:
                    request_id = uuid.uuid4().hex
                    logger.debug(f"Generated fallback request ID in get_current_user: {request_id}")

            # Get plugin contexts from request state if available
            global_context = getattr(request.state, "plugin_global_context", None) if request else None
            if not global_context:
                # Create global context
                global_context = GlobalContext(
                    request_id=request_id,
                    server_id=None,
                    tenant_id=None,
                )

            context_table = getattr(request.state, "plugin_context_table", None) if request else None

            # Invoke custom auth resolution hook
            # violations_as_exceptions=True so PluginViolationError is raised for explicit denials
            auth_result, context_table_result = await plugin_manager.invoke_hook(
                HttpHookType.HTTP_AUTH_RESOLVE_USER,
                payload=HttpAuthResolveUserPayload(
                    credentials=credentials_dict,
                    headers=HttpHeaderPayload(root=headers),
                    client_host=client_host,
                    client_port=client_port,
                ),
                global_context=global_context,
                local_contexts=context_table,
                violations_as_exceptions=True,  # Raise PluginViolationError for auth denials
            )

            # If plugin successfully authenticated user, return it
            if auth_result.modified_payload and isinstance(auth_result.modified_payload, dict):
                logger.info("User authenticated via plugin hook")
                # Create EmailUser from dict returned by plugin
                user_dict = auth_result.modified_payload
                user = EmailUser(
                    email=user_dict.get("email"),
                    password_hash=user_dict.get("password_hash", ""),
                    full_name=user_dict.get("full_name"),
                    is_admin=user_dict.get("is_admin", False),
                    is_active=user_dict.get("is_active", True),
                    email_verified_at=user_dict.get("email_verified_at"),
                    created_at=user_dict.get("created_at", datetime.now(timezone.utc)),
                    updated_at=user_dict.get("updated_at", datetime.now(timezone.utc)),
                )

                # Store auth_method in request.state so it can be accessed by RBAC middleware
                if request and auth_result.metadata:
                    auth_method = auth_result.metadata.get("auth_method")
                    if auth_method:
                        request.state.auth_method = auth_method
                        logger.debug(f"Stored auth_method '{auth_method}' in request.state")

                if request and context_table_result:
                    request.state.plugin_context_table = context_table_result

                if request and global_context:
                    request.state.plugin_global_context = global_context
                return user
            # If continue_processing=True (no payload), fall through to standard auth

    except PluginViolationError as e:
        # Plugin explicitly denied authentication with custom message
        logger.warning(f"Authentication denied by plugin: {e.message}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=e.message,  # Use plugin's custom error message
            headers={"WWW-Authenticate": "Bearer"},
        )
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        # Log but don't fail on plugin errors - fall back to standard auth
        logger.warning(f"HTTP_AUTH_RESOLVE_USER hook failed, falling back to standard auth: {e}")

    # EXISTING: Standard authentication (JWT, API tokens)
    if not credentials:
        logger.warning("No credentials provided")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    logger.debug("Attempting authentication with token: %s...", credentials.credentials[:20])
    email = None

    try:
        # Try JWT token first using the centralized verify_jwt_token function
        logger.debug("Attempting JWT token validation")
        payload = await verify_jwt_token(credentials.credentials)

        logger.debug("JWT token validated successfully")
        # Extract user identifier (support both new and legacy token formats)
        email = payload.get("sub")
        if email is None:
            # Try legacy format
            email = payload.get("email")

        if email is None:
            logger.debug("No email/sub found in JWT payload")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        logger.debug("JWT authentication successful for email: %s", email)

        # Check for token revocation if JTI is present (new format)
        # Uses fresh DB session via asyncio.to_thread to avoid blocking event loop
        jti = payload.get("jti")
        if jti:
            try:
                is_revoked = await asyncio.to_thread(_check_token_revoked_sync, jti)
                if is_revoked:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Token has been revoked",
                        headers={"WWW-Authenticate": "Bearer"},
                    )
            except HTTPException:
                raise
            except Exception as revoke_check_error:
                # Log the error but don't fail authentication for admin tokens
                logger.warning(f"Token revocation check failed for JTI {jti}: {revoke_check_error}")

        # Check team level token, if applicable. If public token, then will be defaulted to personal team.
        # Uses fresh DB session to avoid holding connection during downstream calls
        team_id = await get_team_from_token(payload)
        if request:
            request.state.team_id = team_id

    except HTTPException:
        # Re-raise HTTPException from verify_jwt_token (handles expired/invalid tokens)
        raise
    except Exception as jwt_error:
        # JWT validation failed, try database API token
        # Uses fresh DB session via asyncio.to_thread to avoid blocking event loop
        logger.debug("JWT validation failed with error: %s, trying database API token", jwt_error)
        try:
            token_hash = hashlib.sha256(credentials.credentials.encode()).hexdigest()
            logger.debug("Generated token hash: %s", token_hash)

            # Lookup API token using fresh session in thread pool
            api_token_info = await asyncio.to_thread(_lookup_api_token_sync, token_hash)
            logger.debug(f"Database lookup result: {api_token_info is not None}")

            if api_token_info:
                # Check for error conditions returned by helper
                if api_token_info.get("expired"):
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="API token expired",
                        headers={"WWW-Authenticate": "Bearer"},
                    )

                if api_token_info.get("revoked"):
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="API token has been revoked",
                        headers={"WWW-Authenticate": "Bearer"},
                    )

                # Use the email from the API token
                email = api_token_info["user_email"]
                logger.debug(f"API token authentication successful for email: {email}")
            else:
                logger.debug("API token not found in database")
                logger.debug("No valid authentication method found")
                # Neither JWT nor API token worked
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid authentication credentials",
                    headers={"WWW-Authenticate": "Bearer"},
                )
        except HTTPException:
            # Re-raise HTTP exceptions
            raise
        except Exception as e:
            # Neither JWT nor API token validation worked
            logger.debug(f"Database API token validation failed with exception: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )

    # Get user from database using fresh session in thread pool
    user = await asyncio.to_thread(_get_user_by_email_sync, email)

    if user is None:
        # Special case for platform admin - if user doesn't exist but token is valid
        # and email matches platform admin, create a virtual admin user object
        if email == getattr(settings, "platform_admin_email", "admin@example.com"):
            # Create a virtual admin user for authentication purposes
            user = EmailUser(
                email=email,
                password_hash="",  # nosec B106 - Not used for JWT authentication
                full_name=getattr(settings, "platform_admin_full_name", "Platform Administrator"),
                is_admin=True,
                is_active=True,
                email_verified_at=datetime.now(timezone.utc),
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
                headers={"WWW-Authenticate": "Bearer"},
            )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account disabled",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user
