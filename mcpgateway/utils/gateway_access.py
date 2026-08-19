# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/gateway_access.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Gateway access control utilities.

This module provides helper functions for checking gateway access permissions
in direct_proxy mode, ensuring consistent RBAC enforcement across the codebase.
"""

# Standard
from typing import Any, Dict, List, Mapping, Optional, TYPE_CHECKING

# Third-Party
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.utils.admin_check import is_user_admin
from mcpgateway.utils.services_auth import decode_auth

if TYPE_CHECKING:
    # First-Party
    from mcpgateway.services.reverse_proxy_protocol import DownstreamAuth

# Header name used by clients to target a specific gateway for direct_proxy mode.
# Defined once here to avoid string literal repetition across the codebase.
GATEWAY_ID_HEADER = "X-Context-Forge-Gateway-Id"


def extract_gateway_id_from_headers(headers: Optional[Dict[str, str]]) -> Optional[str]:
    """Extract gateway ID from request headers (case-insensitive).

    Args:
        headers: Request headers dictionary (may be None).

    Returns:
        Gateway ID string if found, None otherwise.
    """
    if not headers:
        return None
    header_lower = GATEWAY_ID_HEADER.lower()
    for name, value in headers.items():
        if name.lower() == header_lower:
            return value
    return None


async def check_gateway_access(
    db: Session,
    gateway: DbGateway,
    user_email: Optional[str],
    token_teams: Optional[List[str]],
) -> bool:
    """Check if user has access to a gateway based on visibility rules.

    Used for direct_proxy mode to ensure users can only access gateways they have permission to use.

    Access Rules:
    - Public gateways: Accessible by all authenticated users
    - Team gateways: Accessible by team members (team_id in user's teams)
    - Private gateways: Accessible only by owner (owner_email matches)

    Args:
        db: Database session for team membership lookup if needed.
        gateway: Gateway ORM object.
        user_email: Email of the requesting user (None = unauthenticated).
        token_teams: List of team IDs from token.
            - None = unrestricted admin access
            - [] = public-only token
            - [...] = team-scoped token

    Returns:
        True if access is allowed, False otherwise.
    """
    visibility = gateway.visibility if hasattr(gateway, "visibility") else "public"
    gateway_team_id = gateway.team_id if hasattr(gateway, "team_id") else None
    gateway_owner_email = gateway.owner_email if hasattr(gateway, "owner_email") else None

    if visibility == "public":
        return True

    # Admin bypass (PR #4341 invariant): never reveal another user's private
    # gateways. Anonymous bypass (token_teams=None AND user_email=None) sees
    # public + team only. DB-resolved admin sessions ((email, None) shape)
    # additionally see their own private gateways. Mirrors the hybrid in
    # BaseService._apply_access_control / _check_*_access.
    if user_email is None and token_teams is None:
        return visibility != "private"
    if token_teams is None and user_email and is_user_admin(db, user_email):
        return visibility != "private" or gateway_owner_email == user_email

    if not user_email:
        return False

    # Public-only tokens (empty teams array) can ONLY access public gateways
    is_public_only_token = token_teams is not None and len(token_teams) == 0
    if is_public_only_token:
        return False  # Already checked public above

    # Owner can always access their own gateways
    if gateway_owner_email and gateway_owner_email == user_email:
        return True

    # Team gateways: check team membership
    if gateway_team_id:
        # Use token_teams if provided, otherwise look up from DB
        if token_teams is not None:
            team_ids = token_teams
        else:
            # First-Party
            from mcpgateway.services.team_management_service import TeamManagementService  # pylint: disable=import-outside-toplevel

            team_service = TeamManagementService(db)
            user_teams = await team_service.get_user_teams(user_email)
            team_ids = [team.id for team in user_teams]

        # Team/public visibility allows access if user is in the team
        if visibility in ["team", "public"] and gateway_team_id in team_ids:
            return True

    # Default: deny access
    return False


class GatewayAuthValueError(ValueError):
    """Stored gateway credential material is malformed or not forwardable downstream.

    Messages name only the auth mode and a fixed reason — never credential
    material — so the error is safe to wrap into service exceptions, logs, and
    telemetry text.
    """


# Auth modes whose stored material can be forwarded to a downstream server as HTTP headers.
DOWNSTREAM_FORWARDABLE_AUTH_TYPES = frozenset({"bearer", "basic", "authheaders"})


def _bearer_basic_headers(auth_type: str, decoded: Mapping[str, str]) -> Dict[str, str]:
    """Normalize bearer/basic stored material to a single ``Authorization`` header."""
    if auth_type == "bearer":
        token = decoded.get("Authorization", "").replace("Bearer ", "")
        return {"Authorization": f"Bearer {token}"} if token else {}
    auth_header = decoded.get("Authorization", "")
    return {"Authorization": auth_header} if auth_header else {}


def build_gateway_auth_headers(gateway: DbGateway) -> Dict[str, str]:
    """Build authentication headers for gateway requests.

    Extracts and formats authentication headers from gateway configuration,
    handling both bearer and basic auth types with dict or encoded string values.

    Args:
        gateway: Gateway ORM object with auth_type and auth_value attributes.

    Returns:
        Dictionary of HTTP headers with Authorization header if auth is configured.
        Returns empty dict if no auth is configured or if token/credentials are empty.

    Examples:
        >>> gateway = DbGateway(auth_type="bearer", auth_value={"Authorization": "Bearer token123"})
        >>> headers = build_gateway_auth_headers(gateway)
        >>> headers["Authorization"]
        'Bearer token123'
    """
    auth_type = getattr(gateway, "auth_type", None)
    auth_value = getattr(gateway, "auth_value", None)
    if auth_type not in ("bearer", "basic") or not auth_value:
        return {}
    if isinstance(auth_value, dict):
        decoded: Mapping[str, Any] = auth_value
    elif isinstance(auth_value, str):
        decoded = decode_auth(auth_value)
    else:
        return {}
    return _bearer_basic_headers(auth_type, decoded)


def normalize_downstream_auth_headers(auth_type: Optional[str], auth_value: Optional[Any]) -> Dict[str, str]:
    """Strictly normalize stored gateway credentials for PROXIED downstream forwarding.

    Covers the three forwardable modes: ``bearer``/``basic`` (normalized to a single
    ``Authorization`` header, matching ``build_gateway_auth_headers`` semantics) and
    ``authheaders`` (the full custom header mapping). Returns ``{}`` when no material
    is stored, so the wire envelope omits ``authentication``/``authType`` entirely.

    Args:
        auth_type: Stored gateway auth type ("bearer", "basic", "authheaders", ...).
        auth_value: Stored auth material — encrypted string or already-decoded mapping.

    Returns:
        The header mapping to attach downstream, or ``{}`` when nothing is stored.

    Raises:
        GatewayAuthValueError: If the mode is not forwardable downstream (e.g.
            ``query_param``/``oauth``/``one_time_auth``) or the stored material is
            undecryptable, not a mapping, or carries non-string header keys/values.
            The message names only the mode and a fixed reason — never material.
    """
    if not auth_type or not auth_value:
        return {}
    if auth_type not in DOWNSTREAM_FORWARDABLE_AUTH_TYPES:
        raise GatewayAuthValueError(f"auth mode '{auth_type}' is not supported for downstream forwarding")
    if isinstance(auth_value, str):
        try:
            raw_decoded: Any = decode_auth(auth_value)
        except Exception as exc:  # boundary: every decrypt/parse failure becomes one code-only typed error
            raise GatewayAuthValueError(f"stored '{auth_type}' credentials are undecryptable or malformed") from exc
        if not isinstance(raw_decoded, Mapping):
            raise GatewayAuthValueError(f"stored '{auth_type}' credentials are not a header mapping")
        decoded = raw_decoded
    elif isinstance(auth_value, Mapping):
        decoded = auth_value
    else:
        raise GatewayAuthValueError(f"stored '{auth_type}' credentials have an unsupported representation")
    strict: Dict[str, str] = {}
    for key, value in decoded.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise GatewayAuthValueError(f"stored '{auth_type}' credentials must be string header key/value pairs")
        strict[key] = value
    if auth_type in ("bearer", "basic"):
        return _bearer_basic_headers(auth_type, strict)
    return strict


def build_downstream_auth(auth_type: Optional[str], auth_value: Optional[Any]) -> Optional["DownstreamAuth"]:
    """Build the typed downstream-auth envelope for PROXIED dispatch.

    Wraps ``normalize_downstream_auth_headers``: returns ``None`` when no forwardable
    material is stored (the wire envelope then omits ``authentication``/``authType``
    entirely), otherwise a ``DownstreamAuth`` carrying the normalized headers and the
    auth mode. The material is never logged.

    Args:
        auth_type: Stored gateway auth type ("bearer", "basic", "authheaders", ...).
        auth_value: Stored auth material — encrypted string or already-decoded mapping.

    Returns:
        A ``DownstreamAuth`` for the dispatch envelope, or ``None`` when nothing is stored.

    Raises:
        GatewayAuthValueError: If the mode is not forwardable downstream or the stored
            material is malformed. The message names only the mode and a fixed
            reason — never material.
    """
    # Lazy import: services/__init__ eagerly imports the tool/resource/prompt services,
    # which import this module — a top-level import here would circular-import.
    # First-Party
    from mcpgateway.services.reverse_proxy_protocol import DownstreamAuth  # pylint: disable=import-outside-toplevel

    headers = normalize_downstream_auth_headers(auth_type, auth_value)
    if not headers:
        return None
    return DownstreamAuth(headers=headers, auth_type=auth_type)
