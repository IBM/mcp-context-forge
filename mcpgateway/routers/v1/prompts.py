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
import time
from typing import Any, Dict, List, Optional

# Third-Party
from fastapi import (
    APIRouter,
    Body,
    Depends,
    HTTPException,
    Request,
    status,
)
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import get_db
from mcpgateway.db import Prompt as DbPrompt
from mcpgateway.db import PromptMetric

# Import dependency injection functions
from mcpgateway.dependencies import get_logging_service, get_prompt_service
from mcpgateway.plugins.framework import PluginViolationError
from mcpgateway.schemas import (
    PromptCreate,
    PromptExecuteArgs,
    PromptRead,
    PromptUpdate,
)
from mcpgateway.services.prompt_service import (
    PromptError,
    PromptNameConflictError,
    PromptNotFoundError,
)
from mcpgateway.utils.error_formatter import ErrorFormatter
from mcpgateway.utils.metadata_capture import MetadataCapture
from mcpgateway.utils.verify_credentials import require_auth

# Initialize logging service first
logging_service = get_logging_service()
logger = logging_service.get_logger("prompt routes")

# Initialize service
prompt_service = get_prompt_service()

# Create API router
prompt_router = APIRouter(prefix="/prompts", tags=["Prompts"])


@prompt_router.post("/{prompt_id}/toggle")
async def toggle_prompt_status(
    prompt_id: int,
    activate: bool = True,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> Dict[str, Any]:
    """
    Toggle the activation status of a prompt.

    Args:
        prompt_id: ID of the prompt to toggle.
        activate: True to activate, False to deactivate.
        db: Database session.
        user: Authenticated user.

    Returns:
        Status message and updated prompt details.

    Raises:
        HTTPException: If the toggle fails (e.g., prompt not found or database error); emitted with *400 Bad Request* status and an error message.
    """
    logger.debug(f"User: {user} requested toggle for prompt {prompt_id}, activate={activate}")
    try:
        prompt = await prompt_service.toggle_prompt_status(db, prompt_id, activate)
        return {
            "status": "success",
            "message": f"Prompt {prompt_id} {'activated' if activate else 'deactivated'}",
            "prompt": prompt.model_dump(),
        }
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@prompt_router.get("", response_model=List[PromptRead])
@prompt_router.get("/", response_model=List[PromptRead])
async def list_prompts(
    cursor: Optional[str] = None,
    include_inactive: bool = False,
    tags: Optional[str] = None,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> List[PromptRead]:
    """
    List prompts with optional pagination and inclusion of inactive items.

    Args:
        cursor: Cursor for pagination.
        include_inactive: Include inactive prompts.
        tags: Comma-separated list of tags to filter by.
        db: Database session.
        user: Authenticated user.

    Returns:
        List of prompt records.
    """
    # Parse tags parameter if provided
    tags_list = None
    if tags:
        tags_list = [tag.strip() for tag in tags.split(",") if tag.strip()]

    logger.debug(f"User: {user} requested prompt list with include_inactive={include_inactive}, cursor={cursor}, tags={tags_list}")
    return await prompt_service.list_prompts(db, cursor=cursor, include_inactive=include_inactive, tags=tags_list)


@prompt_router.post("", response_model=PromptRead)
@prompt_router.post("/", response_model=PromptRead)
async def create_prompt(
    prompt: PromptCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> PromptRead:
    """
    Create a new prompt.

    Args:
        prompt (PromptCreate): Payload describing the prompt to create.
        request (Request): The FastAPI request object for metadata extraction.
        db (Session): Active SQLAlchemy session.
        user (str): Authenticated username.

    Returns:
        PromptRead: The newly-created prompt.

    Raises:
        HTTPException: * **409 Conflict** - another prompt with the same name already exists.
            * **400 Bad Request** - validation or persistence error raised
                by :pyclass:`~mcpgateway.services.prompt_service.PromptService`.
    """
    logger.debug(f"User: {user} requested to create prompt: {prompt}")
    try:
        # Extract metadata from request
        metadata = MetadataCapture.extract_creation_metadata(request, user)

        return await prompt_service.register_prompt(
            db,
            prompt,
            created_by=metadata["created_by"],
            created_from_ip=metadata["created_from_ip"],
            created_via=metadata["created_via"],
            created_user_agent=metadata["created_user_agent"],
            import_batch_id=metadata["import_batch_id"],
            federation_source=metadata["federation_source"],
        )
    except Exception as e:
        if isinstance(e, PromptNameConflictError):
            # If the prompt name already exists, return a 409 Conflict error
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
        if isinstance(e, PromptError):
            # If there is a general prompt error, return a 400 Bad Request error
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
        if isinstance(e, ValidationError):
            # If there is a validation error, return a 422 Unprocessable Entity error
            logger.error(f"Validation error while creating prompt: {e}")
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=ErrorFormatter.format_validation_error(e))
        if isinstance(e, IntegrityError):
            # If there is an integrity error, return a 409 Conflict error
            logger.error(f"Integrity error while creating prompt: {e}")
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ErrorFormatter.format_database_error(e))
        # For any other unexpected errors, return a 500 Internal Server Error
        logger.error(f"Unexpected error while creating prompt: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An unexpected error occurred while creating the prompt")


@prompt_router.post("/{name}")
async def get_prompt(
    name: str,
    args: Dict[str, str] = Body({}),
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> Any:
    """Get a prompt by name with arguments.

    This implements the prompts/get functionality from the MCP spec,
    which requires a POST request with arguments in the body.


    Args:
        name: Name of the prompt.
        args: Template arguments.
        db: Database session.
        user: Authenticated user.

    Returns:
        Rendered prompt or metadata.

    Raises:
        Exception: Re-raised if not a handled exception type.
    """
    logger.debug(f"User: {user} requested prompt: {name} with args={args}")
    start_time = time.monotonic()
    success = False
    error_message = None
    result = None

    try:
        PromptExecuteArgs(args=args)
        result = await prompt_service.get_prompt(db, name, args)
        success = True
        logger.debug(f"Prompt execution successful for '{name}'")
    except Exception as ex:
        error_message = str(ex)
        logger.error(f"Could not retrieve prompt {name}: {ex}")
        if isinstance(ex, PluginViolationError):
            # Return the actual plugin violation message
            result = JSONResponse(content={"message": ex.message, "details": str(ex.violation) if hasattr(ex, "violation") else None}, status_code=422)
        elif isinstance(ex, (ValueError, PromptError)):
            # Return the actual error message
            result = JSONResponse(content={"message": str(ex)}, status_code=422)
        else:
            raise

    # Record metrics (moved outside try/except/finally to ensure it runs)
    end_time = time.monotonic()
    response_time = end_time - start_time

    # Get the prompt from database to get its ID
    prompt = db.execute(select(DbPrompt).where(DbPrompt.name == name)).scalar_one_or_none()

    if prompt:
        metric = PromptMetric(
            prompt_id=prompt.id,
            response_time=response_time,
            is_success=success,
            error_message=error_message,
        )
        db.add(metric)
        db.commit()

    return result


@prompt_router.get("/{name}")
async def get_prompt_no_args(
    name: str,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> Any:
    """Get a prompt by name without arguments.

    This endpoint is for convenience when no arguments are needed.

    Args:
        name: The name of the prompt to retrieve
        db: Database session
        user: Authenticated user

    Returns:
        The prompt template information

    Raises:
        Exception: Re-raised from prompt service.
    """
    logger.debug(f"User: {user} requested prompt: {name} with no arguments")
    start_time = time.monotonic()
    success = False
    error_message = None
    result = None

    try:
        result = await prompt_service.get_prompt(db, name, {})
        success = True
    except Exception as ex:
        error_message = str(ex)
        raise

    # Record metrics
    end_time = time.monotonic()
    response_time = end_time - start_time

    # Get the prompt from database to get its ID
    prompt = db.execute(select(DbPrompt).where(DbPrompt.name == name)).scalar_one_or_none()

    if prompt:
        metric = PromptMetric(
            prompt_id=prompt.id,
            response_time=response_time,
            is_success=success,
            error_message=error_message,
        )
        db.add(metric)
        db.commit()

    return result


@prompt_router.put("/{name}", response_model=PromptRead)
async def update_prompt(
    name: str,
    prompt: PromptUpdate,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> PromptRead:
    """
    Update (overwrite) an existing prompt definition.

    Args:
        name (str): Identifier of the prompt to update.
        prompt (PromptUpdate): New prompt content and metadata.
        db (Session): Active SQLAlchemy session.
        user (str): Authenticated username.

    Returns:
        PromptRead: The updated prompt object.

    Raises:
        HTTPException: * **409 Conflict** - a different prompt with the same *name* already exists and is still active.
            * **400 Bad Request** - validation or persistence error raised by :pyclass:`~mcpgateway.services.prompt_service.PromptService`.
    """
    logger.info(f"User: {user} requested to update prompt: {name} with data={prompt}")
    logger.debug(f"User: {user} requested to update prompt: {name} with data={prompt}")
    try:
        return await prompt_service.update_prompt(db, name, prompt)
    except Exception as e:
        if isinstance(e, PromptNotFoundError):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
        if isinstance(e, ValidationError):
            logger.error(f"Validation error while updating prompt: {e}")
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=ErrorFormatter.format_validation_error(e))
        if isinstance(e, IntegrityError):
            logger.error(f"Integrity error while updating prompt: {e}")
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ErrorFormatter.format_database_error(e))
        if isinstance(e, PromptNameConflictError):
            # If the prompt name already exists, return a 409 Conflict error
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
        if isinstance(e, PromptError):
            # If there is a general prompt error, return a 400 Bad Request error
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
        # For any other unexpected errors, return a 500 Internal Server Error
        logger.error(f"Unexpected error while updating prompt: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An unexpected error occurred while updating the prompt")


@prompt_router.delete("/{name}")
async def delete_prompt(name: str, db: Session = Depends(get_db), user: str = Depends(require_auth)) -> Dict[str, str]:
    """
    Delete a prompt by name.

    Args:
        name: Name of the prompt.
        db: Database session.
        user: Authenticated user.

    Returns:
        Status message.

    Raises:
        HTTPException: If the prompt is not found, a prompt error occurs, or an unexpected error occurs during deletion.
    """
    logger.debug(f"User: {user} requested deletion of prompt {name}")
    try:
        await prompt_service.delete_prompt(db, name)
        return {"status": "success", "message": f"Prompt {name} deleted"}
    except Exception as e:
        if isinstance(e, PromptNotFoundError):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
        if isinstance(e, PromptError):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
        logger.error(f"Unexpected error while deleting prompt {name}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An unexpected error occurred while deleting the prompt")

    # except PromptNotFoundError as e:
    #     return {"status": "error", "message": str(e)}
    # except PromptError as e:
    #     return {"status": "error", "message": str(e)}
