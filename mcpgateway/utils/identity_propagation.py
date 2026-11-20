# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/identity_propagation.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Identity propagation utilities for forwarding end-user identity to upstream MCP servers.

This module provides functions to build HTTP headers and MCP ``_meta`` payloads
carrying user identity, as well as filtering of sensitive attributes before
propagation.

Examples:
    >>> from mcpgateway.transports.context import UserContext
    >>> uc = UserContext(user_id="alice@co.com", email="alice@co.com", is_admin=False, groups=["eng"], auth_method="bearer")
    >>> filtered = filter_sensitive_attributes(uc, ["password_hash"])
    >>> "password_hash" not in filtered.attributes
    True
"""

# Standard
import logging
import time
from typing import Any, Dict, Optional
import uuid

# Third-Party
import jwt

# First-Party
from mcpgateway.config import settings
from mcpgateway.transports.context import UserContext

logger = logging.getLogger(__name__)

_CLAIMS_TOKEN_TTL_SECONDS = 60
_CLAIMS_TOKEN_ISSUER = "mcpgateway-identity-propagation"
_SIGNING_REFUSED = "Identity claim signing requires a dedicated IDENTITY_CLAIMS_SECRET and a target audience"


def _resolve_config(gateway: Optional[Any] = None, identity_propagation: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Resolve identity propagation configuration.

    Per-gateway config overrides global settings when present.

    Args:
        gateway: Optional gateway DB object with ``identity_propagation`` JSON field.
        identity_propagation: Optional per-gateway config dict. Takes precedence over ``gateway``.

    Returns:
        Resolved configuration dict.
    """
    if identity_propagation is not None:
        gw_cfg = identity_propagation
    else:
        gw_cfg = getattr(gateway, "identity_propagation", None) or {} if gateway else {}
    return {
        "enabled": gw_cfg.get("enabled", settings.identity_propagation_enabled),
        "mode": gw_cfg.get("mode", settings.identity_propagation_mode),
        "headers_prefix": gw_cfg.get("headers_prefix", settings.identity_propagation_headers_prefix),
        "sign_claims": gw_cfg.get("sign_claims", settings.identity_sign_claims),
        "sensitive_attributes": gw_cfg.get("sensitive_attributes", settings.identity_sensitive_attributes),
    }


class IdentitySigningError(ValueError):
    """Identity claims cannot be signed because the signing configuration is missing or unsafe."""


def _claims_secret() -> str:
    """Return the dedicated identity-claims signing secret.

    Returns:
        The configured ``IDENTITY_CLAIMS_SECRET`` value.

    Raises:
        IdentitySigningError: If the secret is unset, empty, or equal to ``JWT_SECRET_KEY``.
    """
    secret = settings.identity_claims_secret.get_secret_value() if settings.identity_claims_secret else ""
    jwt_secret = settings.jwt_secret_key.get_secret_value() if settings.jwt_secret_key else ""
    if not secret or secret == jwt_secret:
        raise IdentitySigningError(_SIGNING_REFUSED)
    return secret


def _identity_claims(user_context: UserContext) -> Dict[str, Any]:
    """Build the identity claim dict shared by ``_meta.user`` and the signed token.

    Args:
        user_context: The authenticated user's identity.

    Returns:
        Identity claims; optional fields are omitted when empty, ``is_admin`` is always present.

    Examples:
        >>> from mcpgateway.transports.context import UserContext
        >>> _identity_claims(UserContext(user_id="a", teams=["t1"]))
        {'id': 'a', 'teams': ['t1'], 'is_admin': False}
    """
    claims: Dict[str, Any] = {"id": user_context.user_id}
    if user_context.email:
        claims["email"] = user_context.email
    if user_context.full_name:
        claims["full_name"] = user_context.full_name
    if user_context.groups:
        claims["groups"] = user_context.groups
    if user_context.teams:
        claims["teams"] = user_context.teams
    if user_context.roles:
        claims["roles"] = user_context.roles
    claims["is_admin"] = user_context.is_admin
    if user_context.auth_method:
        claims["auth_method"] = user_context.auth_method
    if user_context.service_account:
        claims["service_account"] = user_context.service_account
    if user_context.delegation_chain:
        claims["delegation_chain"] = user_context.delegation_chain
    return claims


def _resolve_audience(gateway: Optional[Any], audience: Optional[str]) -> Optional[str]:
    """Return the explicit audience, else the gateway id.

    Args:
        gateway: Optional gateway object.
        audience: Explicit audience; wins over the gateway id.

    Returns:
        The audience string, or ``None`` when neither source has one.
    """
    if audience:
        return audience
    gateway_id = getattr(gateway, "id", None) if gateway is not None else None
    return str(gateway_id) if gateway_id else None


def _claims_token(claims: Dict[str, Any], audience: Optional[str]) -> str:
    """Sign every identity claim as a short-lived, audience-bound HS256 JWS.

    Args:
        claims: Identity claims from ``_identity_claims``.
        audience: Target upstream identifier, bound as ``aud``.

    Returns:
        Compact JWS string.

    Raises:
        IdentitySigningError: If no audience is known or no dedicated secret is configured.
    """
    if not audience:
        raise IdentitySigningError(_SIGNING_REFUSED)
    now = int(time.time())
    payload = {
        **claims,
        "iss": _CLAIMS_TOKEN_ISSUER,
        "aud": audience,
        "iat": now,
        "exp": now + _CLAIMS_TOKEN_TTL_SECONDS,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, _claims_secret(), algorithm="HS256")


