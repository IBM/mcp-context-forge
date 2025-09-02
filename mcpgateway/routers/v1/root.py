# -*- coding: utf-8 -*-
"""
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

MCP Gateway - Roots API Router.

This module provides REST API endpoints for managing root URIs in the MCP Gateway.
Roots represent base URIs that serve as entry points for resource discovery and navigation.

Features and Responsibilities:
- CRUD operations for root URI management (create, read, delete)
- Real-time change notifications via Server-Sent Events (SSE)
- URI-based root addressing with path parameter support
- Root service integration for centralized management
- Authentication enforcement for all operations
- Comprehensive logging for audit and debugging

Endpoints:
- GET /roots: List all registered root URIs
- POST /roots: Add new root URI with name
- DELETE /roots/{uri:path}: Remove root by URI
- GET /roots/changes: Subscribe to real-time root changes via SSE

Parameters:
- All endpoints require authentication via JWT Bearer token or Basic Auth
- URI paths support nested addressing for hierarchical roots
- SSE endpoint provides continuous streaming of change events

Returns:
- List endpoint returns array of Root objects with URI and name
- Add endpoint returns the newly created Root object
- Delete endpoint returns success status message
- Changes endpoint returns StreamingResponse with event-stream media type
"""

# Standard
from typing import Dict, List

# Third-Party
from fastapi import (
    APIRouter,
    Depends,
)
from fastapi.responses import StreamingResponse

# First-Party
# Import dependency injection functions
from mcpgateway.dependencies import get_root_service
from mcpgateway.models import (
    Root,
)
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.utils.verify_credentials import require_auth

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger("root routers")

# Initialize services
root_service = get_root_service()

# Create API router
root_router = APIRouter(prefix="/roots", tags=["Roots"])


@root_router.get("", response_model=List[Root])
@root_router.get("/", response_model=List[Root])
async def list_roots(
    user: str = Depends(require_auth),
) -> List[Root]:
    """
    Retrieve a list of all registered roots.

    Args:
        user: Authenticated user.

    Returns:
        List of Root objects.
    """
    logger.debug(f"User '{user}' requested list of roots")
    return await root_service.list_roots()


@root_router.post("", response_model=Root)
@root_router.post("/", response_model=Root)
async def add_root(
    root: Root,  # Accept JSON body using the Root model from models.py
    user: str = Depends(require_auth),
) -> Root:
    """
    Add a new root.

    Args:
        root: Root object containing URI and name.
        user: Authenticated user.

    Returns:
        The added Root object.
    """
    logger.debug(f"User '{user}' requested to add root: {root}")
    return await root_service.add_root(str(root.uri), root.name)


@root_router.delete("/{uri:path}")
async def remove_root(
    uri: str,
    user: str = Depends(require_auth),
) -> Dict[str, str]:
    """
    Remove a registered root by URI.

    Args:
        uri: URI of the root to remove.
        user: Authenticated user.

    Returns:
        Status message indicating result.
    """
    logger.debug(f"User '{user}' requested to remove root with URI: {uri}")
    await root_service.remove_root(uri)
    return {"status": "success", "message": f"Root {uri} removed"}


@root_router.get("/changes")
async def subscribe_roots_changes(
    user: str = Depends(require_auth),
) -> StreamingResponse:
    """
    Subscribe to real-time changes in root list via Server-Sent Events (SSE).

    Args:
        user: Authenticated user.

    Returns:
        StreamingResponse with event-stream media type.
    """
    logger.debug(f"User '{user}' subscribed to root changes stream")
    return StreamingResponse(root_service.subscribe_changes(), media_type="text/event-stream")
