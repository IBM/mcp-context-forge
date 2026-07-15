"""
Vault token storage backend.

Stores OAuth tokens in HashiCorp Vault KV v2 using httpx for HTTP API calls.
Path structure: {mount}/data/{prefix}/{team_id}/{server_id}/{url-encoded-email}
where server_id is SHA-256 hash of gateways.url (mcp_url).
"""

import asyncio
import hashlib
import logging
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import httpx
from sqlalchemy.orm import Session

from mcpgateway.common.validators import SecurityValidator
from mcpgateway.config import Settings
from mcpgateway.db import Gateway
from mcpgateway.services.oauth_manager import OAuthManager, parse_expires_in

from .base import AbstractTokenBackend, TokenRecord, normalize_resource_url

logger = logging.getLogger(__name__)


class VaultConnectionError(Exception):
    """Raised when Vault is unreachable or returns server errors."""


class VaultAuthError(Exception):
    """Raised when Vault authentication fails (403)."""


class VaultTokenBackend(AbstractTokenBackend):
    """
    Vault KV v2 token storage backend.

    Features:
    - Resolves gateway_id → gateways.url → server_id (SHA-256 hash)
    - Constructs path: {mount}/data/{prefix}/{team_id}/{server_id}/{url-encoded-email}
    - Stores tokens plain-text in Vault (Vault encrypts at rest)
    - Retry logic (3 attempts with exponential backoff)
    - Optional in-memory token cache with TTL (class-level so it persists across requests)
    """

    # Class-level token cache shared across all instances in the process.
    # Keyed by (team_id, server_id, email); values are {token, cache_expires}.
    # Must be class-level: VaultTokenBackend is instantiated per-request, so an
    # instance-level cache would be discarded at the end of every request.
    # OrderedDict preserves insertion order AND supports move_to_end(), which is
    # required for correct LRU eviction (popitem(last=False) removes the entry
    # that was accessed least recently).
    _token_cache: OrderedDict[tuple[str, str, str], dict[str, Any]] = OrderedDict()

    # Sentinel to log the cleanup no-op warning only once per process.
    _cleanup_warned: bool = False

    def __init__(self, db: Session, settings: Settings):
        """Initialize Vault backend.

        Args:
            db: SQLAlchemy session (for gateway_id → gateways.url resolution)
            settings: Application settings
        """
        self.db = db
        self.settings = settings

        # Vault connection
        self.vault_addr = settings.vault_addr
        self.vault_token = settings.vault_token.get_secret_value() if settings.vault_token else None
        self.vault_namespace = settings.vault_namespace or None
        self.mount = settings.vault_kv_mount
        self.prefix = settings.vault_kv_path_prefix
        self.tls_verify = settings.vault_tls_verify

        if not self.vault_token:
            raise ValueError("VAULT_TOKEN is required when OAUTH_TOKEN_BACKEND=vault")

        # Cache configuration — always initialised so attribute access is safe
        # regardless of whether the cache is currently enabled.
        self.cache_enabled = settings.vault_token_cache_enabled
        self.cache_ttl = settings.vault_token_cache_ttl
        self.cache_max_size = settings.vault_token_cache_max_size

    def _hash_server_id(self, mcp_url: str) -> str:
        """Hash mcp_url to stable server_id (first 16 hex chars of SHA-256).

        16 hex characters = 64-bit prefix, which provides ~2^32 birthday-collision
        resistance (i.e., collisions become probable only around 4 billion distinct
        gateway URLs). The previous 8-char (32-bit) truncation became probable
        around 65,536 URLs for large deployments.

        Args:
            mcp_url: Gateway URL (e.g., https://mcp.github.acme.com)

        Returns:
            16-character hex string
        """
        return hashlib.sha256(mcp_url.encode()).hexdigest()[:16]

    def _construct_vault_path(self, team_id: str | None, mcp_url: str, app_user_email: str) -> str:
        """Construct full Vault KV v2 path.

        Args:
            team_id: Team identifier (or None for shared fallback path)
            mcp_url: Gateway URL (will be hashed to server_id)
            app_user_email: User email (will be URL-encoded)

        Returns:
            Full Vault path (e.g., secret/data/contextforge/oauth/engineering/647ad7b3/alice%40example.com)
            or shared fallback path when team_id is None: secret/data/contextforge/oauth/shared/647ad7b3/alice%40example.com
        """
        server_id = self._hash_server_id(mcp_url)
        email_encoded = quote(app_user_email, safe="")
        # Use "shared" path when team_id is None (fallback for sessions without team context)
        team_segment = team_id if team_id else "shared"
        return f"{self.mount}/data/{self.prefix}/{team_segment}/{server_id}/{email_encoded}"

    def _construct_metadata_path(self, team_id: str | None, mcp_url: str, app_user_email: str) -> str:
        """Construct Vault KV v2 metadata path (for hard delete).

        Args:
            team_id: Team identifier (or None for shared fallback path)
            mcp_url: Gateway URL
            app_user_email: User email

        Returns:
            Metadata path (e.g., secret/metadata/contextforge/oauth/engineering/647ad7b3/alice%40example.com)
            or shared fallback path when team_id is None
        """
        server_id = self._hash_server_id(mcp_url)
        email_encoded = quote(app_user_email, safe="")
        team_segment = team_id if team_id else "shared"
        return f"{self.mount}/metadata/{self.prefix}/{team_segment}/{server_id}/{email_encoded}"

    def _construct_credentials_path(self, team_id: str | None, mcp_url: str) -> str:
        """Construct Vault KV v2 path for OAuth credentials.

        OAuth credentials (client_id/client_secret/etc) are stored per team to enable
        multi-team same-URL scenarios where each team has independent OAuth apps.

        Args:
            team_id: Team identifier (or None for shared fallback path)
            mcp_url: Gateway URL (will be hashed to server_id)

        Returns:
            Vault path (e.g., secret/data/contextforge/oauth/credentials/engineering/647ad7b3)
            or shared fallback path when team_id is None
        """
        server_id = self._hash_server_id(mcp_url)
        team_segment = team_id if team_id else "shared"
        return f"{self.mount}/data/{self.prefix}/credentials/{team_segment}/{server_id}"

    async def _vault_request(self, method: str, path: str, data: dict | None = None) -> dict | None:
        """Make HTTP request to Vault with retry logic.

        Args:
            method: HTTP method (GET, POST, DELETE)
            path: Vault API path (relative to /v1/)
            data: Request body (for POST)

        Returns:
            JSON response or None if 404

        Raises:
            VaultConnectionError: If Vault unreachable after retries
            VaultAuthError: If authentication fails (403)
        """
        headers = {"X-Vault-Token": self.vault_token}
        if self.vault_namespace:
            headers["X-Vault-Namespace"] = self.vault_namespace

        url = f"{self.vault_addr}/v1/{path}"

        for attempt in range(3):
            try:
                async with httpx.AsyncClient(verify=self.tls_verify, timeout=10.0) as client:
                    if method == "GET":
                        resp = await client.get(url, headers=headers)
                    elif method == "POST":
                        resp = await client.post(url, headers=headers, json=data)
                    elif method == "DELETE":
                        resp = await client.delete(url, headers=headers)
                    else:
                        raise ValueError(f"Unsupported HTTP method: {method}")

                    # Handle 404 as "not found" (expected for missing tokens)
                    if resp.status_code == 404:
                        return None

                    # Raise for other errors
                    resp.raise_for_status()

                    # Return JSON response, or empty dict for DELETE / no-body responses.
                    # Log a warning when a non-404 success has no body — this usually
                    # means a misconfigured mount path or an unexpected Vault response.
                    if not resp.content:
                        if method != "DELETE":
                            logger.warning(
                                "Vault returned empty body for %s %s (status=%d); check mount path and path prefix configuration",
                                method,
                                SecurityValidator.sanitize_log_message(path),
                                resp.status_code,
                            )
                        return {}
                    return resp.json()

            except (httpx.ConnectTimeout, httpx.ConnectError, httpx.ReadTimeout) as e:
                # Retry on network errors
                if attempt < 2:
                    logger.warning(
                        "Vault request attempt %d failed with %s: %s",
                        attempt + 1,
                        type(e).__name__,
                        SecurityValidator.sanitize_log_message(str(e)),
                    )
                    await asyncio.sleep(2**attempt)  # 1s, 2s
                    continue
                logger.error(
                    "Vault unreachable after 3 attempts: %s. Error: %s: %s",
                    SecurityValidator.sanitize_log_message(url),
                    type(e).__name__,
                    SecurityValidator.sanitize_log_message(str(e)),
                )
                raise VaultConnectionError("Credential storage unavailable") from e

            except httpx.HTTPStatusError as e:
                # Retry on 5xx server errors
                if e.response.status_code >= 500 and attempt < 2:
                    logger.warning(
                        "Vault returned %d on attempt %d: %s",
                        e.response.status_code,
                        attempt + 1,
                        SecurityValidator.sanitize_log_message(str(e)),
                    )
                    await asyncio.sleep(2**attempt)  # 1s, 2s
                    continue
                # Don't retry 4xx client errors
                if e.response.status_code == 403:
                    logger.critical("Vault auth failure - VAULT_TOKEN invalid or expired")
                    raise VaultAuthError("VAULT_TOKEN invalid or expired") from e
                # Re-raise other HTTP errors (4xx)
                raise

        # Should never reach here due to raise in loop, but make mypy happy
        raise VaultConnectionError("Unexpected error in Vault request retry logic")

    async def store_tokens(
        self,
        gateway_id: str,
        team_id: str,
        user_id: str,
        app_user_email: str,
        access_token: str,
        refresh_token: str | None,
        expires_in: int | None,
        scopes: list[str],
    ) -> TokenRecord:
        """Store OAuth tokens in Vault.

        Args:
            gateway_id: Gateway ID (resolved to mcp_url)
            team_id: Team identifier (used in Vault path)
            user_id: OAuth provider user ID
            app_user_email: ContextForge user email
            access_token: Access token (stored plain-text in Vault)
            refresh_token: Refresh token (stored plain-text in Vault)
            expires_in: Token expiration in seconds, or None
            scopes: OAuth scopes

        Returns:
            TokenRecord with plain-text tokens
        """
        mcp_url = self._resolve_mcp_url(gateway_id)
        path = self._construct_vault_path(team_id, mcp_url, app_user_email)

        # Calculate expiration
        expires_at = None
        if expires_in is not None:
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        now = datetime.now(timezone.utc)

        # Preserve created_at from any existing record so that audit history and
        # max-age policies see the original issuance timestamp, not the refresh time.
        existing = await self._vault_request("GET", path)
        original_created_at: str | None = None
        if existing and "data" in existing and "data" in existing["data"]:
            original_created_at = existing["data"]["data"].get("created_at")

        # Build payload (nested token object for cleaner structure)
        payload = {
            "data": {
                "email": app_user_email,
                "team_id": team_id,
                "mcp_url": mcp_url,  # ← Key difference: store mcp_url, not gateway_id
                "token": {
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "scopes": scopes,
                },
                "user_id": user_id,
                "token_type": "Bearer",
                "expires_at": expires_at.isoformat() if expires_at else None,
                "created_at": original_created_at or now.isoformat(),
                "updated_at": now.isoformat(),
            }
        }

        # Write to Vault
        await self._vault_request("POST", path, payload)

        # Invalidate cache (class-level dict persists across requests)
        if self.cache_enabled:
            server_id = self._hash_server_id(mcp_url)
            cache_key = (team_id, server_id, app_user_email)
            VaultTokenBackend._token_cache.pop(cache_key, None)

        logger.info(
            "Stored OAuth tokens in Vault for gateway %s (mcp_url=%s), team=%s, user=%s",
            SecurityValidator.sanitize_log_message(gateway_id),
            SecurityValidator.sanitize_log_message(mcp_url),
            SecurityValidator.sanitize_log_message(team_id),
            SecurityValidator.sanitize_log_message(app_user_email),
        )

        return TokenRecord(
            gateway_id=gateway_id,
            mcp_url=mcp_url,
            team_id=team_id,
            user_id=user_id,
            app_user_email=app_user_email,
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="Bearer",
            expires_at=expires_at,
            scopes=scopes,
            created_at=now,
            updated_at=now,
        )

    async def get_user_token(
        self,
        gateway_id: str,
        team_id: str,
        app_user_email: str,
        threshold_seconds: int = 300,
    ) -> str | None:
        """Get valid access token from Vault, refreshing if necessary.

        Args:
            gateway_id: Gateway ID (resolved to mcp_url)
            team_id: Team identifier
            app_user_email: ContextForge user email
            threshold_seconds: Seconds before expiry to consider token expired

        Returns:
            Plain-text access token or None
        """
        mcp_url = self._resolve_mcp_url(gateway_id)
        server_id = self._hash_server_id(mcp_url)
        cache_key = (team_id, server_id, app_user_email)

        # Check cache first (class-level OrderedDict — persists across requests).
        # Move accessed entry to the end so the front always holds the LRU entry.
        if self.cache_enabled and cache_key in VaultTokenBackend._token_cache:
            cached = VaultTokenBackend._token_cache[cache_key]
            if datetime.now(timezone.utc) < cached["cache_expires"]:
                logger.debug("Cache hit for token: team=%s, server_id=%s, email=%s", team_id, server_id, app_user_email)
                VaultTokenBackend._token_cache.move_to_end(cache_key)
                return cached["token"]
            # Expired cache entry — remove it proactively
            VaultTokenBackend._token_cache.pop(cache_key, None)

        # Fetch from Vault
        path = self._construct_vault_path(team_id, mcp_url, app_user_email)
        result = await self._vault_request("GET", path)

        if not result or "data" not in result:
            logger.debug(
                "No OAuth tokens found in Vault for gateway %s (mcp_url=%s), team=%s, user=%s",
                SecurityValidator.sanitize_log_message(gateway_id),
                SecurityValidator.sanitize_log_message(mcp_url),
                SecurityValidator.sanitize_log_message(team_id),
                SecurityValidator.sanitize_log_message(app_user_email),
            )
            return None

        data = result["data"]["data"]
        access_token = data["token"]["access_token"]
        refresh_token = data["token"].get("refresh_token")
        expires_at_str = data.get("expires_at")

        # Check expiry and refresh if needed
        if expires_at_str:
            expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
            if (expires_at - datetime.now(timezone.utc)).total_seconds() < threshold_seconds:
                logger.info(
                    "OAuth token near expiry for gateway %s, team=%s, user=%s",
                    SecurityValidator.sanitize_log_message(gateway_id),
                    SecurityValidator.sanitize_log_message(team_id),
                    SecurityValidator.sanitize_log_message(app_user_email),
                )
                if refresh_token:
                    new_token = await self._refresh_access_token(gateway_id, team_id, app_user_email, refresh_token, data)
                    if new_token:
                        # Cache the freshly-refreshed token before returning
                        self._write_token_cache(cache_key, new_token)
                        return new_token
                return None  # Expired, no refresh available

        # Cache token (class-level OrderedDict — persists across requests).
        self._write_token_cache(cache_key, access_token)

        return access_token

    async def get_token_info(
        self,
        gateway_id: str,
        team_id: str,
        app_user_email: str,
    ) -> dict | None:
        """Get non-sensitive token metadata from Vault.

        Args:
            gateway_id: Gateway ID
            team_id: Team identifier
            app_user_email: ContextForge user email

        Returns:
            Token info dict or None
        """
        mcp_url = self._resolve_mcp_url(gateway_id)
        path = self._construct_vault_path(team_id, mcp_url, app_user_email)
        result = await self._vault_request("GET", path)

        if not result or "data" not in result:
            return None

        data = result["data"]["data"]
        expires_at_str = data.get("expires_at")
        updated_at_str = data.get("updated_at")

        # Determine status
        status = "valid"
        if expires_at_str:
            expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            if expires_at <= now:
                status = "expired"
            elif (expires_at - now).total_seconds() < 300:
                status = "near_expiry"

        return {
            "scopes": data["token"]["scopes"],
            "expires_at": expires_at_str,
            "status": status,
            "updated_at": updated_at_str,
        }

    async def revoke_user_tokens(
        self,
        gateway_id: str,
        team_id: str,
        app_user_email: str,
    ) -> bool:
        """Delete tokens from Vault (hard delete via metadata endpoint).

        Args:
            gateway_id: Gateway ID
            team_id: Team identifier
            app_user_email: ContextForge user email

        Returns:
            True if deleted, False if not found
        """
        mcp_url = self._resolve_mcp_url(gateway_id)
        metadata_path = self._construct_metadata_path(team_id, mcp_url, app_user_email)

        try:
            result = await self._vault_request("DELETE", metadata_path)

            # Invalidate cache (class-level dict persists across requests)
            if self.cache_enabled:
                server_id = self._hash_server_id(mcp_url)
                cache_key = (team_id, server_id, app_user_email)
                VaultTokenBackend._token_cache.pop(cache_key, None)

            logger.info(
                "Revoked OAuth tokens in Vault for gateway %s (mcp_url=%s), team=%s, user=%s",
                SecurityValidator.sanitize_log_message(gateway_id),
                SecurityValidator.sanitize_log_message(mcp_url),
                SecurityValidator.sanitize_log_message(team_id),
                SecurityValidator.sanitize_log_message(app_user_email),
            )
            return result is not None  # None = 404 (not found)

        except Exception as e:
            logger.error("Failed to revoke OAuth tokens in Vault: %s", str(e))
            return False

    def _write_token_cache(self, cache_key: tuple[str, str, str], token: str) -> None:
        """Write a token to the class-level LRU cache, evicting the LRU entry if full.

        Args:
            cache_key: (team_id, server_id, email) tuple
            token: Plain-text access token to cache
        """
        VaultTokenBackend._token_cache[cache_key] = {
            "token": token,
            "cache_expires": datetime.now(timezone.utc) + timedelta(seconds=self.cache_ttl),
        }
        # Move to end (most-recently-used position)
        VaultTokenBackend._token_cache.move_to_end(cache_key)
        # Evict least-recently-used entry (front of OrderedDict) if over capacity
        if len(VaultTokenBackend._token_cache) > self.cache_max_size:
            VaultTokenBackend._token_cache.popitem(last=False)

    async def cleanup_expired_tokens(
        self,
        max_age_days: int = 30,
    ) -> int:
        """No-op for Vault backend.

        Vault KV TTL or operator-configured cleanup policies handle expiration.
        Logs at INFO level only once per process lifetime to avoid log spam when
        the maintenance job runs periodically.

        Args:
            max_age_days: Ignored (for interface compatibility)

        Returns:
            0 (no tokens cleaned)
        """
        if not VaultTokenBackend._cleanup_warned:
            VaultTokenBackend._cleanup_warned = True
            logger.info(
                "cleanup_expired_tokens is a no-op for Vault backend. Configure Vault KV TTL or retention policies to handle cleanup. This warning is logged only once per process.",
            )
        return 0

    async def get_oauth_credentials(self, team_id: str, mcp_url: str) -> dict | None:
        """Retrieve team-scoped OAuth credentials from Vault.

        This enables multi-team same-URL scenarios where each team registers
        the same MCP server with independent OAuth apps and credentials.

        Args:
            team_id: Team identifier from JWT 'teams' claim
            mcp_url: Gateway URL

        Returns:
            OAuth config dict (client_id, client_secret, authorization_url, etc.)
            or None if not found in Vault

        Example Vault path:
            secret/data/contextforge/oauth/credentials/engineering/647ad7b3
        """
        path = self._construct_credentials_path(team_id, mcp_url)

        try:
            result = await self._vault_request("GET", path)

            if not result or "data" not in result:
                logger.debug(
                    "No OAuth credentials found in Vault for team=%s, mcp_url=%s. Will fall back to gateway.oauth_config from database.",
                    SecurityValidator.sanitize_log_message(team_id),
                    SecurityValidator.sanitize_log_message(mcp_url),
                )
                return None

            credentials = result["data"]["data"]
            logger.info(
                "Retrieved OAuth credentials from Vault for team=%s, mcp_url=%s",
                SecurityValidator.sanitize_log_message(team_id),
                SecurityValidator.sanitize_log_message(mcp_url),
            )
            return credentials

        except Exception as e:
            logger.warning(
                "Failed to retrieve OAuth credentials from Vault for team=%s, mcp_url=%s: %s. Will fall back to gateway.oauth_config from database.",
                SecurityValidator.sanitize_log_message(team_id),
                SecurityValidator.sanitize_log_message(mcp_url),
                SecurityValidator.sanitize_log_message(str(e)),
            )
            return None

    async def store_oauth_credentials(
        self,
        team_id: str,
        mcp_url: str,
        credentials: dict,
    ) -> bool:
        """Store team-scoped OAuth credentials in Vault.

        Args:
            team_id: Team identifier
            mcp_url: Gateway URL
            credentials: OAuth config dict (client_id, client_secret, etc.)

        Returns:
            True if stored successfully, False otherwise

        Example Vault path:
            secret/data/contextforge/oauth/credentials/engineering/647ad7b3
        """
        path = self._construct_credentials_path(team_id, mcp_url)

        payload = {
            "data": {
                "team_id": team_id,
                "mcp_url": mcp_url,
                **credentials,  # Include all OAuth config fields
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        }

        try:
            await self._vault_request("POST", path, payload)
            logger.info(
                "Stored OAuth credentials in Vault for team=%s, mcp_url=%s",
                SecurityValidator.sanitize_log_message(team_id),
                SecurityValidator.sanitize_log_message(mcp_url),
            )
            return True

        except Exception as e:
            logger.error(
                "Failed to store OAuth credentials in Vault for team=%s, mcp_url=%s: %s",
                SecurityValidator.sanitize_log_message(team_id),
                SecurityValidator.sanitize_log_message(mcp_url),
                SecurityValidator.sanitize_log_message(str(e)),
            )
            return False

    # ──────────────────────────────────────────────────────────────────────
    # Private helper methods
    # ──────────────────────────────────────────────────────────────────────

    async def _refresh_access_token(
        self,
        gateway_id: str,
        team_id: str,
        app_user_email: str,
        refresh_token: str,
        vault_data: dict,
    ) -> str | None:
        """Refresh an expired access token using refresh token.

        Args:
            gateway_id: Gateway ID
            team_id: Team identifier
            app_user_email: ContextForge user email
            refresh_token: Plain-text refresh token
            vault_data: Current Vault token data (for preserving metadata)

        Returns:
            New access token or None if refresh failed
        """
        try:
            # Get the gateway configuration
            gateway = self.db.query(Gateway).filter(Gateway.id == gateway_id).first()

            if not gateway or not gateway.oauth_config:
                logger.error("No OAuth configuration found for gateway %s", gateway_id)
                return None

            # PR #4341: Refuse refresh on private gateway whose owner != token owner
            gateway_visibility = getattr(gateway, "visibility", "public")
            gateway_owner_email = getattr(gateway, "owner_email", None)
            if gateway_visibility == "private" and gateway_owner_email and gateway_owner_email != app_user_email:
                logger.warning(
                    "OAuth refresh denied: gateway %s is private and owned by %s, not token owner %s",
                    gateway_id,
                    gateway_owner_email,
                    app_user_email,
                )
                return None

            oauth_config = gateway.oauth_config.copy()

            # RFC 8707: Set resource parameter
            existing_resource = oauth_config.get("resource")
            if existing_resource:
                if isinstance(existing_resource, list):
                    normalized = [normalize_resource_url(r, preserve_query=True) for r in existing_resource]
                    oauth_config["resource"] = [r for r in normalized if r]
                else:
                    oauth_config["resource"] = normalize_resource_url(existing_resource, preserve_query=True)
            elif gateway.url:
                oauth_config["resource"] = normalize_resource_url(gateway.url)

            # Use OAuthManager to refresh the token
            oauth_manager = OAuthManager()

            logger.info("Attempting to refresh token in Vault for gateway %s, user %s", gateway_id, app_user_email)
            token_response = await oauth_manager.refresh_token(
                refresh_token,
                oauth_config,
                ca_certificate=gateway.ca_certificate,
                client_cert=gateway.client_cert,
                client_key=gateway.client_key,
            )

            # Extract new tokens
            new_access_token = token_response["access_token"]
            new_refresh_token = token_response.get("refresh_token", refresh_token)
            expires_in = parse_expires_in(token_response)

            # Store refreshed tokens back to Vault
            await self.store_tokens(
                gateway_id=gateway_id,
                team_id=team_id,
                user_id=vault_data.get("user_id", ""),
                app_user_email=app_user_email,
                access_token=new_access_token,
                refresh_token=new_refresh_token,
                expires_in=expires_in,
                scopes=vault_data["token"]["scopes"],
            )

            logger.info("Successfully refreshed token in Vault for gateway %s, user %s", gateway_id, app_user_email)

            return new_access_token

        except Exception as e:
            logger.error("Failed to refresh OAuth token in Vault for gateway %s: %s", gateway_id, str(e))
            # If refresh fails with invalid/expired error, delete tokens
            if "invalid" in str(e).lower() or "expired" in str(e).lower():
                logger.warning("Refresh token appears invalid/expired, deleting tokens in Vault for gateway %s", gateway_id)
                await self.revoke_user_tokens(gateway_id, team_id, app_user_email)
            return None
