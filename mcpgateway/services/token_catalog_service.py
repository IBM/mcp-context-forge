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
from sqlalchemy import and_, case, func, or_, select
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

    async def _generate_token(
        self, user_email: str, jti: str, team_id: Optional[str] = None, expires_at: Optional[datetime] = None, scope: Optional["TokenScope"] = None, user: Optional[object] = None
    ) -> str:
        """Generate a JWT token for API access.

        This internal method creates a properly formatted JWT token with all
        necessary claims including user identity, scopes, team membership,
        and expiration. The token follows the MCP Gateway JWT structure.

        Args:
            user_email: User's email address for the token subject
            jti: JWT ID for token uniqueness
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
            "jti": jti,  # JWT ID for uniqueness
            "user": {"email": user_email, "full_name": "API Token User", "is_admin": user.is_admin if user else False, "auth_provider": "api_token"},  # Use actual admin status if user provided
            "teams": [team_id] if team_id else [],
            "namespaces": [f"user:{user_email}", "public"] + ([f"team:{team_id}"] if team_id else []),
        }

        # Add expiration if specified
        if expires_at:
            payload["exp"] = int(expires_at.timestamp())

        # Add scoping information if available
        # Empty permissions = defer to RBAC at runtime (not wildcard access)
        if scope:
            payload["scopes"] = {
                "server_id": scope.server_id,
                "permissions": scope.permissions if scope.permissions is not None else [],
                "ip_restrictions": scope.ip_restrictions or [],
                "time_restrictions": scope.time_restrictions or {},
            }
        else:
            payload["scopes"] = {
                "server_id": None,
                "permissions": [],  # Empty = inherit from RBAC at runtime
                "ip_restrictions": [],
                "time_restrictions": {},
            }

        # Generate JWT token using the centralized token creation utility
        # The create_jwt_token will handle expiration and other standard claims
        return await create_jwt_token(payload, expires_in_minutes=0)

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

    def _validate_scope_containment(
        self,
        requested_permissions: Optional[List[str]],
        caller_permissions: Optional[List[str]],
    ) -> None:
        """Validate that requested permissions don't exceed caller's permissions.

        SECURITY: This is fail-secure. If caller_permissions is empty/None,
        custom scopes are DENIED. Users without explicit permissions can only
        create tokens with empty scope (inherit at runtime).

        Args:
            requested_permissions: Permissions requested for new/updated token
            caller_permissions: Caller's effective permissions (RBAC + current token scopes)

        Raises:
            ValueError: If requested permissions exceed caller's permissions
        """
        # No requested permissions = empty scope, always allowed
        if not requested_permissions:
            return

        # FAIL-SECURE: If caller has no permissions, deny any custom scope
        if not caller_permissions:
            raise ValueError("Cannot specify custom token permissions. " + "You have no explicit permissions to delegate. " + "Create a token without scope to inherit permissions at runtime.")

        # Wildcard caller can grant anything
        if "*" in caller_permissions:
            return

        # Wildcard request requires wildcard caller
        if "*" in requested_permissions:
            raise ValueError("Cannot create token with wildcard permissions. " + "Your effective permissions do not include wildcard access.")

        # Check each requested permission
        for req_perm in requested_permissions:
            if req_perm in caller_permissions:
                continue

            # Check for category wildcard (e.g., "tools.*" allows "tools.read")
            if "." in req_perm:
                category = req_perm.split(".")[0]
                if f"{category}.*" in caller_permissions:
                    continue

            raise ValueError(f"Cannot grant permission '{req_perm}' - not in your effective permissions.")

    async def create_token(
        self,
        user_email: str,
        name: str,
        description: Optional[str] = None,
        scope: Optional[TokenScope] = None,
        expires_in_days: Optional[int] = None,
        tags: Optional[List[str]] = None,
        team_id: Optional[str] = None,
        caller_permissions: Optional[List[str]] = None,
    ) -> tuple[EmailApiToken, str]:
        """
        Create a new API token with team-level scoping and additional configurations.

        This method generates a JWT-based API token with team-level scoping and optional security configurations,
        such as expiration, permissions, IP restrictions, and usage limits. The token is associated with a user
        and a specific team, ensuring access control and multi-tenancy support.

        The function will:
        - Validate the existence of the user.
        - Ensure the user is an active member of the specified team.
        - Verify that the token name is unique for the user+team combination.
        - Generate a JWT with the specified scoping parameters (e.g., permissions, IP, etc.).
        - Store the token in the database with the relevant details and return the token and raw JWT string.

        Args:
            user_email (str): The email address of the user requesting the token.
            name (str): A unique, human-readable name for the token (must be unique per user+team).
            description (Optional[str]): A description for the token (default is None).
            scope (Optional[TokenScope]): The scoping configuration for the token, including permissions,
                server ID, IP restrictions, etc. (default is None).
            expires_in_days (Optional[int]): The expiration time in days for the token (None means no expiration).
            tags (Optional[List[str]]): A list of organizational tags for the token (default is an empty list).
            team_id (Optional[str]): The team ID to which the token should be scoped. This is required for team-level scoping.
            caller_permissions (Optional[List[str]]): The permissions of the caller creating the token. Used for
                scope containment validation to ensure the new token cannot have broader permissions than the caller.

        Returns:
            tuple[EmailApiToken, str]: A tuple where the first element is the `EmailApiToken` database record and
            the second element is the raw JWT token string. The `EmailApiToken` contains the database record with the
            token details.

        Raises:
            ValueError: If any of the following validation checks fail:
                - The `user_email` does not correspond to an existing user.
                - The `team_id` is missing or the user is not an active member of the specified team.
                - A token with the same name already exists for the given user and team.
                - Invalid token configuration (e.g., invalid expiration date).

        Examples:
            >>> # This method requires database operations, shown for reference
            >>> service = TokenCatalogService(None)  # Would use real DB session
            >>> # token, raw_token = await service.create_token(...)
            >>> # Returns (EmailApiToken, raw_token_string) tuple
        """
        # # Enforce team-level scoping requirement
        # if not team_id:
        #     raise ValueError("team_id is required for token creation. " "Please select a specific team before creating a token. " "You cannot create tokens while viewing 'All Teams'.")

        # Validate user exists
        user = self.db.execute(select(EmailUser).where(EmailUser.email == user_email)).scalar_one_or_none()

        if not user:
            raise ValueError(f"User not found: {user_email}")

        # Validate scope containment (fail-secure if no caller_permissions)
        if scope and scope.permissions:
            self._validate_scope_containment(scope.permissions, caller_permissions)

        # Validate team exists and user is active member
        if team_id:
            # First-Party
            from mcpgateway.db import EmailTeam, EmailTeamMember  # pylint: disable=import-outside-toplevel

            # Check if team exists
            team = self.db.execute(select(EmailTeam).where(EmailTeam.id == team_id)).scalar_one_or_none()

            if not team:
                raise ValueError(f"Team not found: {team_id}")

            # Verify user is an active member of the team
            membership = self.db.execute(
                select(EmailTeamMember).where(and_(EmailTeamMember.team_id == team_id, EmailTeamMember.user_email == user_email, EmailTeamMember.is_active.is_(True)))
            ).scalar_one_or_none()

            if not membership:
                raise ValueError(f"User {user_email} is not an active member of team {team_id}. Only team members can create tokens for the team.")

        # Check for duplicate active token name for this user+team
        existing_token = self.db.execute(
            select(EmailApiToken).where(and_(EmailApiToken.user_email == user_email, EmailApiToken.name == name, EmailApiToken.team_id == team_id, EmailApiToken.is_active.is_(True)))
        ).scalar_one_or_none()

        if existing_token:
            raise ValueError(f"Token with name '{name}' already exists for user {user_email} in team {team_id}. Please choose a different name.")

        # CALCULATE EXPIRATION DATE
        expires_at = None
        if expires_in_days:
            expires_at = utc_now() + timedelta(days=expires_in_days)

        jti = str(uuid.uuid4())  # Unique JWT ID
        # Generate JWT token with all necessary claims
        raw_token = await self._generate_token(user_email=user_email, jti=jti, team_id=team_id, expires_at=expires_at, scope=scope, user=user)  # Pass user object to include admin status

        # Hash token for secure storage
        token_hash = self._hash_token(raw_token)

        # Create database record
        api_token = EmailApiToken(
            id=str(uuid.uuid4()),
            user_email=user_email,
            team_id=team_id,  # Store team association
            name=name,
            jti=jti,
            description=description,
            token_hash=token_hash,  # Store hash, not raw token
            expires_at=expires_at,
            tags=tags or [],
            # Store scoping information
            server_id=scope.server_id if scope else None,
            resource_scopes=scope.permissions if scope else [],
            ip_restrictions=scope.ip_restrictions if scope else [],
            time_restrictions=scope.time_restrictions if scope else {},
            usage_limits=scope.usage_limits if scope else {},
            # Token status
            is_active=True,
            created_at=utc_now(),
            last_used=None,
        )

        self.db.add(api_token)
        self.db.commit()
        self.db.refresh(api_token)

        token_type = f"team-scoped (team: {team_id})" if team_id else "public-only"
        logger.info(f"Created {token_type} API token '{name}' for user {user_email}. Token ID: {api_token.id}, Expires: {expires_at or 'Never'}")
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
        self,
        token_id: str,
        user_email: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        scope: Optional[TokenScope] = None,
        tags: Optional[List[str]] = None,
        caller_permissions: Optional[List[str]] = None,
    ) -> Optional[EmailApiToken]:
        """Update an existing token with scope containment validation.

        Args:
            token_id: Token ID to update
            user_email: Owner's email for security
            name: New token name
            description: New description
            scope: New scoping configuration
            tags: New tags
            caller_permissions: Caller's effective permissions for scope containment

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

        # Validate scope containment for scope changes
        if scope and scope.permissions:
            self._validate_scope_containment(scope.permissions, caller_permissions)

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

    async def revoke_token(self, token_id: str, user_email: str, revoked_by: str, reason: Optional[str] = None) -> bool:
        """Revoke a token owned by the specified user.

        Args:
            token_id: Token ID to revoke
            user_email: Owner's email - token must belong to this user (ownership check)
            revoked_by: Email of user performing revocation (for audit)
            reason: Optional reason for revocation

        Returns:
            bool: True if token was revoked, False if not found or not authorized

        Examples:
            >>> service = TokenCatalogService(None)  # Would use real DB session
            >>> # Returns bool: True if token was revoked successfully
        """
        # SECURITY FIX: Filter by owner to prevent cross-user revocation
        token = await self.get_token(token_id, user_email)
        if not token:
            return False

        # Mark token as inactive
        token.is_active = False

        # Add to blacklist
        revocation = TokenRevocation(jti=token.jti, revoked_by=revoked_by, reason=reason)

        self.db.add(revocation)
        self.db.commit()

        # Invalidate auth cache for revoked token
        try:
            # Standard
            import asyncio  # pylint: disable=import-outside-toplevel

            # First-Party
            from mcpgateway.cache.auth_cache import auth_cache  # pylint: disable=import-outside-toplevel

            asyncio.create_task(auth_cache.invalidate_revocation(token.jti))
        except Exception as cache_error:
            logger.debug(f"Failed to invalidate auth cache for revoked token: {cache_error}")

        logger.info(f"Revoked token '{token.name}' (JTI: {token.jti}) by {revoked_by}")

        return True

    async def admin_revoke_token(self, token_id: str, revoked_by: str, reason: Optional[str] = None) -> bool:
        """Admin-only: Revoke any token without ownership check.

        WARNING: This method bypasses ownership verification.
        Only call from admin-authenticated endpoints.

        Args:
            token_id: Token ID to revoke
            revoked_by: Admin email for audit
            reason: Revocation reason

        Returns:
            bool: True if token was revoked, False if not found

        Examples:
            >>> service = TokenCatalogService(None)  # Would use real DB session
            >>> # Returns bool: True if token was revoked successfully
        """
        # No user filter - admin can revoke any token
        token = await self.get_token(token_id)
        if not token:
            return False

        token.is_active = False
        revocation = TokenRevocation(jti=token.jti, revoked_by=revoked_by, reason=reason)
        self.db.add(revocation)
        self.db.commit()

        try:
            # Standard
            import asyncio  # pylint: disable=import-outside-toplevel

            # First-Party
            from mcpgateway.cache.auth_cache import auth_cache  # pylint: disable=import-outside-toplevel

            asyncio.create_task(auth_cache.invalidate_revocation(token.jti))
        except Exception as cache_error:
            logger.debug(f"Failed to invalidate auth cache: {cache_error}")

        logger.info(f"Admin revoked token '{token.name}' (JTI: {token.jti}) by {revoked_by}")
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

        # Get token JTI if specific token requested
        token_jti = None
        if token_id:
            token = await self.get_token(token_id, user_email)
            if token:
                token_jti = token.jti

        # Use SQL aggregation for PostgreSQL, Python fallback for SQLite
        dialect_name = self.db.get_bind().dialect.name
        if dialect_name == "postgresql":
            return await self._get_usage_stats_postgresql(user_email, start_date, token_jti, days)
        return await self._get_usage_stats_python(user_email, start_date, token_jti, days)

    async def _get_usage_stats_postgresql(self, user_email: str, start_date: datetime, token_jti: Optional[str], days: int) -> dict:
        """Compute usage stats using PostgreSQL SQL aggregation.

        Args:
            user_email: User's email address
            start_date: Start date for analysis
            token_jti: Optional token JTI filter
            days: Number of days being analyzed

        Returns:
            dict: Usage statistics computed via SQL
        """
        # Build filter conditions
        conditions = [TokenUsageLog.user_email == user_email, TokenUsageLog.timestamp >= start_date]
        if token_jti:
            conditions.append(TokenUsageLog.token_jti == token_jti)

        base_filter = and_(*conditions)

        # Main stats query using SQL aggregation
        # Match Python behavior:
        # - status_code must be non-null AND non-zero AND < 400 for success count
        # - response_time_ms must be non-null AND non-zero for average (Python: if log.response_time_ms)
        stats_query = (
            select(
                func.count().label("total"),  # pylint: disable=not-callable
                func.sum(
                    case(
                        (and_(TokenUsageLog.status_code.isnot(None), TokenUsageLog.status_code > 0, TokenUsageLog.status_code < 400), 1),
                        else_=0,
                    )
                ).label("successful"),
                func.sum(case((TokenUsageLog.blocked.is_(True), 1), else_=0)).label("blocked"),
                # Only average non-null and non-zero response times (NULL values are ignored by AVG)
                func.avg(
                    case(
                        (and_(TokenUsageLog.response_time_ms.isnot(None), TokenUsageLog.response_time_ms > 0), TokenUsageLog.response_time_ms),
                        else_=None,
                    )
                ).label("avg_response"),
            )
            .select_from(TokenUsageLog)
            .where(base_filter)
        )

        result = self.db.execute(stats_query).fetchone()

        total_requests = result.total or 0
        successful_requests = result.successful or 0
        blocked_requests = result.blocked or 0
        avg_response_time = float(result.avg_response) if result.avg_response else 0.0

        # Top endpoints query using SQL GROUP BY
        # Match Python behavior: exclude None AND empty string endpoints (Python: if log.endpoint)
        endpoints_query = (
            select(TokenUsageLog.endpoint, func.count().label("count"))  # pylint: disable=not-callable
            .where(and_(base_filter, TokenUsageLog.endpoint.isnot(None), TokenUsageLog.endpoint != ""))
            .group_by(TokenUsageLog.endpoint)
            .order_by(func.count().desc())  # pylint: disable=not-callable
            .limit(5)
        )

        endpoints_result = self.db.execute(endpoints_query).fetchall()
        top_endpoints = [(row.endpoint, row.count) for row in endpoints_result]

        return {
            "period_days": days,
            "total_requests": total_requests,
            "successful_requests": successful_requests,
            "blocked_requests": blocked_requests,
            "success_rate": successful_requests / total_requests if total_requests > 0 else 0,
            "average_response_time_ms": round(avg_response_time, 2),
            "top_endpoints": top_endpoints,
        }

    async def _get_usage_stats_python(self, user_email: str, start_date: datetime, token_jti: Optional[str], days: int) -> dict:
        """Compute usage stats using Python (fallback for SQLite).

        Args:
            user_email: User's email address
            start_date: Start date for analysis
            token_jti: Optional token JTI filter
            days: Number of days being analyzed

        Returns:
            dict: Usage statistics computed in Python
        """
        query = select(TokenUsageLog).where(and_(TokenUsageLog.user_email == user_email, TokenUsageLog.timestamp >= start_date))

        if token_jti:
            query = query.where(TokenUsageLog.token_jti == token_jti)

        usage_logs = self.db.execute(query).scalars().all()

        # Calculate statistics
        total_requests = len(usage_logs)
        successful_requests = sum(1 for log in usage_logs if log.status_code and log.status_code < 400)
        blocked_requests = sum(1 for log in usage_logs if log.blocked)

        # Average response time
        response_times = [log.response_time_ms for log in usage_logs if log.response_time_ms]
        avg_response_time = sum(response_times) / len(response_times) if response_times else 0

        # Most accessed endpoints
        endpoint_counts: dict = {}
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
        """Clean up expired tokens using bulk UPDATE.

        Uses a single SQL UPDATE statement instead of loading tokens into memory
        and updating them one by one. This is more efficient and avoids memory
        issues when many tokens expire at once.

        Returns:
            int: Number of tokens cleaned up

        Examples:
            >>> service = TokenCatalogService(None)  # Would use real DB session
            >>> # Returns int: Number of tokens cleaned up
        """
        try:
            now = utc_now()
            count = self.db.query(EmailApiToken).filter(EmailApiToken.expires_at < now, EmailApiToken.is_active.is_(True)).update({"is_active": False}, synchronize_session=False)

            self.db.commit()

            if count > 0:
                logger.info(f"Cleaned up {count} expired tokens")

            return count

        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to cleanup expired tokens: {e}")
            return 0
