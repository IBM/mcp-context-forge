# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/oidc_tls.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Single TLS trust policy for outbound SSO/OIDC calls.

Discovery, token exchange, userinfo and JWKS retrieval all resolve TLS trust
here. A provider with a ``ca_certificate`` trusts that CA in addition to the
system store. Any other provider follows the global ``SKIP_SSL_VERIFY`` setting.
"""

# Standard
from contextlib import asynccontextmanager
import hashlib
import logging
import ssl
from typing import Any, AsyncIterator, Optional

# Third-Party
import httpx
import jwt

# First-Party
from mcpgateway.services.http_client_service import get_default_verify, get_isolated_http_client
from mcpgateway.utils.log_sanitizer import sanitize_for_log
from mcpgateway.utils.ssl_context_cache import get_cached_ssl_context

logger = logging.getLogger(__name__)


class CaCertificateError(ValueError):
    """Raised when a provider ``ca_certificate`` is not a loadable PEM CA bundle."""


def ca_fingerprint(ca_certificate: str) -> str:
    """Return the SHA-256 hex digest of a CA bundle, safe to log and to use in cache keys.

    Args:
        ca_certificate: PEM CA bundle.

    Returns:
        Hex SHA-256 digest.

    Examples:
        >>> len(ca_fingerprint("A"))
        64
    """
    return hashlib.sha256(ca_certificate.encode()).hexdigest()


def evict_ca_entries(ca_certificate: Optional[str], *caches: dict) -> None:
    """Drop the entries keyed on a CA bundle that is no longer in use.

    Args:
        ca_certificate: The replaced or cleared PEM CA bundle.
        *caches: Caches keyed through ``tls_cache_key``.

    Examples:
        >>> cache = {"a#ca:" + ca_fingerprint("X"): 1, "a": 2}
        >>> evict_ca_entries("X", cache)
        >>> cache
        {'a': 2}
    """
    if not ca_certificate:
        return
    suffix = f"#ca:{ca_fingerprint(ca_certificate)}"
    for cache in caches:
        for key in [k for k in cache if k.endswith(suffix)]:
            cache.pop(key, None)


def validate_ca_certificate(ca_certificate: Optional[str]) -> Optional[str]:
    """Normalize and validate a provider CA bundle.

    Args:
        ca_certificate: PEM text, or an empty value to clear the setting.

    Returns:
        The stripped PEM text, or None when the value is empty.

    Raises:
        CaCertificateError: If the text is not a loadable PEM CA bundle.

    Examples:
        >>> validate_ca_certificate("  ") is None
        True
        >>> validate_ca_certificate("not a certificate")
        Traceback (most recent call last):
            ...
        mcpgateway.services.oidc_tls.CaCertificateError: ca_certificate is not a valid PEM CA bundle
    """
    if not ca_certificate or not ca_certificate.strip():
        return None
    pem = ca_certificate.strip()
    try:
        get_cached_ssl_context(pem)
    except (ssl.SSLError, ValueError) as exc:
        raise CaCertificateError("ca_certificate is not a valid PEM CA bundle") from exc
    return pem


def provider_ssl_context(ca_certificate: Optional[str]) -> Optional[ssl.SSLContext]:
    """Return the SSL context for a provider CA bundle.

    Args:
        ca_certificate: PEM CA bundle, or None.

    Returns:
        A cached context trusting the bundle plus system CAs, or None when no bundle is set.

    Examples:
        >>> provider_ssl_context(None) is None
        True
    """
    return get_cached_ssl_context(ca_certificate) if ca_certificate else None


def tls_cache_key(base: str, ca_certificate: Optional[str]) -> str:
    """Return a cache key that never shares entries between different trust anchors.

    Args:
        base: Issuer or JWKS URI.
        ca_certificate: PEM CA bundle, or None.

    Returns:
        ``base`` unchanged without a CA, otherwise ``base`` plus a hash of the CA.

    Examples:
        >>> tls_cache_key("https://idp/jwks", None)
        'https://idp/jwks'
        >>> tls_cache_key("https://idp/jwks", "A") != tls_cache_key("https://idp/jwks", "B")
        True
    """
    if not ca_certificate:
        return base
    return f"{base}#ca:{ca_fingerprint(ca_certificate)}"


@asynccontextmanager
async def provider_http_client(ca_certificate: Optional[str]) -> AsyncIterator[httpx.AsyncClient]:
    """Yield an HTTP client that applies the provider TLS policy.

    Args:
        ca_certificate: PEM CA bundle, or None.

    Yields:
        The shared client without a CA, otherwise an isolated client pinned to the provider CA.
        Neither client follows redirects.
    """
    ctx = provider_ssl_context(ca_certificate)
    if ctx is None:
        # First-Party
        from mcpgateway.services.http_client_service import get_http_client  # pylint: disable=import-outside-toplevel

        yield await get_http_client()
        return
    # shortcut: one client, pool and handshake per call, upgrade to a size-bounded client cache per CA hash if login latency matters
    async with get_isolated_http_client(verify=ctx, follow_redirects=False) as client:
        yield client


class _NoRedirectPyJWKClient(jwt.PyJWKClient):
    """PyJWKClient that fetches JWKS via httpx with follow_redirects=False.

    PyJWT's default fetch_data() uses urllib.request.urlopen which follows HTTP
    redirects transparently, bypassing the same-origin check on jwks_uri.
    Overriding with httpx (follow_redirects=False) closes the SSRF redirect bypass.
    TLS trust is the ``ssl_context`` passed at construction (the provider CA),
    otherwise get_default_verify(), so SKIP_SSL_VERIFY applies.
    JWKS holds the signing keys that verify tokens, so a fetch with TLS
    verification off logs a warning that names the jwks_uri.
    """

    def fetch_data(self) -> Any:
        """Fetch JWKS data without following redirects.

        Returns:
            The decoded JWKS document.

        Raises:
            PyJWKClientConnectionError: If the fetch fails.
        """
        verify = self.ssl_context if self.ssl_context is not None else get_default_verify()
        if not verify:
            logger.warning("Fetching JWKS from %s with TLS verification disabled (SKIP_SSL_VERIFY=true). Token signing keys are not authenticated.", sanitize_for_log(self.uri))
        try:
            with httpx.Client(follow_redirects=False, timeout=self.timeout, verify=verify) as _client:
                resp = _client.get(self.uri, headers=self.headers)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPError as exc:
            raise jwt.exceptions.PyJWKClientConnectionError(f'Fail to fetch data from the url, err: "{exc}"') from exc
