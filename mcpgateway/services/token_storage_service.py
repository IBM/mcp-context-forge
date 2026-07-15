# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/token_storage_service.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

OAuth Token Storage Service for ContextForge - Façade Pattern.

This module provides a unified interface for token storage, delegating to
pluggable backends (database or Vault) based on configuration.

Phase 1: Minimal façade implementation with backend selection.
"""

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from mcpgateway.config import get_settings

# Import backends
from mcpgateway.services.token_backends import (
    AbstractTokenBackend,
    DatabaseTokenBackend,
    TokenRecord,
    VaultTokenBackend,
)

# For backward compatibility with tests that patch get_encryption_service
# Import it so it's accessible as a module attribute
from mcpgateway.services.token_backends.db_backend import get_encryption_service  # noqa: F401  # pylint: disable=unused-import

logger = logging.getLogger(__name__)


def build_token_user_context(
    db: Session,
    user_email: str,
    token_teams: Optional[List[str]],
) -> Dict[str, Any]:
    """Build a user_context dict for TokenStorageService without querying DB for teams.

    SECURITY: ``token_teams`` is the sole authority for the teams list.
    It comes from ``request.state.token_teams`` (already resolved by
    ``normalize_token_teams`` or ``resolve_session_teams`` in auth middleware).
    We deliberately do NOT query ``EmailTeamMember`` here — doing so would
    widen a narrowed session token back to full DB membership, violating the
    Layer 1 token-scoping invariant documented in AGENTS.md.

    The ``is_admin`` flag is a global, non-token-scoped property so a DB
    lookup for it is safe and intentional.

    Args:
        db: SQLAlchemy session (used only for the is_admin flag lookup).
        user_email: ContextForge user email address.
        token_teams: JWT-scoped team list from ``request.state.token_teams``.
            - ``None``  → Admin UI session (no teams claim) → shared Vault path
            - ``[]``    → Public-only token                 → shared Vault path
            - ``[...]`` → Team-scoped API token             → team Vault path

    Returns:
        Dict with keys ``email``, ``teams``, ``is_admin``.

    Examples:
        >>> from unittest.mock import MagicMock, patch
        >>> db = MagicMock()
        >>> db.execute.return_value.scalar_one_or_none.return_value = None
        >>> ctx = build_token_user_context(db, 'alice@example.com', ['engineering'])
        >>> ctx == {'email': 'alice@example.com', 'teams': ['engineering'], 'is_admin': False}
        True
        >>> ctx2 = build_token_user_context(db, 'alice@example.com', None)
        >>> ctx2['teams'] is None
        True
    """
    # First-Party - deferred to avoid circular imports at module load time
    from mcpgateway.db import EmailUser  # pylint: disable=import-outside-toplevel
    from sqlalchemy import select  # pylint: disable=import-outside-toplevel

    is_admin = False
    user_row = db.execute(select(EmailUser).where(EmailUser.email == user_email)).scalar_one_or_none()
    if user_row:
        is_admin = user_row.is_admin

    # Collapse both None (missing teams claim — Admin UI) and [] (explicit public-only
    # token) to None so the Vault backend routes both to the "shared" path segment.
    # These two cases have different meanings in the AGENTS.md token-scoping table
    # (None = Admin bypass, [] = public-only), but the Vault-path concern is only
    # *which bucket to store tokens in*: both Admin UI sessions and public-only tokens
    # lack a meaningful team scope, so sharing one Vault path is intentional for
    # Phase 1. If Phase 2 requires separate "shared-admin" vs. "shared-public" paths,
    # change this line to: ``effective_teams = token_teams if token_teams is not None else None``
    # and add the two distinct path segments in VaultTokenBackend._construct_vault_path().
    effective_teams: Optional[List[str]] = token_teams if token_teams else None

    return {
        "email": user_email,
        "teams": effective_teams,
        "is_admin": is_admin,
    }


class TokenStorageService:
    """
    Façade for OAuth token storage with pluggable backends.

    Selects backend based on OAUTH_TOKEN_BACKEND environment variable:
    - 'database' (default): DatabaseTokenBackend (existing behavior)
    - 'vault': VaultTokenBackend (stores in HashiCorp Vault)

    Extracts team_id from user_context and passes to backend along with gateway_id.
    Public method signatures remain unchanged for backward compatibility.
    """

    def __init__(self, db: Session, user_context: Optional[Dict[str, Any]] = None):
        """Initialize token storage service with selected backend.

        Args:
            db: SQLAlchemy session (used by both backends for different purposes:
                DatabaseTokenBackend uses it for token CRUD operations,
                VaultTokenBackend uses it for gateway_id → gateways.url resolution)
            user_context: JWT claims or session data for team_id extraction.
                Expected keys: 'email', 'teams' (list), 'is_admin' (bool)

        Raises:
            ValueError: If OAUTH_TOKEN_BACKEND has unknown value
        """
        self.db = db
        self.user_context = user_context or {}
        settings = get_settings()

        # Select backend based on configuration
        if settings.oauth_token_backend == "vault":
            self._backend: AbstractTokenBackend = VaultTokenBackend(db, settings)
            logger.info("Token storage backend: Vault (addr=%s)", settings.vault_addr)
        elif settings.oauth_token_backend == "database":
            self._backend = DatabaseTokenBackend(db, settings)
            logger.debug("Token storage backend: Database")
        else:
            raise ValueError(f"Unknown OAUTH_TOKEN_BACKEND: {settings.oauth_token_backend}. Expected 'database' or 'vault'.")

    def _get_team_id(self, gateway_id: str, app_user_email: str) -> Optional[str]:
        """
        Extract team_id from JWT user_context (sole source of truth).

        AUTHORITY DECISION: For multi-team tokens, uses teams[0] as the effective team.
        This is deterministic because:
        1. Token scoping middleware orders teams consistently (from DB query order)
        2. Vault backend requires a single team_id for path selection
        3. Same teams[0] logic used in OAuthManager.initiate_authorization_code_flow()

        Why JWT is the sole authority:
        - Vault path must match the team_id from the JWT that authorized the OAuth flow
        - Token scoping middleware (Layer 1) already validated user is member of this team
        - No fallback to DB prevents stale data or mismatched team context
        - Consistent with ContextForge security model: JWT claims are authoritative

        Args:
            gateway_id: Gateway ID (used only for the warning log message)
            app_user_email: User email (used only for the warning log message)

        Returns:
            Team identifier string from JWT (teams[0] if multiple teams), or None when
            the JWT has no 'teams' claim (Admin UI sessions without team context). A None
            return causes the Vault backend to use the shared path (vault/oauth/shared/...).

        Examples:
            >>> from unittest.mock import MagicMock
            >>> db = MagicMock()
            >>> service = TokenStorageService(db, user_context={'email': 'user@example.com', 'teams': ['engineering']})
            >>> service._get_team_id('gateway-123', 'user@example.com')
            'engineering'
            >>> service2 = TokenStorageService(db, user_context={'email': 'user@example.com'})
            >>> service2._get_team_id('gateway-123', 'user@example.com') is None
            True
        """
        # JWT teams claim is the ONLY source of truth
        if self.user_context:
            teams = self.user_context.get("teams", [])
            # Filter out empty strings — a JWT with teams=[""] is treated the same
            # as teams=[] (no meaningful team scope → shared path).
            if isinstance(teams, list):
                teams = [t for t in teams if t and isinstance(t, str)]
            if isinstance(teams, list) and teams:
                team_id = teams[0]

                # SECURITY: Vault backend relies on teams[0] being consistent across requests
                # for the same user. This consistency is guaranteed by AuthMiddleware's DB ordering
                # (sort by EmailTeamMember.id ascending). If teams ordering regresses, tokens would
                # be stored under the wrong Vault path, causing authorization failures.
                #
                # REGRESSION RISK: Any change to the team-query ORDER BY in AuthMiddleware
                # (e.g., sorting by team_name for display purposes) silently breaks multi-team
                # token lookup for the Vault backend. There is no runtime assertion here — track
                # this with a test fixture that exercises a multi-team user and asserts that
                # _get_team_id() returns the same team_id across multiple requests with the
                # same JWT. See: tests/unit/services/test_token_storage_service.py.
                #
                # Log a warning when multiple teams are present to aid debugging.
                if len(teams) > 1 and hasattr(self._backend, "__class__") and "Vault" in self._backend.__class__.__name__:
                    logger.warning(
                        "User %s has %d teams; using teams[0]=%s for Vault OAuth token path. "
                        "Vault backend requires stable team ordering (guaranteed by AuthMiddleware DB query ordering). "
                        "If token lookups fail, verify middleware team ordering has not regressed.",
                        app_user_email,
                        len(teams),
                        team_id,
                    )

                return team_id

        # Fallback: return None when JWT teams missing (for Admin UI sessions without team context)
        # This triggers fallback storage behavior (database or shared Vault path, less isolated)
        logger.warning(
            "OAuth token operation for user=%s, gateway=%s has no team_id from JWT 'teams' claim. "
            "Falling back to non-team-isolated storage (database or shared path). "
            "For multi-tenant isolation, ensure JWT includes 'teams' claim.",
            app_user_email,
            gateway_id,
        )
        return None

    async def store_tokens(
        self,
        gateway_id: str,
        user_id: str,
        app_user_email: str,
        access_token: str,
        refresh_token: Optional[str],
        expires_in: Optional[int],
        scopes: List[str],
    ) -> TokenRecord:
        """Store OAuth tokens for a gateway-user combination.

        Args:
            gateway_id: ID of the gateway
            user_id: OAuth provider user ID
            app_user_email: ContextForge user email (required)
            access_token: Access token from OAuth provider
            refresh_token: Refresh token from OAuth provider (optional)
            expires_in: Token expiration time in seconds, or None if the provider does not specify expiration
            scopes: List of OAuth scopes granted

        Returns:
            TokenRecord with token data

        Raises:
            OAuthError: If token storage fails
        """
        team_id = self._get_team_id(gateway_id, app_user_email)
        return await self._backend.store_tokens(
            gateway_id=gateway_id,
            team_id=team_id,
            user_id=user_id,
            app_user_email=app_user_email,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
            scopes=scopes,
        )

    async def get_user_token(
        self,
        gateway_id: str,
        app_user_email: str,
        threshold_seconds: int = 300,
    ) -> Optional[str]:
        """Get a valid access token for a specific ContextForge user, refreshing if necessary.

        Args:
            gateway_id: ID of the gateway
            app_user_email: ContextForge user email (required)
            threshold_seconds: Seconds before expiry to consider token expired

        Returns:
            Valid access token or None if no valid token available for this user
        """
        team_id = self._get_team_id(gateway_id, app_user_email)
        return await self._backend.get_user_token(
            gateway_id=gateway_id,
            team_id=team_id,
            app_user_email=app_user_email,
            threshold_seconds=threshold_seconds,
        )

    async def get_user_auth_headers(
        self,
        gateway_id: str,
        app_user_email: str,
    ) -> Optional[Dict[str, str]]:
        """Get per-user non-OAuth auth headers (bearer/basic/authheaders) for a user.

        Only the Vault backend stores these (written by ICA as a ``headers`` dict at the
        per-user path). Returns None for backends that don't support it.

        Args:
            gateway_id: ID of the gateway
            app_user_email: ContextForge user email (required)

        Returns:
            The ``{header: value}`` dict, or None.
        """
        backend_getter = getattr(self._backend, "get_user_auth_headers", None)
        if backend_getter is None:
            return None
        team_id = self._get_team_id(gateway_id, app_user_email)
        return await backend_getter(
            gateway_id=gateway_id,
            team_id=team_id,
            app_user_email=app_user_email,
        )

    async def get_token_info(
        self,
        gateway_id: str,
        app_user_email: str,
    ) -> Optional[Dict[str, Any]]:
        """Get information about stored OAuth tokens.

        Args:
            gateway_id: ID of the gateway
            app_user_email: ContextForge user email

        Returns:
            Token information dictionary or None if not found
        """
        team_id = self._get_team_id(gateway_id, app_user_email)
        return await self._backend.get_token_info(
            gateway_id=gateway_id,
            team_id=team_id,
            app_user_email=app_user_email,
        )

    async def revoke_user_tokens(
        self,
        gateway_id: str,
        app_user_email: str,
    ) -> bool:
        """Revoke OAuth tokens for a specific user.

        Args:
            gateway_id: ID of the gateway
            app_user_email: ContextForge user email

        Returns:
            True if tokens were revoked successfully
        """
        team_id = self._get_team_id(gateway_id, app_user_email)
        return await self._backend.revoke_user_tokens(
            gateway_id=gateway_id,
            team_id=team_id,
            app_user_email=app_user_email,
        )

    async def cleanup_expired_tokens(
        self,
        max_age_days: int = 30,
    ) -> int:
        """Clean up expired/old tokens.

        DatabaseTokenBackend: Deletes expired rows from oauth_tokens table.
        VaultTokenBackend: Returns 0 (Vault KV TTL handles cleanup).

        Args:
            max_age_days: Maximum age of tokens to keep

        Returns:
            Number of tokens cleaned up (0 for Vault backend)
        """
        return await self._backend.cleanup_expired_tokens(max_age_days=max_age_days)

    async def get_oauth_credentials(
        self,
        team_id: Optional[str],
        mcp_url: str,
    ) -> Optional[Dict[str, Any]]:
        """Retrieve team-scoped OAuth credentials from the active backend.

        DatabaseTokenBackend always returns None (no-op).
        VaultTokenBackend returns credentials stored at the team's Vault path.

        Args:
            team_id: Team identifier from JWT (or None for shared path)
            mcp_url: Gateway URL

        Returns:
            OAuth config dict or None if not found / not supported
        """
        return await self._backend.get_oauth_credentials(team_id, mcp_url)
