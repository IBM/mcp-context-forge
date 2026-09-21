# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/mcp_servers_router.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

MCP Servers REST API router.

Endpoints:
    POST /v1/mcp-servers/test            — Test MCP server / gateway connectivity
    POST /v1/mcp-servers/test-handshake  — Test whether a server URL speaks MCP
"""

# Standard
from typing import Optional
import uuid

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.auth_context import extract_token_team_ids
from mcpgateway.db import get_db
from mcpgateway.middleware.rbac import get_current_user_with_permissions, require_permission
from mcpgateway.schemas import GatewayHandshakeRequest, GatewayHandshakeResponse, GatewayTestRequest, GatewayTestResponse
from mcpgateway.services.gateway_service import test_gateway_connectivity, test_gateway_handshake
from mcpgateway.services.logging_service import LoggingService

logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

router = APIRouter(prefix="/v1/mcp-servers", tags=["MCP Servers"])


def _validated_team_id(team_id: Optional[str] = Query(None, description="Filter by team ID")) -> Optional[str]:
    """Validate and normalize team_id query parameter.

    Args:
        team_id: Raw team ID from query params.

    Returns:
        Normalized team ID hex string or None.

    Raises:
        HTTPException: If the team ID is not a valid UUID.

    Examples:
        >>> _validated_team_id(None) is None
        True
        >>> _validated_team_id("") is None
        True
        >>> try:
        ...     _validated_team_id("not-a-uuid")
        ... except Exception as e:
        ...     e.status_code
        400
    """
    # Match admin _normalize_team_id: empty string means "no filter"
    if not team_id:
        return None
    try:
        return uuid.UUID(str(team_id)).hex
    except (ValueError, AttributeError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid team ID") from exc


@router.post("/test", response_model=GatewayTestResponse)
@require_permission("gateways.read", allow_admin_bypass=False)
async def check_mcp_server_connectivity(
    request: GatewayTestRequest,
    team_id: Optional[str] = Depends(_validated_team_id),
    user=Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> GatewayTestResponse:
    """Test MCP server / gateway connectivity.

    Delegates to the shared ``test_gateway_connectivity`` implementation in
    ``mcpgateway.services.gateway_service``, which handles SSRF protection,
    DNS-pinning, OAuth token acquisition, and structured logging.

    Args:
        request (GatewayTestRequest): The request object containing the gateway URL and request details.
        team_id (Optional[str]): Optional team ID for team-specific gateways.
        user: Authenticated user context.
        db (Session): Database session dependency.

    Returns:
        GatewayTestResponse: The response from the gateway, including status code, latency, and body.

    Examples:
        >>> callable(check_mcp_server_connectivity)
        True
        >>> check_mcp_server_connectivity.__name__
        'check_mcp_server_connectivity'
    """
    # Reject cross-team access: token_teams=None means admin bypass; a list means the
    # caller is scoped to those teams only. A caller-supplied team_id outside that list
    # would allow enumerating other teams' registered gateway hostnames (SSRF allowlist).
    if team_id is not None:
        token_teams = user.get("token_teams") if isinstance(user, dict) else None
        if token_teams is not None and team_id not in token_teams:
            raise HTTPException(status_code=403, detail="Access to requested team is not permitted")

    return await test_gateway_connectivity(request, team_id, user, db)


@router.post("/test-handshake", response_model=GatewayHandshakeResponse)
@require_permission("gateways.read", allow_admin_bypass=False)
async def check_mcp_server_handshake(
    request: GatewayHandshakeRequest,
    team_id: Optional[str] = Depends(_validated_team_id),
    user=Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> GatewayHandshakeResponse:
    """Test whether an MCP server URL speaks MCP via a protocol handshake.

    Delegates to ``test_gateway_handshake`` in
    ``mcpgateway.services.gateway_service``, which tries the stateless
    ``server/discover`` method first and falls back to a stateful SDK
    ``initialize`` round-trip, classifying failures for actionable UI copy.

    Args:
        request (GatewayHandshakeRequest): The request object containing the server URL and optional headers.
        team_id (Optional[str]): Optional team ID for team-specific gateways.
        user: Authenticated user context.
        db (Session): Database session dependency.

    Returns:
        GatewayHandshakeResponse: The handshake outcome, including negotiation path,
            server identity, capabilities, component counts, and failure classification.

    Examples:
        >>> callable(check_mcp_server_handshake)
        True
        >>> check_mcp_server_handshake.__name__
        'check_mcp_server_handshake'
    """
    # Reject cross-team access: token_teams=None means admin bypass; a list means the
    # caller is scoped to those teams only. A caller-supplied team_id outside that list
    # would allow enumerating other teams' registered gateway hostnames (SSRF allowlist).
    if team_id is not None:
        token_teams = extract_token_team_ids(user)
        if token_teams is not None and team_id not in token_teams:
            raise HTTPException(status_code=403, detail="Access to requested team is not permitted")

    return await test_gateway_handshake(request, team_id, user, db)
