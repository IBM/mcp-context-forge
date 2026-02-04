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
from typing import Optional
from urllib.parse import urlparse, urlunparse

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import get_db
from mcpgateway.db import Server as DbServer
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.utils.verify_credentials import require_auth

# Get logger instance
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

router = APIRouter(tags=["well-known"])

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


@router.get("/.well-known/oauth-protected-resource")
async def get_oauth_protected_resource(
    request: Request,
    server_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    RFC 9728 OAuth 2.0 Protected Resource Metadata endpoint.

    Returns OAuth configuration for a server per RFC 9728, enabling MCP clients
    to discover OAuth authorization servers and authenticate using browser-based SSO.

    Args:
        request: FastAPI request object for building resource URL.
        server_id: The ID of the server to get OAuth configuration for.
        db: Database session dependency.

    Returns:
        JSONResponse with RFC 9728 Protected Resource Metadata.

    Raises:
        HTTPException: 404 if server_id not provided, server not found, disabled,
            non-public, OAuth not enabled, or not configured.

    Examples:
        >>> # Request OAuth metadata for a server
        >>> # GET /.well-known/oauth-protected-resource?server_id=server-123
        >>> # Returns:
        >>> # {
        >>> #   "resource": "https://gateway.example.com/servers/server-123",
        >>> #   "authorization_servers": ["https://idp.example.com"],
        >>> #   "bearer_methods_supported": ["header"],
        >>> #   "scopes_supported": ["openid", "profile"]
        >>> # }
    """
    if not settings.well_known_enabled:
        raise HTTPException(status_code=404, detail="Well-known endpoints are disabled")

    # Return 404 when no server_id to avoid exposing Admin UI SSO configuration
    if not server_id:
        raise HTTPException(status_code=404, detail="Not found")

    server = db.get(DbServer, server_id)

    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    # Return 404 for disabled servers
    if not server.enabled:
        raise HTTPException(status_code=404, detail="Server not found")

    # Only expose OAuth metadata for public servers to avoid leaking metadata
    if getattr(server, "visibility", "public") != "public":
        raise HTTPException(status_code=404, detail="Server not found")

    if not getattr(server, "oauth_enabled", False):
        raise HTTPException(status_code=404, detail="OAuth not enabled for this server")

    oauth_config = getattr(server, "oauth_config", None)
    if not oauth_config:
        raise HTTPException(status_code=404, detail="OAuth not configured for this server")

    # Build RFC 9728 Protected Resource Metadata response
    # Note: get_base_url_with_protocol uses request.base_url which already includes root_path
    base_url = get_base_url_with_protocol(request)
    resource_url = f"{base_url}/servers/{server_id}"

    # Extract authorization server(s) - support both list and single value
    authorization_servers = oauth_config.get("authorization_servers", [])
    if not authorization_servers:
        auth_server = oauth_config.get("authorization_server")
        if auth_server:
            authorization_servers = [auth_server]

    if not authorization_servers:
        raise HTTPException(status_code=404, detail="OAuth authorization_server not configured")

    response_data = {
        "resource": resource_url,
        "authorization_servers": authorization_servers,
        "bearer_methods_supported": ["header"],
    }

    # Add optional scopes if configured (never echo secrets from oauth_config)
    scopes = oauth_config.get("scopes_supported") or oauth_config.get("scopes")
    if scopes:
        response_data["scopes_supported"] = scopes

    # Add cache headers
    headers = {"Cache-Control": f"public, max-age={settings.well_known_cache_max_age}"}

    logger.debug(f"Returning OAuth protected resource metadata for server {server_id}")
    return JSONResponse(content=response_data, headers=headers)


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
