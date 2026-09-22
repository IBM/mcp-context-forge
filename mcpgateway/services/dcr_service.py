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
from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

# Third-Party
import httpx
import orjson
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.common.validators import pin_url_to_resolved_ip, SecurityValidator
from mcpgateway.config import get_settings
from mcpgateway.db import RegisteredOAuthClient
from mcpgateway.services.encryption_service import get_encryption_service
from mcpgateway.services.http_client_service import get_isolated_http_client
from mcpgateway.utils.origin import is_same_origin, origin_from_url

logger = logging.getLogger(__name__)

# In-memory cache for AS metadata
# Format: {issuer: {"metadata": dict, "cached_at": datetime}}
_metadata_cache: Dict[str, Dict[str, Any]] = {}


@dataclass(frozen=True)
class _PinnedDcrTarget:
    """An outbound DCR request target that is validated and pinned to one address.

    Attributes:
        url: Request URL whose host is the address resolved at validation time.
        headers: Headers that restore the original authority.
        extensions: httpx extensions that bind TLS verification to the original hostname.
    """

    url: str
    headers: Dict[str, str] = field(default_factory=dict)
    extensions: Dict[str, str] = field(default_factory=dict)


class DcrService:
    """Service for OAuth 2.0 Dynamic Client Registration (RFC 7591 client)."""

    def __init__(self):
        """Initialize DCR service."""
        self.settings = get_settings()

    def _get_timeout(self) -> float:
        """Get the OAuth request timeout from settings.

        Returns:
            Timeout in seconds for OAuth/DCR requests
        """
        return float(self.settings.oauth_request_timeout)

    async def _prepare_pinned_request(self, url: Optional[str], issuer: Optional[str], field_name: str) -> _PinnedDcrTarget:
        """Validate an outbound DCR URL and pin its connection to one address.

        The authorization server controls its own metadata document, so a URL
        read from that document is untrusted input. Two gates apply. The URL
        must share the issuer origin, which the request schema already
        validated. The URL must then pass the outbound URL policy, and the
        connection dials the address resolved during that check. Pinning closes
        the DNS rebinding window that GHSA-9hgc-g3w5-67cm describes.

        Args:
            url: URL read from the AS metadata, the registration response, or the issuer.
            issuer: Normalized issuer URL for this authorization server.
            field_name: Field name, used in error messages.

        Returns:
            _PinnedDcrTarget: The pinned URL with its authority headers and TLS extensions.

        Raises:
            DcrError: If the URL leaves the issuer origin or the URL policy blocks it.
        """
        if not url or not issuer or not is_same_origin(url, origin_from_url(issuer)):
            raise DcrError(f"{field_name} must share the issuer origin")

        try:
            validated_target = await SecurityValidator.validate_url_for_connection_pinning(url, field_name)
        except ValueError as validation_error:
            raise DcrError(f"{field_name} blocked by URL policy") from validation_error

        resolved_ip = validated_target.get("resolved_ip")
        original_hostname = validated_target.get("hostname")
        original_authority = validated_target.get("original_authority")
        pinning_available = bool(resolved_ip and original_hostname and original_authority)

        if self.settings.ssrf_protection_enabled and not pinning_available:
            raise DcrError(f"{field_name} blocked by URL policy")

        if not pinning_available:
            return _PinnedDcrTarget(url=url)

        return _PinnedDcrTarget(
            url=pin_url_to_resolved_ip(url, resolved_ip),
            headers={"Host": original_authority},
            extensions={"sni_hostname": original_hostname},
        )

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
        # Normalize issuer URL by removing trailing slash for consistency.
        # Per RFC 8414 Section 3.1, any terminating "/" MUST be removed before
        # inserting "/.well-known/" and the well-known URI suffix.
        # This also works around MCP Python SDK issue #1919 where Pydantic's
        # AnyHttpUrl adds trailing slashes to bare hostnames.
        # See: https://github.com/modelcontextprotocol/python-sdk/issues/1919
        normalized_issuer = issuer.rstrip("/")

        # Check cache first (using normalized issuer as key for consistency)
        if normalized_issuer in _metadata_cache:
            cached_entry = _metadata_cache[normalized_issuer]
            cached_at = cached_entry["cached_at"]
            cache_age = (datetime.now(timezone.utc) - cached_at).total_seconds()

            if cache_age < self.settings.dcr_metadata_cache_ttl:
                logger.debug("Using cached AS metadata for %s", normalized_issuer)
                return cached_entry["metadata"]

        # Try RFC 8414 path first
        # Per RFC 8414 Section 3.1: "the well-known URI is formed by inserting the
        # well-known URI string... between the host component and any existing path
        # component of the issuer's identifier".
        # See: https://datatracker.ietf.org/doc/html/rfc8414#section-3.1
        parsed = urlsplit(normalized_issuer)
        rfc8414_url = f"{parsed.scheme}://{parsed.netloc}/.well-known/oauth-authorization-server"
        if parsed.path:
            rfc8414_url += parsed.path

        rfc8414_target = await self._prepare_pinned_request(rfc8414_url, normalized_issuer, "AS metadata discovery URL")

        try:
            async with get_isolated_http_client(follow_redirects=False) as client:
                response = await client.get(
                    rfc8414_target.url,
                    timeout=self._get_timeout(),
                    follow_redirects=False,
                    headers=rfc8414_target.headers,
                    extensions=rfc8414_target.extensions,
                )
                if 300 <= response.status_code < 400:
                    raise DcrError(f"AS metadata discovery redirect refused for {normalized_issuer} (status: {response.status_code})")
                if response.status_code == 200:
                    try:
                        metadata = response.json()
                    except ValueError:
                        raise DcrError(f"AS metadata discovery returned a non-JSON body for {normalized_issuer} (status: {response.status_code})")

                    # Validate issuer matches (normalize metadata issuer for comparison)
                    metadata_issuer = (metadata.get("issuer") or "").rstrip("/")
                    if metadata_issuer != normalized_issuer:
                        raise DcrError(f"AS metadata issuer mismatch: expected {normalized_issuer}, got {metadata.get('issuer')}")

                    # Cache the metadata
                    _metadata_cache[normalized_issuer] = {"metadata": metadata, "cached_at": datetime.now(timezone.utc)}

                    logger.info("Discovered AS metadata for %s via RFC 8414", normalized_issuer)
                    return metadata
        except httpx.HTTPError as e:
            logger.debug("RFC 8414 discovery failed for %s: %s, trying OIDC fallback", normalized_issuer, e)

        # Try OIDC discovery fallback
        oidc_url = f"{normalized_issuer}/.well-known/openid-configuration"

        oidc_target = await self._prepare_pinned_request(oidc_url, normalized_issuer, "AS metadata discovery URL")

        try:
            async with get_isolated_http_client(follow_redirects=False) as client:
                response = await client.get(
                    oidc_target.url,
                    timeout=self._get_timeout(),
                    follow_redirects=False,
                    headers=oidc_target.headers,
                    extensions=oidc_target.extensions,
                )
                if 300 <= response.status_code < 400:
                    raise DcrError(f"AS metadata discovery redirect refused for {normalized_issuer} (status: {response.status_code})")
                if response.status_code == 200:
                    try:
                        metadata = response.json()
                    except ValueError:
                        raise DcrError(f"AS metadata discovery returned a non-JSON body for {normalized_issuer} (status: {response.status_code})")

                    # Validate issuer matches (normalize metadata issuer for comparison)
                    metadata_issuer = (metadata.get("issuer") or "").rstrip("/")
                    if metadata_issuer != normalized_issuer:
                        raise DcrError(f"AS metadata issuer mismatch: expected {normalized_issuer}, got {metadata.get('issuer')}")

                    # Cache the metadata
                    _metadata_cache[normalized_issuer] = {"metadata": metadata, "cached_at": datetime.now(timezone.utc)}

                    logger.info("Discovered AS metadata for %s via OIDC discovery", normalized_issuer)
                    return metadata

                raise DcrError(f"AS metadata not found for {normalized_issuer} (status: {response.status_code})")
        except httpx.HTTPError as e:
            raise DcrError(f"Failed to discover AS metadata for {normalized_issuer}: {e}")

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

        pinned_target = await self._prepare_pinned_request(registration_endpoint, normalized_issuer, "DCR registration_endpoint")

        # Send registration request
        try:
            async with get_isolated_http_client(follow_redirects=False) as client:
                response = await client.post(
                    pinned_target.url,
                    json=registration_request,
                    headers=pinned_target.headers,
                    extensions=pinned_target.extensions,
                    timeout=self._get_timeout(),
                )
                # Accept both 200 OK and 201 Created (some servers don't follow RFC 7591 strictly)
                if response.status_code in (200, 201):
                    try:
                        registration_response = response.json()
                    except ValueError:
                        raise DcrError(f"Client registration succeeded but the response body is not valid JSON (status: {response.status_code})")
                else:
                    try:
                        error_data = response.json()
                    except ValueError:
                        raise DcrError(f"Client registration failed: upstream returned status {response.status_code} with a non-JSON body")
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

        pinned_target = await self._prepare_pinned_request(client_record.registration_client_uri, client_record.issuer, "DCR registration_client_uri")

        # Send update request
        try:
            headers = {"Authorization": f"Bearer {registration_access_token}", **pinned_target.headers}
            async with get_isolated_http_client(follow_redirects=False) as client:
                response = await client.put(
                    pinned_target.url,
                    json=update_request,
                    headers=headers,
                    extensions=pinned_target.extensions,
                    timeout=self._get_timeout(),
                )
                if response.status_code == 200:
                    try:
                        updated_response = response.json()
                    except ValueError:
                        raise DcrError(f"Client registration update succeeded but the response body is not valid JSON (status: {response.status_code})")

                    # Update encrypted secret if changed
                    if "client_secret" in updated_response:
                        client_record.client_secret_encrypted = await encryption.encrypt_secret_async(updated_response["client_secret"])

                    db.commit()
                    db.refresh(client_record)

                    logger.info("Successfully updated client registration for %s", client_record.client_id)
                    return client_record

                try:
                    error_data = response.json()
                except ValueError:
                    raise DcrError(f"Failed to update client: upstream returned status {response.status_code} with a non-JSON body")
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

        try:
            pinned_target = await self._prepare_pinned_request(client_record.registration_client_uri, client_record.issuer, "DCR registration_client_uri")
        except DcrError as policy_error:
            logger.error("Refused to delete a client registration at a blocked URL: %s", SecurityValidator.sanitize_log_message(str(policy_error)))
            return False

        # Send delete request
        try:
            headers = {"Authorization": f"Bearer {registration_access_token}", **pinned_target.headers}
            async with get_isolated_http_client(follow_redirects=False) as client:
                response = await client.delete(
                    pinned_target.url,
                    headers=headers,
                    extensions=pinned_target.extensions,
                    timeout=self._get_timeout(),
                )
                if response.status_code in [204, 404]:  # 204 = deleted, 404 = already gone
                    logger.info("Successfully deleted client registration for %s", client_record.client_id)
                    return True

                logger.warning("Unexpected status when deleting client: %s", response.status_code)
                return False
        except httpx.HTTPError as e:
            logger.error("Failed to delete client at AS: %s", e)
            return False


class DcrError(Exception):
    """DCR-related errors."""
