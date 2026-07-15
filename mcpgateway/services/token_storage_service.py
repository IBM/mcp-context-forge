# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/token_storage_service.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

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
            raise ValueError(
                f"Unknown OAUTH_TOKEN_BACKEND: {settings.oauth_token_backend}. "
                f"Expected 'database' or 'vault'."
            )

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
                if len(teams) > 1 and hasattr(self._backend, '__class__') and 'Vault' in self._backend.__class__.__name__:
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

        except Exception as e:
            logger.error("Failed to retrieve OAuth token: %s", str(e))
            return None

    # REMOVED: get_any_valid_token() - This was a security vulnerability
    # All OAuth tokens MUST be user-specific to prevent cross-user token access

    async def get_token_info(
        """Refresh an expired access token using refresh token.

        Args:
            token_record: OAuth token record to refresh

        Returns:
            New access token or None if refresh failed
        """
        try:
            if not token_record.refresh_token:
                logger.warning("No refresh token available for gateway %s", token_record.gateway_id)
                return None

            # Get the gateway configuration to retrieve OAuth settings
            # First-Party
            from mcpgateway.db import Gateway  # pylint: disable=import-outside-toplevel

            gateway = self.db.query(Gateway).filter(Gateway.id == token_record.gateway_id).first()

            if not gateway or not gateway.oauth_config:
                logger.error("No OAuth configuration found for gateway %s", token_record.gateway_id)
                return None

            # Refuse refresh on a private gateway whose owner is not the token
            # owner (PR #4341 invariant): prevents OAuth secret leakage when a
            # gateway's ownership / visibility changes after token issuance.
            # The token owner is ``app_user_email`` (ContextForge user), not
            # the OAuth provider's ``user_id``. Public and team gateways are
            # not gated here — their RBAC enforcement happens at the call
            # sites that issue refreshes.
            gateway_visibility = getattr(gateway, "visibility", "public")
            gateway_owner_email = getattr(gateway, "owner_email", None)
            if gateway_visibility == "private" and gateway_owner_email and gateway_owner_email != token_record.app_user_email:
                logger.warning(
                    "OAuth refresh denied: gateway %s is private and owned by %s, not token owner %s",
                    token_record.gateway_id,
                    gateway_owner_email,
                    token_record.app_user_email,
                )
                return None

            # Decrypt the refresh token if encryption is available
            refresh_token = token_record.refresh_token
            if self.encryption:
                try:
                    refresh_token = await self.encryption.decrypt_secret_async(refresh_token)
                except Exception as e:
                    logger.error("Failed to decrypt refresh token: %s", str(e))
                    return None

            # Decrypt client_secret if encryption is available.
            # Always attempt decryption rather than using an is_encrypted() heuristic.
            # Fail closed on decryption failure: decrypt_secret_async() is the idempotent
            # wrapper — it returns None (never raises) when decryption fails due to a wrong
            # key or corrupted ciphertext. Sending None or the raw ciphertext envelope as a
            # literal client_secret to an Authorization Server causes repeated invalid_client
            # attempts that can trigger IdP rate-limiting/lockout. We raise OAuthError on
            # None so the outer OAuthError handler preserves the token for a later retry.
            oauth_config = gateway.oauth_config.copy()
            if "client_secret" in oauth_config and oauth_config["client_secret"]:
                if self.encryption:
                    client_secret_value = oauth_config["client_secret"]
                    decrypted_secret = await self.encryption.decrypt_secret_async(client_secret_value)
                    if decrypted_secret is None:
                        raise OAuthError(
                            f"client_secret decryption failed for gateway {token_record.gateway_id}: "
                            "decrypt_secret_async returned None (wrong AUTH_ENCRYPTION_SECRET or corrupted ciphertext). "
                            "Check that AUTH_ENCRYPTION_SECRET matches the value used when the gateway was stored."
                        )
                    oauth_config["client_secret"] = decrypted_secret

            # RFC 8707: Set resource parameter for JWT access tokens during refresh
            # Standard
            from urllib.parse import urlparse, urlunparse  # pylint: disable=import-outside-toplevel

            def normalize_resource(url: str, *, preserve_query: bool = False) -> str | None:
                """Normalize a resource value per RFC 8707, or pass through opaque identifiers.

                URL-shaped inputs are canonicalized (fragment stripped; query stripped
                or preserved per ``preserve_query``).  Non-URL inputs are returned
                verbatim so that opaque audience identifiers learned from IdPs that do
                not honor RFC 8707 (e.g. ServiceNow / Authentik returning ``aud=client_id``)
                round-trip correctly through token refresh.  RFC 8707 §2 explicitly
                permits the AS to map ``resource`` to an abstract identifier; the
                resource server therefore must accept either form.

                Args:
                    url: Resource URL or opaque audience identifier to normalize.
                    preserve_query: If True, preserve query (for explicit config). If False, strip query.

                Returns:
                    Normalized URL string, the original opaque value, or None if input is empty.
                """
                if not url:
                    return None
                parsed = urlparse(url)
                # If the value lacks a scheme it is not a URL; treat as an opaque
                # audience identifier and pass through verbatim so a learned
                # client_id-style audience survives refresh.
                if not parsed.scheme:
                    return url
                # Remove fragment (MUST NOT); query: preserve for explicit, strip for auto-derived
                query = parsed.query if preserve_query else ""
                return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, query, ""))

            # RFC 8707: Set resource parameter for JWT access tokens during refresh
            # Respect omit_resource flag - if explicitly set to true, skip all resource handling
            omit_resource = oauth_config.get("omit_resource", False)
            if omit_resource:
                # User explicitly disabled resource parameter - remove it if present
                oauth_config.pop("resource", None)
                logger.debug("Omitting resource parameter for gateway %s as per omit_resource=true config", token_record.gateway_id)
            else:
                existing_resource = oauth_config.get("resource")
                if existing_resource:
                    # Normalize existing resource - preserve query for explicit config
                    if isinstance(existing_resource, list):
                        original_count = len(existing_resource)
                        normalized = [normalize_resource(r, preserve_query=True) for r in existing_resource]
                        oauth_config["resource"] = [r for r in normalized if r]
                        if not oauth_config["resource"] and original_count > 0:
                            logger.warning("All %s configured resource values were empty and removed during refresh", original_count)
                    else:
                        normalized = normalize_resource(existing_resource, preserve_query=True)
                        if not normalized and existing_resource:
                            logger.warning("Configured resource was empty and removed during refresh: %s", existing_resource)
                        oauth_config["resource"] = normalized
                elif gateway.url:
                    # Derive from gateway.url if not explicitly configured (strip query)
                    oauth_config["resource"] = normalize_resource(gateway.url)
                    if not oauth_config.get("resource"):
                        logger.warning("Gateway URL is empty, skipping resource parameter: %s", gateway.url)

            # Use OAuthManager to refresh the token
            # First-Party
            from mcpgateway.services.oauth_manager import OAuthManager, parse_expires_in  # pylint: disable=import-outside-toplevel

            oauth_manager = OAuthManager()

            logger.info("Attempting to refresh token for gateway %s, user %s", token_record.gateway_id, token_record.app_user_email)
            token_response = await oauth_manager.refresh_token(
                refresh_token,
                oauth_config,
                ca_certificate=gateway.ca_certificate,
                client_cert=gateway.client_cert,
                client_key=gateway.client_key,
            )

            # Update stored tokens with new values
            new_access_token = token_response["access_token"]
            new_refresh_token = token_response.get("refresh_token", refresh_token)  # Some providers return new refresh token
            # Reuse the same parsing as the initial-auth path so refresh and
            # callback flows agree on what "missing expires_in" means.
            expires_in = parse_expires_in(token_response)

            # Encrypt new tokens if encryption is available
            encrypted_access = new_access_token
            encrypted_refresh = new_refresh_token
            if self.encryption:
                encrypted_access = await self.encryption.encrypt_secret_async(new_access_token)
                encrypted_refresh = await self.encryption.encrypt_secret_async(new_refresh_token)

            # Update the token record
            token_record.access_token = encrypted_access
            token_record.refresh_token = encrypted_refresh
            now = datetime.now(timezone.utc)
            if expires_in is not None:
                token_record.expires_at = now + timedelta(seconds=expires_in)
            else:
                # Refresh response omitted expires_in. If the token previously had a finite
                # expiry, preserve the prior TTL (expires_at - updated_at) so proactive
                # refresh keeps working - clearing it outright would cause _is_token_expired
                # to return False forever and stop the refresh loop. If there was no prior
                # expiry, leave it as None (provider-level "no known lifetime").
                preserved_ttl = _preserve_prior_ttl(token_record)
                if preserved_ttl is not None:
                    logger.info(
                        "No expires_in on refresh response for gateway %s; preserving prior TTL of %d seconds",
                        SecurityValidator.sanitize_log_message(token_record.gateway_id),
                        preserved_ttl,
                    )
                    token_record.expires_at = now + timedelta(seconds=preserved_ttl)
                else:
                    logger.info(
                        "No expires_in on refresh response for gateway %s; no prior TTL to preserve",
                        SecurityValidator.sanitize_log_message(token_record.gateway_id),
                    )
                    token_record.expires_at = None
            token_record.updated_at = now

            self.db.commit()
            logger.info("Successfully refreshed token for gateway %s, user %s", token_record.gateway_id, token_record.app_user_email)

            return new_access_token

        except OAuthInvalidGrantError as e:
            # RFC 6749 §5.2: invalid_grant is a permanent failure — the refresh
            # token has been revoked, expired, or does not match the grant.
            # OAuthInvalidGrantError is raised by OAuthManager only when the
            # token endpoint explicitly returns {"error": "invalid_grant"}, so
            # this match is based on structured type, not substring heuristics.
            logger.warning(
                "Refresh token is permanently invalid for gateway %s (invalid_grant). Deleting token to force re-authorization. Error: %s",
                token_record.gateway_id,
                str(e),
            )
            self.db.delete(token_record)
            self.db.commit()
            return None
        except OAuthError as e:
            # All other OAuth errors (invalid_client, invalid_request, network
            # failures wrapped as OAuthError, decryption failure, etc.).
            # These are configuration or transient errors — NOT a permanent
            # token failure.  Preserve the token so a later retry can succeed.
            logger.error(
                "Token refresh failed for gateway %s but error does not indicate invalid refresh token. Preserving token for retry. Error: %s",
                token_record.gateway_id,
                str(e),
            )
            return None
        except Exception as e:
            # Non-OAuth errors (network, parsing, encryption, etc.)
            logger.error("Unexpected error refreshing token for gateway %s: %s", token_record.gateway_id, str(e))
            # Preserve token - this is likely a transient or configuration issue
            return None

    def _is_token_expired(self, token_record: OAuthToken, threshold_seconds: int = 300) -> bool:
        """Check if token is expired or near expiration.

        Tokens with ``expires_at IS NULL`` are returned as non-expired by
        design: when the OAuth provider omits ``expires_in`` (RFC 6749 §5.1
        marks it RECOMMENDED, not REQUIRED — see e.g. GitHub OAuth Apps),
        the gateway has no local lifetime to check against. Stale-token
        accumulation is bounded by
        :meth:`cleanup_expired_tokens`, which ages out NULL-expiry rows
        once ``created_at`` exceeds ``max_age_days``.

        Args:
            token_record: OAuth token record to check
            threshold_seconds: Seconds before expiry to consider token expired

        Returns:
            True if token is expired or near expiration

        Examples:
            >>> from types import SimpleNamespace
            >>> from datetime import datetime, timedelta
            >>> svc = TokenStorageService(None)
            >>> future = datetime.now(tz=timezone.utc) + timedelta(seconds=600)
            >>> past = datetime.now(tz=timezone.utc) - timedelta(seconds=10)
            >>> rec_future = SimpleNamespace(expires_at=future)
            >>> rec_past = SimpleNamespace(expires_at=past)
            >>> svc._is_token_expired(rec_future, threshold_seconds=300)  # 10 min ahead, 5 min threshold
            False
            >>> svc._is_token_expired(rec_future, threshold_seconds=900)  # 10 min ahead, 15 min threshold
            True
            >>> svc._is_token_expired(rec_past, threshold_seconds=0)
            True
            >>> svc._is_token_expired(SimpleNamespace(expires_at=None))
            False
        """
        if not token_record.expires_at:
            # No provider-supplied lifetime; treat as non-expired (see contract above).
            return False
        expires_at = token_record.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) + timedelta(seconds=threshold_seconds) >= expires_at

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
