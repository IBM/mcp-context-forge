# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/entra_graph_client.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

App-only Microsoft Graph client for Entra group-overage resolution (issue #5977).

Beyond the Entra group-claim limit a token carries overage markers instead
of a groups array. Under ``jwt_trust_overage_policy = "graph_lookup"`` this
client resolves the user's security groups with an app-only
client-credentials token. The token is acquired from the SSO provider
record's token endpoint with the stored encrypted client secret, decrypted
at call time. The inbound bearer token is never used: it is audience-bound
to ContextForge and Graph would reject it. The delegated ``/me`` flow of
the SSO browser path is not used either.

Group resolution results are cached in Redis keyed by the user's ``oid``
through the shared ``AuthCache._get_redis_key`` helper (key type ``graph``),
so keys carry the auth-cache version segment. The TTL is bounded by the
presenting token's ``exp``. A Redis read error degrades to a cache miss and
a live Graph lookup; a Redis write error is logged and skipped.
"""

# Standard
import logging
import time
from typing import Any, List, Optional

# Third-Party
import orjson

# First-Party
from mcpgateway.cache.auth_cache import AuthCache
from mcpgateway.config import settings

logger = logging.getLogger(__name__)

#: Microsoft Graph v1.0 base URL.
GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"

#: App-only scope for the client-credentials token request.
GRAPH_SCOPE = "https://graph.microsoft.com/.default"

#: Cache TTL fallback in seconds when the presenting token carries no exp.
DEFAULT_CACHE_TTL = 300


class EntraGraphError(Exception):
    """Raised when app-only Graph group resolution fails."""


class EntraGraphClient:
    """App-only Microsoft Graph client for trust-mode overage resolution.

    Uses the OAuth2 client-credentials grant with the SSO provider record's
    stored encrypted client secret. Results are cached per ``oid`` in Redis
    when Redis is available.

    Attributes:
        _auth_cache: Shared auth cache used for the Redis handle and the
            versioned key helper.
    """

    def __init__(self, auth_cache: Optional[AuthCache] = None) -> None:
        """Initialize the client.

        Args:
            auth_cache: Optional shared AuthCache override (tests). Defaults
                to a new AuthCache, which supplies the Redis client and the
                versioned key helper.
        """
        self._auth_cache = auth_cache or AuthCache()

    async def get_member_groups(self, provider: Any, oid: str, token_exp: Optional[int] = None) -> List[str]:
        """Resolve the security-group object IDs for a user's ``oid``.

        Reads the oid-keyed Redis cache first. A cache hit returns the stored
        group list. A Redis read error is a cache miss and falls through to a
        live Graph call. A successful live call is written back with a TTL
        bounded by the presenting token's ``exp``.

        Args:
            provider: SSO provider record supplying the token endpoint and
                the encrypted client credentials.
            oid: Entra object ID of the user (``oid`` claim).
            token_exp: Expiry (epoch seconds) of the presenting token. Bounds
                the cache TTL.

        Returns:
            List of security-group object IDs, de-duplicated and bounded by
            ``sso_entra_graph_api_max_groups``.

        Raises:
            EntraGraphError: When token acquisition or the Graph call fails.
        """
        redis = await self._auth_cache._get_redis_client()
        cache_key = self._auth_cache._get_redis_key("graph", oid)

        if redis is not None:
            try:
                cached = await redis.get(cache_key)
            except Exception as exc:  # noqa: BLE001 — cache read errors degrade to a live Graph lookup
                logger.warning("Graph group cache read failed for oid %s: %s; falling back to live Graph lookup", oid, exc)
                cached = None
            if cached:
                try:
                    groups = orjson.loads(cached)
                except ValueError:
                    logger.warning("Graph group cache entry for oid %s is not valid JSON; falling back to live Graph lookup", oid)
                else:
                    if isinstance(groups, list):
                        return [str(group) for group in groups]
                    logger.warning("Graph group cache entry for oid %s is not a list; falling back to live Graph lookup", oid)

        groups = await self._fetch_member_groups(provider, oid)

        if redis is not None:
            try:
                await redis.setex(cache_key, self._cache_ttl(token_exp), orjson.dumps(groups))
            except Exception as exc:  # noqa: BLE001 — a cache write failure never fails the request
                logger.warning("Graph group cache write failed for oid %s: %s", oid, exc)

        return groups

    @staticmethod
    def _cache_ttl(token_exp: Optional[int]) -> int:
        """Compute the cache TTL, bounded by the presenting token's exp.

        Args:
            token_exp: Expiry (epoch seconds) of the presenting token.

        Returns:
            TTL in seconds. With an ``exp`` the TTL never exceeds the token's
            remaining lifetime; without one the default applies.
        """
        if token_exp:
            return max(1, int(token_exp - time.time()))
        return DEFAULT_CACHE_TTL

    async def _acquire_app_token(self, provider: Any) -> str:
        """Acquire an app-only Graph token via the client-credentials grant.

        Decrypts the SSO provider record's stored client secret at call time
        and posts the grant to the provider's token endpoint. The inbound
        bearer token is never used.

        Args:
            provider: SSO provider record with ``token_url``, ``client_id``,
                and ``client_secret_encrypted``.

        Returns:
            The app-only access token.

        Raises:
            EntraGraphError: When the secret is missing or undecryptable, or
                the token endpoint fails.
        """
        encrypted_secret = getattr(provider, "client_secret_encrypted", None)
        provider_id = getattr(provider, "id", "unknown")
        if not encrypted_secret:
            raise EntraGraphError(f"SSO provider {provider_id!r} has no stored client secret; cannot acquire an app-only Graph token.")

        # First-Party
        from mcpgateway.services.encryption_service import get_encryption_service  # pylint: disable=import-outside-toplevel

        client_secret = await get_encryption_service(settings.auth_encryption_secret).decrypt_secret_async(encrypted_secret)
        if not client_secret:
            raise EntraGraphError(f"Failed to decrypt the stored client secret of SSO provider {provider_id!r}.")

        # First-Party
        from mcpgateway.services.http_client_service import get_http_client  # pylint: disable=import-outside-toplevel

        client = await get_http_client()
        try:
            response = await client.post(
                provider.token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": provider.client_id,
                    "client_secret": client_secret,
                    "scope": GRAPH_SCOPE,
                },
                headers={"Accept": "application/json"},
                timeout=settings.sso_entra_graph_api_timeout,
            )
        except Exception as exc:
            raise EntraGraphError(f"App-only token request for SSO provider {provider_id!r} failed: {exc}") from exc
        if response.status_code != 200:
            raise EntraGraphError(f"App-only token request for SSO provider {provider_id!r} returned HTTP {response.status_code}.")

        access_token = response.json().get("access_token")
        if not access_token:
            raise EntraGraphError(f"App-only token response for SSO provider {provider_id!r} carried no access_token.")
        return access_token

    async def _fetch_member_groups(self, provider: Any, oid: str) -> List[str]:
        """Call Graph getMemberObjects for the user's ``oid``.

        Posts ``{"securityEnabledOnly": true}`` to
        ``/users/{oid}/getMemberObjects`` with the app-only token. Requests
        are bounded by ``sso_entra_graph_api_timeout`` and results by
        ``sso_entra_graph_api_max_groups``.

        Args:
            provider: SSO provider record (credential source).
            oid: Entra object ID of the user.

        Returns:
            De-duplicated list of security-group object IDs.

        Raises:
            EntraGraphError: When the Graph call fails or the payload shape
                is unexpected (fail-closed).
        """
        app_token = await self._acquire_app_token(provider)

        # First-Party
        from mcpgateway.services.http_client_service import get_http_client  # pylint: disable=import-outside-toplevel

        client = await get_http_client()
        try:
            response = await client.post(
                f"{GRAPH_BASE_URL}/users/{oid}/getMemberObjects",
                headers={"Authorization": f"Bearer {app_token}"},
                json={"securityEnabledOnly": True},
                timeout=settings.sso_entra_graph_api_timeout,
            )
        except Exception as exc:
            raise EntraGraphError(f"Graph getMemberObjects request for oid {oid} failed: {exc}") from exc
        if response.status_code != 200:
            raise EntraGraphError(f"Graph getMemberObjects for oid {oid} returned HTTP {response.status_code}.")

        group_values = response.json().get("value", [])
        if not isinstance(group_values, list):
            raise EntraGraphError(f"Graph getMemberObjects for oid {oid} returned an unexpected payload: 'value' is not a list.")

        deduped_groups: List[str] = []
        seen_groups: set = set()
        for group_id in group_values:
            if not isinstance(group_id, str):
                continue
            normalized_group_id = group_id.strip()
            if not normalized_group_id or normalized_group_id in seen_groups:
                continue
            seen_groups.add(normalized_group_id)
            deduped_groups.append(normalized_group_id)

        max_groups = settings.sso_entra_graph_api_max_groups
        if max_groups > 0 and len(deduped_groups) > max_groups:
            logger.warning(
                "Graph returned %d groups for oid %s; applying configured cap (%d)",
                len(deduped_groups),
                oid,
                max_groups,
            )
            deduped_groups = deduped_groups[:max_groups]

        logger.info("Resolved %d groups from Graph for oid %s", len(deduped_groups), oid)
        return deduped_groups
