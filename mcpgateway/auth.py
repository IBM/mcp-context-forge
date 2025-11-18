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
from mcpgateway.db import EmailUser, SessionLocal
from mcpgateway.plugins.framework import get_plugin_manager, GlobalContext, HttpAuthResolveUserPayload, HttpHeaderPayload, HttpHookType, PluginViolationError
from mcpgateway.services.team_management_service import TeamManagementService  # pylint: disable=import-outside-toplevel
from mcpgateway.utils.verify_credentials import verify_jwt_token

# Security scheme
bearer_scheme = HTTPBearer(auto_error=False)


def get_db() -> Generator[Session, Never, None]:
    """Database dependency.

    Yields:
        Session: SQLAlchemy database session

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
    finally:
        db.close()


async def get_team_from_token(payload: Dict[str, Any], db: Session) -> Optional[str]:
    """
    Extract the team ID from an authentication token payload. If the token does
    not include a team, the user's personal team is retrieved from the database.

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
        db (Session):
            SQLAlchemy database session used to query team data.

    Returns:
        Optional[str]:
            The resolved team ID. Returns `None` if no team can be determined
            either from the payload or from the database.

    Examples:
        >>> import sys, asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>>
        >>> # --- Mock setup for both tests ---
        >>> mock_db = MagicMock()
        >>>
        >>> # Patch TeamManagementService import path dynamically
        >>> mock_team_service = AsyncMock()
        >>> mock_team = MagicMock(id="personal_team_123", is_personal=True)
        >>> mock_team_service.get_user_teams.return_value = [mock_team]
        >>>
        >>> sys.modules['mcpgateway.services.team_management_service'] = type(sys)("dummy")
        >>> sys.modules['mcpgateway.services.team_management_service'].TeamManagementService = lambda db: mock_team_service
        >>>
        >>> # --- Case 1: Token has team ---
        >>> payload = {"sub": "user@example.com", "teams": ["team_456"]}
        >>> asyncio.run(get_team_from_token(payload, mock_db))
        'team_456'
        >>> del sys.modules["mcpgateway.services.team_management_service"]
    """
    team_id = payload.get("teams")[0] if payload.get("teams") else None
    user_email = payload.get("sub")
    # If no team found in token, get user's personal team
    if not team_id:

        team_service = TeamManagementService(db)
        user_teams = await team_service.get_user_teams(user_email, include_personal=True)
        personal_team = next((team for team in user_teams if team.is_personal), None)
        team_id = personal_team.id if personal_team else None

    return team_id


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
    request: Optional[object] = None,
) -> EmailUser:
    """Get current authenticated user from JWT token with revocation checking.

    Supports plugin-based custom authentication via HTTP_AUTH_RESOLVE_USER hook.

    Args:
        credentials: HTTP authorization credentials
        db: Database session
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

            # Get request ID from request state (set by middleware) or generate new one
            request_id = None
            if request and hasattr(request, "state") and hasattr(request.state, "request_id"):
                request_id = request.state.request_id
            else:
                request_id = uuid.uuid4().hex

            # Create global context
            global_context = GlobalContext(
                request_id=request_id,
                server_id=None,
                tenant_id=None,
            )

            # Invoke custom auth resolution hook
            # violations_as_exceptions=True so PluginViolationError is raised for explicit denials
            auth_result, _ = await plugin_manager.invoke_hook(
                HttpHookType.HTTP_AUTH_RESOLVE_USER,
                payload=HttpAuthResolveUserPayload(
                    credentials=credentials_dict,
                    headers=HttpHeaderPayload(root=headers),
                    client_host=client_host,
                    client_port=client_port,
                ),
                global_context=global_context,
                local_contexts=None,
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
                if request and hasattr(request, "state") and auth_result.metadata:
                    auth_method = auth_result.metadata.get("auth_method")
                    if auth_method:
                        request.state.auth_method = auth_method
                        logger.debug(f"Stored auth_method '{auth_method}' in request.state")

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
        jti = payload.get("jti")
        if jti:
            try:
                # First-Party
                from mcpgateway.services.token_catalog_service import TokenCatalogService  # pylint: disable=import-outside-toplevel

                token_service = TokenCatalogService(db)
                is_revoked = await token_service.is_token_revoked(jti)
                if is_revoked:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Token has been revoked",
                        headers={"WWW-Authenticate": "Bearer"},
                    )
            except Exception as revoke_check_error:
                # Log the error but don't fail authentication for admin tokens
                logger.warning(f"Token revocation check failed for JTI {jti}: {revoke_check_error}")

        # Check team level token, if applicable. If public token, then will be defaulted to personal team.
        team_id = await get_team_from_token(payload, db)
        if request and hasattr(request, "state"):
            request.state.team_id = team_id

    except HTTPException:
        # Re-raise HTTPException from verify_jwt_token (handles expired/invalid tokens)
        raise
    except Exception as jwt_error:
        # JWT validation failed, try database API token
        logger.debug("JWT validation failed with error: %s, trying database API token", jwt_error)
        try:
            # First-Party
            from mcpgateway.services.token_catalog_service import TokenCatalogService  # pylint: disable=import-outside-toplevel

            token_service = TokenCatalogService(db)
            token_hash = hashlib.sha256(credentials.credentials.encode()).hexdigest()
            logger.debug("Generated token hash: %s", token_hash)

            # Find active API token by hash
            # Third-Party
            from sqlalchemy import select

            # First-Party
            from mcpgateway.db import EmailApiToken

            result = db.execute(select(EmailApiToken).where(EmailApiToken.token_hash == token_hash, EmailApiToken.is_active.is_(True)))
            api_token = result.scalar_one_or_none()
            logger.debug(f"Database lookup result: {api_token is not None}")

            if api_token:
                logger.debug(f"Found API token for user: {api_token.user_email}")
                # Check if token is expired
                if api_token.expires_at and api_token.expires_at < datetime.now(timezone.utc):
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="API token expired",
                        headers={"WWW-Authenticate": "Bearer"},
                    )

                # Check if token is revoked
                is_revoked = await token_service.is_token_revoked(api_token.jti)
                if is_revoked:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="API token has been revoked",
                        headers={"WWW-Authenticate": "Bearer"},
                    )

                # Use the email from the API token
                email = api_token.user_email
                logger.debug(f"API token authentication successful for email: {email}")

                # Update last_used timestamp
                # First-Party
                from mcpgateway.db import utc_now

                api_token.last_used = utc_now()
                db.commit()
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

    # Get user from database
    # First-Party
    from mcpgateway.services.email_auth_service import EmailAuthService  # pylint: disable=import-outside-toplevel

    auth_service = EmailAuthService(db)
    user = await auth_service.get_user_by_email(email)

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
