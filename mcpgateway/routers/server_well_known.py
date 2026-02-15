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
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import get_db
from mcpgateway.db import Server as DbServer
from mcpgateway.routers.well_known import get_base_url_with_protocol, get_well_known_file_content
from mcpgateway.services.logging_service import LoggingService

# Get logger instance
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

# Router without prefix - will be mounted at /servers in main.py
router = APIRouter(tags=["Servers"])


@router.get("/{server_id}/.well-known/oauth-protected-resource")
async def server_oauth_protected_resource(
    request: Request,
    server_id: str,
):
    """
    DEPRECATED: OAuth 2.0 Protected Resource Metadata endpoint (server-scoped, non-compliant).

    This endpoint is deprecated and non-compliant with RFC 9728. It returns a 301 redirect.

    RFC 9728 Section 3.1 requires the well-known path to be constructed by inserting
    /.well-known/oauth-protected-resource/ into the resource URL, not appending it.

    Old (non-compliant): /servers/{server_id}/.well-known/oauth-protected-resource
    New (RFC 9728):      /.well-known/oauth-protected-resource/servers/{server_id}/mcp

    Args:
        request: FastAPI request object for building redirect URL.
        server_id: The ID of the server.

    Raises:
        HTTPException: 404 if well-known disabled, 301 redirect to compliant endpoint.
    """
    if not settings.well_known_enabled:
        raise HTTPException(status_code=404, detail="Not found")

    # Build RFC 9728 compliant redirect URL
    base_url = get_base_url_with_protocol(request)
    compliant_url = f"{base_url}/.well-known/oauth-protected-resource/servers/{server_id}/mcp"

    logger.warning(f"Deprecated server-scoped OAuth metadata endpoint called for server {server_id}. " f"Redirecting to RFC 9728 compliant endpoint: {compliant_url}")

    # Return 301 Permanent Redirect
    raise HTTPException(status_code=301, detail="Moved Permanently", headers={"Location": compliant_url})


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
