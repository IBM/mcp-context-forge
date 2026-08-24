# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/token_backends/base.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Base interface for pluggable token storage backends.

This module defines the abstract interface that all token storage backends
must implement, plus a plain dataclass for token records (no SQLAlchemy).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

# Re-export canonical normalize_resource from utils.oauth_resource
# (avoids duplication - refresh_helpers imports from here for backward compat)
from mcpgateway.utils.oauth_resource import normalize_resource as normalize_resource_url

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

__all__ = ["TokenRecord", "AbstractTokenBackend", "normalize_resource_url"]


@dataclass
class TokenRecord:
    """
    Plain dataclass for token records - no SQLAlchemy dependencies.
    Used by all backends to return token data in a consistent format.
    """

    gateway_id: str  # gateways.id (UUID) - used by DB backend as FK
    mcp_url: str  # gateways.url - resolved by VaultTokenBackend; Vault path key
    team_id: str | None  # Team identifier - None for shared/fallback path (Admin UI sessions)
    user_id: str  # OAuth provider user ID (e.g., GitHub numeric UID)
    app_user_email: str  # ContextForge user identity
    access_token: str  # Plain-text (backends handle encryption differently)
    refresh_token: str | None  # Nullable
    token_type: str  # Always "Bearer"
    expires_at: datetime | None  # Nullable (some providers omit expiry)
    scopes: list[str]  # OAuth scopes
    created_at: datetime
    updated_at: datetime
    learned_aud: str | None = None  # Learned JWT audience from token introspection
    learned_iss: str | None = None  # Learned JWT issuer from token introspection


