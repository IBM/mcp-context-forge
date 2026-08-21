# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/auth.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Main Authentication Router.
This module provides simplified authentication endpoints for both session and API key management.
It serves as the primary entry point for authentication workflows.
"""

# Standard
import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import uuid

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials
import jwt
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.auth import get_current_user, TokenValidationError, validate_token_user
from mcpgateway.common.validators import SecurityValidator
from mcpgateway.config import settings
from mcpgateway.db import EmailUser, SessionLocal
from mcpgateway.routers.email_auth import create_access_token, get_client_ip, get_user_agent
from mcpgateway.schemas import AuthenticationResponse, EmailUserResponse
from mcpgateway.services.audit_trail_service import get_audit_trail_service
from mcpgateway.services.csrf_service import generate_csrf_token, set_csrf_cookie
from mcpgateway.services.email_auth_service import EmailAuthService
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.token_blocklist_service import get_token_blocklist_service
from mcpgateway.utils.security_cookies import set_auth_cookie
from mcpgateway.utils.verify_credentials import get_auth_header_value, security, verify_jwt_token_cached

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
    try:
        session_id = getattr(request.state, "jti", None)
        if not session_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing session identifier")

        # Generate fresh CSRF token
        csrf_token = generate_csrf_token(user_id=current_user.email, session_id=session_id, secret=settings.csrf_secret_key.get_secret_value(), expiry=settings.csrf_token_expiry)

        # Create response with CSRF cookie
        response = JSONResponse(content={"csrf_token": csrf_token})
        set_csrf_cookie(response, csrf_token, settings)

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating CSRF token for {current_user.email}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to generate CSRF token")


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
              "password": "ChangeMe_12345678$"  # pragma: allowlist secret
            }

        Username format (compatibility):
            {
              "username": "admin@example.com",
              "password": "ChangeMe_12345678$"  # pragma: allowlist secret
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

        # Generate CSRF token for session (rotate on login)
        if settings.csrf_rotate_on_login:
            try:
                # Decode JWT to get jti (don't verify since we just created it)
                payload = jwt.decode(access_token, options={"verify_signature": False})
                session_id = payload.get("jti", "")

                # Generate CSRF token
                csrf_token = generate_csrf_token(user_id=user.email, session_id=session_id, secret=settings.csrf_secret_key.get_secret_value(), expiry=settings.csrf_token_expiry)

                auth_response = AuthenticationResponse(access_token=access_token, token_type="bearer", expires_in=expires_in, user=EmailUserResponse.from_email_user(user))  # nosec B106 - OAuth2 token type, not a password
                response = JSONResponse(content=auth_response.model_dump(mode="json"))

                set_csrf_cookie(response, csrf_token, settings)

                return response
            except Exception as e:
                logger.warning(f"Failed to set CSRF token for {user.email}: {e}")
                # Fall back to response without CSRF token (non-critical)

        # Return session token for UI access and API key management
        return AuthenticationResponse(access_token=access_token, token_type="bearer", expires_in=expires_in, user=EmailUserResponse.from_email_user(user))  # nosec B106 - OAuth2 token type, not a password

    except HTTPException:
        raise
    except ValueError as e:
        logger.warning(f"Login validation error: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Login error for {login_request.email or login_request.username}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Authentication service error")


@auth_router.post("/logout")
async def logout(request: Request, current_user: EmailUser = Depends(get_current_user), db: Session = Depends(get_db)):
    """Logout user and revoke session token.

    This endpoint implements server-side token revocation by adding the token
    to the blocklist, providing immediate invalidation as recommended by X-Force Red.

    Args:
        request: FastAPI request object
        current_user: Current authenticated user from dependency
        db: Database session

    Returns:
        Success response confirming logout

    Raises:
        HTTPException: If logout fails

    Security:
        - Adds token to server-side blocklist
        - Token cannot be reused after logout
        - Supports audit trail for security monitoring
    """
    try:
        # User is already authenticated via dependency injection
        user = current_user

        # Extract JWT from the configured auth header (default: Authorization).
        # Reading from settings.auth_header_name keeps logout aligned with the
        # auth dependency that just validated the same caller; otherwise a custom
        # AUTH_HEADER_NAME lets a request authenticate but never revoke its token.
        auth_header = get_auth_header_value(request.headers) or ""
        scheme, _, raw_token = auth_header.partition(" ")
        if scheme.lower() != "bearer" or not raw_token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No valid authorization token provided")

        token = raw_token.strip()

        # Decode token to get JTI and expiry
        try:
            # Handle both SecretStr and string types for jwt_secret_key
            secret_key = settings.jwt_secret_key
            if hasattr(secret_key, "get_secret_value"):
                secret_key = secret_key.get_secret_value()

            payload = jwt.decode(token, secret_key, algorithms=[settings.jwt_algorithm], options={"verify_signature": False})  # Already verified by get_current_user

            jti = payload.get("jti")
            exp = payload.get("exp")
            last_activity = payload.get("last_activity", payload.get("iat"))

            if not jti:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Token does not support revocation (missing JTI)")

            # Convert timestamps to datetime
            token_expiry = datetime.fromtimestamp(exp, tz=timezone.utc) if exp else None
            last_activity_dt = datetime.fromtimestamp(last_activity, tz=timezone.utc) if last_activity else None

            # Revoke token using blocklist service
            blocklist_service = get_token_blocklist_service(db=db)
            success = blocklist_service.revoke_token(jti=jti, revoked_by=user.email, reason="logout", token_expiry=token_expiry, last_activity=last_activity_dt)

            if not success:
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to revoke token")

            logger.info("User %s logged out successfully", SecurityValidator.sanitize_log_message(user.email), extra={"security_event": "logout", "user_email": user.email, "jti": jti})

            return {"message": "Logged out successfully", "revoked_token": jti}

        except jwt.DecodeError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token format")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Logout error: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Logout service error")


# ---------------------------------------------------------------------------
# Session refresh & validation
# ---------------------------------------------------------------------------


class SessionRefreshResponse(BaseModel):
    """Response payload for POST /auth/refresh."""

    access_token: str
    token_type: str = "bearer"  # nosec B105 - OAuth2 token type, not a password
    expires_in: int
    expires_at: str
    csrf_token: Optional[str] = None


class SessionValidateResponse(BaseModel):
    """Response payload for GET /auth/validate."""

    valid: bool
    expires_at: Optional[str] = None
    expires_in: Optional[int] = None
    user: EmailUserResponse
    session_source: str
    config: Dict[str, Any]


async def get_session_user(request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> EmailUser:
    """Authenticate the request via bearer header or session cookie.

    Args:
        request: FastAPI request object
        credentials: Optional bearer credentials from the configured auth header

    Returns:
        EmailUser: Authenticated user

    Raises:
        HTTPException: 401 if neither a valid bearer token nor a valid session cookie is presented
    """
    if credentials and credentials.credentials:
        return await get_current_user(credentials, request=request)

    cookie_token = request.cookies.get("jwt_token") or request.cookies.get("access_token")
    if not cookie_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required", headers={"WWW-Authenticate": "Bearer"})

    try:
        return await validate_token_user(request, cookie_token)
    except TokenValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


def _extract_raw_token(request: Request) -> tuple[Optional[str], bool]:
    """Extract the raw JWT from the auth header or cookie.

    Args:
        request: FastAPI request object

    Returns:
        Tuple of (raw token or None, True when the token came from a cookie)
    """
    auth_header = get_auth_header_value(request.headers) or ""
    scheme, _, header_token = auth_header.partition(" ")
    if scheme.lower() == "bearer" and header_token.strip():
        return header_token.strip(), False
    cookie_token = request.cookies.get("jwt_token") or request.cookies.get("access_token")
    if cookie_token:
        return cookie_token, True
    return None, False


def _decode_token_unverified(raw_token: str) -> Dict[str, Any]:
    """Decode a JWT payload without verifying the signature (only for tokens this gateway just minted).

    Args:
        raw_token: Raw JWT string

    Returns:
        Decoded payload dict, or an empty dict if the token cannot be decoded
    """
    try:
        return jwt.decode(raw_token, options={"verify_signature": False})
    except jwt.DecodeError:
        return {}


async def _verify_session_token(raw_token: str, request: Request, current_user: EmailUser) -> Dict[str, Any]:
    """Verify the request's session token and bind it to the authenticated user.

    Full signature/expiry verification plus revocation and subject checks, so
    claims are never trusted from a token that was not verified by the gateway
    (the auth dependency may have authenticated via a non-JWT mechanism).

    Args:
        raw_token: Raw JWT string extracted from the request
        request: FastAPI request object
        current_user: Currently authenticated user

    Returns:
        Verified JWT payload

    Raises:
        HTTPException: 401 if the token is invalid, expired, revoked, or its
            subject does not match the authenticated user
    """
    try:
        payload = await verify_jwt_token_cached(raw_token, request)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session token")

    jti = payload.get("jti")
    if jti:
        blocklist_service = get_token_blocklist_service()
        if await asyncio.to_thread(blocklist_service.is_token_revoked, jti):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session token has been revoked")

    subject = str(payload.get("sub") or "")
    if subject not in (str(current_user.id), str(current_user.email)):
        logger.warning(
            "Session token subject mismatch for %s",
            SecurityValidator.sanitize_log_message(str(current_user.email)),
            extra={"security_event": "token_subject_mismatch", "security_severity": "medium", "user_email": current_user.email},
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session token does not match authenticated user")

    return payload


def _session_source_from_payload(payload: Dict[str, Any]) -> str:
    """Classify how the session was established from JWT claims.

    Args:
        payload: Decoded JWT payload

    Returns:
        One of "local", "sso", or "api_token"
    """
    if payload.get("token_use") == "api":
        return "api_token"
    if payload.get("source") == "external_idp":
        return "sso"
    provider = str(payload.get("auth_provider") or "local").strip().lower()
    return "local" if provider in ("", "local", "basic") else "sso"


def _session_config_hints() -> Dict[str, Any]:
    """Build the session-lifecycle config block for UI clients (durations in seconds).

    Returns:
        Dict of session-lifecycle hints
    """
    return {
        "token_expiry": settings.token_expiry * 60,
        "idle_timeout": settings.token_idle_timeout * 60,
        "max_lifetime": settings.session_max_lifetime * 60,
        "warning_time": settings.session_warning_time,
        "refresh_buffer": settings.session_refresh_buffer,
        "activity_tracking": settings.session_activity_tracking,
    }


@auth_router.get("/validate", response_model=SessionValidateResponse)
async def validate_session(request: Request, current_user: EmailUser = Depends(get_session_user)) -> SessionValidateResponse:
    """Validate the current session and report its expiry, source, and config hints.

    Args:
        request: FastAPI request object
        current_user: Currently authenticated user

    Returns:
        SessionValidateResponse: Session expiry, user profile, session source, and config hints
    """
    raw_token, _ = _extract_raw_token(request)
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No session token to validate")
    payload = await _verify_session_token(raw_token, request, current_user)

    expires_at: Optional[str] = None
    expires_in: Optional[int] = None
    exp_ts = payload.get("exp")
    if exp_ts:
        expires_at = datetime.fromtimestamp(exp_ts, tz=timezone.utc).isoformat()
        expires_in = max(0, int(exp_ts - datetime.now(tz=timezone.utc).timestamp()))

    return SessionValidateResponse(
        valid=True,
        expires_at=expires_at,
        expires_in=expires_in,
        user=EmailUserResponse.from_email_user(current_user),
        session_source=_session_source_from_payload(payload),
        config=_session_config_hints(),
    )


@auth_router.post("/refresh", response_model=SessionRefreshResponse)
async def refresh_session(request: Request, current_user: EmailUser = Depends(get_session_user)) -> Response:
    """Refresh the current session by issuing a new JWT with extended expiry.

    Args:
        request: FastAPI request object
        current_user: Currently authenticated user

    Returns:
        SessionRefreshResponse: New access token, expiry, and rotated CSRF token

    Raises:
        HTTPException: 401 if the session token is missing, malformed, past the
            absolute lifetime cap, or cannot be rotated (already refreshed or
            revocation not persisted); 403 for non-session tokens
    """
    raw_token, from_cookie = _extract_raw_token(request)
    if not raw_token:
        # Non-JWT auth (basic/proxy) has no session token to refresh
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No session token to refresh")

    payload = await _verify_session_token(raw_token, request, current_user)

    if payload.get("token_use") != "session":  # nosec B105 - Not a password; token_use is a JWT claim type
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only session tokens can be refreshed. API tokens have their own expiry and revocation lifecycle.")

    session_source = _session_source_from_payload(payload)
    now_ts = int(datetime.now(tz=timezone.utc).timestamp())

    # session_start is stamped at first login and carried across refreshes
    session_start = int(payload.get("session_start") or payload.get("iat") or now_ts)
    if settings.session_max_lifetime > 0 and (now_ts - session_start) >= settings.session_max_lifetime * 60:
        logger.warning(
            "Session refresh refused: absolute lifetime exceeded for %s",
            SecurityValidator.sanitize_log_message(current_user.email),
            extra={"security_event": "session_max_lifetime", "security_severity": "medium", "user_email": current_user.email},
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Session exceeded maximum lifetime ({settings.session_max_lifetime} minutes). Please log in again.")

    old_jti = payload.get("jti")
    if not old_jti:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session token does not support rotation (missing jti)")

    # Single-use rotation: revoke the predecessor before minting so the old token
    # cannot be replayed to mint further tokens. fail_if_already_revoked makes the
    # revocation compare-and-set — concurrent refreshes race and exactly one wins.
    # Fail closed when revocation cannot be persisted.
    old_exp_ts = payload.get("exp")
    blocklist_service = get_token_blocklist_service()
    rotated = await asyncio.to_thread(
        blocklist_service.revoke_token,
        jti=old_jti,
        revoked_by=current_user.email,
        reason="token_refresh",
        token_expiry=datetime.fromtimestamp(old_exp_ts, tz=timezone.utc) if old_exp_ts else None,
        fail_if_already_revoked=True,
    )
    if not rotated:
        logger.warning(
            "Session refresh refused: predecessor token could not be revoked for %s",
            SecurityValidator.sanitize_log_message(current_user.email),
            extra={"security_event": "session_rotation_failed", "security_severity": "medium", "user_email": current_user.email, "jti": old_jti},
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session token already rotated or revocation failed. Please log in again.")

    new_jti = str(uuid.uuid4())
    # Preserve the old token's scope narrowing; teams are resolved server-side from the DB
    access_token, expires_in = await create_access_token(current_user, token_scopes=payload.get("scopes"), jti=new_jti, extra_claims={"session_start": session_start})
    new_exp_ts = _decode_token_unverified(access_token).get("exp", now_ts + expires_in)
    expires_at = datetime.fromtimestamp(new_exp_ts, tz=timezone.utc).isoformat()

    # Rotate the CSRF token (CSRF tokens are HMAC-bound to the jti, which changed)
    csrf_token: Optional[str] = None
    try:
        csrf_token = generate_csrf_token(user_id=current_user.email, session_id=new_jti, secret=settings.csrf_secret_key.get_secret_value(), expiry=settings.csrf_token_expiry)
    except Exception as e:
        logger.warning(f"Failed to rotate CSRF token on refresh for {current_user.email}: {e}")

    refresh_response = SessionRefreshResponse(access_token=access_token, token_type="bearer", expires_in=expires_in, expires_at=expires_at, csrf_token=csrf_token)  # nosec B106 - OAuth2 token type
    response = JSONResponse(content=refresh_response.model_dump(mode="json"))
    if csrf_token:
        set_csrf_cookie(response, csrf_token, settings)
    if from_cookie:
        set_auth_cookie(response, access_token)

    audit_trail = get_audit_trail_service()
    audit_trail.log_action(
        user_id=current_user.email,
        action="session_refresh",
        resource_type="session",
        resource_id=new_jti,
        user_email=current_user.email,
        client_ip=get_client_ip(request),
        user_agent=get_user_agent(request),
        context={"old_jti": old_jti, "session_source": session_source},
    )

    logger.info(
        "Session refreshed for %s",
        SecurityValidator.sanitize_log_message(current_user.email),
        extra={"security_event": "session_refresh", "user_email": current_user.email, "jti": new_jti},
    )
    return response
