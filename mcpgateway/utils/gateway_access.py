# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/gateway_access.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Gateway access control utilities.

This module provides helper functions for checking gateway access permissions
in direct_proxy mode, ensuring consistent RBAC enforcement across the codebase.
"""

# Standard
from typing import Dict, List, Optional

# Third-Party
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.utils.services_auth import decode_auth

# Header name used by clients to target a specific gateway for direct_proxy mode.
# Defined once here to avoid string literal repetition across the codebase.
GATEWAY_ID_HEADER = "X-Context-Forge-Gateway-Id"


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

    # Public gateways are accessible by everyone
    if visibility == "public":
        return True

    # Admin bypass: token_teams=None AND user_email=None means unrestricted admin
    # This happens when is_admin=True and no team scoping in token
    if token_teams is None and user_email is None:
        return True

    # No user context (but not admin) = deny access to non-public gateways
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
    headers: Dict[str, str] = {}

    if gateway.auth_type == "bearer" and gateway.auth_value:
        if isinstance(gateway.auth_value, dict):
            token = gateway.auth_value.get("Authorization", "").replace("Bearer ", "")
            if token:  # Only add header if token is not empty
                headers["Authorization"] = f"Bearer {token}"
        elif isinstance(gateway.auth_value, str):
            decoded = decode_auth(gateway.auth_value)
            token = decoded.get("Authorization", "").replace("Bearer ", "")
            if token:  # Only add header if token is not empty
                headers["Authorization"] = f"Bearer {token}"
    elif gateway.auth_type == "basic" and gateway.auth_value:
        if isinstance(gateway.auth_value, dict):
            auth_header = gateway.auth_value.get("Authorization", "")
            if auth_header:  # Only add header if not empty
                headers["Authorization"] = auth_header
        elif isinstance(gateway.auth_value, str):
            decoded = decode_auth(gateway.auth_value)
            auth_header = decoded.get("Authorization", "")
            if auth_header:  # Only add header if not empty
                headers["Authorization"] = auth_header

    return headers

