# -*- coding: utf-8 -*-
"""
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

MCP Gateway - Main FastAPI Application.

This module defines the core FastAPI application for the Model Context Protocol (MCP) Gateway.
It serves as the entry point for handling all HTTP and WebSocket traffic.

Features and Responsibilities:
- Initializes and orchestrates services for tools, resources, prompts, servers, gateways, and roots.
- Supports full MCP protocol operations: initialize, ping, notify, complete, and sample.
- Integrates authentication (JWT and basic), CORS, caching, and middleware.
- Serves a rich Admin UI for managing gateway entities via HTMX-based frontend.
- Exposes routes for JSON-RPC, SSE, and WebSocket transports.
- Manages application lifecycle including startup and graceful shutdown of all services.

Structure:
- Declares routers for MCP protocol operations and administration.
- Registers dependencies (e.g., DB sessions, auth handlers).
- Applies middleware including custom documentation protection.
- Configures resource caching and session registry using pluggable backends.
- Provides OpenAPI metadata and redirect handling depending on UI feature flags.
"""

# Standard
from typing import Any, Dict, List, Optional

# Third-Party
from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import get_db
from mcpgateway.dependencies import get_export_service, get_import_service, get_logging_service
from mcpgateway.services.export_service import ExportError
from mcpgateway.services.import_service import ConflictStrategy, ImportConflictError
from mcpgateway.services.import_service import ImportError as ImportServiceError
from mcpgateway.services.import_service import ImportValidationError
from mcpgateway.utils.verify_credentials import require_auth

export_import_router = APIRouter(tags=["Export/Import"])

# Initialize logging service first
logging_service = get_logging_service()
logger = logging_service.get_logger("export import router")

export_service = get_export_service()
import_service = get_import_service()


