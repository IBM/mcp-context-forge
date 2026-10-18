# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/token_exchange_actor.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

RFC 8693 actor token resolution for token-exchange delegation.

Every exchange path (tool call, resource read, manual refresh) resolves the
actor token here, so the delegation rules live in one place. The actor is the
gateway's own OAuth client. ``OAuthManager.token_exchange()`` independently
refuses a delegation config without an actor token, so a call site that skips
this resolver fails closed instead of impersonating.

SECURITY: an actor token is a bearer credential. Never log its value.
"""

# Standard
import logging
from typing import Any, Dict, Optional, Tuple

# First-Party
from mcpgateway.common.oauth import ACTOR_TOKEN_SOURCE_CLIENT_ASSERTION, ACTOR_TOKEN_SOURCE_CLIENT_CREDENTIALS, ACTOR_TOKEN_SOURCE_NONE, DEFAULT_ACTOR_TOKEN_TYPES
from mcpgateway.services.gateway_service_token_cache import get_service_token_cache, SERVICE_TOKEN_CLIENT_AUTH_KEYS, service_token_fingerprint
from mcpgateway.services.oauth_manager import OAuthError, OAuthManager

logger = logging.getLogger(__name__)

ACTOR_PURPOSE = "actor"
# Conservative TTL when the authorization server omits expires_in.
_ACTOR_FALLBACK_TTL = 60


def actor_token_source(oauth_config: Optional[Dict[str, Any]]) -> str:
    """Return the configured actor token source, defaulting to ``none``.

    Args:
        oauth_config: Gateway ``oauth_config``, or ``None``.

    Returns:
        ``none``, ``client_credentials``, or ``client_assertion``.

    Examples:
        >>> actor_token_source({"actor_token_source": "client_assertion"})
        'client_assertion'
        >>> actor_token_source({}), actor_token_source(None)
        ('none', 'none')
    """
    if not isinstance(oauth_config, dict):
        return ACTOR_TOKEN_SOURCE_NONE
    return oauth_config.get("actor_token_source") or ACTOR_TOKEN_SOURCE_NONE


def exchange_mode(oauth_config: Optional[Dict[str, Any]]) -> str:
    """Return the audit ``mode`` of a token-exchange config.

    Args:
        oauth_config: Gateway ``oauth_config``, or ``None``.

    Returns:
        ``delegation`` when an actor token source is configured, else ``impersonation``.

    Examples:
        >>> exchange_mode({"actor_token_source": "client_credentials"})
        'delegation'
        >>> exchange_mode({"actor_token_source": "none"})
        'impersonation'
    """
    return "impersonation" if actor_token_source(oauth_config) == ACTOR_TOKEN_SOURCE_NONE else "delegation"


def exchange_cache_variant(oauth_config: Optional[Dict[str, Any]]) -> str:
    """Return the ``TokenExchangeCache`` key variant for the config's exchange mode.

    Impersonation keeps the empty variant, so its keys stay unchanged.

    Args:
        oauth_config: Gateway ``oauth_config``, or ``None``.

    Returns:
        ``""`` for impersonation, ``actor:<source>`` for delegation.

    Examples:
        >>> exchange_cache_variant({})
        ''
        >>> exchange_cache_variant({"actor_token_source": "client_credentials"})
        'actor:client_credentials'
    """
    source = actor_token_source(oauth_config)
    return "" if source == ACTOR_TOKEN_SOURCE_NONE else f"actor:{source}"


def build_actor_oauth_config(oauth_config: Dict[str, Any]) -> Dict[str, Any]:
    """Derive the client-credentials config that requests a ``client_credentials`` actor token.

    The config carries only the parent's client-auth keys: no scopes, no
    ``discovery`` overrides, and no token-exchange keys.

    Args:
        oauth_config: Token-exchange gateway ``oauth_config``.

    Returns:
        A new ``client_credentials`` config dict.

    Examples:
        >>> build_actor_oauth_config({"grant_type": "token-exchange", "token_url": "https://as/token", "client_id": "cf", "scopes": ["a"], "discovery": {"client_id": "svc"}})
        {'token_url': 'https://as/token', 'client_id': 'cf', 'grant_type': 'client_credentials'}
    """
    effective: Dict[str, Any] = {key: oauth_config[key] for key in SERVICE_TOKEN_CLIENT_AUTH_KEYS if oauth_config.get(key) is not None}
    effective["grant_type"] = "client_credentials"
    return effective


async def resolve_actor_token(
    oauth_manager: OAuthManager,
    oauth_config: Dict[str, Any],
    *,
    gateway_id: Optional[str],
    ca_certificate: Optional[str] = None,
    client_cert: Optional[str] = None,
    client_key: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """Return the actor token and its RFC 8693 type for one exchange.

    ``client_credentials`` tokens are cached per gateway for their lifetime.
    ``client_assertion`` tokens are signed fresh for each exchange, because each
    carries a new ``jti`` and authorization servers can reject replays.

    Args:
        oauth_manager: OAuth manager that requests or signs the actor token.
        oauth_config: Stored token-exchange gateway ``oauth_config``.
        gateway_id: Gateway identifier for the cache key, or ``None`` to skip caching.
        ca_certificate: Optional custom CA certificate for the token endpoint.
        client_cert: Optional client certificate for mTLS to the token endpoint.
        client_key: Optional client private key for mTLS to the token endpoint.

    Returns:
        ``(actor_token, actor_token_type)``, or ``(None, None)`` for impersonation.

    Raises:
        OAuthError: If the actor token cannot be obtained. The message carries no token value.
    """
    source = actor_token_source(oauth_config)
    if source == ACTOR_TOKEN_SOURCE_NONE:
        return None, None
    token_type = oauth_config.get("actor_token_type") or DEFAULT_ACTOR_TOKEN_TYPES.get(source)

    if source == ACTOR_TOKEN_SOURCE_CLIENT_CREDENTIALS:
        token = await _client_credentials_actor_token(oauth_manager, oauth_config, gateway_id, ca_certificate, client_cert, client_key)
    elif source == ACTOR_TOKEN_SOURCE_CLIENT_ASSERTION:
        token = await _client_assertion_actor_token(oauth_manager, oauth_config)
    else:
        raise OAuthError("Unsupported actor_token_source")
    return token, token_type


async def invalidate_actor_token(gateway_id: Optional[str], oauth_config: Optional[Dict[str, Any]]) -> None:
    """Discard the cached ``client_credentials`` actor token of a gateway after a rejected exchange.

    Args:
        gateway_id: Gateway identifier.
        oauth_config: Gateway ``oauth_config``. No-op unless the source is ``client_credentials``.
    """
    if gateway_id and actor_token_source(oauth_config) == ACTOR_TOKEN_SOURCE_CLIENT_CREDENTIALS:
        await get_service_token_cache().invalidate(gateway_id, purpose=ACTOR_PURPOSE)


async def _client_credentials_actor_token(
    oauth_manager: OAuthManager,
    oauth_config: Dict[str, Any],
    gateway_id: Optional[str],
    ca_certificate: Optional[str],
    client_cert: Optional[str],
    client_key: Optional[str],
) -> str:
    """Return a cached or new client-credentials actor token.

    Args:
        oauth_manager: OAuth manager that requests the token.
        oauth_config: Token-exchange gateway ``oauth_config``.
        gateway_id: Gateway identifier, or ``None`` to skip caching.
        ca_certificate: Optional custom CA certificate for the token endpoint.
        client_cert: Optional client certificate for mTLS to the token endpoint.
        client_key: Optional client private key for mTLS to the token endpoint.

    Returns:
        The actor access token.
    """
    actor_config = build_actor_oauth_config(oauth_config)
    if not gateway_id:
        return await _request_client_credentials_actor_token(oauth_manager, actor_config, None, "", ca_certificate, client_cert, client_key)

    cache = get_service_token_cache()
    fingerprint = service_token_fingerprint(actor_config)
    cached = await cache.get(ACTOR_PURPOSE, gateway_id, fingerprint)
    if cached:
        return cached
    async with cache.lock(ACTOR_PURPOSE, gateway_id, fingerprint):
        cached = await cache.get(ACTOR_PURPOSE, gateway_id, fingerprint)
        if cached:
            return cached
        return await _request_client_credentials_actor_token(oauth_manager, actor_config, gateway_id, fingerprint, ca_certificate, client_cert, client_key)


async def _request_client_credentials_actor_token(
    oauth_manager: OAuthManager,
    actor_config: Dict[str, Any],
    gateway_id: Optional[str],
    fingerprint: str,
    ca_certificate: Optional[str],
    client_cert: Optional[str],
    client_key: Optional[str],
) -> str:
    """Request a client-credentials actor token and cache it when a gateway id is known.

    Args:
        oauth_manager: OAuth manager that requests the token.
        actor_config: Output of ``build_actor_oauth_config()``.
        gateway_id: Gateway identifier, or ``None`` to skip caching.
        fingerprint: Config fingerprint for the cache key.
        ca_certificate: Optional custom CA certificate for the token endpoint.
        client_cert: Optional client certificate for mTLS to the token endpoint.
        client_key: Optional client private key for mTLS to the token endpoint.

    Returns:
        The actor access token.

    Raises:
        OAuthError: If the token request fails or returns no access token.
    """
    try:
        response = await oauth_manager.get_client_credentials_token_response(actor_config, ca_certificate=ca_certificate, client_cert=client_cert, client_key=client_key)
        token = response["access_token"]
    except Exception as exc:
        # The cause is chained for debugging; the message names no token value.
        raise OAuthError("Actor token request failed for token-exchange delegation") from exc
    if not isinstance(token, str) or not token:
        raise OAuthError("Actor token request returned no access token")
    if gateway_id:
        try:
            expires_in = int(response.get("expires_in") or _ACTOR_FALLBACK_TTL)
        except (TypeError, ValueError):
            expires_in = _ACTOR_FALLBACK_TTL
        await get_service_token_cache().set(ACTOR_PURPOSE, gateway_id, fingerprint, token, expires_in=expires_in)
    return token


async def _client_assertion_actor_token(oauth_manager: OAuthManager, oauth_config: Dict[str, Any]) -> str:
    """Sign a fresh RFC 7523 JWT that names the gateway client as the actor.

    Args:
        oauth_manager: OAuth manager that signs the assertion.
        oauth_config: Token-exchange gateway ``oauth_config``.

    Returns:
        The signed actor JWT.

    Raises:
        OAuthError: If the key cannot be decrypted, loaded, or used to sign.
    """
    try:
        runtime_credentials = await oauth_manager._prepare_runtime_credentials(oauth_config, "token-exchange actor")  # pylint: disable=protected-access
        return await oauth_manager.build_client_assertion(runtime_credentials)
    except OAuthError:
        raise
    except Exception as exc:
        raise OAuthError("Actor token signing failed for token-exchange delegation") from exc