class AbstractTokenBackend(ABC):
    """
    Backend-agnostic token storage interface.

    All methods receive gateway_id and team_id. Each backend uses them appropriately:
      - DatabaseTokenBackend → uses gateway_id directly as FK; team_id ignored (no DB column yet)
      - VaultTokenBackend    → uses team_id in path; resolves gateway_id → mcp_url → server_id

    The CLIENT never passes gateway_id or team_id. It only knows server_id (virtual server URL).
    The service layer extracts team_id from authenticated user context (JWT/session), and
    resolves gateway_id from: server_id → server_tool_association → tools.gateway_id.
    """

    def _resolve_mcp_url(self, gateway_id: str) -> str:
        """Resolve gateway_id → gateways.url.

        Shared helper used by both DatabaseTokenBackend and VaultTokenBackend.
        Requires ``self.db`` to be set by the concrete subclass ``__init__``.

        Args:
            gateway_id: Gateway UUID

        Returns:
            Gateway URL (mcp_url)

        Raises:
            ValueError: If gateway not found
        """
        # Import here to avoid a hard dependency from base.py on the ORM model.
        from mcpgateway.db import Gateway  # pylint: disable=import-outside-toplevel

        db: "Session" = self.db  # type: ignore[attr-defined]  # pylint: disable=no-member
        gateway = db.get(Gateway, gateway_id)
        if not gateway:
            raise ValueError(f"Gateway {gateway_id} not found")
        return gateway.url

    @abstractmethod
    async def store_tokens(
        self,
        gateway_id: str,  # UUID from gateways.id - passed by all existing call sites
        team_id: str,  # Team identifier from user context (JWT/session)
        user_id: str,  # OAuth provider user ID
        app_user_email: str,  # ContextForge user email
        access_token: str,
        refresh_token: str | None,
        expires_in: int | None,
        scopes: list[str],
        learned_aud: str | None = None,  # Learned JWT audience from token introspection
        learned_iss: str | None = None,  # Learned JWT issuer from token introspection
    ) -> TokenRecord:
        """
        Store OAuth tokens for a user.

        Called at OAuth callback after IdP returns tokens.
        DatabaseTokenBackend: encrypts with Fernet, UPSERTs to oauth_tokens table
        VaultTokenBackend: resolves gateway_id → mcp_url, writes plain-text to Vault KV v2

        Args:
            gateway_id: UUID from gateways.id - passed by all existing call sites
            team_id: Team identifier from user context (JWT/session)
            user_id: OAuth provider user ID
            app_user_email: ContextForge user email
            access_token: Access token from OAuth provider
            refresh_token: Refresh token from OAuth provider (optional)
            expires_in: Token expiration in seconds, or None
            scopes: OAuth scopes granted
            learned_aud: Per-user learned audience claim from IdP token (optional)
            learned_iss: Per-user learned issuer claim from IdP token (optional)

        Returns:
            TokenRecord with plain-text tokens for immediate use
        """

    @abstractmethod
    async def get_user_token(
        self,
        gateway_id: str,
        team_id: str,  # Team identifier from user context
        app_user_email: str,
        threshold_seconds: int = 300,
    ) -> str | None:
        """
        Retrieve access token for a user, auto-refreshing if near expiry.

        Called on every tool call / health-check / resource fetch.
        Returns plain-text access token ready for Authorization header.
        Returns None if no token found (user needs to authorize).

        Auto-refresh logic:
        - If token expires within threshold_seconds, attempt refresh
        - If refresh succeeds, store new token and return it
        - If refresh fails, return None (user must re-authorize)
        """

    @abstractmethod
    async def get_token_info(
        self,
        gateway_id: str,
        team_id: str,  # Team identifier from user context
        app_user_email: str,
    ) -> dict | None:
        """
        Get non-sensitive token metadata for admin/status API.

        Returns dict with keys:
        - scopes: list[str]
        - expires_at: str (ISO-8601) or None
        - status: "valid" | "expired" | "near_expiry"
        - updated_at: str (ISO-8601)

        Returns None if no token found.
        Does NOT return actual token values.
        """

    @abstractmethod
    async def revoke_user_tokens(
        self,
        gateway_id: str,
        team_id: str,  # Team identifier from user context
        app_user_email: str,
    ) -> bool:
        """
        Delete/revoke stored tokens for a user.

        Called at user logout or admin revoke.
        DatabaseTokenBackend: SQL DELETE on matching row
        VaultTokenBackend: Vault KV soft-delete (hard-delete via metadata endpoint)

        Returns True if deleted, False if not found.
        """

    @abstractmethod
    async def cleanup_expired_tokens(
        self,
        max_age_days: int = 30,
    ) -> int:
        """
        Clean up expired/old tokens (maintenance job).

        DatabaseTokenBackend: SQL DELETE WHERE expires_at < cutoff
        VaultTokenBackend: No-op, returns 0 (Vault KV TTL handles cleanup)

        Returns count of deleted tokens.
        """

    @abstractmethod
    async def get_user_learned_audience(
        self,
        gateway_id: str,
        team_id: str,  # Team identifier - required by Vault backend for path construction
        app_user_email: str,
    ) -> tuple[str | None, str | None]:
        """
        Return the per-user learned JWT audience and issuer for a gateway-user pair.

        Used by token_validation_service.validate_oauth_token_claims to authoritatively
        validate a user's token audience against the value learned from their own prior
        OAuth callback, rather than a globally-shared gateway.oauth_config value.

        Args:
            gateway_id: ID of the gateway
            team_id: Team identifier (Vault backend uses this for path; DB backend ignores it)
            app_user_email: ContextForge user email

        Returns:
            Tuple of (learned_aud, learned_iss). Either element may be None if
            no token record exists or if the fields were never populated.
        """

    async def get_oauth_credentials(self, team_id: str | None, mcp_url: str) -> dict | None:  # pylint: disable=unused-argument
        """
        Retrieve team-scoped OAuth credentials (optional extension).

        Default implementation returns None (not supported).
        VaultTokenBackend overrides this to look up per-team client credentials
        stored at {mount}/data/{prefix}/credentials/{team_id}/{server_id}.

        Args:
            team_id: Team identifier (or None for shared path)
            mcp_url: Gateway URL

        Returns:
            OAuth config dict or None if not found / not supported.
        """
        return None

    async def store_oauth_credentials(  # pylint: disable=unused-argument
        self,
        team_id: str,
        mcp_url: str,
        credentials: dict,
    ) -> bool:
        """Store team-scoped OAuth credentials (optional extension).

        Default implementation returns False (not supported).
        VaultTokenBackend overrides this to write per-team client credentials
        at {mount}/data/{prefix}/credentials/{team_id}/{server_id}.

        This enables multi-team same-URL scenarios where each team registers
        the same MCP server with independent OAuth apps and credentials.
        Reserved for a future admin API that provisions per-team OAuth apps.

        Args:
            team_id: Team identifier
            mcp_url: Gateway URL
            credentials: OAuth config dict (client_id, client_secret, etc.)

        Returns:
            True if stored successfully, False if not supported or on error.
        """
        return False

    async def get_user_auth_headers(  # pylint: disable=unused-argument
        self,
        gateway_id: str,
        team_id: str,
        app_user_email: str,
    ) -> dict | None:
        """Return per-user non-OAuth auth headers for a gateway call.

        ICA (Identity-aware Credential Agent) writes a plain ``{header: value}``
        dict under a ``headers`` key at the same per-user Vault path used for
        OAuth tokens (``{mount}/data/{prefix}/{team}/{server_id}/{email}``).
        This method retrieves that dict so callers can merge it into the upstream
        request headers for non-OAuth gateway auth types (bearer/basic/authheaders).

        Default implementation returns None (not supported by this backend).
        VaultTokenBackend overrides this to read the ``headers`` field from the
        per-user Vault record.

        Args:
            gateway_id: Gateway UUID (resolved to mcp_url by Vault backend)
            team_id: Team identifier (used in Vault path; ignored by DB backend)
            app_user_email: ContextForge user email

        Returns:
            Dict of ``{header_name: header_value}`` pairs, or None if not supported
            or no per-user record exists.
        """
        return None
