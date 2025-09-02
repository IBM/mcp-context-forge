# -*- coding: utf-8 -*-
"""
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

MCP Gateway - Metrics API Router.

This module provides REST API endpoints for retrieving and managing performance metrics
across all MCP Gateway entities including tools, resources, servers, and prompts.

Features and Responsibilities:
- Aggregates metrics from all entity services (tools, resources, servers, prompts)
- Provides endpoints for retrieving consolidated performance data
- Supports selective and global metrics reset functionality
- Enforces authentication for all metrics operations
- Logs all metrics access and modification operations for audit purposes

Endpoints:
- GET /metrics: Retrieve aggregated metrics for all entity types
- POST /metrics/reset: Reset metrics for specific entities or globally

Parameters:
- All endpoints require authentication via JWT Bearer token or Basic Auth
- Reset endpoint accepts optional entity type and entity ID filters

Returns:
- Metrics endpoint returns dictionary with aggregated statistics per entity type
- Reset endpoint returns success confirmation with operation details
"""

# Standard
from typing import Optional

# Third-Party
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
)
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import get_db

# Import dependency injection functions
from mcpgateway.dependencies import (
    get_a2a_agent_service,
    get_logging_service,
    get_prompt_service,
    get_resource_service,
    get_server_service,
    get_tool_service,
)
from mcpgateway.utils.verify_credentials import require_auth

# Import the admin routes from the new module


# Initialize logging service first
logging_service = get_logging_service()
logger = logging_service.get_logger("mcpgateway")


# Initialize services
tool_service = get_tool_service()
resource_service = get_resource_service()
server_service = get_server_service()
prompt_service = get_prompt_service()
a2a_service = get_a2a_agent_service()

# Create API router
metrics_router = APIRouter(prefix="/metrics", tags=["Metrics"])


@metrics_router.get("", response_model=dict)
async def get_metrics(db: Session = Depends(get_db), user: str = Depends(require_auth)) -> dict:
    """
    Retrieve aggregated metrics for all entity types (Tools, Resources, Servers, Prompts, A2A Agents).

    Args:
        db: Database session
        user: Authenticated user

    Returns:
        A dictionary with keys for each entity type and their aggregated metrics.
    """
    logger.debug(f"User {user} requested aggregated metrics")
    tool_metrics = await tool_service.aggregate_metrics(db)
    resource_metrics = await resource_service.aggregate_metrics(db)
    server_metrics = await server_service.aggregate_metrics(db)
    prompt_metrics = await prompt_service.aggregate_metrics(db)

    metrics_result = {
        "tools": tool_metrics,
        "resources": resource_metrics,
        "servers": server_metrics,
        "prompts": prompt_metrics,
    }

    # Include A2A metrics only if A2A features are enabled
    if a2a_service and settings.mcpgateway_a2a_metrics_enabled:
        a2a_metrics = await a2a_service.aggregate_metrics(db)
        metrics_result["a2a_agents"] = a2a_metrics

    return metrics_result


@metrics_router.post("/reset", response_model=dict)
async def reset_metrics(entity: Optional[str] = None, entity_id: Optional[int] = None, db: Session = Depends(get_db), user: str = Depends(require_auth)) -> dict:
    """
    Reset metrics for a specific entity type and optionally a specific entity ID,
    or perform a global reset if no entity is specified.

    Args:
        entity: One of "tool", "resource", "server", "prompt", "a2a_agent", or None for global reset.
        entity_id: Specific entity ID to reset metrics for (optional).
        db: Database session
        user: Authenticated user

    Returns:
        A success message in a dictionary.

    Raises:
        HTTPException: If an invalid entity type is specified.
    """
    logger.debug(f"User {user} requested metrics reset for entity: {entity}, id: {entity_id}")
    if entity is None:
        # Global reset
        await tool_service.reset_metrics(db)
        await resource_service.reset_metrics(db)
        await server_service.reset_metrics(db)
        await prompt_service.reset_metrics(db)
        if a2a_service and settings.mcpgateway_a2a_metrics_enabled:
            await a2a_service.reset_metrics(db)
    elif entity.lower() == "tool":
        await tool_service.reset_metrics(db, entity_id)
    elif entity.lower() == "resource":
        await resource_service.reset_metrics(db)
    elif entity.lower() == "server":
        await server_service.reset_metrics(db)
    elif entity.lower() == "prompt":
        await prompt_service.reset_metrics(db)
    elif entity.lower() in ("a2a_agent", "a2a"):
        if a2a_service and settings.mcpgateway_a2a_metrics_enabled:
            await a2a_service.reset_metrics(db, entity_id)
        else:
            raise HTTPException(status_code=400, detail="A2A features are disabled")
    else:
        raise HTTPException(status_code=400, detail="Invalid entity type for metrics reset")
    return {"status": "success", "message": f"Metrics reset for {entity if entity else 'all entities'}"}
