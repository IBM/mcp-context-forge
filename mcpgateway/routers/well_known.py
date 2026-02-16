# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/well_known.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Well-Known URI Handler Router.
This module implements a flexible /.well-known/* endpoint handler that supports
standard well-known URIs like security.txt and robots.txt with user-configurable content.
Defaults assume private API deployment with crawling disabled.
"""

# Standard
from datetime import datetime, timedelta, timezone
import re
from typing import Optional
from urllib.parse import urlparse, urlunparse

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import get_db
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.server_service import ServerError, ServerNotFoundError, ServerService
from mcpgateway.utils.verify_credentials import require_auth

# Get logger instance
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

router = APIRouter(tags=["well-known"])

# UUID validation pattern for RFC 9728 endpoint
UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}$", re.IGNORECASE)

# Well-known URI registry with validation
WELL_KNOWN_REGISTRY = {
    "robots.txt": {"content_type": "text/plain", "description": "Robot exclusion standard", "rfc": "RFC 9309"},
    "security.txt": {"content_type": "text/plain", "description": "Security contact information", "rfc": "RFC 9116"},
    "ai.txt": {"content_type": "text/plain", "description": "AI usage policies", "rfc": "Draft"},
    "dnt-policy.txt": {"content_type": "text/plain", "description": "Do Not Track policy", "rfc": "W3C"},
    "change-password": {"content_type": "text/plain", "description": "Change password URL", "rfc": "RFC 8615"},
}


def get_base_url_with_protocol(request: Request) -> str:
    """
    Build base URL with correct protocol based on proxy headers.

    Uses X-Forwarded-Proto header if present (proxy scenario),
    otherwise falls back to request.url.scheme.

    Note: request.base_url already includes root_path in FastAPI.

    Args:
        request: The FastAPI request object.

    Returns:
        Base URL string with correct protocol, without trailing slash.

    Examples:
        >>> from mcpgateway.routers.well_known import get_base_url_with_protocol
        >>> callable(get_base_url_with_protocol)
        True
    """
    forwarded_proto = request.headers.get("x-forwarded-proto")
    if forwarded_proto:
        proto = forwarded_proto.split(",")[0].strip()
    else:
        proto = request.url.scheme

    parsed = urlparse(str(request.base_url))
    new_parsed = parsed._replace(scheme=proto)
    return str(urlunparse(new_parsed)).rstrip("/")


def validate_security_txt(content: str) -> Optional[str]:
    """Validate security.txt format and add headers if missing.

    Args:
        content: The security.txt content to validate.

    Returns:
        Validated security.txt content with added headers, or None if content is empty.
    """
    if not content:
        return None

    lines = content.strip().split("\n")

    # Check if Expires field exists
    has_expires = any(line.strip().startswith("Expires:") for line in lines)

    # Add Expires field if missing (6 months from now)
    if not has_expires:
        expires = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=180)
        lines.append(f"Expires: {expires.isoformat()}Z")

    # Ensure it starts with required headers
    validated = []

    # Add header comment if not present
    if not lines[0].startswith("#"):
        validated.append("# Security contact information for MCP Gateway")
        validated.append(f"# Generated: {datetime.now(timezone.utc).replace(microsecond=0).isoformat()}Z")
        validated.append("")

    validated.extend(lines)

    return "\n".join(validated)


@router.get("/.well-known/oauth-protected-resource/{path:path}")
async def get_oauth_protected_resource_rfc9728(
    path: str,
    request: Request,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """
    RFC 9728 OAuth 2.0 Protected Resource Metadata endpoint (path-based).

    Per RFC 9728 Section 3.1, the well-known URI is constructed by:
    1. Taking the resource URL: http://localhost:4444/servers/{UUID}/mcp
    2. Removing trailing slash and inserting /.well-known/oauth-protected-resource/
    3. Result: http://localhost:4444/.well-known/oauth-protected-resource/servers/{UUID}/mcp

    This endpoint does not require authentication per RFC 9728 requirements.

    Args:
        path: The resource path after oauth-protected-resource/ (e.g., "servers/{UUID}/mcp")
        request: FastAPI request object for building resource URL
        db: Database session dependency

    Returns:
        JSONResponse with RFC 9728 Protected Resource Metadata:
        {
            "resource": "http://localhost:4444/servers/{UUID}/mcp",
            "authorization_servers": ["https://auth.example.com"],
            "bearer_methods_supported": ["header"],
            "scopes_supported": ["read", "write"]
        }

    Raises:
        HTTPException: 404 if path format invalid, server not found, disabled,
            non-public, OAuth not enabled, or not configured.

    Examples:
        >>> # Request OAuth metadata for a server
        >>> # GET /.well-known/oauth-protected-resource/servers/abc123/mcp
        >>> # Returns RFC 9728 compliant metadata
    """
    if not settings.well_known_enabled:
        raise HTTPException(status_code=404, detail="Not found")

    # Parse path to extract server_id with validation
    # Expected formats:
    #   - "servers/{UUID}/mcp" (standard MCP endpoint)
    #   - "servers/{UUID}" (fallback without /mcp suffix)
    path_parts = path.strip("/").split("/")

    # Validate path structure
    if len(path_parts) < 2 or path_parts[0] != "servers":
        logger.debug(f"Invalid RFC 9728 path format: {path}")
        raise HTTPException(status_code=404, detail="Invalid resource path format. Expected: /.well-known/oauth-protected-resource/servers/{server_id}/mcp")

    server_id = path_parts[1]

    # Validate server_id is a valid UUID (prevents path traversal and injection)
    if not UUID_PATTERN.match(server_id):
        logger.warning(f"Invalid server_id format (not a UUID): {server_id}")
        raise HTTPException(status_code=404, detail="Invalid server_id format. Must be a valid UUID.")

    # Reject paths with extra segments after /mcp (e.g., servers/uuid/mcp/extra)
    if len(path_parts) > 3:
        logger.warning(f"RFC 9728 path has unexpected segments: {path}")
        raise HTTPException(status_code=404, detail="Invalid resource path format. Expected: /.well-known/oauth-protected-resource/servers/{server_id}/mcp")

    # Build resource URL with /mcp suffix per MCP specification
    base_url = get_base_url_with_protocol(request)
    resource_url = f"{base_url}/servers/{server_id}/mcp"

    server_service = ServerService()
    try:
        response_data = server_service.get_oauth_protected_resource_metadata(db=db, server_id=server_id, resource_base_url=resource_url)
    except ServerNotFoundError:
        raise HTTPException(status_code=404, detail="Server not found")
    except ServerError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Add cache headers per RFC 9728 recommendations
    headers = {"Cache-Control": f"public, max-age={settings.well_known_cache_max_age}"}

    logger.debug(f"Served RFC 9728 OAuth metadata for server {server_id}")
    return JSONResponse(content=response_data, headers=headers)


@router.get("/.well-known/oauth-protected-resource")
async def get_oauth_protected_resource(
    request: Request,
    server_id: Optional[str] = None,
):
    """
    DEPRECATED: OAuth 2.0 Protected Resource Metadata endpoint (query parameter based).

    This endpoint is deprecated and non-compliant with RFC 9728. It returns 404.

    RFC 9728 requires path-based discovery, not query parameters.
    Use the RFC 9728 compliant endpoint instead:
    /.well-known/oauth-protected-resource/servers/{server_id}/mcp

    Args:
        request: FastAPI request object (unused).
        server_id: Server ID query parameter (ignored).

    Raises:
        HTTPException: Always raises 404 with deprecation notice.
    """
    if not settings.well_known_enabled:
        raise HTTPException(status_code=404, detail="Not found")

    logger.warning("Deprecated query-param OAuth metadata endpoint called. " "Use RFC 9728 compliant path-based endpoint: " "/.well-known/oauth-protected-resource/servers/{server_id}/mcp")
    raise HTTPException(
        status_code=404, detail=("This endpoint is deprecated and non-compliant with RFC 9728. " "Use the path-based endpoint: " "/.well-known/oauth-protected-resource/servers/{server_id}/mcp")
    )


def get_well_known_file_content(filename: str) -> PlainTextResponse:
    """
    Get the response for a well-known URI file.

    This is a shared helper function used by both the root-level and
    virtual server well-known endpoints.

    Supports:
    - robots.txt: Robot exclusion (default: disallow all)
    - security.txt: Security contact information (if configured)
    - ai.txt: AI usage policies (if configured)
    - dnt-policy.txt: Do Not Track policy (if configured)
    - Custom files: Additional well-known files via configuration

    Args:
        filename: The well-known filename requested (without path prefix).

    Returns:
        PlainTextResponse with the file content.

    Raises:
        HTTPException: 404 if file not found, not configured, or well-known disabled.

    Examples:
        >>> from mcpgateway.routers.well_known import get_well_known_file_content
        >>> callable(get_well_known_file_content)
        True
    """
    if not settings.well_known_enabled:
        raise HTTPException(status_code=404, detail="Not found")

    # Normalize filename (remove any leading slashes)
    filename = filename.strip("/")

    # Prepare common headers
    common_headers = {"Cache-Control": f"public, max-age={settings.well_known_cache_max_age}"}

    # Handle robots.txt
    if filename == "robots.txt":
        headers = {**common_headers, "X-Robots-Tag": "noindex, nofollow"}
        return PlainTextResponse(content=settings.well_known_robots_txt, media_type="text/plain; charset=utf-8", headers=headers)

    # Handle security.txt
    elif filename == "security.txt":
        if not settings.well_known_security_txt_enabled:
            raise HTTPException(status_code=404, detail="security.txt not configured")

        content = validate_security_txt(settings.well_known_security_txt)
        if not content:
            raise HTTPException(status_code=404, detail="security.txt not configured")

        return PlainTextResponse(content=content, media_type="text/plain; charset=utf-8", headers=common_headers)

    # Handle custom files (includes ai.txt, dnt-policy.txt if configured)
    elif filename in settings.custom_well_known_files:
        content = settings.custom_well_known_files[filename]

        # Determine content type
        content_type = "text/plain; charset=utf-8"
        if filename in WELL_KNOWN_REGISTRY:
            content_type = f"{WELL_KNOWN_REGISTRY[filename]['content_type']}; charset=utf-8"

        return PlainTextResponse(content=content, media_type=content_type, headers=common_headers)

    # File not found
    else:
        # Provide helpful error for known well-known URIs
        if filename in WELL_KNOWN_REGISTRY:
            raise HTTPException(status_code=404, detail=f"{filename} is not configured. This is a {WELL_KNOWN_REGISTRY[filename]['description']} file.")
        else:
            raise HTTPException(status_code=404, detail="Not found")


@router.get("/.well-known/{filename:path}", include_in_schema=False)
async def get_well_known_file(filename: str, response: Response, request: Request):
    """
    Serve well-known URI files at the root level.

    Supports:
    - robots.txt: Robot exclusion (default: disallow all)
    - security.txt: Security contact information (if configured)
    - ai.txt: AI usage policies (if configured)
    - dnt-policy.txt: Do Not Track policy (if configured)
    - Custom files: Additional well-known files via configuration

    Args:
        filename: The well-known filename requested
        response: FastAPI response object for headers
        request: FastAPI request object for logging

    Returns:
        Plain text content of the requested file

    Raises:
        HTTPException: 404 if file not found or well-known disabled

    Examples:
        >>> import asyncio
        >>> asyncio.iscoroutinefunction(get_well_known_file)
        True
    """
    return get_well_known_file_content(filename)


@router.get("/admin/well-known", response_model=dict)
async def get_well_known_status(user: str = Depends(require_auth)):
    """
    Get status of well-known URI configuration.

    Args:
        user: Authenticated user from dependency injection.

    Returns:
        Dict containing well-known configuration status and available files.
    """
    configured_files = []

    # Always available
    configured_files.append({"path": "/.well-known/robots.txt", "enabled": True, "description": "Robot exclusion standard", "cache_max_age": settings.well_known_cache_max_age})

    # Conditionally available
    if settings.well_known_security_txt_enabled:
        configured_files.append({"path": "/.well-known/security.txt", "enabled": True, "description": "Security contact information", "cache_max_age": settings.well_known_cache_max_age})

    # Custom files
    for filename in settings.custom_well_known_files:
        configured_files.append({"path": f"/.well-known/{filename}", "enabled": True, "description": "Custom well-known file", "cache_max_age": settings.well_known_cache_max_age})

    return {"enabled": settings.well_known_enabled, "configured_files": configured_files, "supported_files": list(WELL_KNOWN_REGISTRY.keys()), "cache_max_age": settings.well_known_cache_max_age}
