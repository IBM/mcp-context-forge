# -*- coding: utf-8 -*-
"""
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

MCP Gateway - Agent-to-Agent (A2A) API Router.

This module implements REST endpoints for managing Agent-to-Agent communication
within the MCP Gateway ecosystem. It provides CRUD operations and invocation
capabilities for A2A agents that enable autonomous agent interactions.

Features and Responsibilities:
- A2A agent registration, discovery, and lifecycle management
- Agent invocation with parameter passing and interaction type specification
- Status management (activate/deactivate) for agent availability control
- Tag-based filtering and categorization of agents
- Metadata tracking for audit trails and provenance
- Integration with authentication and authorization systems
- Error handling with appropriate HTTP status codes and messages

Endpoints:
- GET /a2a: List all registered A2A agents with optional filtering
- GET /a2a/{agent_id}: Retrieve specific agent details by ID
- POST /a2a: Register new A2A agent with configuration
- PUT /a2a/{agent_id}: Update existing agent configuration
- POST /a2a/{agent_id}/toggle: Activate or deactivate agent
- DELETE /a2a/{agent_id}: Remove agent from registry
- POST /a2a/{agent_name}/invoke: Execute agent with parameters

Parameters:
- All endpoints require authentication via JWT Bearer token or Basic Auth
- Agent configurations include name, description, capabilities, and connection details
- Invocation supports different interaction types (query, execute, etc.)
- Metadata automatically captured for creation and modification tracking

Returns:
- Standard REST responses with appropriate HTTP status codes
- Agent objects following A2AAgentRead schema for consistency
- Error responses with detailed messages for troubleshooting
- Invocation results as flexible JSON structures
"""

# Standard
from typing import Any, Dict, List, Optional

# Third-Party
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import get_db
from mcpgateway.dependencies import get_a2a_agent_service, get_logging_service
from mcpgateway.schemas import (
    A2AAgentCreate,
    A2AAgentRead,
    A2AAgentUpdate,
)
from mcpgateway.services.a2a_service import A2AAgentError, A2AAgentNameConflictError, A2AAgentNotFoundError
from mcpgateway.utils.error_formatter import ErrorFormatter
from mcpgateway.utils.metadata_capture import MetadataCapture
from mcpgateway.utils.verify_credentials import require_auth

# Initialize logging service first
logging_service = get_logging_service()
logger = logging_service.get_logger("a2a routes")

# Initialize A2A service only if A2A features are enabled
a2a_service = get_a2a_agent_service()

# Create API router
a2a_router = APIRouter(prefix="/a2a", tags=["A2A Agents"])