@export_import_router.get("/export", response_model=Dict[str, Any])
async def export_configuration(
    export_format: str = "json",  # pylint: disable=unused-argument
    types: Optional[str] = None,
    exclude_types: Optional[str] = None,
    tags: Optional[str] = None,
    include_inactive: bool = False,
    include_dependencies: bool = True,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> Dict[str, Any]:
    """
    Export gateway configuration to JSON format.

    Args:
        export_format: Export format (currently only 'json' supported)
        types: Comma-separated list of entity types to include (tools,gateways,servers,prompts,resources,roots)
        exclude_types: Comma-separated list of entity types to exclude
        tags: Comma-separated list of tags to filter by
        include_inactive: Whether to include inactive entities
        include_dependencies: Whether to include dependent entities
        db: Database session
        user: Authenticated user

    Returns:
        Export data in the specified format

    Raises:
        HTTPException: If export fails
    """
    try:
        logger.info(f"User {user} requested configuration export")

        # Parse parameters
        include_types = None
        if types:
            include_types = [t.strip() for t in types.split(",") if t.strip()]

        exclude_types_list = None
        if exclude_types:
            exclude_types_list = [t.strip() for t in exclude_types.split(",") if t.strip()]

        tags_list = None
        if tags:
            tags_list = [t.strip() for t in tags.split(",") if t.strip()]

        # Extract username from user (which could be string or dict with token)
        username = user if isinstance(user, str) else user.get("username", "unknown")

        # Perform export
        export_data = await export_service.export_configuration(
            db=db, include_types=include_types, exclude_types=exclude_types_list, tags=tags_list, include_inactive=include_inactive, include_dependencies=include_dependencies, exported_by=username
        )

        return export_data

    except ExportError as e:
        logger.error(f"Export failed for user {user}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected export error for user {user}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")


@export_import_router.post("/export/selective", response_model=Dict[str, Any])
async def export_selective_configuration(
    entity_selections: Dict[str, List[str]] = Body(...), include_dependencies: bool = True, db: Session = Depends(get_db), user: str = Depends(require_auth)
) -> Dict[str, Any]:
    """
    Export specific entities by their IDs/names.

    Args:
        entity_selections: Dict mapping entity types to lists of IDs/names to export
        include_dependencies: Whether to include dependent entities
        db: Database session
        user: Authenticated user

    Returns:
        Selective export data

    Raises:
        HTTPException: If export fails

    Example request body:
        {
            "tools": ["tool1", "tool2"],
            "servers": ["server1"],
            "prompts": ["prompt1"]
        }
    """
    try:
        logger.info(f"User {user} requested selective configuration export")

        # Extract username from user (which could be string or dict with token)
        username = user if isinstance(user, str) else user.get("username", "unknown")

        export_data = await export_service.export_selective(db=db, entity_selections=entity_selections, include_dependencies=include_dependencies, exported_by=username)

        return export_data

    except ExportError as e:
        logger.error(f"Selective export failed for user {user}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected selective export error for user {user}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")


@export_import_router.post("/import", response_model=Dict[str, Any])
async def import_configuration(
    import_data: Dict[str, Any] = Body(...),
    conflict_strategy: str = "update",
    dry_run: bool = False,
    rekey_secret: Optional[str] = None,
    selected_entities: Optional[Dict[str, List[str]]] = None,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> Dict[str, Any]:
    """
    Import configuration data with conflict resolution.

    Args:
        import_data: The configuration data to import
        conflict_strategy: How to handle conflicts: skip, update, rename, fail
        dry_run: If true, validate but don't make changes
        rekey_secret: New encryption secret for cross-environment imports
        selected_entities: Dict of entity types to specific entity names/ids to import
        db: Database session
        user: Authenticated user

    Returns:
        Import status and results

    Raises:
        HTTPException: If import fails or validation errors occur
    """
    try:
        logger.info(f"User {user} requested configuration import (dry_run={dry_run})")

        # Validate conflict strategy
        try:
            strategy = ConflictStrategy(conflict_strategy.lower())
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid conflict strategy. Must be one of: {[s.value for s in ConflictStrategy]}")

        # Extract username from user (which could be string or dict with token)
        username = user if isinstance(user, str) else user.get("username", "unknown")

        # Perform import
        import_status = await import_service.import_configuration(
            db=db, import_data=import_data, conflict_strategy=strategy, dry_run=dry_run, rekey_secret=rekey_secret, imported_by=username, selected_entities=selected_entities
        )

        return import_status.to_dict()

    except ImportValidationError as e:
        logger.error(f"Import validation failed for user {user}: {str(e)}")
        raise HTTPException(status_code=422, detail=f"Validation error: {str(e)}")
    except ImportConflictError as e:
        logger.error(f"Import conflict for user {user}: {str(e)}")
        raise HTTPException(status_code=409, detail=f"Conflict error: {str(e)}")
    except ImportServiceError as e:
        logger.error(f"Import failed for user {user}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected import error for user {user}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}")


@export_import_router.get("/import/status/{import_id}", response_model=Dict[str, Any])
async def get_import_status(import_id: str, user: str = Depends(require_auth)) -> Dict[str, Any]:
    """
    Get the status of an import operation.

    Args:
        import_id: The import operation ID
        user: Authenticated user

    Returns:
        Import status information

    Raises:
        HTTPException: If import not found
    """
    logger.debug(f"User {user} requested import status for {import_id}")

    import_status = import_service.get_import_status(import_id)
    if not import_status:
        raise HTTPException(status_code=404, detail=f"Import {import_id} not found")

    return import_status.to_dict()


@export_import_router.get("/import/status", response_model=List[Dict[str, Any]])
async def list_import_statuses(user: str = Depends(require_auth)) -> List[Dict[str, Any]]:
    """
    List all import operation statuses.

    Args:
        user: Authenticated user

    Returns:
        List of import status information
    """
    logger.debug(f"User {user} requested all import statuses")

    statuses = import_service.list_import_statuses()
    return [status.to_dict() for status in statuses]


@export_import_router.post("/import/cleanup", response_model=Dict[str, Any])
async def cleanup_import_statuses(max_age_hours: int = 24, user: str = Depends(require_auth)) -> Dict[str, Any]:
    """
    Clean up completed import statuses older than specified age.

    Args:
        max_age_hours: Maximum age in hours for keeping completed imports
        user: Authenticated user

    Returns:
        Cleanup results
    """
    logger.info(f"User {user} requested import status cleanup (max_age_hours={max_age_hours})")

    removed_count = import_service.cleanup_completed_imports(max_age_hours)
    return {"status": "success", "message": f"Cleaned up {removed_count} completed import statuses", "removed_count": removed_count}