def build_identity_headers(
    user_context: UserContext,
    gateway: Optional[Any] = None,
    identity_propagation: Optional[Dict[str, Any]] = None,
    audience: Optional[str] = None,
) -> Dict[str, str]:
    """Build HTTP headers carrying user identity for upstream servers.

    When claim signing is on, ``{prefix}-Claims-Signature`` carries an HS256 JWS
    over every identity claim, bound to ``audience`` and valid for 60 seconds.

    Args:
        user_context: The authenticated user's identity.
        gateway: Optional gateway DB object for per-gateway config overrides.
        identity_propagation: Optional per-gateway config dict. Takes precedence over ``gateway``.
        audience: Upstream identifier bound as the token ``aud``. Defaults to ``gateway.id``.

    Returns:
        Dict of HTTP headers to merge into the outbound request.

    Examples:
        >>> from mcpgateway.transports.context import UserContext
        >>> uc = UserContext(user_id="bob@co.com", email="bob@co.com", is_admin=True, teams=["t1","t2"], auth_method="bearer")
        >>> h = build_identity_headers(uc)
        >>> isinstance(h, dict)
        True
    """
    cfg = _resolve_config(gateway, identity_propagation)
    if not cfg["enabled"]:
        return {}

    prefix = cfg["headers_prefix"]
    headers: Dict[str, str] = {
        f"{prefix}-Id": user_context.user_id,
    }

    if user_context.email:
        headers[f"{prefix}-Email"] = user_context.email
    if user_context.full_name:
        headers[f"{prefix}-Full-Name"] = user_context.full_name
    if user_context.groups:
        headers[f"{prefix}-Groups"] = ",".join(user_context.groups)
    if user_context.teams:
        headers[f"{prefix}-Teams"] = ",".join(user_context.teams)
    if user_context.roles:
        headers[f"{prefix}-Roles"] = ",".join(user_context.roles)
    headers[f"{prefix}-Admin"] = str(user_context.is_admin).lower()
    if user_context.auth_method:
        headers[f"{prefix}-Auth-Method"] = user_context.auth_method
    if user_context.service_account:
        headers[f"{prefix}-Service-Account"] = user_context.service_account
    if user_context.delegation_chain:
        headers[f"{prefix}-Delegation-Chain"] = ",".join(user_context.delegation_chain)

    if cfg["sign_claims"]:
        headers[f"{prefix}-Claims-Signature"] = _claims_token(_identity_claims(user_context), _resolve_audience(gateway, audience))

    return headers


def build_identity_meta(
    user_context: UserContext,
    existing_meta: Optional[Dict[str, Any]] = None,
    gateway: Optional[Any] = None,
    identity_propagation: Optional[Dict[str, Any]] = None,
    audience: Optional[str] = None,
) -> Dict[str, Any]:
    """Build ``_meta`` dict with user identity for MCP protocol propagation.

    Merges user identity into the existing ``_meta`` dict (if any). When claim
    signing is on, ``user.claims_signature`` carries the same kind of JWS as the
    headers.

    Args:
        user_context: The authenticated user's identity.
        existing_meta: Existing _meta dict to merge into.
        gateway: Optional gateway DB object for per-gateway config overrides.
        identity_propagation: Optional per-gateway config dict. Takes precedence over ``gateway``.
        audience: Upstream identifier bound as the token ``aud``. Defaults to ``gateway.id``.

    Returns:
        Updated _meta dict with user identity under the ``user`` key.

    Examples:
        >>> from mcpgateway.transports.context import UserContext
        >>> uc = UserContext(user_id="alice@co.com", groups=["eng"])
        >>> meta = build_identity_meta(uc, {"existing_key": "val"})
        >>> meta["existing_key"]
        'val'
    """
    cfg = _resolve_config(gateway, identity_propagation)
    if not cfg["enabled"]:
        return existing_meta or {}

    meta = dict(existing_meta) if existing_meta else {}
    user_info = _identity_claims(user_context)
    if cfg["sign_claims"]:
        user_info["claims_signature"] = _claims_token(_identity_claims(user_context), _resolve_audience(gateway, audience))

    meta["user"] = user_info
    return meta


def filter_sensitive_attributes(
    user_context: UserContext,
    sensitive_keys: Optional[list[str]] = None,
) -> UserContext:
    """Return a copy of the user context with sensitive attributes removed.

    Args:
        user_context: The original user context.
        sensitive_keys: List of attribute keys to strip.  Falls back to
            ``settings.identity_sensitive_attributes`` if not provided.

    Returns:
        A new UserContext with sensitive keys removed from ``attributes``.

    Examples:
        >>> from mcpgateway.transports.context import UserContext
        >>> uc = UserContext(user_id="x", attributes={"password_hash": "secret", "dept": "eng"})
        >>> filtered = filter_sensitive_attributes(uc, ["password_hash"])
        >>> "password_hash" in filtered.attributes
        False
        >>> filtered.attributes["dept"]
        'eng'
    """
    if sensitive_keys is None:
        sensitive_keys = settings.identity_sensitive_attributes
    filtered_attrs = {k: v for k, v in user_context.attributes.items() if k not in sensitive_keys}
    return user_context.model_copy(update={"attributes": filtered_attrs})
