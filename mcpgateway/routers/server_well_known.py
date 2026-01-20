# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/server_well_known.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Virtual Server Well-Known URI Handler Router.

This module implements well-known URI endpoints for virtual servers at
/servers/{server_id}/.well-known/* paths. It supports:
- oauth-protected-resource (RFC 9728 OAuth Protected Resource Metadata)
- robots.txt, security.txt, ai.txt, dnt-policy.txt (shared with root endpoints)

These endpoints allow MCP clients to discover OAuth configuration and other
metadata specific to individual virtual servers.
"""

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import get_db
from mcpgateway.db import Server as DbServer
from mcpgateway.routers.well_known import get_base_url_with_protocol, get_well_known_file_content
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.server_service import ServerError, ServerNotFoundError, ServerService

# Get logger instance
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

# Initialize services
server_service = ServerService()

# Router without prefix - will be mounted at /servers in main.py
router = APIRouter(tags=["Servers"])


@router.get("/{server_id}/.well-known/oauth-protected-resource")
async def server_oauth_protected_resource(
    request: Request,
    server_id: str,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """
    RFC 9728 OAuth 2.0 Protected Resource Metadata endpoint for a specific server.

    Returns OAuth configuration for the server per RFC 9728, enabling MCP clients
    to discover OAuth authorization servers and authenticate using browser-based SSO.
    This endpoint does not require authentication per RFC 9728 requirements.

    Args:
        request: FastAPI request object for building resource URL.
        server_id: The ID of the server to get OAuth configuration for.
        db: Database session dependency.

    Returns:
        JSONResponse with RFC 9728 Protected Resource Metadata.

    Raises:
        HTTPException: 404 if server not found, disabled, non-public, OAuth not enabled, or not configured.
    """
    # Check global well-known toggle first to respect admin configuration
    if not settings.well_known_enabled:
        raise HTTPException(status_code=404, detail="Not found")

    # Build resource URL using proper protocol detection for proxies
    # Note: get_base_url_with_protocol uses request.base_url which already includes root_path
    base_url = get_base_url_with_protocol(request)
    resource_url = f"{base_url}/servers/{server_id}"

    try:
        response_data = server_service.get_oauth_protected_resource_metadata(db, server_id, resource_url)
    except ServerNotFoundError:
        raise HTTPException(status_code=404, detail="Server not found")
    except ServerError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Add cache headers
    headers = {"Cache-Control": f"public, max-age={settings.well_known_cache_max_age}"}

    return JSONResponse(content=response_data, headers=headers)


@router.get("/{server_id}/.well-known/{filename:path}", include_in_schema=False)
async def server_well_known_file(
    server_id: str,
    filename: str,
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    """
    Serve well-known URI files for a specific virtual server.

    Returns the same well-known files as the root endpoint (robots.txt, security.txt,
    ai.txt, dnt-policy.txt) but scoped to a virtual server path. This allows MCP clients
    to discover these files at the virtual server level.

    The endpoint validates that the server exists and is publicly accessible before
    serving the file. This avoids leaking information about private/team servers.

    Args:
        server_id: The ID of the virtual server.
        filename: The well-known filename requested (e.g., "robots.txt").
        db: Database session dependency.

    Returns:
        PlainTextResponse with the file content.

    Raises:
        HTTPException: 404 if server not found, disabled, non-public, or file not configured.
    """
    # Check global well-known toggle first to avoid leaking server existence
    if not settings.well_known_enabled:
        raise HTTPException(status_code=404, detail="Not found")

    # Validate server exists and is publicly accessible
    server = db.get(DbServer, server_id)

    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    if not server.enabled:
        raise HTTPException(status_code=404, detail="Server not found")

    if getattr(server, "visibility", "public") != "public":
        raise HTTPException(status_code=404, detail="Server not found")

    # Use shared helper to get the file content
    return get_well_known_file_content(filename)
