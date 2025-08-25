# -*- coding: utf-8 -*-
"""
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

MCP Gateway - Gateways API Router.

This module provides REST API endpoints for managing peer gateways in the MCP Gateway federation.
Gateways represent remote MCP Gateway instances that can be federated for distributed operations
and resource sharing across multiple gateway nodes.

Features and Responsibilities:
- CRUD operations for gateway management (create, read, update, delete)
- Gateway registration and discovery for federation
- Status management (activate/deactivate gateways)
- Connection validation and health monitoring
- Federation support for distributed MCP networks
- Comprehensive error handling with proper HTTP status codes
- Authentication enforcement for all operations

Endpoints:
- GET /gateways: List all registered gateways with optional filtering
- POST /gateways: Register new gateway for federation
- GET /gateways/{id}: Retrieve specific gateway details
- PUT /gateways/{id}: Update existing gateway configuration
- DELETE /gateways/{id}: Remove gateway from federation
- POST /gateways/{id}/toggle: Activate/deactivate gateway

Parameters:
- All endpoints require authentication via JWT Bearer token or Basic Auth
- Gateway IDs can be UUIDs or custom identifiers
- Status toggles support activation state management
- Connection validation ensures gateway reachability

Returns:
- List endpoints return arrays of GatewayRead objects
- CRUD operations return individual GatewayRead objects
- Delete operations return success confirmation messages
- Toggle operations return status with updated gateway data
"""

# Standard
from typing import Any, Dict, List

# Third-Party
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    status,
)
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import get_db

# Import dependency injection functions
from mcpgateway.dependencies import get_gateway_service, get_logging_service
from mcpgateway.schemas import (
    GatewayCreate,
    GatewayRead,
    GatewayUpdate,
)
from mcpgateway.services.gateway_service import GatewayConnectionError, GatewayNameConflictError, GatewayNotFoundError
from mcpgateway.utils.error_formatter import ErrorFormatter
from mcpgateway.utils.metadata_capture import MetadataCapture
from mcpgateway.utils.verify_credentials import require_auth

# Initialize logging service first
logging_service = get_logging_service()
logger = logging_service.get_logger("gateway routes")


# Initialize services
gateway_service = get_gateway_service()

# Create API router
gateway_router = APIRouter(prefix="/gateways", tags=["Gateways"])


