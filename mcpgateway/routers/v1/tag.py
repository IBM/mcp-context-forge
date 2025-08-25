# -*- coding: utf-8 -*-
"""
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

MCP Gateway - Tags API Router.

This module provides REST API endpoints for managing and querying tags across all
MCP Gateway entities (tools, resources, prompts, servers, gateways). Tags enable
categorization, filtering, and discovery of related entities.

Features and Responsibilities:
- Cross-entity tag aggregation and statistics
- Tag-based entity discovery and filtering
- Entity type filtering for targeted queries
- Tag usage statistics and metadata
- Comprehensive error handling with proper HTTP status codes
- Authentication enforcement for all operations

Endpoints:
- GET /tags: List all unique tags with optional entity type filtering
- GET /tags/{tag_name}/entities: Get all entities with specific tag

Parameters:
- All endpoints require authentication via JWT Bearer token or Basic Auth
- Entity type filtering supports comma-separated lists (tools,resources,prompts,servers,gateways)
- Optional inclusion of entity lists for comprehensive tag information

Returns:
- List tags endpoint returns array of TagInfo objects with statistics
- Entity lookup endpoint returns array of TaggedEntity objects
- Both endpoints support filtering by entity types for targeted results
"""

# Standard
from typing import List, Optional

# Third-Party
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
)
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import get_db

# Import dependency injection functions
from mcpgateway.dependencies import get_tag_service
from mcpgateway.schemas import (
    TaggedEntity,
    TagInfo,
)
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.utils.verify_credentials import require_auth

# Import the admin routes from the new module


# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger("tag routes")


# Initialize service
tag_service = get_tag_service()

# Create API router
tag_router = APIRouter(prefix="/tags", tags=["Tags"])


# APIs
@tag_router.get("", response_model=List[TagInfo])
@tag_router.get("/", response_model=List[TagInfo])
async def list_tags(
    entity_types: Optional[str] = None,
    include_entities: bool = False,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> List[TagInfo]:
    """
    Retrieve all unique tags across specified entity types.

    Args:
        entity_types: Comma-separated list of entity types to filter by
                     (e.g., "tools,resources,prompts,servers,gateways").
                     If not provided, returns tags from all entity types.
        include_entities: Whether to include the list of entities that have each tag
        db: Database session
        user: Authenticated user

    Returns:
        List of TagInfo objects containing tag names, statistics, and optionally entities

    Raises:
        HTTPException: If tag retrieval fails
    """
    # Parse entity types parameter if provided
    entity_types_list = None
    if entity_types:
        entity_types_list = [et.strip().lower() for et in entity_types.split(",") if et.strip()]

    logger.debug(f"User {user} is retrieving tags for entity types: {entity_types_list}, include_entities: {include_entities}")

    try:
        tags = await tag_service.get_all_tags(db, entity_types=entity_types_list, include_entities=include_entities)
        return tags
    except Exception as e:
        logger.error(f"Failed to retrieve tags: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve tags: {str(e)}")


@tag_router.get("/{tag_name}/entities", response_model=List[TaggedEntity])
async def get_entities_by_tag(
    tag_name: str,
    entity_types: Optional[str] = None,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> List[TaggedEntity]:
    """
    Get all entities that have a specific tag.

    Args:
        tag_name: The tag to search for
        entity_types: Comma-separated list of entity types to filter by
                     (e.g., "tools,resources,prompts,servers,gateways").
                     If not provided, returns entities from all types.
        db: Database session
        user: Authenticated user

    Returns:
        List of TaggedEntity objects

    Raises:
        HTTPException: If entity retrieval fails
    """
    # Parse entity types parameter if provided
    entity_types_list = None
    if entity_types:
        entity_types_list = [et.strip().lower() for et in entity_types.split(",") if et.strip()]

    logger.debug(f"User {user} is retrieving entities for tag '{tag_name}' with entity types: {entity_types_list}")

    try:
        entities = await tag_service.get_entities_by_tag(db, tag_name=tag_name, entity_types=entity_types_list)
        return entities
    except Exception as e:
        logger.error(f"Failed to retrieve entities for tag '{tag_name}': {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve entities: {str(e)}")
