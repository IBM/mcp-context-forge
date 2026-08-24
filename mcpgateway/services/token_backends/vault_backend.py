# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/token_backends/vault_backend.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

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
from mcpgateway.services.oauth_manager import OAuthError, OAuthInvalidGrantError, OAuthManager, parse_expires_in

from .base import AbstractTokenBackend, TokenRecord
from .refresh_helpers import apply_omit_resource_and_normalize, check_private_gateway_access, compute_prior_ttl

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

    # Per-(gateway_id, team_id, email) asyncio locks that serialise concurrent
    # near-expiry refresh calls.  Without this, two concurrent requests that both
    # see a near-expiry token both call the IdP; against a rotating-refresh-token
    # IdP the losing call receives invalid_grant and then calls revoke_user_tokens(),
    # deleting the token the winning call just stored.
    #
    # _refresh_locks_mutex guards mutations to the dict itself; individual per-key
    # locks are asyncio.Lock() instances that serialise the refresh critical section.
    _refresh_locks: dict[tuple[str, str, str], "asyncio.Lock"] = {}
    _refresh_locks_mutex: "asyncio.Lock | None" = None

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
        # URL-encode team_id to prevent path traversal if a future caller passes a slug
        # or display name containing '/' or other path separators. UUIDs (current callers)
        # are unaffected — quote("uuid-string", safe="") is a no-op for hex-dash strings.
        team_segment = quote(team_id, safe="") if team_id else "shared"
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
        # URL-encode team_id for the same reason as _construct_vault_path above.
        team_segment = quote(team_id, safe="") if team_id else "shared"
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
        # URL-encode team_id for the same reason as _construct_vault_path and
        # _construct_metadata_path — future callers passing slugs/display names
        # instead of UUIDs cannot inject path separators. No-op for current callers.
        team_segment = quote(team_id, safe="") if team_id else "shared"
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
                # Wrap all terminal HTTP errors (non-403 4xx, or exhausted 5xx) as
                # VaultConnectionError so every caller gets one of the two declared
                # exception types — no raw httpx.HTTPStatusError escapes to callers
                # that only catch (VaultConnectionError, VaultAuthError).
                logger.error(
                    "Vault returned HTTP %d for %s %s",
                    e.response.status_code,
                    method,
                    SecurityValidator.sanitize_log_message(path),
                )
                raise VaultConnectionError(f"Vault returned HTTP {e.response.status_code}") from e

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
        learned_aud: str | None = None,
        learned_iss: str | None = None,
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
            learned_aud: Learned JWT audience from token introspection (stored in Vault)
            learned_iss: Learned JWT issuer from token introspection (stored in Vault)

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

        # Preserve created_at and learned_aud/learned_iss from any existing record.
        # created_at: audit history and max-age policies see the original issuance timestamp.
        # learned_aud/iss: avoid erasing previously-learned values when caller passes None
        # (matches the DB backend's conditional-update pattern for consistency).
        existing = await self._vault_request("GET", path)
        original_created_at: str | None = None
        existing_learned_aud: str | None = None
        existing_learned_iss: str | None = None
        if existing and "data" in existing and "data" in existing["data"]:
            existing_data = existing["data"]["data"]
            original_created_at = existing_data.get("created_at")
            existing_learned_aud = existing_data.get("learned_aud")
            existing_learned_iss = existing_data.get("learned_iss")

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
                "token_type": "Bearer",  # nosec B105 - OAuth token_type constant, not a password
                "expires_at": expires_at.isoformat() if expires_at else None,
                # Preserve existing learned values when caller passes None (matches DB backend)
                "learned_aud": learned_aud if learned_aud is not None else existing_learned_aud,
                "learned_iss": learned_iss if learned_iss is not None else existing_learned_iss,
                "created_at": original_created_at or now.isoformat(),
                "updated_at": now.isoformat(),
            }
        }

        # Write to Vault — treat a None return (404 from _vault_request) as a
        # misconfigured mount: raise so the caller gets a hard failure rather than
        # a silent no-op that logs "Stored OAuth tokens in Vault" but writes nothing.
        # Also wraps unexpected exceptions to keep the declared exception contract.
        try:
            write_result = await self._vault_request("POST", path, payload)
        except (VaultConnectionError, VaultAuthError):
            raise  # already the right type; propagate directly
        except Exception as e:
            logger.error(
                "Vault write failed for gateway %s, user %s: %s",
                SecurityValidator.sanitize_log_message(gateway_id),
                SecurityValidator.sanitize_log_message(app_user_email),
                SecurityValidator.sanitize_log_message(str(e)),
            )
            raise VaultConnectionError("Token write to Vault failed") from e

        if write_result is None:
            # _vault_request returns None on 404 — the KV mount path is wrong.
            # Do NOT log success or return a TokenRecord; surface the misconfiguration.
            logger.error(
                "Vault write returned 404 for gateway %s (path=%s) — check VAULT_KV_MOUNT and VAULT_PATH_PREFIX configuration",
                SecurityValidator.sanitize_log_message(gateway_id),
                SecurityValidator.sanitize_log_message(path),
            )
            raise VaultConnectionError("Vault mount not found (404) — check VAULT_KV_MOUNT configuration")

        # Mark the cache entry as immediately expired rather than deleting it.
        # Deleting only clears this worker's copy; other workers in a multi-pod
        # deployment would continue serving the pre-store token until their own
        # TTL elapsed.  Writing an already-expired timestamp makes the entry stale
        # on the very next read in all workers, bounding the stale-window to at
        # most one cache-hit cycle (< cache_ttl seconds).
        # This is the same expire-in-place pattern used by revoke_user_tokens().
        if self.cache_enabled:
            server_id = self._hash_server_id(mcp_url)
            cache_key = (team_id, server_id, app_user_email)
            if cache_key in VaultTokenBackend._token_cache:
                VaultTokenBackend._token_cache[cache_key]["cache_expires"] = datetime.now(timezone.utc) - timedelta(seconds=1)

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
            token_type="Bearer",  # nosec B106 - OAuth token_type constant, not a password
            expires_at=expires_at,
            scopes=scopes,
            created_at=now,
            updated_at=now,
            learned_aud=learned_aud,
            learned_iss=learned_iss,
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
        try:
            mcp_url = self._resolve_mcp_url(gateway_id)
            server_id = self._hash_server_id(mcp_url)
            cache_key = (team_id, server_id, app_user_email)

            # Check cache first (class-level OrderedDict — persists across requests).
            # Move accessed entry to the end so the front always holds the LRU entry.
            if self.cache_enabled and cache_key in VaultTokenBackend._token_cache:
                cached = VaultTokenBackend._token_cache[cache_key]
                if datetime.now(timezone.utc) < cached["cache_expires"]:
                    logger.debug(
                        "Cache hit for token: team=%s, server_id=%s, email=%s",
                        SecurityValidator.sanitize_log_message(team_id),
                        SecurityValidator.sanitize_log_message(server_id),
                        SecurityValidator.sanitize_log_message(app_user_email),
                    )
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
            token_data = data.get("token")
            if not token_data or not isinstance(token_data, dict):
                # Record exists but has no OAuth token shape (e.g. ICA-written
                # header-only record with only a "headers" field).  Return None
                # so the caller falls through to the "please authorize" path
                # rather than raising a raw KeyError that surfaces as a
                # confusing ToolInvocationError("... 'token'").
                logger.debug(
                    "Vault record for gateway %s, team=%s, user=%s has no 'token' field — not an OAuth record",
                    SecurityValidator.sanitize_log_message(gateway_id),
                    SecurityValidator.sanitize_log_message(team_id),
                    SecurityValidator.sanitize_log_message(app_user_email),
                )
                return None
            access_token = token_data.get("access_token")
            if not access_token:
                # Malformed record: has a 'token' dict but no 'access_token' inside.
                logger.debug(
                    "Vault record for gateway %s, team=%s, user=%s has 'token' but no 'access_token'",
                    SecurityValidator.sanitize_log_message(gateway_id),
                    SecurityValidator.sanitize_log_message(team_id),
                    SecurityValidator.sanitize_log_message(app_user_email),
                )
                return None
            refresh_token = token_data.get("refresh_token")
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
                        new_token = await self._refresh_access_token(gateway_id, team_id, app_user_email, refresh_token, data, threshold_seconds=threshold_seconds)
                        if new_token:
                            # Cache the freshly-refreshed token before returning
                            self._write_token_cache(cache_key, new_token)
                            return new_token
                    return None  # Expired, no refresh available

            # Cache token (class-level OrderedDict — persists across requests).
            self._write_token_cache(cache_key, access_token)

            return access_token

        except (VaultConnectionError, VaultAuthError) as e:
            logger.warning(
                "Vault unavailable in get_user_token for gateway %s, user %s: %s",
                SecurityValidator.sanitize_log_message(gateway_id),
                SecurityValidator.sanitize_log_message(app_user_email),
                str(e),
            )
            return None

    async def get_user_auth_headers(
        self,
        gateway_id: str,
        team_id: str,
        app_user_email: str,
    ) -> dict | None:
        """Get per-user non-OAuth auth headers from Vault.

        For non-OAuth credential types (bearer / basic / authheaders) ICA writes the
        credential as a plain ``{header: value}`` dict under a ``headers`` field at the
        SAME per-user Vault path used for OAuth tokens. This returns that dict so the
        caller can merge it into the upstream request headers, exactly like the
        gateway-wide static auth path does.

        Args:
            gateway_id: Gateway ID (resolved to mcp_url)
            team_id: Team identifier
            app_user_email: ContextForge user email

        Returns:
            The ``{header: value}`` dict, or None if no per-user record / no headers field.
        """
        try:
            mcp_url = self._resolve_mcp_url(gateway_id)
            path = self._construct_vault_path(team_id, mcp_url, app_user_email)
            result = await self._vault_request("GET", path)
            if not result or "data" not in result:
                return None
            data = result["data"]["data"]
            headers = data.get("headers")
            if isinstance(headers, dict) and headers:
                return {str(k): str(v) for k, v in headers.items() if k and v}
            return None
        except (VaultConnectionError, VaultAuthError) as e:
            # Re-raise so _resolve_vault_auth_headers in tool_service.py fails closed
            # rather than silently falling back to the shared gateway credential during
            # a Vault outage — preserves per-user credential isolation (CWE-284).
            logger.warning(
                "Vault unavailable in get_user_auth_headers for gateway %s, user %s: %s — failing closed to protect per-user credential isolation",
                SecurityValidator.sanitize_log_message(gateway_id),
                SecurityValidator.sanitize_log_message(app_user_email),
                str(e),
            )
            raise

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
        try:
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

        except (VaultConnectionError, VaultAuthError) as e:
            logger.warning(
                "Vault unavailable in get_token_info for gateway %s, user %s: %s",
                SecurityValidator.sanitize_log_message(gateway_id),
                SecurityValidator.sanitize_log_message(app_user_email),
                str(e),
            )
            return None

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

            # Mark the cache entry as immediately expired rather than deleting it.
            # Deleting would only clear this worker's copy; other workers in a
            # multi-worker / multi-pod deployment would continue serving the revoked
            # token until their own TTL elapsed.  By writing an already-expired
            # timestamp the entry is treated as stale on the very next read in all
            # workers that share the class-level cache, bounding the post-revocation
            # window to at most one cache-hit cycle (< cache_ttl seconds).
            if self.cache_enabled:
                server_id = self._hash_server_id(mcp_url)
                cache_key = (team_id, server_id, app_user_email)
                if cache_key in VaultTokenBackend._token_cache:
                    VaultTokenBackend._token_cache[cache_key]["cache_expires"] = datetime.now(timezone.utc) - timedelta(seconds=1)

            logger.info(
                "Revoked OAuth tokens in Vault for gateway %s (mcp_url=%s), team=%s, user=%s",
                SecurityValidator.sanitize_log_message(gateway_id),
                SecurityValidator.sanitize_log_message(mcp_url),
                SecurityValidator.sanitize_log_message(team_id),
                SecurityValidator.sanitize_log_message(app_user_email),
            )
            return result is not None  # None = 404 (not found)

        except (VaultConnectionError, VaultAuthError):
            # Vault is unhealthy — re-raise so the caller knows revocation may
            # have failed.  Returning False is unsafe here: it reads as "token
            # not found" when the token may still be live in Vault.
            raise
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

    async def get_user_learned_audience(
        self,
        gateway_id: str,
        team_id: str,
        app_user_email: str,
    ) -> tuple[str | None, str | None]:
        """Return the per-user learned JWT audience and issuer for a gateway-user pair.

        Retrieves learned_aud and learned_iss from the Vault token record for this
        gateway-team-user combination. These values are captured at OAuth callback time
        and used by token_validation_service to validate tokens against the IdP's actual
        audience/issuer rather than gateway.oauth_config defaults.

        Args:
            gateway_id: ID of the gateway
            team_id: Team identifier (used in Vault path construction)
            app_user_email: ContextForge user email

        Returns:
            Tuple of (learned_aud, learned_iss). Either element may be None if
            no token record exists or if the fields were never populated.
        """
        try:
            mcp_url = self._resolve_mcp_url(gateway_id)
            path = self._construct_vault_path(team_id, mcp_url, app_user_email)
            result = await self._vault_request("GET", path)

            if not result or "data" not in result:
                logger.debug(
                    "No token record found in Vault for gateway %s, team=%s, user=%s",
                    SecurityValidator.sanitize_log_message(gateway_id),
                    SecurityValidator.sanitize_log_message(team_id),
                    SecurityValidator.sanitize_log_message(app_user_email),
                )
                return (None, None)

            data = result["data"]["data"]
            learned_aud = data.get("learned_aud")
            learned_iss = data.get("learned_iss")

            logger.debug(
                "Retrieved learned audience for gateway %s, team=%s, user=%s: aud=%s, iss=%s",
                SecurityValidator.sanitize_log_message(gateway_id),
                SecurityValidator.sanitize_log_message(team_id),
                SecurityValidator.sanitize_log_message(app_user_email),
                SecurityValidator.sanitize_log_message(str(learned_aud)),
                SecurityValidator.sanitize_log_message(str(learned_iss)),
            )

            return (learned_aud, learned_iss)

        except Exception as e:
            logger.debug(
                "Failed to retrieve learned audience for gateway %s, team=%s, user=%s: %s",
                SecurityValidator.sanitize_log_message(gateway_id),
                SecurityValidator.sanitize_log_message(team_id),
                SecurityValidator.sanitize_log_message(app_user_email),
                SecurityValidator.sanitize_log_message(str(e)),
            )
            return (None, None)

    # NOTE (Phase 2): wire get_oauth_credentials / store_oauth_credentials into the
    # authorize/refresh flow so that teams can override the per-gateway oauth_config
    # stored in the database with team-scoped credentials kept in Vault.  Both methods
    # are fully implemented below but have no call sites in the current Phase 1 scope.
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

    async def _get_refresh_lock(self, gateway_id: str, team_id: str, app_user_email: str) -> "asyncio.Lock":
        """Return (creating on first use) the per-key asyncio.Lock for refresh serialisation.

        The mutex guard is itself lazy-initialised because asyncio.Lock() must be
        created inside a running event loop (Python 3.10+).

        Args:
            gateway_id: Gateway ID
            team_id: Team identifier
            app_user_email: ContextForge user email

        Returns:
            asyncio.Lock scoped to this (gateway_id, team_id, app_user_email) triple.
        """
        if VaultTokenBackend._refresh_locks_mutex is None:
            VaultTokenBackend._refresh_locks_mutex = asyncio.Lock()
        key = (gateway_id, team_id, app_user_email)
        async with VaultTokenBackend._refresh_locks_mutex:  # pylint: disable=not-async-context-manager
            if key not in VaultTokenBackend._refresh_locks:
                if len(VaultTokenBackend._refresh_locks) >= self.cache_max_size:
                    # Evict the oldest IDLE (unlocked) entry to bound dict size,
                    # mirroring the LRU cap already on _token_cache.
                    # NEVER evict a held lock: a concurrent _get_refresh_lock call
                    # for the same key would receive a fresh lock object and run a
                    # duplicate IdP refresh while the original holder still owns the
                    # old object — defeating serialisation and triggering invalid_grant
                    # on rotating-refresh-token IdPs.
                    for oldest_key, oldest_lock in VaultTokenBackend._refresh_locks.items():
                        if not oldest_lock.locked():
                            del VaultTokenBackend._refresh_locks[oldest_key]
                            break
                    # If every entry is currently held, allow temporary growth —
                    # correctness takes priority over a strict size bound during bursts.
                VaultTokenBackend._refresh_locks[key] = asyncio.Lock()
            return VaultTokenBackend._refresh_locks[key]

    async def _refresh_access_token(
        self,
        gateway_id: str,
        team_id: str,
        app_user_email: str,
        refresh_token: str,
        vault_data: dict,
        threshold_seconds: int = 300,
    ) -> str | None:
        """Refresh an expired access token using refresh token.

        Serialises concurrent near-expiry refreshes via a per-key asyncio.Lock so
        that only one worker calls the IdP at a time.  After acquiring the lock the
        method re-reads the token from Vault; if the first waiter already refreshed
        the token we return that fresh value immediately without a second IdP call.

        Args:
            gateway_id: Gateway ID
            team_id: Team identifier
            app_user_email: ContextForge user email
            refresh_token: Plain-text refresh token
            vault_data: Current Vault token data (for preserving metadata)
            threshold_seconds: Seconds before expiry to consider token near-expiry.
                Must match the value used by the caller (get_user_token) so the
                "already refreshed" recheck uses the same freshness window as the
                near-expiry trigger.

        Returns:
            New access token or None if refresh failed
        """
        lock = await self._get_refresh_lock(gateway_id, team_id, app_user_email)
        async with lock:
            # Re-read under the lock.  If a concurrent waiter already completed the
            # refresh cycle the token will no longer be near-expiry — return it
            # without burning the (potentially one-use) refresh token a second time.
            mcp_url_check = self._resolve_mcp_url(gateway_id)
            path_check = self._construct_vault_path(team_id, mcp_url_check, app_user_email)
            fresh_result = await self._vault_request("GET", path_check)
            if fresh_result and "data" in fresh_result:
                fresh_data = fresh_result["data"]["data"]
                fresh_token = fresh_data.get("token", {}).get("access_token")
                fresh_expires_str = fresh_data.get("expires_at")
                if fresh_token:
                    if not fresh_expires_str:
                        # IdP omitted expires_in — any fresh access token written by
                        # the winner is valid indefinitely.  Return it immediately to
                        # avoid burning a rotating refresh token a second time.
                        logger.debug(
                            "Token already refreshed (no expiry) by a concurrent waiter for gateway %s, user %s",
                            SecurityValidator.sanitize_log_message(gateway_id),
                            SecurityValidator.sanitize_log_message(app_user_email),
                        )
                        return fresh_token
                    fresh_expires = datetime.fromisoformat(fresh_expires_str.replace("Z", "+00:00"))
                    # Use the same threshold that triggered the refresh so the
                    # guard window is consistent with the trigger window.
                    if (fresh_expires - datetime.now(timezone.utc)).total_seconds() >= threshold_seconds:
                        logger.debug(
                            "Token already refreshed by a concurrent waiter for gateway %s, user %s",
                            SecurityValidator.sanitize_log_message(gateway_id),
                            SecurityValidator.sanitize_log_message(app_user_email),
                        )
                        return fresh_token

            return await self._do_refresh_access_token(gateway_id, team_id, app_user_email, refresh_token, vault_data)

    async def _do_refresh_access_token(
        self,
        gateway_id: str,
        team_id: str,
        app_user_email: str,
        refresh_token: str,
        vault_data: dict,
    ) -> str | None:
        """Inner refresh logic — called only while the per-key lock is held.

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
                logger.error("No OAuth configuration found for gateway %s", SecurityValidator.sanitize_log_message(gateway_id))
                return None

            # PR #4341: Refuse refresh on private gateway whose owner != token owner
            if not check_private_gateway_access(
                gateway_visibility=getattr(gateway, "visibility", "public"),
                gateway_owner_email=getattr(gateway, "owner_email", None),
                token_owner_email=app_user_email,
                gateway_id=gateway_id,
            ):
                return None

            oauth_config = gateway.oauth_config.copy()

            # Decrypt client_secret before calling the token endpoint.
            # The gateway record stores client_secret encrypted at rest (same as DB backend).
            # Sending an encrypted ciphertext envelope to the IdP causes repeated
            # invalid_client errors that can trigger IdP rate-limiting / account lockout.
            # Fail closed: raise OAuthError so the outer handler preserves the stored
            # token for a later retry (same behaviour as DatabaseTokenBackend:436-446).
            if "client_secret" in oauth_config and oauth_config["client_secret"]:
                encryption_secret = getattr(self.settings, "auth_encryption_secret", None)
                if encryption_secret:
                    try:
                        from mcpgateway.services.encryption_service import get_encryption_service  # pylint: disable=import-outside-toplevel

                        encryption = get_encryption_service(encryption_secret)
                        decrypted_secret = await encryption.decrypt_secret_async(oauth_config["client_secret"])
                        if decrypted_secret is None:
                            raise OAuthError(
                                f"client_secret decryption failed for gateway {gateway_id}: "
                                "decrypt_secret_async returned None (wrong AUTH_ENCRYPTION_SECRET or corrupted ciphertext). "
                                "Check that AUTH_ENCRYPTION_SECRET matches the value used when the gateway was stored."
                            )
                        oauth_config["client_secret"] = decrypted_secret
                    except OAuthError:
                        raise
                    except Exception as enc_err:
                        # Fail closed: raise so the outer OAuthError handler preserves
                        # the stored token for a later retry rather than sending the
                        # raw ciphertext envelope as the literal client_secret to the IdP
                        # (same behaviour as DatabaseTokenBackend lines 436-446).
                        raise OAuthError(f"client_secret decryption setup failed for gateway {gateway_id}: {enc_err}") from enc_err

            # RFC 8707: Set resource parameter for JWT access tokens during refresh
            # PR #5244: Apply omit_resource flag and normalize resource parameter
            apply_omit_resource_and_normalize(oauth_config, gateway.url, gateway_id)

            # Use OAuthManager to refresh the token
            oauth_manager = OAuthManager()

            logger.info(
                "Attempting to refresh token in Vault for gateway %s, user %s",
                SecurityValidator.sanitize_log_message(gateway_id),
                SecurityValidator.sanitize_log_message(app_user_email),
            )
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

            # PR #5244: Preserve prior TTL if refresh response omits expires_in
            if expires_in is None:
                expires_in = compute_prior_ttl(
                    vault_data.get("expires_at"),
                    vault_data.get("updated_at"),
                    gateway_id,
                )
                if expires_in is None:
                    logger.info(
                        "No expires_in on refresh response for gateway %s; no prior TTL to preserve",
                        SecurityValidator.sanitize_log_message(gateway_id),
                    )

            # Store refreshed tokens back to Vault.
            # Round-trip the previously-learned audience/issuer so they are not
            # erased by the refresh cycle — the refresh response never carries
            # aud/iss, and store_tokens guards with `if not None`.
            await self.store_tokens(
                gateway_id=gateway_id,
                team_id=team_id,
                user_id=vault_data.get("user_id", ""),
                app_user_email=app_user_email,
                access_token=new_access_token,
                refresh_token=new_refresh_token,
                expires_in=expires_in,
                scopes=vault_data["token"]["scopes"],
                learned_aud=vault_data.get("learned_aud"),
                learned_iss=vault_data.get("learned_iss"),
            )

            logger.info(
                "Successfully refreshed token in Vault for gateway %s, user %s",
                SecurityValidator.sanitize_log_message(gateway_id),
                SecurityValidator.sanitize_log_message(app_user_email),
            )

            return new_access_token

        except OAuthInvalidGrantError as e:
            # RFC 6749 §5.2: invalid_grant is a permanent failure — the refresh
            # token has been revoked, expired, or does not match the grant.
            # OAuthInvalidGrantError is raised by OAuthManager only when the
            # token endpoint explicitly returns {"error": "invalid_grant"}, so
            # this match is based on structured type, not substring heuristics.
            logger.warning(
                "Refresh token is permanently invalid for gateway %s (invalid_grant). Deleting token to force re-authorization. Error: %s",
                SecurityValidator.sanitize_log_message(gateway_id),
                str(e),
            )
            await self.revoke_user_tokens(gateway_id, team_id, app_user_email)
            return None
        except OAuthError as e:
            # All other OAuth errors (invalid_client, invalid_request, network
            # failures wrapped as OAuthError, etc.).
            # These are configuration or transient errors — NOT a permanent
            # token failure.  Preserve the token so a later retry can succeed.
            logger.error(
                "Token refresh failed for gateway %s but error does not indicate invalid refresh token. Preserving token for retry. Error: %s",
                SecurityValidator.sanitize_log_message(gateway_id),
                str(e),
            )
            return None
        except Exception as e:
            # Non-OAuth errors (network, parsing, Vault connectivity, etc.)
            logger.error(
                "Unexpected error refreshing token in Vault for gateway %s: %s",
                SecurityValidator.sanitize_log_message(gateway_id),
                str(e),
            )
            # Preserve token - this is likely a transient or configuration issue
            return None
