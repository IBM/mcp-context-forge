# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/token_backends/refresh_helpers.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Shared helper functions for OAuth token refresh logic.

These helpers are used by both DatabaseTokenBackend and VaultTokenBackend
to avoid code duplication for PR #5244 features.
"""

import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from mcpgateway.common.validators import SecurityValidator

from .base import normalize_resource_url

logger = logging.getLogger(__name__)


def check_private_gateway_access(
    gateway_visibility: str | None,
    gateway_owner_email: str | None,
    token_owner_email: str,
    gateway_id: str,
) -> bool:
    """Check if token owner can refresh tokens on a private gateway.

    Per PR #4341: Refuse refresh on private gateways when the gateway owner
    differs from the token owner. This prevents user A's tokens from being
    used to refresh gateway access for user B's private gateway.

    Args:
        gateway_visibility: Gateway visibility ("private", "public", or None)
        gateway_owner_email: Email of gateway owner (may be None)
        token_owner_email: Email of token owner (from stored token record)
        gateway_id: Gateway ID for logging

    Returns:
        True if access is allowed (public gateway or owner match),
        False if access is denied (private gateway with mismatched owner)
    """
    visibility = gateway_visibility or "public"
    if visibility == "private" and gateway_owner_email and gateway_owner_email != token_owner_email:
        logger.warning(
            "OAuth refresh denied: gateway %s is private and owned by %s, not token owner %s",
            gateway_id,
            gateway_owner_email,
            token_owner_email,
        )
        return False
    return True


def apply_omit_resource_and_normalize(
    oauth_config: dict[str, Any],
    gateway_url: str | None,
    gateway_id: str,
) -> None:
    """Apply omit_resource flag and normalize resource parameter.

    This implements the PR #5244 feature where omit_resource=true prevents
    resource parameter injection, fixing compatibility with IdPs that reject
    the resource parameter.

    Modifies oauth_config in-place.

    Args:
        oauth_config: OAuth configuration dict (will be modified in-place)
        gateway_url: Gateway URL for auto-deriving resource (or None)
        gateway_id: Gateway ID for logging

    Returns:
        None (modifies oauth_config in-place)
    """
    # RFC 8707: Set resource parameter for JWT access tokens during refresh
    # Respect omit_resource flag - if explicitly set to true, skip all resource handling
    omit_resource = oauth_config.get("omit_resource", False)
    if omit_resource:
        # User explicitly disabled resource parameter - remove it if present
        oauth_config.pop("resource", None)
        logger.debug("Omitting resource parameter for gateway %s as per omit_resource=true config", gateway_id)
    else:
        existing_resource = oauth_config.get("resource")
        if existing_resource:
            # Normalize existing resource - preserve query for explicit config
            if isinstance(existing_resource, list):
                original_count = len(existing_resource)
                normalized = [normalize_resource_url(r, preserve_query=True) for r in existing_resource]
                oauth_config["resource"] = [r for r in normalized if r]
                if not oauth_config["resource"] and original_count > 0:
                    logger.warning("All %s configured resource values were empty and removed during refresh", original_count)
            else:
                normalized = normalize_resource_url(existing_resource, preserve_query=True)
                if not normalized and existing_resource:
                    logger.warning("Configured resource was empty and removed during refresh: %s", existing_resource)
                oauth_config["resource"] = normalized
        elif gateway_url:
            # Derive from gateway.url if not explicitly configured (origin only: scheme + netloc)
            # RFC 8707 §2.2: IdPs issue origin-level audiences, so derive scheme://netloc
            parsed = urlparse(gateway_url)
            if parsed.scheme and parsed.netloc:
                oauth_config["resource"] = f"{parsed.scheme}://{parsed.netloc}"
            else:
                oauth_config["resource"] = None
            if not oauth_config.get("resource"):
                logger.warning("Gateway URL is empty, skipping resource parameter: %s", gateway_url)


def compute_prior_ttl(
    expires_at: datetime | str | None,
    updated_at: datetime | str | None,
    gateway_id: str,
) -> int | None:
    """Compute the token's prior TTL in seconds, or None if not derivable.

    Used when an OAuth refresh response omits expires_in but the token
    previously had a finite lifetime - the gateway preserves the original
    issuance TTL by computing expires_at - updated_at from the existing
    record. Returns None when either timestamp is missing or the difference
    is non-positive (clock skew or already-expired records).

    Args:
        expires_at: Token expiration timestamp (datetime or ISO string)
        updated_at: Last update timestamp (datetime or ISO string)
        gateway_id: Gateway ID for logging

    Returns:
        Positive integer seconds of prior TTL, or None.
    """
    if not expires_at or not updated_at:
        return None

    try:
        # Convert to datetime if string (for Vault backend)
        if isinstance(expires_at, str):
            prev_expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        else:
            prev_expires_at = expires_at

        if isinstance(updated_at, str):
            prev_updated_at = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        else:
            prev_updated_at = updated_at

        # Ensure timezone-aware for subtraction
        if prev_expires_at.tzinfo is None:
            prev_expires_at = prev_expires_at.replace(tzinfo=timezone.utc)
        if prev_updated_at.tzinfo is None:
            prev_updated_at = prev_updated_at.replace(tzinfo=timezone.utc)

        prev_ttl = int((prev_expires_at - prev_updated_at).total_seconds())
        if prev_ttl <= 0:
            return None

        logger.info(
            "No expires_in on refresh response for gateway %s; preserving prior TTL of %d seconds",
            SecurityValidator.sanitize_log_message(gateway_id),
            prev_ttl,
        )
        return prev_ttl

    except (ValueError, AttributeError, TypeError) as e:
        logger.debug("Could not compute prior TTL for gateway %s: %s", gateway_id, str(e))
        return None
