# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/identity_propagation.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Identity propagation utilities for forwarding end-user identity to upstream MCP servers.

This module provides functions to build HTTP headers and MCP ``_meta`` payloads
carrying user identity, as well as filtering of sensitive attributes before
propagation.

Examples:
    >>> from mcpgateway.plugins.framework.models import UserContext
    >>> uc = UserContext(user_id="alice@co.com", email="alice@co.com", is_admin=False, groups=["eng"], auth_method="bearer")
    >>> filtered = filter_sensitive_attributes(uc, ["password_hash"])
    >>> "password_hash" not in filtered.attributes
    True
"""

# Standard
import hashlib
import hmac
import logging
from typing import Any, Dict, Optional

# First-Party
from mcpgateway.config import settings
from mcpgateway.plugins.framework.models import UserContext

logger = logging.getLogger(__name__)


def _resolve_config(gateway: Optional[Any] = None) -> Dict[str, Any]:
    """Resolve identity propagation configuration.

    Per-gateway config overrides global settings when present.

    Args:
        gateway: Optional gateway DB object with ``identity_propagation`` JSON field.

    Returns:
        Resolved configuration dict.
    """
    gw_cfg = getattr(gateway, "identity_propagation", None) or {} if gateway else {}
    return {
        "enabled": gw_cfg.get("enabled", settings.identity_propagation_enabled),
        "mode": gw_cfg.get("mode", settings.identity_propagation_mode),
        "headers_prefix": gw_cfg.get("headers_prefix", settings.identity_propagation_headers_prefix),
        "sign_claims": gw_cfg.get("sign_claims", settings.identity_sign_claims),
        "sensitive_attributes": gw_cfg.get("sensitive_attributes", settings.identity_sensitive_attributes),
    }


def _sign_claims(payload: str) -> str:
    """Compute HMAC-SHA256 signature over the given payload string.

    Args:
        payload: String to sign.

    Returns:
        Hex-encoded HMAC signature.
    """
    secret = settings.identity_claims_secret or (settings.jwt_secret_key.get_secret_value() if settings.jwt_secret_key else "")
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def build_identity_headers(
    user_context: UserContext,
    gateway: Optional[Any] = None,
) -> Dict[str, str]:
    """Build HTTP headers carrying user identity for upstream servers.

    Args:
        user_context: The authenticated user's identity.
        gateway: Optional gateway DB object for per-gateway config overrides.

    Returns:
        Dict of HTTP headers to merge into the outbound request.

    Examples:
        >>> from mcpgateway.plugins.framework.models import UserContext
        >>> uc = UserContext(user_id="bob@co.com", email="bob@co.com", is_admin=True, teams=["t1","t2"], auth_method="bearer")
        >>> h = build_identity_headers(uc)
        >>> isinstance(h, dict)
        True
    """
    cfg = _resolve_config(gateway)
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
        # Sign the user_id + email combination
        sig_payload = f"{user_context.user_id}:{user_context.email or ''}"
        headers[f"{prefix}-Claims-Signature"] = _sign_claims(sig_payload)

    return headers


def build_identity_meta(
    user_context: UserContext,
    existing_meta: Optional[Dict[str, Any]] = None,
    gateway: Optional[Any] = None,
) -> Dict[str, Any]:
    """Build ``_meta`` dict with user identity for MCP protocol propagation.

    Merges user identity into the existing ``_meta`` dict (if any).

    Args:
        user_context: The authenticated user's identity.
        existing_meta: Existing _meta dict to merge into.
        gateway: Optional gateway DB object for per-gateway config overrides.

    Returns:
        Updated _meta dict with user identity under the ``user`` key.

    Examples:
        >>> from mcpgateway.plugins.framework.models import UserContext
        >>> uc = UserContext(user_id="alice@co.com", groups=["eng"])
        >>> meta = build_identity_meta(uc, {"existing_key": "val"})
        >>> meta["existing_key"]
        'val'
    """
    cfg = _resolve_config(gateway)
    if not cfg["enabled"]:
        return existing_meta or {}

    meta = dict(existing_meta) if existing_meta else {}
    user_info: Dict[str, Any] = {
        "id": user_context.user_id,
    }
    if user_context.email:
        user_info["email"] = user_context.email
    if user_context.full_name:
        user_info["full_name"] = user_context.full_name
    if user_context.groups:
        user_info["groups"] = user_context.groups
    if user_context.teams:
        user_info["teams"] = user_context.teams
    if user_context.roles:
        user_info["roles"] = user_context.roles
    user_info["is_admin"] = user_context.is_admin
    if user_context.auth_method:
        user_info["auth_method"] = user_context.auth_method
    if user_context.service_account:
        user_info["service_account"] = user_context.service_account
    if user_context.delegation_chain:
        user_info["delegation_chain"] = user_context.delegation_chain

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
        >>> from mcpgateway.plugins.framework.models import UserContext
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
