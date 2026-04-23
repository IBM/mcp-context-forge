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
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import SessionLocal
from mcpgateway.routers.email_auth import create_access_token, get_client_ip, get_user_agent
from mcpgateway.schemas import AuthenticationResponse, EmailUserResponse, SuccessResponse
from mcpgateway.services.email_auth_service import EmailAuthService
from mcpgateway.services.logging_service import LoggingService

# Initialize logging
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

# Create router
auth_router = APIRouter(prefix="/auth", tags=["Authentication"])

# Security scheme for Bearer token authentication
security = HTTPBearer(auto_error=False)


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


@auth_router.post("/logout", response_model=SuccessResponse, status_code=status.HTTP_200_OK)
async def logout(request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security), db: Session = Depends(get_db)):
    """Logout by revoking the current session token.

    Implements server-side token blocklist per X-Force Red penetration testing
    recommendations. The token is immediately added to the revocation blacklist,
    preventing replay attacks after logout.

    Security Fix (X-Force Red Security Audit):
    - Previous behavior: Logout only cleared client-side cookies, token remained valid
    - New behavior: Token added to server-side blocklist and invalidated immediately
    - Vulnerability: Token replay after logout (X-Force Red pen test finding)
    - Solution: Server-side revocation with Redis-cached blocklist

    Args:
        request: FastAPI request object
        credentials: Bearer token from Authorization header
        db: Database session

    Returns:
        SuccessResponse with logout confirmation

    Raises:
        HTTPException 401: If no token provided or token invalid
        HTTPException 400: If attempting to revoke non-session token
        HTTPException 500: If revocation fails

    Example:
        Request:
            POST /auth/logout
            Authorization: Bearer <session_token>

        Response:
            {
              "success": true,
              "message": "Successfully logged out. Session token revoked."
            }
    """
    # Validate Authorization header
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No authentication token provided",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    try:
        # Decode and validate JWT token
        # First-Party
        from mcpgateway.utils.verify_credentials import verify_jwt_token_cached

        try:
            payload = await verify_jwt_token_cached(token)
        except Exception as verify_error:
            logger.warning(f"Logout attempt with invalid token: {verify_error}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Extract claims
        jti = payload.get("jti")
        user_email = payload.get("sub")
        token_use = payload.get("token_use")

        # Validation
        if not jti:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Token does not contain JTI (JWT ID) - cannot revoke")

        if not user_email:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Token does not contain user identity")

        # Only allow revoking session tokens via logout
        # API tokens should use DELETE /tokens/{token_id}
        if token_use != "session":  # nosec B105 - checking token type, not password
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Cannot logout with {token_use} token. Use DELETE /tokens/{{token_id}} for API tokens.")

        # Check if already revoked (idempotent operation)
        # First-Party
        from mcpgateway.db import TokenRevocation

        existing_revocation = db.query(TokenRevocation).filter(TokenRevocation.jti == jti).first()

        if existing_revocation:
            logger.info(f"Token {jti} already revoked by {existing_revocation.revoked_by} at {existing_revocation.revoked_at}")
            return SuccessResponse(success=True, message="Already logged out. Token was previously revoked.")

        # Create revocation record (X-Force Red fix: server-side blocklist)
        revocation = TokenRevocation(jti=jti, revoked_by=user_email, reason="User logout")

        db.add(revocation)
        db.commit()

        # Invalidate auth cache synchronously for immediate effect
        # (Prevents race condition where revoked token is accepted before cache updates)
        try:
            # First-Party
            from mcpgateway.cache.auth_cache import auth_cache

            await auth_cache.invalidate_revocation(jti)
            logger.debug(f"Invalidated auth cache for revoked token: {jti}")
        except Exception as cache_error:
            # Non-critical - revocation is persisted in DB
            logger.warning(f"Failed to invalidate auth cache (non-critical): {cache_error}")

        # Security event logging
        ip_address = get_client_ip(request)
        user_agent = get_user_agent(request)

        logger.info(
            f"User logout (X-Force Red fix): {user_email} revoked session token {jti[:8]}... " f"from {ip_address} ({user_agent})",
            extra={
                "security_event": "logout",
                "user_email": user_email,
                "jti": jti,
                "ip_address": ip_address,
                "user_agent": user_agent,
                "xforce_red_fix": True,  # Flag for security audit queries
                "icacf_22": True,  # Internal tracking reference
            },
        )

        return SuccessResponse(success=True, message="Successfully logged out. Session token revoked.")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Logout error: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Logout failed due to server error")
