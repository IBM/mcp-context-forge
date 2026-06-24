# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/oidc_discovery.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Shared OIDC discovery and JWKS client caching for OAuth/OIDC token verification.

This module consolidates OIDC discovery and JWKS client caching logic previously
duplicated between mcpgateway/utils/verify_credentials.py (OAuth access token
verification for virtual server MCP endpoints) and mcpgateway/services/sso_service.py
(SSO id_token verification during interactive login).

The implementation uses the more robust discovery strategy from verify_credentials.py,
which probes both RFC 8414 (OAuth Authorization Server Metadata) and OIDC Discovery
endpoints, with configurable success/negative TTL caching.
"""

# Future
from __future__ import annotations

# Standard
import logging
from time import monotonic
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit

# Third-Party
import jwt

# Logger
logger = logging.getLogger(__name__)

# Module-level caches (shared across all callers)
_oidc_metadata_cache: dict[str, tuple[float, Optional[dict[str, Any]], float]] = {}
_jwks_client_cache: dict[str, jwt.PyJWKClient] = {}

# Default TTL values (can be overridden via discover_oidc_metadata parameters)
DEFAULT_METADATA_TTL = 300  # seconds — successful discovery
DEFAULT_NEGATIVE_TTL_PERMANENT = 30  # seconds — 404/malformed
DEFAULT_NEGATIVE_TTL_TRANSIENT = 5  # seconds — timeouts / 5xx / network


def _build_metadata_urls(issuer: str) -> list[str]:
    """Return the well-known metadata URLs to probe for ``issuer``.

    Supports both RFC 8414 (OAuth Authorization Server Metadata) and OpenID
    Connect Discovery 1.0. The two specs differ in where the well-known
    segment is inserted relative to the issuer's path component:

    * **RFC 8414**: the well-known segment is inserted between the host and
      any path component — ``https://example.com/issuer1`` →
      ``https://example.com/.well-known/oauth-authorization-server/issuer1``.
    * **OIDC Discovery 1.0**: the well-known segment is *appended* to the
      issuer path — ``https://example.com/issuer1`` →
      ``https://example.com/issuer1/.well-known/openid-configuration``.

    Both are tried in order; RFC 8414 comes first because ``authorization_servers``
    in RFC 9728 is a generic OAuth issuer list and may point at servers that
    do not publish an OIDC document at all.

    For issuers with no path component, the two OIDC and OAuth URLs collapse
    to ``{host}/.well-known/<segment>``.

    Args:
        issuer: The authorization server issuer URL.

    Returns:
        A list of candidate metadata URLs, in the order they should be tried.
    """
    parts = urlsplit(issuer.rstrip("/"))
    issuer_path = parts.path  # "" or "/..."

    oauth_path = "/.well-known/oauth-authorization-server"
    if issuer_path:
        oauth_path = f"{oauth_path}{issuer_path}"
    oauth_url = urlunsplit((parts.scheme, parts.netloc, oauth_path, "", ""))

    oidc_path = f"{issuer_path}/.well-known/openid-configuration"
    oidc_url = urlunsplit((parts.scheme, parts.netloc, oidc_path, "", ""))

    # When issuer has no path, both URLs differ only by the well-known
    # segment; still probe both so a server that only publishes one form is
    # discovered. ``dict.fromkeys`` preserves order while de-duplicating.
    return list(dict.fromkeys([oauth_url, oidc_url]))


async def discover_oidc_metadata(
    issuer: str,
    *,
    success_ttl: float = DEFAULT_METADATA_TTL,
    negative_ttl_permanent: float = DEFAULT_NEGATIVE_TTL_PERMANENT,
    negative_ttl_transient: float = DEFAULT_NEGATIVE_TTL_TRANSIENT,
) -> Optional[dict[str, Any]]:
    """Fetch and cache authorization-server metadata via RFC 8414 / OIDC discovery.

    Tries both the RFC 8414 OAuth authorization server metadata endpoint
    (``/.well-known/oauth-authorization-server``) and the OIDC discovery
    endpoint (``/.well-known/openid-configuration``). Either one producing a
    valid JSON metadata document is considered a success. Only when *both*
    probes fail is the issuer negatively cached, so a non-OIDC OAuth server
    is not permanently blocked by a single failing probe.

    Successful responses are cached for ``success_ttl`` seconds.
    Failures (no probe returned metadata) are cached as ``None`` for
    ``negative_ttl_*`` seconds so a misbehaving IdP cannot amplify request
    volume on every inbound token.

    Args:
        issuer: Authorization server issuer URL.
        success_ttl: Cache TTL in seconds for successful discovery (default: 300).
        negative_ttl_permanent: Cache TTL for permanent failures like 404/malformed JSON (default: 30).
        negative_ttl_transient: Cache TTL for transient failures like 5xx/timeouts (default: 5).

    Returns:
        Provider metadata dict, or None on failure.
    """
    normalized = issuer.rstrip("/")
    cached = _oidc_metadata_cache.get(normalized)
    if cached is not None:
        cached_at, metadata, ttl = cached
        if monotonic() - cached_at < ttl:
            return metadata
        _oidc_metadata_cache.pop(normalized, None)

    # First-Party
    from mcpgateway.services.http_client_service import get_http_client  # pylint: disable=import-outside-toplevel

    client = await get_http_client()
    probe_errors: list[str] = []
    saw_transient = False
    for url in _build_metadata_urls(normalized):
        try:
            resp = await client.get(url, timeout=10)
        except Exception as exc:
            # Network errors (DNS, connection refused, TLS, timeout) are
            # transient — the IdP may recover within seconds.
            probe_errors.append(f"{url}: {type(exc).__name__}: {exc}")
            logger.debug("OIDC metadata probe errored for %s: %s", url, exc)
            saw_transient = True
            continue

        if resp.status_code != 200:
            # 5xx is transient (server-side outage); 404 / other 4xx is
            # permanent (URL is simply wrong for this issuer).
            probe_errors.append(f"{url}: HTTP {resp.status_code}")
            logger.debug("OIDC metadata probe returned %s for %s", resp.status_code, url)
            if resp.status_code >= 500 or resp.status_code in {408, 429}:
                saw_transient = True
            continue

        try:
            metadata = resp.json()
        except Exception as exc:
            # Malformed JSON is permanent — fix the IdP config.
            probe_errors.append(f"{url}: invalid JSON: {exc}")
            logger.debug("OIDC metadata probe returned invalid JSON for %s: %s", url, exc)
            continue

        if not isinstance(metadata, dict):
            probe_errors.append(f"{url}: metadata is not a JSON object")
            continue

        # RFC 8414 §3.3: verify the metadata ``issuer`` matches what we
        # expected. A compromised CDN/proxy could serve metadata for a
        # different issuer; caching it would let an attacker control the
        # jwks_uri for a legitimate issuer.
        metadata_issuer = metadata.get("issuer", "")
        if isinstance(metadata_issuer, str) and metadata_issuer.rstrip("/") != normalized:
            probe_errors.append(f"{url}: metadata issuer {metadata_issuer!r} does not match expected {normalized!r}")
            logger.debug("Metadata issuer mismatch at %s: got %s, expected %s", url, metadata_issuer, normalized)
            continue

        _oidc_metadata_cache[normalized] = (monotonic(), metadata, success_ttl)
        return metadata

    # All probes failed. Choose TTL based on whether any probe looked
    # transient: if yes, cache for the short transient window so a brief
    # IdP blip does not blackhole all virtual servers sharing this issuer
    # for the permanent window.
    ttl_on_failure = negative_ttl_transient if saw_transient else negative_ttl_permanent
    logger.warning(
        "Authorization server metadata discovery failed for %s (ttl=%ss, probes=%s)",
        normalized,
        ttl_on_failure,
        probe_errors,
    )
    _oidc_metadata_cache[normalized] = (monotonic(), None, ttl_on_failure)
    return None


def get_jwks_client(jwks_uri: str) -> jwt.PyJWKClient:
    """Get or create a cached PyJWKClient instance for the given JWKS URI.

    The client is cached indefinitely (until process restart) to avoid
    re-fetching JWKS on every token verification. PyJWKClient handles its
    own internal caching and refresh logic.

    Args:
        jwks_uri: JWKS endpoint URL.

    Returns:
        Cached or newly created PyJWKClient instance.
    """
    if jwks_uri not in _jwks_client_cache:
        _jwks_client_cache[jwks_uri] = jwt.PyJWKClient(jwks_uri)
    return _jwks_client_cache[jwks_uri]


def clear_caches() -> None:
    """Clear all OIDC metadata and JWKS client caches.

    Primarily used for testing to ensure clean state between test cases.
    """
    _oidc_metadata_cache.clear()
    _jwks_client_cache.clear()
