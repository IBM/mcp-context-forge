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
from functools import lru_cache
import logging
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse, urlunparse

# Third-Party
from cryptography.hazmat.primitives import serialization

# First-Party
from mcpgateway.config import get_settings
from mcpgateway.services.dcr_service import DcrService

logger = logging.getLogger(__name__)

CIMD_METADATA_FLAG = "client_id_metadata_document_supported"
CIMD_DOCUMENT_PATH = "/oauth/client-metadata.json"


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


def _file_signature(path_str: str) -> Optional[tuple]:
    """Return a change signature (path, mtime, size) for a key file, or ``None`` when unset or missing.

    Args:
        path_str: Configured key file path, possibly empty.

    Returns:
        Optional[tuple]: Signature that changes when the file is replaced or edited.
    """
    if not path_str:
        return None
    path = Path(path_str)
    if not path.is_absolute():
        path = Path.cwd() / path
    try:
        stat = path.stat()
    except OSError:
        return None
    return (str(path), stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=4)
def _load_validated_private_key(cimd_path: str, jwt_path: str, signature: tuple) -> str:
    """Read and validate the CIMD private key. Cached per file signature so rotation takes effect.

    Args:
        cimd_path: Configured ``CIMD_PRIVATE_KEY_PATH``.
        jwt_path: Configured ``JWT_PRIVATE_KEY_PATH``, possibly empty.
        signature: File signatures of both paths, used only as the cache key.

    Returns:
        str: PEM-encoded private key.

    Raises:
        CimdKeyError: If the key is unreadable, not a private key, or identical to the JWT signing key.
    """
    del signature  # cache key only
    pem = _read_key_file(cimd_path)
    try:
        serialization.load_pem_private_key(pem.encode("utf-8"), password=None)
    except Exception as exc:
        raise CimdKeyError("CIMD_PRIVATE_KEY_PATH does not contain a valid unencrypted PEM private key") from exc

    if jwt_path:
        try:
            jwt_pem = _read_key_file(jwt_path)
        except CimdKeyError:
            jwt_pem = ""
        if jwt_pem.strip() == pem.strip():
            raise CimdKeyError("CIMD_PRIVATE_KEY_PATH must not reference the gateway JWT signing key")
    return pem


def load_cimd_private_key() -> str:
    """Load the dedicated CIMD private key.

    The key must be separate from the gateway JWT signing key. This function never
    falls back to ``JWT_PRIVATE_KEY_PATH`` or ``JWT_SECRET_KEY``. The result is cached
    until either key file changes.

    Returns:
        str: PEM-encoded private key.

    Raises:
        CimdKeyError: If ``CIMD_PRIVATE_KEY_PATH`` is unset, unreadable, not a private key,
            or identical to the JWT signing key.
    """
    settings = get_settings()
    if not settings.cimd_private_key_path:
        raise CimdKeyError("CIMD_PRIVATE_KEY_PATH is not configured")
    signature = (_file_signature(settings.cimd_private_key_path), _file_signature(settings.jwt_private_key_path))
    return _load_validated_private_key(settings.cimd_private_key_path, settings.jwt_private_key_path, signature)


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

    def __init__(self, dcr_service: Optional[DcrService] = None, root_path: Optional[str] = None) -> None:
        """Initialize the service with the current settings.

        Args:
            dcr_service: Service used for authorization server metadata discovery. Created on first use when omitted.
            root_path: Reverse-proxy root path resolved from the request scope. Falls back to ``APP_ROOT_PATH`` when omitted.
        """
        self.settings = get_settings()
        self._dcr_service = dcr_service
        self._root_path = root_path
        self.skip_reason: Optional[str] = None
        self.as_metadata: Optional[Dict[str, Any]] = None

    @property
    def _base_url(self) -> str:
        """Return the public gateway base URL, derived only from server-side configuration.

        Returns:
            str: ``APP_DOMAIN`` plus the root path without a trailing slash.
        """
        root_path = str(self._root_path if self._root_path is not None else self.settings.app_root_path or "").rstrip("/")
        return f"{str(self.settings.app_domain).rstrip('/')}{root_path}"

    @property
    def _effective_base_url(self) -> str:
        """Return the base URL used to construct redirect and JWKS URLs, honoring override.

        The override must end with ``/oauth/client-metadata.json`` (enforced by ``Settings``),
        so the base is everything before that path.
        """
        if self.settings.cimd_client_metadata_url:
            parsed = urlparse(self.settings.cimd_client_metadata_url)
            path = parsed.path.removesuffix(CIMD_DOCUMENT_PATH)
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
        return f"{self._base_url}{CIMD_DOCUMENT_PATH}"

    def owns_client_id(self, client_id: Any) -> bool:
        """Return whether ``client_id`` is a metadata document URL served by this gateway.

        A request-derived root path can differ from the configured one, so the match is on
        origin and document path rather than on the full URL.

        Args:
            client_id: Stored OAuth ``client_id``.

        Returns:
            bool: ``True`` when ``client_id`` is this gateway's document URL.
        """
        if not isinstance(client_id, str):
            return False
        if client_id == self.client_id:
            return True
        ours, theirs = urlparse(self.client_id), urlparse(client_id)
        return (ours.scheme, ours.netloc) == (theirs.scheme, theirs.netloc) and theirs.path.endswith(CIMD_DOCUMENT_PATH) and not (theirs.query or theirs.fragment)

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
            logger.warning("CIMD skipped for issuer %s: client_id %s is not HTTPS", issuer, self.client_id)
            return "client_id_not_https"
        if redirect_uri != self.redirect_uri:
            logger.warning(
                "CIMD skipped for issuer %s: effective redirect_uri %s does not match published %s. Set APP_ROOT_PATH or CIMD_CLIENT_METADATA_URL to match the public path.",
                issuer,
                redirect_uri,
                self.redirect_uri,
            )
            return "redirect_uri_mismatch"
        allowed = [i.rstrip("/") for i in self.settings.dcr_allowed_issuers]
        if allowed and issuer.rstrip("/") not in allowed:
            logger.warning("CIMD skipped for issuer %s: issuer not in dcr_allowed_issuers allowlist", issuer)
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
        The reason for a ``False`` result is left in ``skip_reason``. The fetched
        authorization server metadata is left in ``as_metadata`` so callers need no second fetch.

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
        self.skip_reason = self.failed_guard(issuer, redirect_uri)
        if self.skip_reason:
            return False

        if self._dcr_service is None:
            self._dcr_service = DcrService()
        try:
            metadata = await self._dcr_service.discover_as_metadata(issuer)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("CIMD support check failed for %s: authorization server metadata discovery raised %s", issuer, type(exc).__name__)
            self.skip_reason = "discovery_failed"
            return False
        self.as_metadata = metadata
        if not self.supports_cimd(metadata):
            self.skip_reason = "not_advertised"
            return False
        return True
