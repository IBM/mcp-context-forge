# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/mcp_servers_router.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

MCP Servers REST API router.

Endpoints:
    POST /v1/mcp-servers/test  — Test MCP server / gateway connectivity
"""

# Standard
from typing import Optional
import uuid

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import get_db
from mcpgateway.middleware.rbac import get_current_user_with_permissions, require_permission
from mcpgateway.schemas import GatewayTestRequest, GatewayTestResponse
from mcpgateway.services.gateway_service import test_gateway_connectivity
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
        >>> _validated_team_id(None)
        >>> _validated_team_id("not-a-uuid")
        Traceback (most recent call last):
            ...
        fastapi.exceptions.HTTPException: 400
    """
    if team_id is None:
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
    return await test_gateway_connectivity(request, team_id, user, db)
