# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/auth.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Main Authentication Router.
This module provides simplified authentication endpoints for both session and API key management.
It serves as the primary entry point for authentication workflows.
"""

# Standard
from typing import Optional

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.auth import get_current_user
from mcpgateway.db import EmailUser, SessionLocal
from mcpgateway.routers.email_auth import create_access_token, get_client_ip, get_user_agent
from mcpgateway.schemas import AuthenticationResponse, EmailUserResponse
from mcpgateway.services.email_auth_service import EmailAuthService
from mcpgateway.services.logging_service import LoggingService

# Initialize logging
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

# Create router
auth_router = APIRouter(prefix="/auth", tags=["Authentication"])


def get_db():
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
        >>> hasattr(db, 'close')
        True
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


class LoginRequest(BaseModel):
    """Login request supporting both email and username formats.

    Attributes:
        email: User email address (can also accept 'username' field for compatibility)
        password: User password
    """

    email: Optional[EmailStr] = None
    username: Optional[str] = None  # For compatibility
    password: str

    def get_email(self) -> str:
        """Get email from either email or username field.

        Returns:
            str: Email address to use for authentication

        Raises:
            ValueError: If neither email nor username is provided

        Examples:
            >>> req = LoginRequest(email="test@example.com", password="pass")
            >>> req.get_email()
            'test@example.com'
            >>> req = LoginRequest(username="user@domain.com", password="pass")
            >>> req.get_email()
            'user@domain.com'
            >>> req = LoginRequest(username="invaliduser", password="pass")
            >>> req.get_email()  # doctest: +IGNORE_EXCEPTION_DETAIL
            Traceback (most recent call last):
            ValueError: Username format not supported. Please use email address.
            >>> req = LoginRequest(password="pass")
            >>> req.get_email()  # doctest: +IGNORE_EXCEPTION_DETAIL
            Traceback (most recent call last):
            ValueError: Either email or username must be provided
        """
        if self.email:
            return str(self.email)
        elif self.username:
            # Support both email format and plain username
            if "@" in self.username:
                return self.username
            else:
                # If it's a plain username, we can't authenticate
                # (since we're email-based system)
                raise ValueError("Username format not supported. Please use email address.")
        else:
            raise ValueError("Either email or username must be provided")


@auth_router.get("/csrf-token")
async def get_csrf_token(request: Request, current_user: "EmailUser" = Depends(get_current_user)):
    """Get a fresh CSRF token for the current authenticated user.

    This endpoint generates a new CSRF token for the current session and sets it
    as a cookie. Used by the frontend to refresh expired tokens.

    Args:
        request: FastAPI request object
        current_user: Currently authenticated user

    Returns:
        dict: JSON response with csrf_token field

    Raises:
        HTTPException: If user authentication fails

    Examples:
        >>> # GET /auth/csrf-token
        >>> # Headers: Authorization: Bearer <token>
        >>> # Response: {"csrf_token": "abc123..."}
    """
    from mcpgateway.services.csrf_service import generate_csrf_token, set_csrf_cookie
    from mcpgateway.config import settings
    from fastapi.responses import JSONResponse
    import jwt
    
    try:
        # Extract JWT token from Authorization header
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authorization header"
            )
        
        token = auth_header[7:]  # Remove "Bearer " prefix
        
        # Decode JWT to get jti for session_id (don't verify since get_current_user already did)
        payload = jwt.decode(token, options={"verify_signature": False})
        session_id = payload.get("jti", "")
        
        # Generate fresh CSRF token
        csrf_token = generate_csrf_token(
            user_id=current_user.email,
            session_id=session_id,
            secret=settings.jwt_secret_key.get_secret_value(),
            expiry=settings.csrf_token_expiry
        )
        
        # Create response with CSRF cookie
        response = JSONResponse(content={"csrf_token": csrf_token})
        set_csrf_cookie(response, csrf_token, settings)
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating CSRF token for {current_user.email}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate CSRF token"
        )


@auth_router.post("/login", response_model=AuthenticationResponse)
async def login(login_request: LoginRequest, request: Request, db: Session = Depends(get_db)):
    """Authenticate user and return session JWT token.

    This endpoint provides Tier 1 authentication for session-based access.
    The returned JWT token should be used for UI access and API key management.

    Args:
        login_request: Login credentials (email/username + password)
        request: FastAPI request object
        db: Database session

    Returns:
        AuthenticationResponse: Session JWT token and user info

    Raises:
        HTTPException: If authentication fails

    Examples:
        Email format (recommended):
            {
              "email": "admin@example.com",
              "password": "ChangeMe_12345678$"
            }

        Username format (compatibility):
            {
              "username": "admin@example.com",
              "password": "ChangeMe_12345678$"
            }
    """
    auth_service = EmailAuthService(db)
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)

    try:
        # Extract email from request
        email = login_request.get_email()

        # Authenticate user
        user = await auth_service.authenticate_user(email=email, password=login_request.password, ip_address=ip_address, user_agent=user_agent)

        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

        if settings.sso_enabled and settings.sso_preserve_admin_auth and not bool(getattr(user, "is_admin", False)):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password authentication is restricted to admin accounts while SSO is enabled.")

        # Create session JWT token (Tier 1 authentication)
        access_token, expires_in = await create_access_token(user)

        logger.info(f"User {email} authenticated successfully")

        # Return session token for UI access and API key management
        return AuthenticationResponse(
            access_token=access_token, token_type="bearer", expires_in=expires_in, user=EmailUserResponse.from_email_user(user)
        )  # nosec B106 - OAuth2 token type, not a password

    except HTTPException:
        raise
    except ValueError as e:
        logger.warning(f"Login validation error: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Login error for {login_request.email or login_request.username}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Authentication service error")
