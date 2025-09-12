# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/token_catalog_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Token Catalog Service.
This module provides comprehensive API token management with scoping,
revocation, usage tracking, and analytics for email-based users.

Examples:
    >>> from mcpgateway.services.token_catalog_service import TokenCatalogService
    >>> service = TokenCatalogService(None)  # Mock database for doctest
    >>> # Service provides full token lifecycle management
"""

# Standard
from datetime import datetime, timedelta, timezone
import hashlib
from typing import List, Optional
import uuid

# Third-Party
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import EmailApiToken, EmailUser, TokenRevocation, TokenUsageLog, utc_now
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.utils.create_jwt_token import create_jwt_token

# Initialize logging
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class TokenScope:
    """Token scoping configuration for fine-grained access control.

    This class encapsulates token scoping parameters including
    server restrictions, permissions, IP limitations, and usage quotas.

    Attributes:
        server_id (Optional[str]): Limit token to specific server
        permissions (List[str]): Specific permission scopes
        ip_restrictions (List[str]): IP address/CIDR restrictions
        time_restrictions (dict): Time-based access limitations
        usage_limits (dict): Rate limiting and quota settings

    Examples:
        >>> scope = TokenScope(
        ...     server_id="prod-server-123",
        ...     permissions=["tools.read", "resources.read"],
        ...     ip_restrictions=["192.168.1.0/24"],
        ...     time_restrictions={"business_hours_only": True}
        ... )
        >>> scope.is_server_scoped()
        True
        >>> scope.has_permission("tools.read")
        True
        >>> scope.has_permission("tools.write")
        False
        >>> scope.has_permission("resources.read")
        True
        >>>
        >>> # Test empty scope
        >>> empty_scope = TokenScope()
        >>> empty_scope.is_server_scoped()
        False
        >>> empty_scope.has_permission("anything")
        False
        >>>
        >>> # Test global scope
        >>> global_scope = TokenScope(permissions=["*"])
        >>> global_scope.has_permission("*")
        True
    """

    def __init__(
        self,
        server_id: Optional[str] = None,
        permissions: Optional[List[str]] = None,
        ip_restrictions: Optional[List[str]] = None,
        time_restrictions: Optional[dict] = None,
        usage_limits: Optional[dict] = None,
    ):
        """Initialize TokenScope with specified restrictions and limits.

        Args:
            server_id: Optional server ID to scope token to specific server
            permissions: List of permissions granted to this token
            ip_restrictions: List of IP addresses/ranges allowed to use token
            time_restrictions: Dictionary of time-based access restrictions
            usage_limits: Dictionary of usage limits for the token
        """
        self.server_id = server_id
        self.permissions = permissions or []
        self.ip_restrictions = ip_restrictions or []
        self.time_restrictions = time_restrictions or {}
        self.usage_limits = usage_limits or {}

    def is_server_scoped(self) -> bool:
        """Check if token is scoped to a specific server.

        Returns:
            bool: True if scoped to a server, False otherwise.
        """
        return self.server_id is not None

    def has_permission(self, permission: str) -> bool:
        """Check if scope includes specific permission.

        Args:
            permission: Permission string to check for.

        Returns:
            bool: True if permission is included, False otherwise.
        """
        return permission in self.permissions

    def to_dict(self) -> dict:
        """Convert scope to dictionary for JSON storage.

        Returns:
            dict: Dictionary representation of the token scope.

        Examples:
            >>> scope = TokenScope(server_id="server-123", permissions=["read", "write"])
            >>> result = scope.to_dict()
            >>> result["server_id"]
            'server-123'
            >>> result["permissions"]
            ['read', 'write']
            >>> isinstance(result, dict)
            True
        """
        return {"server_id": self.server_id, "permissions": self.permissions, "ip_restrictions": self.ip_restrictions, "time_restrictions": self.time_restrictions, "usage_limits": self.usage_limits}

    @classmethod
    def from_dict(cls, data: dict) -> "TokenScope":
        """Create TokenScope from dictionary.

        Args:
            data: Dictionary containing scope configuration.

        Returns:
            TokenScope: New TokenScope instance.

        Examples:
            >>> data = {
            ...     "server_id": "server-456",
            ...     "permissions": ["tools.read", "tools.execute"],
            ...     "ip_restrictions": ["10.0.0.0/8"]
            ... }
            >>> scope = TokenScope.from_dict(data)
            >>> scope.server_id
            'server-456'
            >>> scope.permissions
            ['tools.read', 'tools.execute']
            >>> scope.is_server_scoped()
            True
            >>> scope.has_permission("tools.read")
            True
            >>>
            >>> # Test empty dict
            >>> empty_scope = TokenScope.from_dict({})
            >>> empty_scope.server_id is None
            True
            >>> empty_scope.permissions
            []
        """
        return cls(
            server_id=data.get("server_id"),
            permissions=data.get("permissions", []),
            ip_restrictions=data.get("ip_restrictions", []),
            time_restrictions=data.get("time_restrictions", {}),
            usage_limits=data.get("usage_limits", {}),
        )


class TokenCatalogService:
    """Service for managing user API token catalogs.

    This service provides comprehensive token lifecycle management including
    creation, scoping, revocation, usage tracking, and analytics. It handles
    JWT-based API tokens with fine-grained access control, team support,
    and comprehensive audit logging.

    Key features:
    - Token creation with customizable scopes and permissions
    - Team-based token management with role-based access
    - Token revocation and blacklisting
    - Usage tracking and analytics
    - IP and time-based restrictions
    - Automatic cleanup of expired tokens

    Attributes:
        db (Session): SQLAlchemy database session for token operations

    Examples:
        >>> from mcpgateway.services.token_catalog_service import TokenCatalogService
        >>> service = TokenCatalogService(None)  # Mock database for doctest
        >>> service.db is None
        True
    """

    def __init__(self, db: Session):
        """Initialize TokenCatalogService with database session.

        Args:
            db: SQLAlchemy database session for token operations
        """
        self.db = db

    async def _generate_token(self, user_email: str, team_id: Optional[str] = None, expires_at: Optional[datetime] = None, scope: Optional["TokenScope"] = None, user: Optional[object] = None) -> str:
        """Generate a JWT token for API access.

        This internal method creates a properly formatted JWT token with all
        necessary claims including user identity, scopes, team membership,
        and expiration. The token follows the MCP Gateway JWT structure.

        Args:
            user_email: User's email address for the token subject
            team_id: Optional team ID for team-scoped tokens
            expires_at: Optional expiration datetime
            scope: Optional token scope information for access control
            user: Optional user object to extract admin privileges

        Returns:
            str: Signed JWT token string ready for API authentication

        Note:
            This is an internal method. Use create_token() to generate
            tokens with proper database tracking and validation.
        """
        now = datetime.now(timezone.utc)

        # Build JWT payload with required claims
        payload = {
            "sub": user_email,  # Subject (user email)
            "iss": settings.jwt_issuer,  # Issuer
            "aud": settings.jwt_audience,  # Audience
            "iat": int(now.timestamp()),  # Issued at
            "jti": str(uuid.uuid4()),  # JWT ID for uniqueness
            "user": {"email": user_email, "full_name": "API Token User", "is_admin": user.is_admin if user else False, "auth_provider": "api_token"},  # Use actual admin status if user provided
            "teams": [team_id] if team_id else [],
            "namespaces": [f"user:{user_email}", "public"] + ([f"team:{team_id}"] if team_id else []),
        }

        # Add expiration if specified
        if expires_at:
            payload["exp"] = int(expires_at.timestamp())

        # Add scoping information if available
        if scope:
            payload["scopes"] = {
                "server_id": scope.server_id,
                "permissions": scope.permissions or ["*"],
                "ip_restrictions": scope.ip_restrictions or [],
                "time_restrictions": scope.time_restrictions or {},
            }
        else:
            payload["scopes"] = {
                "server_id": None,
                "permissions": ["*"],
                "ip_restrictions": [],
                "time_restrictions": {},
            }

        # Generate JWT token using the centralized token creation utility
        # The create_jwt_token will handle expiration and other standard claims
        return await create_jwt_token(payload)

    def _hash_token(self, token: str) -> str:
        """Create secure hash of token for storage.

        Args:
            token: Raw token string

        Returns:
            str: SHA-256 hash of token

        Examples:
            >>> service = TokenCatalogService(None)
            >>> hash_val = service._hash_token("test_token")
            >>> len(hash_val) == 64
            True
        """
        return hashlib.sha256(token.encode()).hexdigest()

    async def create_token(
        self,
        user_email: str,
        name: str,
        description: Optional[str] = None,
        scope: Optional[TokenScope] = None,
        expires_in_days: Optional[int] = None,
        tags: Optional[List[str]] = None,
        team_id: Optional[str] = None,
    ) -> tuple[EmailApiToken, str]:
        """Create a new API token for user or team.

        Args:
            user_email: Owner's email address
            name: Human-readable token name
            description: Optional token description
            scope: Token scoping configuration
            expires_in_days: Optional expiry in days
            tags: Optional organizational tags
            team_id: Optional team ID for team-scoped tokens

        Returns:
            Tuple of (EmailApiToken, raw_token_string)

        Raises:
            ValueError: If user not found, token name exists, or team access denied

        Examples:
            >>> # This method requires database operations, shown for reference
            >>> service = TokenCatalogService(None)  # Would use real DB session
            >>> # token, raw_token = await service.create_token(...)
            >>> # Returns (EmailApiToken, raw_token_string) tuple
        """
        # Validate user exists
        user = self.db.execute(select(EmailUser).where(EmailUser.email == user_email)).scalar_one_or_none()

        if not user:
            raise ValueError(f"User not found: {user_email}")

        # Validate team access if team_id is provided
        if team_id:
            # First-Party
            from mcpgateway.db import EmailTeam, EmailTeamMember  # pylint: disable=import-outside-toplevel

            # Check if team exists
            team = self.db.execute(select(EmailTeam).where(EmailTeam.id == team_id)).scalar_one_or_none()
            if not team:
                raise ValueError(f"Team not found: {team_id}")

            # Check if user is a team OWNER
            membership = self.db.execute(
                select(EmailTeamMember).where(and_(EmailTeamMember.team_id == team_id, EmailTeamMember.user_email == user_email, EmailTeamMember.role == "owner", EmailTeamMember.is_active.is_(True)))
            ).scalar_one_or_none()

            if not membership:
                raise ValueError(f"Only team owners can create API keys for team {team_id}")

        # Check for duplicate token name (scoped by user and team)
        name_check_conditions = [EmailApiToken.user_email == user_email, EmailApiToken.name == name, EmailApiToken.is_active.is_(True)]

        if team_id:
            name_check_conditions.append(EmailApiToken.team_id == team_id)
        else:
            name_check_conditions.append(EmailApiToken.team_id.is_(None))

        existing_token = self.db.execute(select(EmailApiToken).where(and_(*name_check_conditions))).scalar_one_or_none()

        if existing_token:
            scope_desc = f" for team {team_id}" if team_id else ""
            raise ValueError(f"Token name '{name}' already exists{scope_desc}")

        # Calculate expiry
        expires_at = None
        if expires_in_days:
            expires_at = utc_now() + timedelta(days=expires_in_days)

        # Generate JWT token with proper claims and user admin status
        raw_token = await self._generate_token(user_email=user_email, team_id=team_id, expires_at=expires_at, scope=scope, user=user)
        token_hash = self._hash_token(raw_token)

        # Create token record
        api_token = EmailApiToken(
            user_email=user_email,
            name=name,
            token_hash=token_hash,
            description=description,
            expires_at=expires_at,
            tags=tags or [],
            team_id=team_id,
            server_id=scope.server_id if scope else None,
            resource_scopes=scope.permissions if scope else [],
            ip_restrictions=scope.ip_restrictions if scope else [],
            time_restrictions=scope.time_restrictions if scope else {},
            usage_limits=scope.usage_limits if scope else {},
        )

        self.db.add(api_token)
        self.db.commit()
        self.db.refresh(api_token)

        scope_desc = f" for team {team_id}" if team_id else ""
        logger.info(f"Created API token '{name}' for user {user_email}{scope_desc}")

        return api_token, raw_token

    async def list_user_tokens(self, user_email: str, include_inactive: bool = False, limit: int = 100, offset: int = 0) -> List[EmailApiToken]:
        """List API tokens for a user.

        Args:
            user_email: User's email address
            include_inactive: Include inactive/expired tokens
            limit: Maximum tokens to return
            offset: Number of tokens to skip

        Returns:
            List[EmailApiToken]: User's API tokens

        Examples:
            >>> service = TokenCatalogService(None)  # Would use real DB session
            >>> # Returns List[EmailApiToken] for user
        """
        # Validate parameters
        if limit <= 0 or limit > 1000:
            limit = 50  # Use default
        offset = max(offset, 0)  # Use default
        query = select(EmailApiToken).where(EmailApiToken.user_email == user_email)

        if not include_inactive:
            query = query.where(and_(EmailApiToken.is_active.is_(True), or_(EmailApiToken.expires_at.is_(None), EmailApiToken.expires_at > utc_now())))

        query = query.order_by(EmailApiToken.created_at.desc()).limit(limit).offset(offset)

        result = self.db.execute(query)
        return result.scalars().all()

    async def list_team_tokens(self, team_id: str, user_email: str, include_inactive: bool = False, limit: int = 100, offset: int = 0) -> List[EmailApiToken]:
        """List API tokens for a team (only accessible by team owners).

        Args:
            team_id: Team ID to list tokens for
            user_email: User's email (must be team owner)
            include_inactive: Include inactive/expired tokens
            limit: Maximum tokens to return
            offset: Number of tokens to skip

        Returns:
            List[EmailApiToken]: Team's API tokens

        Raises:
            ValueError: If user is not a team owner
        """
        # Validate user is team owner
        # First-Party
        from mcpgateway.db import EmailTeamMember  # pylint: disable=import-outside-toplevel

        membership = self.db.execute(
            select(EmailTeamMember).where(and_(EmailTeamMember.team_id == team_id, EmailTeamMember.user_email == user_email, EmailTeamMember.role == "owner", EmailTeamMember.is_active.is_(True)))
        ).scalar_one_or_none()

        if not membership:
            raise ValueError(f"Only team owners can view team tokens for {team_id}")

        # Validate parameters
        if limit <= 0 or limit > 1000:
            limit = 50
        offset = max(offset, 0)

        query = select(EmailApiToken).where(EmailApiToken.team_id == team_id)

        if not include_inactive:
            query = query.where(and_(EmailApiToken.is_active.is_(True), or_(EmailApiToken.expires_at.is_(None), EmailApiToken.expires_at > utc_now())))

        query = query.order_by(EmailApiToken.created_at.desc()).limit(limit).offset(offset)
        result = self.db.execute(query)
        return result.scalars().all()

    async def get_token(self, token_id: str, user_email: Optional[str] = None) -> Optional[EmailApiToken]:
        """Get a specific token by ID.

        Args:
            token_id: Token ID
            user_email: Optional user email filter for security

        Returns:
            Optional[EmailApiToken]: Token if found and authorized

        Examples:
            >>> service = TokenCatalogService(None)  # Would use real DB session
            >>> # Returns Optional[EmailApiToken] if found and authorized
        """
        query = select(EmailApiToken).where(EmailApiToken.id == token_id)

        if user_email:
            query = query.where(EmailApiToken.user_email == user_email)

        result = self.db.execute(query)
        return result.scalar_one_or_none()

    async def update_token(
        self, token_id: str, user_email: str, name: Optional[str] = None, description: Optional[str] = None, scope: Optional[TokenScope] = None, tags: Optional[List[str]] = None
    ) -> Optional[EmailApiToken]:
        """Update an existing token.

        Args:
            token_id: Token ID to update
            user_email: Owner's email for security
            name: New token name
            description: New description
            scope: New scoping configuration
            tags: New tags

        Returns:
            Optional[EmailApiToken]: Updated token if found

        Raises:
            ValueError: If token not found or name conflicts

        Examples:
            >>> service = TokenCatalogService(None)  # Would use real DB session
            >>> # Returns Optional[EmailApiToken] if updated successfully
        """
        token = await self.get_token(token_id, user_email)
        if not token:
            raise ValueError("Token not found or not authorized")

        # Check for duplicate name if changing
        if name and name != token.name:
            existing = self.db.execute(
                select(EmailApiToken).where(and_(EmailApiToken.user_email == user_email, EmailApiToken.name == name, EmailApiToken.id != token_id, EmailApiToken.is_active.is_(True)))
            ).scalar_one_or_none()

            if existing:
                raise ValueError(f"Token name '{name}' already exists")

            token.name = name

        if description is not None:
            token.description = description

        if tags is not None:
            token.tags = tags

        if scope:
            token.server_id = scope.server_id
            token.resource_scopes = scope.permissions
            token.ip_restrictions = scope.ip_restrictions
            token.time_restrictions = scope.time_restrictions
            token.usage_limits = scope.usage_limits

        self.db.commit()
        self.db.refresh(token)

        logger.info(f"Updated token '{token.name}' for user {user_email}")

        return token

    async def revoke_token(self, token_id: str, revoked_by: str, reason: Optional[str] = None) -> bool:
        """Revoke a token immediately.

        Args:
            token_id: Token ID to revoke
            revoked_by: Email of user revoking the token
            reason: Optional reason for revocation

        Returns:
            bool: True if token was revoked

        Examples:
            >>> service = TokenCatalogService(None)  # Would use real DB session
            >>> # Returns bool: True if token was revoked successfully
        """
        token = await self.get_token(token_id)
        if not token:
            return False

        # Mark token as inactive
        token.is_active = False

        # Add to blacklist
        revocation = TokenRevocation(jti=token.jti, revoked_by=revoked_by, reason=reason)

        self.db.add(revocation)
        self.db.commit()

        logger.info(f"Revoked token '{token.name}' (JTI: {token.jti}) by {revoked_by}")

        return True

    async def is_token_revoked(self, jti: str) -> bool:
        """Check if a token JTI is revoked.

        Args:
            jti: JWT ID to check

        Returns:
            bool: True if token is revoked

        Examples:
            >>> service = TokenCatalogService(None)  # Would use real DB session
            >>> # Returns bool: True if token is revoked
        """
        revocation = self.db.execute(select(TokenRevocation).where(TokenRevocation.jti == jti)).scalar_one_or_none()

        return revocation is not None

    async def log_token_usage(
        self,
        jti: str,
        user_email: str,
        endpoint: Optional[str] = None,
        method: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        status_code: Optional[int] = None,
        response_time_ms: Optional[int] = None,
        blocked: bool = False,
        block_reason: Optional[str] = None,
    ) -> None:
        """Log token usage for analytics and security.

        Args:
            jti: JWT ID of token used
            user_email: Token owner's email
            endpoint: API endpoint accessed
            method: HTTP method
            ip_address: Client IP address
            user_agent: Client user agent
            status_code: HTTP response status
            response_time_ms: Response time in milliseconds
            blocked: Whether request was blocked
            block_reason: Reason for blocking

        Examples:
            >>> service = TokenCatalogService(None)  # Would use real DB session
            >>> # Logs token usage for analytics - no return value
        """
        usage_log = TokenUsageLog(
            token_jti=jti,
            user_email=user_email,
            endpoint=endpoint,
            method=method,
            ip_address=ip_address,
            user_agent=user_agent,
            status_code=status_code,
            response_time_ms=response_time_ms,
            blocked=blocked,
            block_reason=block_reason,
        )

        self.db.add(usage_log)
        self.db.commit()

        # Update token last_used timestamp
        token = self.db.execute(select(EmailApiToken).where(EmailApiToken.jti == jti)).scalar_one_or_none()

        if token:
            token.last_used = utc_now()
            self.db.commit()

    async def get_token_usage_stats(self, user_email: str, token_id: Optional[str] = None, days: int = 30) -> dict:
        """Get token usage statistics.

        Args:
            user_email: User's email address
            token_id: Optional specific token ID
            days: Number of days to analyze

        Returns:
            dict: Usage statistics

        Examples:
            >>> service = TokenCatalogService(None)  # Would use real DB session
            >>> # Returns dict with usage statistics
        """
        start_date = utc_now() - timedelta(days=days)

        query = select(TokenUsageLog).where(and_(TokenUsageLog.user_email == user_email, TokenUsageLog.timestamp >= start_date))

        if token_id:
            # Get JTI for the token
            token = await self.get_token(token_id, user_email)
            if token:
                query = query.where(TokenUsageLog.token_jti == token.jti)

        usage_logs = self.db.execute(query).scalars().all()

        # Calculate statistics
        total_requests = len(usage_logs)
        successful_requests = sum(1 for log in usage_logs if log.status_code and log.status_code < 400)
        blocked_requests = sum(1 for log in usage_logs if log.blocked)

        # Average response time
        response_times = [log.response_time_ms for log in usage_logs if log.response_time_ms]
        avg_response_time = sum(response_times) / len(response_times) if response_times else 0

        # Most accessed endpoints
        endpoint_counts = {}
        for log in usage_logs:
            if log.endpoint:
                endpoint_counts[log.endpoint] = endpoint_counts.get(log.endpoint, 0) + 1

        top_endpoints = sorted(endpoint_counts.items(), key=lambda x: x[1], reverse=True)[:5]

        return {
            "period_days": days,
            "total_requests": total_requests,
            "successful_requests": successful_requests,
            "blocked_requests": blocked_requests,
            "success_rate": successful_requests / total_requests if total_requests > 0 else 0,
            "average_response_time_ms": round(avg_response_time, 2),
            "top_endpoints": top_endpoints,
        }

    async def get_token_revocation(self, jti: str) -> Optional[TokenRevocation]:
        """Get token revocation information by JTI.

        Args:
            jti: JWT token ID

        Returns:
            Optional[TokenRevocation]: Revocation info if token is revoked

        Examples:
            >>> service = TokenCatalogService(None)  # Would use real DB session
            >>> # Returns Optional[TokenRevocation] if token is revoked
        """
        result = self.db.execute(select(TokenRevocation).where(TokenRevocation.jti == jti))
        return result.scalar_one_or_none()

    async def cleanup_expired_tokens(self) -> int:
        """Clean up expired tokens.

        Returns:
            int: Number of tokens cleaned up

        Examples:
            >>> service = TokenCatalogService(None)  # Would use real DB session
            >>> # Returns int: Number of tokens cleaned up
        """
        expired_tokens = self.db.execute(select(EmailApiToken).where(and_(EmailApiToken.expires_at < utc_now(), EmailApiToken.is_active.is_(True)))).scalars().all()

        for token in expired_tokens:
            token.is_active = False

        self.db.commit()

        logger.info(f"Cleaned up {len(expired_tokens)} expired tokens")

        return len(expired_tokens)
