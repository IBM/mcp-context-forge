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
from typing import Optional

# Third-Party
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import EmailUser, SessionLocal
from mcpgateway.utils.verify_credentials import verify_jwt_token

# Security scheme
bearer_scheme = HTTPBearer(auto_error=False)


def get_db():
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


async def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme), db: Session = Depends(get_db)) -> EmailUser:
    """Get current authenticated user from JWT token with revocation checking.

    Args:
        credentials: HTTP authorization credentials
        db: Database session

    Returns:
        EmailUser: Authenticated user

    Raises:
        HTTPException: If authentication fails
    """
    logger = logging.getLogger(__name__)

    if not credentials:
        logger.debug("No credentials provided")
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
                is_email_verified=True,
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
