# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/dcr_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Manav Gupta

OAuth 2.0 Dynamic Client Registration Service.

This module handles OAuth 2.0 Dynamic Client Registration (DCR) including:
- AS metadata discovery (RFC 8414)
- Client registration (RFC 7591)
- Client management (update, delete)
"""

# Standard
from datetime import datetime, timezone
import logging
from typing import Any, Dict, List

# Third-Party
import httpx
import orjson
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import get_settings
from mcpgateway.db import RegisteredOAuthClient
from mcpgateway.services.encryption_service import get_encryption_service
from mcpgateway.services.http_client_service import get_http_client

logger = logging.getLogger(__name__)

# In-memory cache for AS metadata
# Format: {issuer: {"metadata": dict, "cached_at": datetime}}
_metadata_cache: Dict[str, Dict[str, Any]] = {}


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

    async def discover_as_metadata(self, issuer: str) -> Dict[str, Any]:
        """Discover AS metadata via RFC 8414.

        Tries:
        1. {issuer}/.well-known/oauth-authorization-server (RFC 8414)
        2. {issuer}/.well-known/openid-configuration (OIDC fallback)

        Args:
            issuer: The AS issuer URL

        Returns:
            Dict containing AS metadata

        Raises:
            DcrError: If metadata cannot be discovered
        """
        # Check cache first
        if issuer in _metadata_cache:
            cached_entry = _metadata_cache[issuer]
            cached_at = cached_entry["cached_at"]
            cache_age = (datetime.now(timezone.utc) - cached_at).total_seconds()

            if cache_age < self.settings.dcr_metadata_cache_ttl:
                logger.debug(f"Using cached AS metadata for {issuer}")
                return cached_entry["metadata"]

        # Try RFC 8414 path first
        rfc8414_url = f"{issuer}/.well-known/oauth-authorization-server"

        try:
            client = await self._get_client()
            response = await client.get(rfc8414_url, timeout=self._get_timeout())
            if response.status_code == 200:
                metadata = response.json()

                # Validate issuer matches
                if metadata.get("issuer") != issuer:
                    raise DcrError(f"AS metadata issuer mismatch: expected {issuer}, got {metadata.get('issuer')}")

                # Cache the metadata
                _metadata_cache[issuer] = {"metadata": metadata, "cached_at": datetime.now(timezone.utc)}

                logger.info(f"Discovered AS metadata for {issuer} via RFC 8414")
                return metadata
        except httpx.HTTPError as e:
            logger.debug(f"RFC 8414 discovery failed for {issuer}: {e}, trying OIDC fallback")

        # Try OIDC discovery fallback
        oidc_url = f"{issuer}/.well-known/openid-configuration"

        try:
            client = await self._get_client()
            response = await client.get(oidc_url, timeout=self._get_timeout())
            if response.status_code == 200:
                metadata = response.json()

                # Validate issuer matches
                if metadata.get("issuer") != issuer:
                    raise DcrError(f"AS metadata issuer mismatch: expected {issuer}, got {metadata.get('issuer')}")

                # Cache the metadata
                _metadata_cache[issuer] = {"metadata": metadata, "cached_at": datetime.now(timezone.utc)}

                logger.info(f"Discovered AS metadata for {issuer} via OIDC discovery")
                return metadata

            raise DcrError(f"AS metadata not found for {issuer} (status: {response.status_code})")
        except httpx.HTTPError as e:
            raise DcrError(f"Failed to discover AS metadata for {issuer}: {e}")

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
        # Validate issuer if allowlist is configured
        if self.settings.dcr_allowed_issuers:
            if issuer not in self.settings.dcr_allowed_issuers:
                raise DcrError(f"Issuer {issuer} is not in allowed issuers list")

        # Discover AS metadata
        metadata = await self.discover_as_metadata(issuer)

        registration_endpoint = metadata.get("registration_endpoint")
        if not registration_endpoint:
            raise DcrError(f"AS {issuer} does not support Dynamic Client Registration (no registration_endpoint)")

        # Build registration request (RFC 7591)
        client_name = self.settings.dcr_client_name_template.replace("{gateway_name}", gateway_name)

        registration_request = {
            "client_name": client_name,
            "redirect_uris": [redirect_uri],
            "grant_types": ["authorization_code"],
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
            raise DcrError(f"Failed to register client with {issuer}: {e}")

        # Encrypt secrets
        encryption = get_encryption_service(self.settings.auth_encryption_secret)

        client_secret = registration_response.get("client_secret")
        client_secret_encrypted = encryption.encrypt_secret(client_secret) if client_secret else None

        registration_access_token = registration_response.get("registration_access_token")
        registration_access_token_encrypted = encryption.encrypt_secret(registration_access_token) if registration_access_token else None

        # Create database record
        registered_client = RegisteredOAuthClient(
            gateway_id=gateway_id,
            issuer=issuer,
            client_id=registration_response["client_id"],
            client_secret_encrypted=client_secret_encrypted,
            redirect_uris=orjson.dumps(registration_response.get("redirect_uris", [redirect_uri])).decode(),
            grant_types=orjson.dumps(registration_response.get("grant_types", ["authorization_code"])).decode(),
            response_types=orjson.dumps(registration_response.get("response_types", ["code"])).decode(),
            scope=registration_response.get("scope", " ".join(scopes)),
            token_endpoint_auth_method=registration_response.get("token_endpoint_auth_method", self.settings.dcr_token_endpoint_auth_method),
            registration_client_uri=registration_response.get("registration_client_uri"),
            registration_access_token_encrypted=registration_access_token_encrypted,
            created_at=datetime.now(timezone.utc),
            expires_at=None,  # TODO: Calculate from client_id_issued_at + client_secret_expires_at  # pylint: disable=fixme
            is_active=True,
        )

        db.add(registered_client)
        db.commit()
        db.refresh(registered_client)

        logger.info(f"Successfully registered client {registered_client.client_id} with {issuer} for gateway {gateway_id}")

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
        # Try to find existing client
        existing_client = (
            db.query(RegisteredOAuthClient)
            .filter(RegisteredOAuthClient.gateway_id == gateway_id, RegisteredOAuthClient.issuer == issuer, RegisteredOAuthClient.is_active.is_(True))  # pylint: disable=singleton-comparison
            .first()
        )

        if existing_client:
            logger.debug(f"Found existing registered client for gateway {gateway_id} and issuer {issuer}")
            return existing_client

        # No existing client, check if auto-register is enabled
        if not self.settings.dcr_auto_register_on_missing_credentials:
            raise DcrError(
                f"No registered client found for gateway {gateway_id} and issuer {issuer}. Auto-register is disabled. Set MCPGATEWAY_DCR_AUTO_REGISTER_ON_MISSING_CREDENTIALS=true to enable."
            )

        # Auto-register
        logger.info(f"No existing client found for gateway {gateway_id}, registering new client with {issuer}")
        return await self.register_client(gateway_id, gateway_name, issuer, redirect_uri, scopes, db)

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
        registration_access_token = encryption.decrypt_secret(client_record.registration_access_token_encrypted)

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
                    client_record.client_secret_encrypted = encryption.encrypt_secret(updated_response["client_secret"])

                db.commit()
                db.refresh(client_record)

                logger.info(f"Successfully updated client registration for {client_record.client_id}")
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
            True if deletion succeeded

        Raises:
            DcrError: If deletion fails (except 404)
        """
        if not client_record.registration_client_uri:
            logger.warning("Cannot delete client at AS: no registration_client_uri")
            return True  # Consider it deleted locally

        if not client_record.registration_access_token_encrypted:
            logger.warning("Cannot delete client at AS: no registration_access_token")
            return True  # Consider it deleted locally

        # Decrypt registration access token
        encryption = get_encryption_service(self.settings.auth_encryption_secret)
        registration_access_token = encryption.decrypt_secret(client_record.registration_access_token_encrypted)

        # Send delete request
        try:
            client = await self._get_client()
            headers = {"Authorization": f"Bearer {registration_access_token}"}
            response = await client.delete(client_record.registration_client_uri, headers=headers, timeout=self._get_timeout())
            if response.status_code in [204, 404]:  # 204 = deleted, 404 = already gone
                logger.info(f"Successfully deleted client registration for {client_record.client_id}")
                return True

            logger.warning(f"Unexpected status when deleting client: {response.status_code}")
            return True  # Consider it best-effort
        except httpx.HTTPError as e:
            logger.warning(f"Failed to delete client at AS: {e}")
            return True  # Best-effort, don't fail if AS is unreachable


class DcrError(Exception):
    """DCR-related errors."""
