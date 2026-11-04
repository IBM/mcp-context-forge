# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/cimd_service.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

OAuth Client ID Metadata Document (CIMD) Service.

The gateway acts as a public OAuth client identified by the HTTPS URL of a
metadata document it publishes. This module builds that document and decides
whether an authorization server supports CIMD, so callers can prefer it over
Dynamic Client Registration (RFC 7591, deprecated by MCP 2026-07-28).
"""

# Standard
import logging
from typing import Any, Dict, Optional

# First-Party
from mcpgateway.config import get_settings
from mcpgateway.services.dcr_service import DcrService

logger = logging.getLogger(__name__)

CIMD_METADATA_FLAG = "client_id_metadata_document_supported"


class CimdService:
    """Builds the gateway's Client ID Metadata Document and detects authorization server support."""

    def __init__(self, dcr_service: Optional[DcrService] = None) -> None:
        """Initialize the service with the current settings.

        Args:
            dcr_service: Service used for authorization server metadata discovery. Created on first use when omitted.
        """
        self.settings = get_settings()
        self._dcr_service = dcr_service

    @property
    def _base_url(self) -> str:
        """Return the public gateway base URL, derived only from server-side configuration.

        Returns:
            str: ``APP_DOMAIN`` plus ``APP_ROOT_PATH`` without a trailing slash.
        """
        root_path = str(self.settings.app_root_path or "").rstrip("/")
        return f"{str(self.settings.app_domain).rstrip('/')}{root_path}"

    @property
    def _effective_base_url(self) -> str:
        """Return the base URL used to construct redirect and JWKS URLs, honoring override."""
        if self.settings.cimd_client_metadata_url:
            from urllib.parse import urlparse, urlunparse

            parsed = urlparse(self.settings.cimd_client_metadata_url)
            path = parsed.path
            for suffix in ("/oauth/client-metadata.json", "/client-metadata.json"):
                if path.endswith(suffix):
                    path = path[: -len(suffix)]
                    break
            return urlunparse((parsed.scheme, parsed.netloc, path, "", "", "")).rstrip("/")
        return self._base_url

    @property
    def client_id(self) -> str:
        """Return the stable URL that identifies the gateway as an OAuth client.

        Returns:
            str: The document URL, which is also the OAuth ``client_id``.

        Examples:
            >>> CimdService().client_id.endswith("/oauth/client-metadata.json")
            True
        """
        if self.settings.cimd_client_metadata_url:
            return self.settings.cimd_client_metadata_url
        return f"{self._base_url}/oauth/client-metadata.json"

    @property
    def redirect_uri(self) -> str:
        """Return the callback URL published in the document.

        Returns:
            str: The gateway OAuth callback URL.
        """
        return f"{self._effective_base_url}/oauth/callback"

    @property
    def jwks_uri(self) -> str:
        """Return the JWKS URL published in the document.

        Returns:
            str: The gateway JWKS endpoint URL.
        """
        return f"{self._effective_base_url}/oauth/client-metadata/jwks.json"

    def build_document(self) -> Dict[str, Any]:
        """Build the Client ID Metadata Document.

        The document holds no secrets.

        Returns:
            Dict[str, Any]: The JSON document served at ``client_id``.

        Examples:
            >>> doc = CimdService().build_document()
            >>> doc["client_id"] == CimdService().client_id
            True
            >>> doc["token_endpoint_auth_method"]
            'none'
        """
        doc = {
            "client_id": self.client_id,
            "client_name": self.settings.cimd_client_name,
            "redirect_uris": [self.redirect_uri],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": self.settings.cimd_token_endpoint_auth_method,
        }
        if self.settings.cimd_token_endpoint_auth_method == "private_key_jwt":
            doc["jwks_uri"] = self.jwks_uri
        return doc

    async def is_applicable(self, issuer: str, redirect_uri: str) -> bool:
        """Return whether CIMD can register the gateway with ``issuer``.

        CIMD applies only when it is enabled, the document is served over HTTPS, the
        callback in use matches the published one, the issuer is permitted, and the
        authorization server advertises ``client_id_metadata_document_supported``.
        Any discovery failure returns ``False`` so the caller falls back to DCR.

        Args:
            issuer: Authorization server issuer URL.
            redirect_uri: Callback URL the authorization request will use.

        Returns:
            bool: ``True`` when CIMD should be used instead of Dynamic Client Registration.

        Examples:
            >>> import asyncio
            >>> from unittest.mock import AsyncMock, Mock
            >>> dcr = Mock(discover_as_metadata=AsyncMock(return_value={"client_id_metadata_document_supported": True}))
            >>> service = CimdService(dcr)
            >>> service.settings = Mock(
            ...     cimd_enabled=True,
            ...     app_domain="https://gw.example.com",
            ...     app_root_path="",
            ...     well_known_enabled=True,
            ...     dcr_allowed_issuers=[],
            ...     cimd_client_metadata_url=None,
            ...     cimd_token_endpoint_auth_method="none",
            ... )
            >>> asyncio.run(service.is_applicable("https://as.example.com", "https://gw.example.com/oauth/callback"))
            True
            >>> asyncio.run(service.is_applicable("https://as.example.com", "https://other.example.com/oauth/callback"))
            False
        """
        if not self.settings.cimd_enabled:
            return False
        if not self.client_id.startswith("https://"):
            logger.info("CIMD skipped for issuer %s: client_id %s is not HTTPS", issuer, self.client_id)
            return False
        if redirect_uri != self.redirect_uri:
            logger.info(
                "CIMD skipped for issuer %s: effective redirect_uri %s does not match published %s",
                issuer,
                redirect_uri,
                self.redirect_uri,
            )
            return False
        allowed = [i.rstrip("/") for i in self.settings.dcr_allowed_issuers]
        if allowed and issuer.rstrip("/") not in allowed:
            logger.info("CIMD skipped for issuer %s: issuer not in dcr_allowed_issuers allowlist", issuer)
            return False

        if self._dcr_service is None:
            self._dcr_service = DcrService()
        try:
            metadata = await self._dcr_service.discover_as_metadata(issuer)
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug("CIMD support check failed for %s: %s", issuer, type(exc).__name__)
            return False
        return metadata.get(CIMD_METADATA_FLAG) is True
