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
from pathlib import Path
from typing import Any, Dict, Optional

# Third-Party
from cryptography.hazmat.primitives import serialization

# First-Party
from mcpgateway.config import get_settings
from mcpgateway.services.dcr_service import DcrService

logger = logging.getLogger(__name__)

CIMD_METADATA_FLAG = "client_id_metadata_document_supported"


class CimdKeyError(Exception):
    """Raised when the dedicated CIMD signing key is missing or unsafe to use."""


def _read_key_file(path_str: str) -> str:
    """Read a PEM key file, resolving relative paths against the working directory.

    Args:
        path_str: Configured key file path.

    Returns:
        str: File contents.

    Raises:
        CimdKeyError: If the file cannot be read.
    """
    path = Path(path_str)
    if not path.is_absolute():
        path = Path.cwd() / path
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CimdKeyError(f"cannot read key file {path}") from exc


def load_cimd_private_key() -> str:
    """Load the dedicated CIMD private key.

    The key must be separate from the gateway JWT signing key. This function never
    falls back to ``JWT_PRIVATE_KEY_PATH`` or ``JWT_SECRET_KEY``.

    Returns:
        str: PEM-encoded private key.

    Raises:
        CimdKeyError: If ``CIMD_PRIVATE_KEY_PATH`` is unset, unreadable, not a private key,
            or identical to the JWT signing key.
    """
    settings = get_settings()
    if not settings.cimd_private_key_path:
        raise CimdKeyError("CIMD_PRIVATE_KEY_PATH is not configured")
    pem = _read_key_file(settings.cimd_private_key_path)
    try:
        serialization.load_pem_private_key(pem.encode("utf-8"), password=None)
    except Exception as exc:
        raise CimdKeyError("CIMD_PRIVATE_KEY_PATH does not contain a valid unencrypted PEM private key") from exc

    if settings.jwt_private_key_path:
        try:
            jwt_pem = _read_key_file(settings.jwt_private_key_path)
        except CimdKeyError:
            jwt_pem = ""
        if jwt_pem.strip() == pem.strip():
            raise CimdKeyError("CIMD_PRIVATE_KEY_PATH must not reference the gateway JWT signing key")
    return pem


def load_cimd_public_key() -> str:
    """Derive the public key published in the CIMD JWKS from the dedicated private key.

    Returns:
        str: PEM-encoded public key.

    Raises:
        CimdKeyError: If the CIMD private key cannot be loaded.
    """
    private_key = serialization.load_pem_private_key(load_cimd_private_key().encode("utf-8"), password=None)
    return private_key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode("utf-8")


def load_cimd_previous_public_key() -> Optional[str]:
    """Return the previous CIMD public key for rotation, or ``None`` when unset or unreadable.

    Returns:
        Optional[str]: PEM-encoded public key.
    """
    path = get_settings().cimd_previous_public_key_path
    if not path:
        return None
    try:
        return _read_key_file(path)
    except CimdKeyError:
        return None


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

    def failed_guard(self, issuer: str, redirect_uri: str) -> Optional[str]:
        """Return the name of the first failed CIMD guard, or ``None`` when all pass.

        The guards are local checks that need no network call: CIMD enabled, HTTPS
        ``client_id``, matching redirect URI, and the ``DCR_ALLOWED_ISSUERS`` allowlist.
        They apply to automatic selection and to a forced ``registration_method``.

        Args:
            issuer: Authorization server issuer URL.
            redirect_uri: Callback URL the authorization request will use.

        Returns:
            Optional[str]: ``cimd_disabled``, ``client_id_not_https``, ``redirect_uri_mismatch``,
                ``issuer_not_allowed``, or ``None``.

        Examples:
            >>> from unittest.mock import Mock
            >>> service = CimdService()
            >>> service.settings = Mock(
            ...     cimd_enabled=True,
            ...     app_domain="https://gw.example.com",
            ...     app_root_path="",
            ...     dcr_allowed_issuers=["https://other.example.com"],
            ...     cimd_client_metadata_url=None,
            ... )
            >>> service.failed_guard("https://as.example.com", "https://gw.example.com/oauth/callback")
            'issuer_not_allowed'
            >>> service.failed_guard("https://other.example.com", "https://evil.example.net/oauth/callback")
            'redirect_uri_mismatch'
        """
        if not self.settings.cimd_enabled:
            return "cimd_disabled"
        if not self.client_id.startswith("https://"):
            logger.info("CIMD skipped for issuer %s: client_id %s is not HTTPS", issuer, self.client_id)
            return "client_id_not_https"
        if redirect_uri != self.redirect_uri:
            logger.info(
                "CIMD skipped for issuer %s: effective redirect_uri %s does not match published %s",
                issuer,
                redirect_uri,
                self.redirect_uri,
            )
            return "redirect_uri_mismatch"
        allowed = [i.rstrip("/") for i in self.settings.dcr_allowed_issuers]
        if allowed and issuer.rstrip("/") not in allowed:
            logger.info("CIMD skipped for issuer %s: issuer not in dcr_allowed_issuers allowlist", issuer)
            return "issuer_not_allowed"
        return None

    @staticmethod
    def supports_cimd(metadata: Optional[Dict[str, Any]]) -> bool:
        """Return whether authorization server metadata advertises CIMD support.

        Args:
            metadata: Authorization server metadata, or ``None`` when discovery failed.

        Returns:
            bool: ``True`` only when ``client_id_metadata_document_supported`` is the boolean ``True``.

        Examples:
            >>> CimdService.supports_cimd({"client_id_metadata_document_supported": True})
            True
            >>> CimdService.supports_cimd({"client_id_metadata_document_supported": "true"})
            False
            >>> CimdService.supports_cimd(None)
            False
        """
        return bool(metadata) and metadata.get(CIMD_METADATA_FLAG) is True

    async def is_applicable(self, issuer: str, redirect_uri: str) -> bool:
        """Return whether CIMD can register the gateway with ``issuer``.

        CIMD applies only when every guard in ``failed_guard`` passes and the
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
        if self.failed_guard(issuer, redirect_uri):
            return False

        if self._dcr_service is None:
            self._dcr_service = DcrService()
        try:
            metadata = await self._dcr_service.discover_as_metadata(issuer)
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug("CIMD support check failed for %s: %s", issuer, type(exc).__name__)
            return False
        return self.supports_cimd(metadata)
