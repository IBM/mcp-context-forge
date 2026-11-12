# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/a2a_oauth.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

OAuth token resolution for outbound A2A agent calls.

An A2A agent with ``auth_type="oauth"`` uses one agent-level token from the
``client_credentials`` grant. The token request carries the RFC 8707 ``resource``
(configured value, else the origin of the agent endpoint). The gateway checks
the token claims with the same rules as gateways before it forwards the token.
"""

# Standard
from collections import OrderedDict
import hashlib
import logging
import time
from typing import Any, Dict, Optional

# First-Party
from mcpgateway.services.a2a_errors import A2AAgentError
from mcpgateway.services.gateway_service_token_cache import get_service_token_cache, service_token_fingerprint
from mcpgateway.services.oauth_manager import OAuthManager
from mcpgateway.services.token_validation_service import validate_oauth_token_claims
from mcpgateway.utils.correlation_id import get_correlation_id
from mcpgateway.utils.oauth_resource import derive_resource_origin
from mcpgateway.utils.url_auth import sanitize_exception_message

logger = logging.getLogger(__name__)

A2A_OAUTH_TOKEN_PURPOSE = "a2a"
_FALLBACK_TTL = 60
_SUPPORTED_GRANT_TYPE = "client_credentials"
_FAILURE_TTL = 10
_FAILURE_MAX_ENTRIES = 1000
_recent_failures: "OrderedDict[str, tuple[float, str]]" = OrderedDict()


class A2AOAuthError(A2AAgentError):
    """Raised when the gateway cannot get a usable OAuth token for an A2A agent."""


def _effective_config(oauth_config: Dict[str, Any], endpoint_url: str) -> Dict[str, Any]:
    """Return the token request config with the RFC 8707 resource resolved.

    Args:
        oauth_config: Stored agent OAuth configuration.
        endpoint_url: Agent endpoint URL, the source of the derived resource.

    Returns:
        Copy of ``oauth_config`` with ``resource`` set when one is known.

    Examples:
        >>> _effective_config({"resource": "https://api.example.com"}, "https://other.example.com/a")["resource"]
        'https://api.example.com'
        >>> _effective_config({}, "https://agent.example.com/a2a")["resource"]
        'https://agent.example.com'
        >>> "resource" in _effective_config({}, "urn:agent")
        False
    """
    effective = dict(oauth_config)
    if not effective.get("resource"):
        derived = derive_resource_origin(endpoint_url)
        if derived:
            effective["resource"] = derived
    return effective


def _cache_fingerprint(effective: Dict[str, Any]) -> str:
    """Return the cache fingerprint, which also covers the resource.

    Args:
        effective: Config from ``_effective_config()``.

    Returns:
        Hex SHA-256 digest.

    Examples:
        >>> _cache_fingerprint({"resource": "a"}) != _cache_fingerprint({"resource": "b"})
        True
        >>> _cache_fingerprint({"audience": "a"}) != _cache_fingerprint({"audience": "b"})
        True
    """
    resource = str(effective.get("resource") or "")
    audience = str(effective.get("audience") or "")
    return hashlib.sha256(f"{service_token_fingerprint(effective)}|{resource}|{audience}".encode("utf-8")).hexdigest()


def _raise_if_recently_failed(fingerprint: str, agent_id: str) -> None:
    """Fail fast when a token request for this agent and config failed moments ago.

    Callers that wait on the single-flight lock reach this check after the first
    caller failed, so an IdP outage costs one retry cycle, not one per waiter.

    Args:
        fingerprint: Cache fingerprint of the token request.
        agent_id: Agent identifier.

    Raises:
        A2AOAuthError: If a failure was recorded inside ``_FAILURE_TTL`` seconds.

    Examples:
        >>> _recent_failures.clear()
        >>> _raise_if_recently_failed("f", "a")
        >>> _remember_failure("a", "f", "boom")
        >>> _raise_if_recently_failed("f", "a")
        Traceback (most recent call last):
            ...
        mcpgateway.services.a2a_oauth.A2AOAuthError: boom
        >>> _recent_failures.clear()
    """
    key = f"{agent_id}:{fingerprint}"
    entry = _recent_failures.get(key)
    if entry is None:
        return
    deadline, message = entry
    if deadline <= time.monotonic():
        _recent_failures.pop(key, None)
        return
    raise A2AOAuthError(message)


def _remember_failure(agent_id: str, fingerprint: str, message: str) -> None:
    """Record a failed token request for ``_FAILURE_TTL`` seconds.

    Args:
        agent_id: Agent identifier.
        fingerprint: Cache fingerprint of the token request.
        message: Error message to raise for callers inside the window.
    """
    _recent_failures[f"{agent_id}:{fingerprint}"] = (time.monotonic() + _FAILURE_TTL, message)
    while len(_recent_failures) > _FAILURE_MAX_ENTRIES:
        _recent_failures.popitem(last=False)


async def resolve_a2a_oauth_headers(agent_id: str, agent_name: str, endpoint_url: str, oauth_config: Optional[Dict[str, Any]], oauth_manager: Optional[OAuthManager] = None) -> Dict[str, str]:
    """Return the ``Authorization`` header for an OAuth A2A agent.

    Args:
        agent_id: Agent identifier, used as the cache key.
        agent_name: Agent name, used in messages.
        endpoint_url: Agent endpoint URL.
        oauth_config: Stored agent OAuth configuration.
        oauth_manager: Token client. Defaults to a new ``OAuthManager``.

    Returns:
        ``{"Authorization": "Bearer <token>"}``.

    Raises:
        A2AOAuthError: If the config is missing or unsupported, the token request fails,
            or the token claims mismatch the configured expectations.
    """
    if not oauth_config:
        raise A2AOAuthError(f"A2A agent '{agent_name}' uses OAuth but has no oauth_config")
    grant_type = oauth_config.get("grant_type", _SUPPORTED_GRANT_TYPE)
    if grant_type != _SUPPORTED_GRANT_TYPE:
        raise A2AOAuthError(f"A2A agent '{agent_name}' uses unsupported OAuth grant_type '{grant_type}'. Only client_credentials is supported.")

    effective = _effective_config(oauth_config, endpoint_url)
    fingerprint = _cache_fingerprint(effective)
    cache = get_service_token_cache()

    cached = await cache.get(A2A_OAUTH_TOKEN_PURPOSE, agent_id, fingerprint)
    if cached:
        return {"Authorization": f"Bearer {cached}"}

    async with cache.lock(A2A_OAUTH_TOKEN_PURPOSE, agent_id, fingerprint):
        cached = await cache.get(A2A_OAUTH_TOKEN_PURPOSE, agent_id, fingerprint)
        if cached:
            return {"Authorization": f"Bearer {cached}"}
        _raise_if_recently_failed(fingerprint, agent_id)

        manager = oauth_manager or OAuthManager()
        started = time.monotonic()
        try:
            response = await manager.get_client_credentials_token_response(effective, send_resource=True)
        except Exception as exc:
            logger.warning("OAuth token request failed for A2A agent %s (%s: %s) correlation_id=%s", agent_name, type(exc).__name__, sanitize_exception_message(str(exc)), get_correlation_id())
            message = f"OAuth token request failed for A2A agent '{agent_name}'"
            _remember_failure(agent_id, fingerprint, message)
            raise A2AOAuthError(message) from exc
        access_token = response["access_token"]

        validation = validate_oauth_token_claims(
            access_token=access_token, oauth_config=oauth_config, gateway_url=endpoint_url, gateway_name=agent_name, token_type=response.get("token_type") or "Bearer"
        )
        for warning in validation.warnings:
            logger.warning("OAuth token validation for A2A agent %s: %s", agent_name, warning)
        blocking = validation.blocking_errors
        if blocking:
            logger.warning("Refusing OAuth token for A2A agent %s: %s correlation_id=%s", agent_name, "; ".join(blocking), get_correlation_id())
            raise A2AOAuthError(f"Refusing to forward OAuth token for A2A agent '{agent_name}': {'; '.join(blocking)}. Fix oauth_config (resource/scopes/issuer) or the IdP token request.")

        try:
            expires_in = int(response.get("expires_in") or _FALLBACK_TTL)
        except (TypeError, ValueError):
            expires_in = _FALLBACK_TTL
        await cache.set(A2A_OAUTH_TOKEN_PURPOSE, agent_id, fingerprint, access_token, expires_in=expires_in)
        _recent_failures.pop(f"{agent_id}:{fingerprint}", None)
        logger.info("Obtained OAuth token for A2A agent %s in %d ms", agent_name, int((time.monotonic() - started) * 1000))
        return {"Authorization": f"Bearer {access_token}"}


async def resolve_a2a_agent_oauth_headers(agent_id: str, agent_name: str, endpoint_url: str, auth_type: Optional[str], oauth_config: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """Return the OAuth headers for an A2A agent, or none for any other auth type.

    Every invocation path calls this one function, so each path raises the same error type.

    Args:
        agent_id: Agent identifier.
        agent_name: Agent name, used in messages.
        endpoint_url: Agent endpoint URL.
        auth_type: Agent authentication type.
        oauth_config: Stored agent OAuth configuration.

    Returns:
        The ``Authorization`` header when ``auth_type`` is ``oauth``, else an empty dict.

    Raises:
        A2AOAuthError: If the gateway cannot get a usable token for the agent. This is an ``A2AAgentError``.
    """
    if auth_type != "oauth":
        return {}
    return await resolve_a2a_oauth_headers(agent_id, agent_name, endpoint_url, oauth_config)
