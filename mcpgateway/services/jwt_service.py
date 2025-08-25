# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/jwt_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Enhanced JWT Service.
Provides enhanced JWT token management with:
- User context and unique token IDs (jti)
- Token revocation and validation
- Security validation and claims enforcement
- API token management
- CSRF protection support
"""

# Standard
from datetime import datetime, timedelta, timezone
import hashlib
import logging
import secrets
from typing import Dict, List, Optional
import uuid

# Third-Party
from fastapi import HTTPException, Request, status
import jwt
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import ApiToken, SessionLocal, User, utc_now
from mcpgateway.utils.auth_logging import log_auth_event

logger = logging.getLogger(__name__)

# Allowed JWT algorithms (never include 'none')
ALLOWED_ALGORITHMS = ["HS256", "HS384", "HS512", "RS256", "RS384", "RS512"]


class JWTService:
    """Enhanced JWT token management service."""

    def __init__(self, db: Session):
        """Initialize JWT service with database session.

        Args:
            db: Database session for token storage
        """
        self.db = db

    async def create_token(self, user: User, name: str, expires_in_days: Optional[int] = None, scopes: Optional[Dict] = None, description: Optional[str] = None) -> Dict[str, str]:
        """
        Create a new JWT token with user context.

        Args:
            user: User to create token for
            name: Human-readable name for the token
            expires_in_days: Token expiration in days (None for settings default)
            scopes: Optional token scopes for future use
            description: Optional token description

        Returns:
            Dict containing the raw JWT token and metadata

        Raises:
            HTTPException: If token creation fails
        """
        # Check if user already has a token with this name
        existing = self.db.query(ApiToken).filter(ApiToken.user_id == user.id, ApiToken.name == name).first()

        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Token with name '{name}' already exists")

        # Calculate expiration
        if expires_in_days is None:
            expires_in_days = settings.token_expiry // (24 * 60)  # Convert minutes to days

        expires_at = utc_now() + timedelta(days=expires_in_days) if expires_in_days > 0 else None

        # Generate unique JWT ID
        jti = str(uuid.uuid4())

        # Create JWT payload
        now = utc_now()
        payload = {
            "sub": user.id,  # Subject (user ID)
            "username": user.username,
            "jti": jti,  # JWT ID for revocation
            "iat": int(now.timestamp()),  # Issued at
            "iss": settings.jwt_issuer,  # Issuer
            "aud": settings.jwt_audience,  # Audience
        }

        if expires_at:
            payload["exp"] = int(expires_at.timestamp())  # Expiration

        # Add user roles/permissions
        payload["is_admin"] = user.is_admin
        payload["is_active"] = user.is_active

        # Add team memberships
        teams = []
        for membership in user.team_memberships:
            teams.append({"id": membership.team.id, "name": membership.team.name, "role": membership.role})
        payload["teams"] = teams

        # Include scopes if provided
        if scopes:
            payload["scopes"] = scopes

        # Create JWT token
        try:
            token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
        except Exception as e:
            logger.error(f"Failed to create JWT token: {e}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create token")

        # Hash the token for storage (don't store raw JWT)
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        # Store token metadata in database
        api_token = ApiToken(user_id=user.id, name=name, token_hash=token_hash, jti=jti, expires_at=expires_at, scopes=scopes, description=description, is_active=True)

        self.db.add(api_token)
        self.db.commit()
        self.db.refresh(api_token)

        # Log token creation
        await log_auth_event(
            db=self.db,
            event_type="token_created",
            user_id=user.id,
            username=user.username,
            success=True,
            details={"token_name": name, "jti": jti, "expires_at": expires_at.isoformat() if expires_at else None},
        )

        logger.info(f"JWT token created for user {user.username}: {name}")

        return {
            "token": token,  # Raw JWT (only returned once)
            "token_id": api_token.id,
            "jti": jti,
            "name": name,
            "description": description,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "created_at": api_token.created_at.isoformat(),
        }

    async def verify_token(self, token: str, request: Optional[Request] = None) -> Dict:
        """
        Verify and decode JWT token with comprehensive validation.

        Args:
            token: The JWT token to verify
            request: Optional FastAPI request for logging

        Returns:
            Decoded token payload with user information

        Raises:
            HTTPException: If token is invalid or revoked
        """
        try:
            # Pre-validation: Check algorithm in header
            try:
                header = jwt.get_unverified_header(token)
                if header.get("alg") not in ALLOWED_ALGORITHMS:
                    await log_auth_event(
                        db=self.db,
                        event_type="token_validation_failed",
                        success=False,
                        failure_reason="Invalid algorithm",
                        ip_address=self._get_client_ip(request),
                        user_agent=self._get_user_agent(request),
                    )
                    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
            except jwt.DecodeError:
                await log_auth_event(
                    db=self.db,
                    event_type="token_validation_failed",
                    success=False,
                    failure_reason="Malformed token header",
                    ip_address=self._get_client_ip(request),
                    user_agent=self._get_user_agent(request),
                )
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

            # Decode and validate token
            payload = jwt.decode(
                token,
                settings.jwt_secret_key,
                algorithms=[settings.jwt_algorithm],
                options={"require": ["exp", "iat", "sub", "jti"] if settings.require_token_expiration else ["iat", "sub", "jti"]},
                audience=settings.jwt_audience,
                issuer=settings.jwt_issuer,
            )

            # Additional validations

            # 1. Check token age (if configured)
            if hasattr(settings, "jwt_max_age_hours") and settings.jwt_max_age_hours > 0:
                token_age = datetime.now(timezone.utc) - datetime.fromtimestamp(payload["iat"], timezone.utc)
                if token_age > timedelta(hours=settings.jwt_max_age_hours):
                    await log_auth_event(
                        db=self.db,
                        event_type="token_validation_failed",
                        username=payload.get("username"),
                        success=False,
                        failure_reason="Token too old",
                        ip_address=self._get_client_ip(request),
                        user_agent=self._get_user_agent(request),
                    )
                    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

            # 2. Check if token is revoked
            jti = payload.get("jti")
            if jti:
                # Hash the token to check against stored hash
                token_hash = hashlib.sha256(token.encode()).hexdigest()

                api_token = self.db.query(ApiToken).filter(ApiToken.jti == jti).first()

                if not api_token:
                    await log_auth_event(
                        db=self.db,
                        event_type="token_validation_failed",
                        username=payload.get("username"),
                        success=False,
                        failure_reason="Token not found in database",
                        ip_address=self._get_client_ip(request),
                        user_agent=self._get_user_agent(request),
                    )
                    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

                if not api_token.is_active:
                    await log_auth_event(
                        db=self.db,
                        event_type="token_validation_failed",
                        user_id=api_token.user_id,
                        username=payload.get("username"),
                        success=False,
                        failure_reason="Token revoked",
                        ip_address=self._get_client_ip(request),
                        user_agent=self._get_user_agent(request),
                    )
                    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

                if api_token.token_hash != token_hash:
                    await log_auth_event(
                        db=self.db,
                        event_type="token_validation_failed",
                        user_id=api_token.user_id,
                        username=payload.get("username"),
                        success=False,
                        failure_reason="Token hash mismatch",
                        ip_address=self._get_client_ip(request),
                        user_agent=self._get_user_agent(request),
                    )
                    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

                # Update last used timestamp
                api_token.last_used = utc_now()
                self.db.commit()

            # 3. Verify user still exists and is active
            user = self.db.query(User).filter(User.id == payload["sub"]).first()
            if not user or not user.is_active:
                await log_auth_event(
                    db=self.db,
                    event_type="token_validation_failed",
                    user_id=payload.get("sub"),
                    username=payload.get("username"),
                    success=False,
                    failure_reason="User inactive or not found",
                    ip_address=self._get_client_ip(request),
                    user_agent=self._get_user_agent(request),
                )
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

            # Add current user information to payload
            payload["user"] = {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "full_name": user.full_name,
                "is_admin": user.is_admin,
                "is_active": user.is_active,
            }

            await log_auth_event(
                db=self.db,
                event_type="token_validated",
                user_id=user.id,
                username=user.username,
                success=True,
                ip_address=self._get_client_ip(request),
                user_agent=self._get_user_agent(request),
            )

            return payload

        except jwt.ExpiredSignatureError:
            await log_auth_event(
                db=self.db,
                event_type="token_validation_failed",
                success=False,
                failure_reason="Token expired",
                ip_address=self._get_client_ip(request),
                user_agent=self._get_user_agent(request),
            )
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        except jwt.InvalidTokenError as e:
            await log_auth_event(
                db=self.db,
                event_type="token_validation_failed",
                success=False,
                failure_reason=f"Invalid token: {type(e).__name__}",
                ip_address=self._get_client_ip(request),
                user_agent=self._get_user_agent(request),
            )
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        except Exception as e:
            logger.error(f"Unexpected error during token validation: {e}")
            await log_auth_event(
                db=self.db,
                event_type="token_validation_failed",
                success=False,
                failure_reason=f"Validation error: {type(e).__name__}",
                ip_address=self._get_client_ip(request),
                user_agent=self._get_user_agent(request),
            )
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    async def revoke_token(self, jti: str, user_id: str) -> bool:
        """
        Revoke a specific token by its JTI.

        Args:
            jti: JWT ID to revoke
            user_id: ID of user requesting revocation (for authorization)

        Returns:
            True if token was revoked successfully

        Raises:
            HTTPException: If token not found or user not authorized
        """
        api_token = self.db.query(ApiToken).filter(ApiToken.jti == jti).first()

        if not api_token:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")

        # Check if user owns the token or is admin
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

        if api_token.user_id != user_id and not user.is_admin:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to revoke this token")

        # Revoke the token
        api_token.is_active = False
        self.db.commit()

        await log_auth_event(
            db=self.db,
            event_type="token_revoked",
            user_id=user_id,
            username=user.username,
            success=True,
            details={"revoked_token_jti": jti, "token_name": api_token.name},
        )

        logger.info(f"Token revoked: {api_token.name} (JTI: {jti}) by user {user.username}")
        return True

    async def revoke_user_tokens(self, user_id: str, revoked_by_user_id: str) -> int:
        """
        Revoke all tokens for a specific user.

        Args:
            user_id: ID of user whose tokens to revoke
            revoked_by_user_id: ID of user performing the revocation

        Returns:
            Number of tokens revoked

        Raises:
            HTTPException: If user not found or not authorized
        """
        # Check authorization
        revoked_by_user = self.db.query(User).filter(User.id == revoked_by_user_id).first()
        if not revoked_by_user:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

        if user_id != revoked_by_user_id and not revoked_by_user.is_admin:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to revoke tokens for this user")

        # Get user info for logging
        target_user = self.db.query(User).filter(User.id == user_id).first()
        if not target_user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        # Revoke all active tokens for the user
        tokens = self.db.query(ApiToken).filter(ApiToken.user_id == user_id, ApiToken.is_active.is_(True)).all()

        count = 0
        for token in tokens:
            token.is_active = False
            count += 1

        self.db.commit()

        await log_auth_event(
            db=self.db,
            event_type="all_tokens_revoked",
            user_id=revoked_by_user_id,
            username=revoked_by_user.username,
            success=True,
            details={"target_user_id": user_id, "target_username": target_user.username, "tokens_revoked": count},
        )

        logger.info(f"All tokens revoked for user {target_user.username} by {revoked_by_user.username} ({count} tokens)")
        return count

    async def list_user_tokens(self, user_id: str) -> List[Dict]:
        """
        List API tokens for a user (without revealing raw tokens).

        Args:
            user_id: ID of user whose tokens to list

        Returns:
            List of token metadata
        """
        tokens = self.db.query(ApiToken).filter(ApiToken.user_id == user_id).order_by(ApiToken.created_at.desc()).all()

        result = []
        for token in tokens:
            result.append(
                {
                    "id": token.id,
                    "name": token.name,
                    "description": token.description,
                    "jti": token.jti,
                    "created_at": token.created_at.isoformat(),
                    "expires_at": token.expires_at.isoformat() if token.expires_at else None,
                    "last_used": token.last_used.isoformat() if token.last_used else None,
                    "is_active": token.is_active,
                    "scopes": token.scopes,
                }
            )

        return result

    async def generate_csrf_token(self) -> str:
        """Generate a CSRF token for cookie-based authentication.

        Returns:
            str: Secure random CSRF token
        """
        return secrets.token_urlsafe(32)

    def _get_client_ip(self, request: Optional[Request]) -> Optional[str]:
        """Extract client IP from request.

        Args:
            request: FastAPI request object

        Returns:
            Optional[str]: Client IP address or None
        """
        if not request:
            return None
        return request.client.host if request.client else None

    def _get_user_agent(self, request: Optional[Request]) -> Optional[str]:
        """Extract user agent from request.

        Args:
            request: FastAPI request object

        Returns:
            Optional[str]: User agent string or None
        """
        if not request:
            return None
        return request.headers.get("user-agent")


# Dependency to get JWT service
def get_jwt_service():
    """Dependency to get JWTService with database session.

    Yields:
        JWTService: JWT service instance with database session
    """
    db = SessionLocal()
    try:
        yield JWTService(db)
    finally:
        db.close()
