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
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.admin import rate_limit
from mcpgateway.auth import get_current_user_from_cookie
from mcpgateway.config import settings
from mcpgateway.db import EmailUser, SessionLocal
from mcpgateway.routers.email_auth import create_access_token, get_client_ip, get_user_agent
from mcpgateway.schemas import AuthenticationResponse, EmailUserResponse
from mcpgateway.services.email_auth_service import EmailAuthService
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.utils.security_cookies import clear_auth_cookie, set_auth_cookie

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
    remember_me: bool = False  # Cookie expiry: 30d if True, 1hr if False

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


@auth_router.post("/login", response_model=AuthenticationResponse)
async def login(login_request: LoginRequest, request: Request, db: Session = Depends(get_db)):
    """Authenticate user and return session JWT token (API clients).

    This endpoint is for API clients that will use the Bearer token in the
    Authorization header. The token is returned in the response body only.
    No cookie is set.

    For browser clients, use POST /auth/browser-login instead.

    Supports both cookie-based (browser) and Bearer token (API) authentication.
    Cookie is set automatically for browser clients; API clients use token from response body.

    Args:
        login_request: Login credentials (email/username + password + optional remember_me)
        request: FastAPI request object
        response: FastAPI response object (for setting cookie)
        db: Database session

    Returns:
        AuthenticationResponse: Session JWT token and user info

    Raises:
        HTTPException: If authentication fails

    Examples:
        Email format (recommended):
            {
              "email": "admin@example.com",
              "password": "ChangeMe_12345678$",
              "remember_me": false
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

        logger.info("User authenticated successfully")

        # Return session token for UI access and API key management
        # Token in response body maintains retro-compatibility with API clients
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


@auth_router.post("/browser-login")
@rate_limit(requests_per_minute=10)
async def browser_login(login_request: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    """Authenticate user and set httpOnly cookie (browser clients).

    This endpoint is for browser clients. It sets an httpOnly cookie with the
    JWT token and returns minimal user info. The token is NOT included in the
    response body, preventing JavaScript access.

    For API clients that need the token in the response, use POST /auth/login instead.

    Args:
        login_request: Login credentials (email/username + password)
        request: FastAPI request object
        response: FastAPI response object for setting cookies
        db: Database session

    Returns:
        dict: Success message and user info (no token in body)

    Raises:
        HTTPException: If authentication fails

    Examples:
        {
          "email": "admin@example.com",
          "password": "ChangeMe_12345678$"
        }
    """
    from mcpgateway.utils.security_cookies import CookieTooLargeError

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

        # Create session JWT token
        access_token, expires_in = await create_access_token(user)

        # Set httpOnly cookie (token NOT in response body)
        try:
            set_auth_cookie(response, access_token, max_age=expires_in)
        except CookieTooLargeError as e:
            logger.error(f"Cookie too large for user: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Authentication token too large. Please contact administrator to reduce team memberships.",
            )

        logger.info("User authenticated successfully via cookie")

        # Return success without token in body
        return {
            "message": "Authenticated successfully",
            "user": EmailUserResponse.from_email_user(user).model_dump(),
        }

    except HTTPException:
        raise
    except ValueError as e:
        logger.warning(f"Login validation error: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Authentication service error")


@auth_router.get("/me", response_model=EmailUserResponse)
async def get_me(current_user: EmailUser = Depends(get_current_user_from_cookie)):
    """Get current authenticated user profile (cookie-based auth only).

    This endpoint is designed for browser clients using httpOnly cookies.
    It does NOT accept Bearer tokens from the Authorization header.

    Returns:
        EmailUserResponse: Current user profile information

    Raises:
        HTTPException: 401 if no cookie or authentication fails

    Examples:
        Browser request with httpOnly cookie set by /auth/browser-login
    """
    return EmailUserResponse.from_email_user(current_user)


@auth_router.post("/logout")
async def logout(response: Response, current_user: EmailUser = Depends(get_current_user_from_cookie)):
    """Logout current user by clearing authentication cookie.

    This endpoint is designed for browser clients using httpOnly cookies.
    It does NOT accept Bearer tokens from the Authorization header.

    Stateless logout: Only clears the browser cookie. The JWT token itself
    remains valid until expiration (no server-side revocation).

    Args:
        response: FastAPI response object for setting cookies
        current_user: Current authenticated user (from cookie)

    Returns:
        dict: Success message

    Raises:
        HTTPException: 401 if no cookie or authentication fails

    Examples:
        Browser request with httpOnly cookie
    """

    clear_auth_cookie(response)
    logger.info("User logged out successfully")

    return {"message": "Logged out successfully"}
