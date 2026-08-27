# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/dcr_service.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

OAuth 2.0 Dynamic Client Registration Service.

This module handles OAuth 2.0 Dynamic Client Registration (DCR) including:
- AS metadata discovery (RFC 8414)
- Client registration (RFC 7591)
- Client management (update, delete)
"""

# Standard
import asyncio
from datetime import datetime, timezone
import logging
from typing import Any, Dict, List
from urllib.parse import urlsplit

# Third-Party
import httpx
import orjson
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.common.validators import SecurityValidator
from mcpgateway.config import get_settings
from mcpgateway.db import RegisteredOAuthClient
from mcpgateway.services.encryption_service import get_encryption_service
from mcpgateway.services.http_client_service import get_http_client

logger = logging.getLogger(__name__)

# In-memory cache for AS metadata
# Format: {issuer: {"metadata": dict, "cached_at": datetime}}
_metadata_cache: Dict[str, Dict[str, Any]] = {}
_metadata_locks: Dict[str, asyncio.Lock] = {}
_metadata_locks_guard = asyncio.Lock()

_DISCOVERY_TIMEOUT_SECONDS = 5.0
_DISCOVERY_MAX_RESPONSE_BYTES = 256 * 1024


class DcrService:
    """Service for OAuth 2.0 Dynamic Client Registration (RFC 7591 client)."""

    def __init__(self):
        """Initialize DCR service."""
        self.settings = get_settings()

    async def _get_client(self) -> httpx.AsyncClient:
        """Get the shared singleton HTTP client.

        Returns:
            Shared httpx.AsyncClient instance with connection pooling
        """
        return await get_http_client()

    def _get_timeout(self) -> float:
        """Get the OAuth request timeout from settings.

        Returns:
            Timeout in seconds for OAuth/DCR requests
        """
        return float(self.settings.oauth_request_timeout)

    @staticmethod
    def _get_cached_metadata(normalized_issuer: str, cache_ttl: int) -> Dict[str, Any] | None:
        """Return fresh cached metadata for an issuer when available."""
        cached_entry = _metadata_cache.get(normalized_issuer)
        if cached_entry is None:
            return None

        cache_age = (datetime.now(timezone.utc) - cached_entry["cached_at"]).total_seconds()
        if cache_age >= cache_ttl:
            return None
        return cached_entry["metadata"]

    async def _metadata_lock(self, normalized_issuer: str) -> asyncio.Lock:
        """Return the process-local singleflight lock for an issuer."""
        async with _metadata_locks_guard:
            return _metadata_locks.setdefault(normalized_issuer, asyncio.Lock())

    async def _validate_discovery_issuer(self, issuer: str) -> str:
        """Validate an issuer URL before it becomes an outbound request target."""
        try:
            target = await SecurityValidator.validate_url_for_connection_pinning(issuer, "OAuth issuer URL")
        except ValueError as exc:
            raise DcrError("OAuth issuer URL is blocked by outbound security policy", code="blocked") from exc

        normalized_issuer = str(target["validated_url"]).rstrip("/")
        parsed = urlsplit(normalized_issuer)
        if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise DcrError("OAuth issuer URL must be an HTTPS origin or path without credentials, query, or fragment", code="blocked")
        return normalized_issuer

    async def _fetch_metadata_document(self, url: str, normalized_issuer: str) -> Dict[str, Any] | None:
        """Fetch one discovery document within public-registration safety limits."""
        try:
            client = await self._get_client()
            response = await client.get(
                url,
                timeout=min(self._get_timeout(), _DISCOVERY_TIMEOUT_SECONDS),
                follow_redirects=False,
                headers={"Accept": "application/json"},
            )
        except httpx.TimeoutException as exc:
            raise DcrError("OAuth issuer metadata request timed out", code="timeout") from exc
        except httpx.HTTPError as exc:
            raise DcrError("OAuth issuer metadata could not be reached", code="not_found") from exc

        if 300 <= response.status_code < 400:
            raise DcrError("OAuth issuer metadata redirects are not allowed", code="invalid_metadata")
        if response.status_code != 200:
            return None

        content_length = response.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > _DISCOVERY_MAX_RESPONSE_BYTES:
                    raise DcrError("OAuth issuer metadata response is too large", code="invalid_metadata")
            except ValueError:
                raise DcrError("OAuth issuer metadata response has an invalid content length", code="invalid_metadata") from None

        content = response.content
        if isinstance(content, bytes) and len(content) > _DISCOVERY_MAX_RESPONSE_BYTES:
            raise DcrError("OAuth issuer metadata response is too large", code="invalid_metadata")

        try:
            metadata = response.json()
        except (ValueError, orjson.JSONDecodeError) as exc:
            raise DcrError("OAuth issuer metadata is not valid JSON", code="invalid_metadata") from exc
        if not isinstance(metadata, dict):
            raise DcrError("OAuth issuer metadata must be a JSON object", code="invalid_metadata")

        metadata_issuer = str(metadata.get("issuer") or "").rstrip("/")
        if metadata_issuer != normalized_issuer:
            raise DcrError("OAuth issuer metadata issuer mismatch", code="invalid_metadata")
        self._validate_metadata_shape(metadata)
        return metadata

    @staticmethod
    def _validate_metadata_shape(metadata: Dict[str, Any]) -> None:
        """Validate metadata fields that are returned to the registration UI."""
        for field_name in ("authorization_endpoint", "token_endpoint"):
            value = metadata.get(field_name)
            if value is None:
                continue
            parsed = urlsplit(value) if isinstance(value, str) else None
            if not parsed or parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
                raise DcrError(f"OAuth issuer metadata has invalid {field_name}", code="invalid_metadata")

        registration_endpoint = metadata.get("registration_endpoint")
        if registration_endpoint is not None:
            parsed = urlsplit(registration_endpoint) if isinstance(registration_endpoint, str) else None
            if not parsed or parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
                raise DcrError("OAuth issuer metadata has invalid registration_endpoint", code="invalid_metadata")

        scopes_supported = metadata.get("scopes_supported")
        if scopes_supported is not None and (not isinstance(scopes_supported, list) or not all(isinstance(scope, str) and scope for scope in scopes_supported)):
            raise DcrError("OAuth issuer metadata has invalid scopes_supported", code="invalid_metadata")

    async def discover_as_metadata(self, issuer: str) -> Dict[str, Any]:
        """Discover AS metadata via RFC 8414.

        Tries:
        1. RFC 8414: /.well-known/oauth-authorization-server inserted between host and path
        2. OIDC fallback: {issuer}/.well-known/openid-configuration

        Args:
            issuer: The AS issuer URL

        Returns:
            Dict containing AS metadata

        Raises:
            DcrError: If metadata cannot be discovered
        """
        # Normalize issuer URL by removing a trailing slash before RFC 8414
        # well-known-path construction. The validation also prevents this public
        # discovery capability from becoming an SSRF probing primitive.
        normalized_issuer = await self._validate_discovery_issuer(issuer)
        cached = self._get_cached_metadata(normalized_issuer, self.settings.dcr_metadata_cache_ttl)
        if cached is not None:
            logger.debug("Using cached AS metadata for %s", normalized_issuer)
            return cached

        metadata_lock = await self._metadata_lock(normalized_issuer)
        try:
            async with metadata_lock:
                cached = self._get_cached_metadata(normalized_issuer, self.settings.dcr_metadata_cache_ttl)
                if cached is not None:
                    logger.debug("Using cached AS metadata for %s", normalized_issuer)
                    return cached

                # RFC 8414 inserts the well-known path between authority and any issuer path.
                parsed = urlsplit(normalized_issuer)
                rfc8414_url = f"{parsed.scheme}://{parsed.netloc}/.well-known/oauth-authorization-server{parsed.path}"
                metadata = await self._fetch_metadata_document(rfc8414_url, normalized_issuer)
                discovery_method = "RFC 8414"

                if metadata is None:
                    metadata = await self._fetch_metadata_document(
                        f"{normalized_issuer}/.well-known/openid-configuration",
                        normalized_issuer,
                    )
                    discovery_method = "OIDC Discovery"

                if metadata is None:
                    raise DcrError("OAuth issuer metadata was not found", code="not_found")

                _metadata_cache[normalized_issuer] = {"metadata": metadata, "cached_at": datetime.now(timezone.utc)}
                logger.info("Discovered AS metadata for %s via %s", normalized_issuer, discovery_method)
                return metadata
        finally:
            # Locks guard only in-flight work. Keeping one for every user-supplied
            # issuer would let this public endpoint grow process memory forever.
            async with _metadata_locks_guard:
                if _metadata_locks.get(normalized_issuer) is metadata_lock and not metadata_lock.locked():
                    _metadata_locks.pop(normalized_issuer, None)

    async def register_client(self, gateway_id: str, gateway_name: str, issuer: str, redirect_uri: str, scopes: List[str], db: Session) -> RegisteredOAuthClient:
        """Register as OAuth client with upstream AS (RFC 7591).

        Args:
            gateway_id: Gateway ID
            gateway_name: Gateway name
            issuer: AS issuer URL
            redirect_uri: OAuth redirect URI
            scopes: List of OAuth scopes
            db: Database session

        Returns:
            RegisteredOAuthClient record

        Raises:
            DcrError: If registration fails
        """
        # Normalize issuer URL for consistent storage and lookup
        normalized_issuer = issuer.rstrip("/")

        # Validate issuer if allowlist is configured (normalize both for comparison)
        if self.settings.dcr_allowed_issuers:
            normalized_allowlist = [i.rstrip("/") for i in self.settings.dcr_allowed_issuers]
            if normalized_issuer not in normalized_allowlist:
                raise DcrError(f"Issuer {issuer} is not in allowed issuers list")

        # Discover AS metadata
        metadata = await self.discover_as_metadata(normalized_issuer)

        registration_endpoint = metadata.get("registration_endpoint")
        if not registration_endpoint:
            raise DcrError(f"AS {normalized_issuer} does not support Dynamic Client Registration (no registration_endpoint)")

        # Build registration request (RFC 7591)
        client_name = self.settings.dcr_client_name_template.replace("{gateway_name}", gateway_name)

        # Determine grant types based on AS metadata
        # Use `or []` to handle both missing key AND explicit null value (prevents TypeError)
        grant_types_supported = metadata.get("grant_types_supported") or []
        requested_grant_types = ["authorization_code"]

        # Only request refresh_token if AS explicitly supports it, or if permissive mode is enabled
        if "refresh_token" in grant_types_supported:
            requested_grant_types.append("refresh_token")
        elif self.settings.dcr_request_refresh_token_when_unsupported and not grant_types_supported:
            # Permissive mode: request refresh_token when AS doesn't advertise grant_types_supported
            # This is useful for AS servers that support refresh tokens but don't advertise it
            requested_grant_types.append("refresh_token")
            logger.debug("Requesting refresh_token for %s (permissive mode, AS omits grant_types_supported)", normalized_issuer)

        registration_request = {
            "client_name": client_name,
            "redirect_uris": [redirect_uri],
            "grant_types": requested_grant_types,
            "response_types": ["code"],
            "token_endpoint_auth_method": self.settings.dcr_token_endpoint_auth_method,
            "scope": " ".join(scopes),
        }

        # Send registration request
        try:
            client = await self._get_client()
            response = await client.post(registration_endpoint, json=registration_request, timeout=self._get_timeout())
            # Accept both 200 OK and 201 Created (some servers don't follow RFC 7591 strictly)
            if response.status_code in (200, 201):
                registration_response = response.json()
            else:
                error_data = response.json()
                error_msg = error_data.get("error", "unknown_error")
                error_desc = error_data.get("error_description", str(error_data))
                raise DcrError(f"Client registration failed: {error_msg} - {error_desc}")
        except httpx.HTTPError as e:
            raise DcrError(f"Failed to register client with {normalized_issuer}: {e}")

        # Encrypt secrets
        encryption = get_encryption_service(self.settings.auth_encryption_secret)

        client_secret = registration_response.get("client_secret")
        client_secret_encrypted = await encryption.encrypt_secret_async(client_secret) if client_secret else None

        registration_access_token = registration_response.get("registration_access_token")
        registration_access_token_encrypted = await encryption.encrypt_secret_async(registration_access_token) if registration_access_token else None

        # Calculate expires at
        expires_at = None
        client_secret_expires_at = registration_response.get("client_secret_expires_at")
        if client_secret_expires_at and client_secret_expires_at > 0:
            expires_at = datetime.fromtimestamp(client_secret_expires_at, tz=timezone.utc)

        # Create database record (use normalized issuer for consistent lookup)
        # Fall back to requested grant_types if AS response omits them
        registered_client = RegisteredOAuthClient(
            gateway_id=gateway_id,
            issuer=normalized_issuer,
            client_id=registration_response["client_id"],
            client_secret_encrypted=client_secret_encrypted,
            redirect_uris=orjson.dumps(registration_response.get("redirect_uris", [redirect_uri])).decode(),
            grant_types=orjson.dumps(registration_response.get("grant_types", requested_grant_types)).decode(),
            response_types=orjson.dumps(registration_response.get("response_types", ["code"])).decode(),
            scope=registration_response.get("scope", " ".join(scopes)),
            token_endpoint_auth_method=registration_response.get("token_endpoint_auth_method", self.settings.dcr_token_endpoint_auth_method),
            registration_client_uri=registration_response.get("registration_client_uri"),
            registration_access_token_encrypted=registration_access_token_encrypted,
            created_at=datetime.now(timezone.utc),
            expires_at=expires_at,
            is_active=True,
        )

        db.add(registered_client)
        db.commit()
        db.refresh(registered_client)

        logger.info(
            "Successfully registered client %s with %s for gateway %s",
            SecurityValidator.sanitize_log_message(registered_client.client_id),
            SecurityValidator.sanitize_log_message(normalized_issuer),
            SecurityValidator.sanitize_log_message(gateway_id),
        )

        return registered_client

    async def get_or_register_client(self, gateway_id: str, gateway_name: str, issuer: str, redirect_uri: str, scopes: List[str], db: Session) -> RegisteredOAuthClient:
        """Get existing registered client or register new one.

        Args:
            gateway_id: Gateway ID
            gateway_name: Gateway name
            issuer: AS issuer URL
            redirect_uri: OAuth redirect URI
            scopes: List of OAuth scopes
            db: Database session

        Returns:
            RegisteredOAuthClient record

        Raises:
            DcrError: If client not found and auto-register is disabled
        """
        # Normalize issuer for consistent lookup (matches how register_client stores it)
        normalized_issuer = issuer.rstrip("/")

        # Try to find existing client using normalized issuer
        existing_client = (
            db.query(RegisteredOAuthClient)
            .filter(RegisteredOAuthClient.gateway_id == gateway_id, RegisteredOAuthClient.issuer == normalized_issuer, RegisteredOAuthClient.is_active.is_(True))  # pylint: disable=singleton-comparison
            .first()
        )

        if existing_client:
            logger.debug("Found existing registered client for gateway %s and issuer %s", gateway_id, normalized_issuer)
            return existing_client

        # No existing client, check if auto-register is enabled
        if not self.settings.dcr_auto_register_on_missing_credentials:
            raise DcrError(
                f"No registered client found for gateway {gateway_id} and issuer {normalized_issuer}. Auto-register is disabled. Set MCPGATEWAY_DCR_AUTO_REGISTER_ON_MISSING_CREDENTIALS=true to enable."
            )

        # Auto-register (pass normalized issuer for consistent storage)
        logger.info(
            "No existing client found for gateway %s, registering new client with %s", SecurityValidator.sanitize_log_message(gateway_id), SecurityValidator.sanitize_log_message(normalized_issuer)
        )
        return await self.register_client(gateway_id, gateway_name, normalized_issuer, redirect_uri, scopes, db)

    async def update_client_registration(self, client_record: RegisteredOAuthClient, db: Session) -> RegisteredOAuthClient:
        """Update existing client registration (RFC 7591 section 4.2).

        Args:
            client_record: Existing RegisteredOAuthClient record
            db: Database session

        Returns:
            Updated RegisteredOAuthClient record

        Raises:
            DcrError: If update fails
        """
        if not client_record.registration_client_uri:
            raise DcrError("Cannot update client: no registration_client_uri available")

        if not client_record.registration_access_token_encrypted:
            raise DcrError("Cannot update client: no registration_access_token available")

        # Decrypt registration access token
        encryption = get_encryption_service(self.settings.auth_encryption_secret)
        registration_access_token = await encryption.decrypt_secret_async(client_record.registration_access_token_encrypted)
        if registration_access_token is None:
            raise DcrError("Failed to decrypt registration access token for update operation")

        # Build update request
        update_request = {"client_id": client_record.client_id, "redirect_uris": orjson.loads(client_record.redirect_uris), "grant_types": orjson.loads(client_record.grant_types)}

        # Send update request
        try:
            client = await self._get_client()
            headers = {"Authorization": f"Bearer {registration_access_token}"}
            response = await client.put(client_record.registration_client_uri, json=update_request, headers=headers, timeout=self._get_timeout())
            if response.status_code == 200:
                updated_response = response.json()

                # Update encrypted secret if changed
                if "client_secret" in updated_response:
                    client_record.client_secret_encrypted = await encryption.encrypt_secret_async(updated_response["client_secret"])

                db.commit()
                db.refresh(client_record)

                logger.info("Successfully updated client registration for %s", client_record.client_id)
                return client_record

            error_data = response.json()
            raise DcrError(f"Failed to update client: {error_data}")
        except httpx.HTTPError as e:
            raise DcrError(f"Failed to update client registration: {e}")

    async def delete_client_registration(self, client_record: RegisteredOAuthClient, db: Session) -> bool:  # pylint: disable=unused-argument
        """Delete/revoke client registration (RFC 7591 section 4.3).

        Args:
            client_record: RegisteredOAuthClient record to delete
            db: Database session

        Returns:
            bool: True if deletion succeeded at the Authorization Server.
                False if deletion failed (missing prerequisites, decryption error, network error).
                Note: Does not guarantee local database deletion.

        Raises:
            DcrError: If deletion fails catastrophically
        """
        if not client_record.registration_client_uri:
            logger.warning("Cannot delete client at AS: no registration_client_uri")
            return False

        if not client_record.registration_access_token_encrypted:
            logger.warning("Cannot delete client at AS: no registration_access_token")
            return False

        # Decrypt registration access token
        encryption = get_encryption_service(self.settings.auth_encryption_secret)
        registration_access_token = await encryption.decrypt_secret_async(client_record.registration_access_token_encrypted)
        if registration_access_token is None:
            logger.error("Failed to decrypt registration access token; cannot authenticate delete request to AS")
            return False

        # Send delete request
        try:
            client = await self._get_client()
            headers = {"Authorization": f"Bearer {registration_access_token}"}
            response = await client.delete(client_record.registration_client_uri, headers=headers, timeout=self._get_timeout())
            if response.status_code in [204, 404]:  # 204 = deleted, 404 = already gone
                logger.info("Successfully deleted client registration for %s", client_record.client_id)
                return True

            logger.warning("Unexpected status when deleting client: %s", response.status_code)
            return False
        except httpx.HTTPError as e:
            logger.error("Failed to delete client at AS: %s", e)
            return False


class DcrError(Exception):
    """DCR-related errors with a safe, structured public classification."""

    def __init__(self, message: str, *, code: str = "invalid_metadata") -> None:
        """Create a DCR error with a safe public error code."""
        super().__init__(message)
        self.code = code