@a2a_router.get("", response_model=List[A2AAgentRead])
@a2a_router.get("/", response_model=List[A2AAgentRead])
async def list_a2a_agents(
    include_inactive: bool = False,
    tags: Optional[str] = None,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> List[A2AAgentRead]:
    """
    Lists all A2A agents in the system, optionally including inactive ones.

    Args:
        include_inactive: Whether to include inactive agents in the response.
        tags: Comma-separated list of tags to filter by.
        db: The database session used to interact with the data store.
        user: The authenticated user making the request.

    Returns:
        List[A2AAgentRead]: A list of A2A agent objects.
    """
    # Parse tags parameter if provided
    tags_list = None
    if tags:
        tags_list = [tag.strip() for tag in tags.split(",") if tag.strip()]

    logger.debug(f"User {user} requested A2A agent list with tags={tags_list}")
    return await a2a_service.list_agents(db, include_inactive=include_inactive, tags=tags_list)


@a2a_router.get("/{agent_id}", response_model=A2AAgentRead)
async def get_a2a_agent(agent_id: str, db: Session = Depends(get_db), user: str = Depends(require_auth)) -> A2AAgentRead:
    """
    Retrieves an A2A agent by its ID.

    Args:
        agent_id: The ID of the agent to retrieve.
        db: The database session used to interact with the data store.
        user: The authenticated user making the request.

    Returns:
        A2AAgentRead: The agent object with the specified ID.

    Raises:
        HTTPException: If the agent is not found.
    """
    try:
        logger.debug(f"User {user} requested A2A agent with ID {agent_id}")
        return await a2a_service.get_agent(db, agent_id)
    except A2AAgentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@a2a_router.post("", response_model=A2AAgentRead, status_code=201)
@a2a_router.post("/", response_model=A2AAgentRead, status_code=201)
async def create_a2a_agent(
    agent: A2AAgentCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> A2AAgentRead:
    """
    Creates a new A2A agent.

    Args:
        agent: The data for the new agent.
        request: The FastAPI request object for metadata extraction.
        db: The database session used to interact with the data store.
        user: The authenticated user making the request.

    Returns:
        A2AAgentRead: The created agent object.

    Raises:
        HTTPException: If there is a conflict with the agent name or other errors.
    """
    try:
        logger.debug(f"User {user} is creating a new A2A agent")
        # Extract metadata from request
        metadata = MetadataCapture.extract_creation_metadata(request, user)

        return await a2a_service.register_agent(
            db,
            agent,
            created_by=metadata["created_by"],
            created_from_ip=metadata["created_from_ip"],
            created_via=metadata["created_via"],
            created_user_agent=metadata["created_user_agent"],
            import_batch_id=metadata["import_batch_id"],
            federation_source=metadata["federation_source"],
        )
    except A2AAgentNameConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except A2AAgentError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValidationError as e:
        logger.error(f"Validation error while creating A2A agent: {e}")
        raise HTTPException(status_code=422, detail=ErrorFormatter.format_validation_error(e))
    except IntegrityError as e:
        logger.error(f"Integrity error while creating A2A agent: {e}")
        raise HTTPException(status_code=409, detail=ErrorFormatter.format_database_error(e))


@a2a_router.put("/{agent_id}", response_model=A2AAgentRead)
async def update_a2a_agent(
    agent_id: str,
    agent: A2AAgentUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> A2AAgentRead:
    """
    Updates the information of an existing A2A agent.

    Args:
        agent_id: The ID of the agent to update.
        agent: The updated agent data.
        request: The FastAPI request object for metadata extraction.
        db: The database session used to interact with the data store.
        user: The authenticated user making the request.

    Returns:
        A2AAgentRead: The updated agent object.

    Raises:
        HTTPException: If the agent is not found, there is a name conflict, or other errors.
    """
    try:
        logger.debug(f"User {user} is updating A2A agent with ID {agent_id}")
        # Extract modification metadata
        mod_metadata = MetadataCapture.extract_modification_metadata(request, user, 0)  # Version will be incremented in service

        return await a2a_service.update_agent(
            db,
            agent_id,
            agent,
            modified_by=mod_metadata["modified_by"],
            modified_from_ip=mod_metadata["modified_from_ip"],
            modified_via=mod_metadata["modified_via"],
            modified_user_agent=mod_metadata["modified_user_agent"],
        )
    except A2AAgentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except A2AAgentNameConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except A2AAgentError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValidationError as e:
        logger.error(f"Validation error while updating A2A agent {agent_id}: {e}")
        raise HTTPException(status_code=422, detail=ErrorFormatter.format_validation_error(e))
    except IntegrityError as e:
        logger.error(f"Integrity error while updating A2A agent {agent_id}: {e}")
        raise HTTPException(status_code=409, detail=ErrorFormatter.format_database_error(e))


@a2a_router.post("/{agent_id}/toggle", response_model=A2AAgentRead)
async def toggle_a2a_agent_status(
    agent_id: str,
    activate: bool = True,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> A2AAgentRead:
    """
    Toggles the status of an A2A agent (activate or deactivate).

    Args:
        agent_id: The ID of the agent to toggle.
        activate: Whether to activate or deactivate the agent.
        db: The database session used to interact with the data store.
        user: The authenticated user making the request.

    Returns:
        A2AAgentRead: The agent object after the status change.

    Raises:
        HTTPException: If the agent is not found or there is an error.
    """
    try:
        logger.debug(f"User {user} is toggling A2A agent with ID {agent_id} to {'active' if activate else 'inactive'}")
        return await a2a_service.toggle_agent_status(db, agent_id, activate)
    except A2AAgentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except A2AAgentError as e:
        raise HTTPException(status_code=400, detail=str(e))


@a2a_router.delete("/{agent_id}", response_model=Dict[str, str])
async def delete_a2a_agent(agent_id: str, db: Session = Depends(get_db), user: str = Depends(require_auth)) -> Dict[str, str]:
    """
    Deletes an A2A agent by its ID.

    Args:
        agent_id: The ID of the agent to delete.
        db: The database session used to interact with the data store.
        user: The authenticated user making the request.

    Returns:
        Dict[str, str]: A success message indicating the agent was deleted.

    Raises:
        HTTPException: If the agent is not found or there is an error.
    """
    try:
        logger.debug(f"User {user} is deleting A2A agent with ID {agent_id}")
        await a2a_service.delete_agent(db, agent_id)
        return {
            "status": "success",
            "message": f"A2A Agent {agent_id} deleted successfully",
        }
    except A2AAgentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except A2AAgentError as e:
        raise HTTPException(status_code=400, detail=str(e))


@a2a_router.post("/{agent_name}/invoke", response_model=Dict[str, Any])
async def invoke_a2a_agent(
    agent_name: str,
    parameters: Dict[str, Any] = Body(default_factory=dict),
    interaction_type: str = Body(default="query"),
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> Dict[str, Any]:
    """
    Invokes an A2A agent with the specified parameters.

    Args:
        agent_name: The name of the agent to invoke.
        parameters: Parameters for the agent interaction.
        interaction_type: Type of interaction (query, execute, etc.).
        db: The database session used to interact with the data store.
        user: The authenticated user making the request.

    Returns:
        Dict[str, Any]: The response from the A2A agent.

    Raises:
        HTTPException: If the agent is not found or there is an error during invocation.
    """
    try:
        logger.debug(f"User {user} is invoking A2A agent '{agent_name}' with type '{interaction_type}'")
        return await a2a_service.invoke_agent(db, agent_name, parameters, interaction_type)
    except A2AAgentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except A2AAgentError as e:
        raise HTTPException(status_code=400, detail=str(e))