@gateway_router.post("/{gateway_id}/toggle")
async def toggle_gateway_status(
    gateway_id: str,
    activate: bool = True,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> Dict[str, Any]:
    """
    Toggle the activation status of a gateway.

    Args:
        gateway_id (str): String ID of the gateway to toggle.
        activate (bool): ``True`` to activate, ``False`` to deactivate.
        db (Session): Active SQLAlchemy session.
        user (str): Authenticated username.

    Returns:
        Dict[str, Any]: A dict containing the operation status, a message, and the updated gateway object.

    Raises:
        HTTPException: Returned with **400 Bad Request** if the toggle operation fails (e.g., the gateway does not exist or the database raises an unexpected error).
    """
    logger.debug(f"User '{user}' requested toggle for gateway {gateway_id}, activate={activate}")
    try:
        gateway = await gateway_service.toggle_gateway_status(
            db,
            gateway_id,
            activate,
        )
        return {
            "status": "success",
            "message": f"Gateway {gateway_id} {'activated' if activate else 'deactivated'}",
            "gateway": gateway.model_dump(),
        }
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@gateway_router.get("", response_model=List[GatewayRead])
@gateway_router.get("/", response_model=List[GatewayRead])
async def list_gateways(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> List[GatewayRead]:
    """
    List all gateways.

    Args:
        include_inactive: Include inactive gateways.
        db: Database session.
        user: Authenticated user.

    Returns:
        List of gateway records.
    """
    logger.debug(f"User '{user}' requested list of gateways with include_inactive={include_inactive}")
    return await gateway_service.list_gateways(db, include_inactive=include_inactive)


@gateway_router.post("", response_model=GatewayRead)
@gateway_router.post("/", response_model=GatewayRead)
async def register_gateway(
    gateway: GatewayCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> GatewayRead:
    """
    Register a new gateway.

    Args:
        gateway: Gateway creation data.
        request: The FastAPI request object for metadata extraction.
        db: Database session.
        user: Authenticated user.

    Returns:
        Created gateway.
    """
    logger.debug(f"User '{user}' requested to register gateway: {gateway}")
    try:
        # Extract metadata from request
        metadata = MetadataCapture.extract_creation_metadata(request, user)

        return await gateway_service.register_gateway(
            db,
            gateway,
            created_by=metadata["created_by"],
            created_from_ip=metadata["created_from_ip"],
            created_via=metadata["created_via"],
            created_user_agent=metadata["created_user_agent"],
        )
    except Exception as ex:
        if isinstance(ex, GatewayConnectionError):
            return JSONResponse(content={"message": "Unable to connect to gateway"}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
        if isinstance(ex, ValueError):
            return JSONResponse(content={"message": "Unable to process input"}, status_code=status.HTTP_400_BAD_REQUEST)
        if isinstance(ex, GatewayNameConflictError):
            return JSONResponse(content={"message": "Gateway name already exists"}, status_code=status.HTTP_409_CONFLICT)
        if isinstance(ex, RuntimeError):
            return JSONResponse(content={"message": "Error during execution"}, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
        if isinstance(ex, ValidationError):
            return JSONResponse(content=ErrorFormatter.format_validation_error(ex), status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)
        if isinstance(ex, IntegrityError):
            return JSONResponse(status_code=status.HTTP_409_CONFLICT, content=ErrorFormatter.format_database_error(ex))
        return JSONResponse(content={"message": "Unexpected error"}, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@gateway_router.get("/{gateway_id}", response_model=GatewayRead)
async def get_gateway(gateway_id: str, db: Session = Depends(get_db), user: str = Depends(require_auth)) -> GatewayRead:
    """
    Retrieve a gateway by ID.

    Args:
        gateway_id: ID of the gateway.
        db: Database session.
        user: Authenticated user.

    Returns:
        Gateway data.
    """
    logger.debug(f"User '{user}' requested gateway {gateway_id}")
    return await gateway_service.get_gateway(db, gateway_id)


@gateway_router.put("/{gateway_id}", response_model=GatewayRead)
async def update_gateway(
    gateway_id: str,
    gateway: GatewayUpdate,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> GatewayRead:
    """
    Update a gateway.

    Args:
        gateway_id: Gateway ID.
        gateway: Gateway update data.
        db: Database session.
        user: Authenticated user.

    Returns:
        Updated gateway.
    """
    logger.debug(f"User '{user}' requested update on gateway {gateway_id} with data={gateway}")
    try:
        return await gateway_service.update_gateway(db, gateway_id, gateway)
    except Exception as ex:
        if isinstance(ex, GatewayNotFoundError):
            return JSONResponse(content={"message": "Gateway not found"}, status_code=status.HTTP_404_NOT_FOUND)
        if isinstance(ex, GatewayConnectionError):
            return JSONResponse(content={"message": "Unable to connect to gateway"}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
        if isinstance(ex, ValueError):
            return JSONResponse(content={"message": "Unable to process input"}, status_code=status.HTTP_400_BAD_REQUEST)
        if isinstance(ex, GatewayNameConflictError):
            return JSONResponse(content={"message": "Gateway name already exists"}, status_code=status.HTTP_409_CONFLICT)
        if isinstance(ex, RuntimeError):
            return JSONResponse(content={"message": "Error during execution"}, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
        if isinstance(ex, ValidationError):
            return JSONResponse(content=ErrorFormatter.format_validation_error(ex), status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)
        if isinstance(ex, IntegrityError):
            return JSONResponse(status_code=status.HTTP_409_CONFLICT, content=ErrorFormatter.format_database_error(ex))
        return JSONResponse(content={"message": "Unexpected error"}, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@gateway_router.delete("/{gateway_id}")
async def delete_gateway(gateway_id: str, db: Session = Depends(get_db), user: str = Depends(require_auth)) -> Dict[str, str]:
    """
    Delete a gateway by ID.

    Args:
        gateway_id: ID of the gateway.
        db: Database session.
        user: Authenticated user.

    Returns:
        Status message.
    """
    logger.debug(f"User '{user}' requested deletion of gateway {gateway_id}")
    await gateway_service.delete_gateway(db, gateway_id)
    return {"status": "success", "message": f"Gateway {gateway_id} deleted"}
