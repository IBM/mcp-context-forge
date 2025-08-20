# -*- coding: utf-8 -*-
"""Admin UI Routes for MCP Gateway.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

This module contains all the administrative UI endpoints for the MCP Gateway.
It provides a comprehensive interface for managing servers, tools, resources,
prompts, gateways, and roots through RESTful API endpoints. The module handles
all aspects of CRUD operations for these entities, including creation,
reading, updating, deletion, and status toggling.

All endpoints in this module require authentication, which is enforced via
the require_auth or require_basic_auth dependency. The module integrates with
various services to perform the actual business logic operations on the
underlying data.
"""

# Standard
from collections import defaultdict
import csv
from datetime import datetime
from functools import wraps
import io
import json
from pathlib import Path
import time
from typing import Any, cast, Dict, List, Optional, Union
import uuid

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
import httpx
from pydantic import ValidationError
from pydantic_core import ValidationError as CoreValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import get_db, GlobalConfig
from mcpgateway.db import Tool as DbTool
from mcpgateway.models import LogLevel
from mcpgateway.schemas import (
    A2AAgentCreate,
    GatewayCreate,
    GatewayRead,
    GatewayTestRequest,
    GatewayTestResponse,
    GatewayUpdate,
    GlobalConfigRead,
    GlobalConfigUpdate,
    PromptCreate,
    PromptMetrics,
    PromptRead,
    PromptUpdate,
    ResourceCreate,
    ResourceMetrics,
    ResourceRead,
    ResourceUpdate,
    ServerCreate,
    ServerMetrics,
    ServerRead,
    ServerUpdate,
    ToolCreate,
    ToolMetrics,
    ToolRead,
    ToolUpdate,
)
from mcpgateway.services.a2a_service import A2AAgentError, A2AAgentNameConflictError, A2AAgentNotFoundError, A2AAgentService
from mcpgateway.services.export_service import ExportError, ExportService
from mcpgateway.services.gateway_service import GatewayConnectionError, GatewayNotFoundError, GatewayService
from mcpgateway.services.import_service import ConflictStrategy
from mcpgateway.services.import_service import ImportError as ImportServiceError
from mcpgateway.services.import_service import ImportService
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.prompt_service import PromptNotFoundError, PromptService
from mcpgateway.services.resource_service import ResourceNotFoundError, ResourceService
from mcpgateway.services.root_service import RootService
from mcpgateway.services.server_service import ServerError, ServerNameConflictError, ServerNotFoundError, ServerService
from mcpgateway.services.tag_service import TagService
from mcpgateway.services.tool_service import ToolError, ToolNotFoundError, ToolService
from mcpgateway.utils.create_jwt_token import get_jwt_token
from mcpgateway.utils.error_formatter import ErrorFormatter
from mcpgateway.utils.metadata_capture import MetadataCapture
from mcpgateway.utils.oauth_encryption import get_oauth_encryption
from mcpgateway.utils.passthrough_headers import PassthroughHeadersError
from mcpgateway.utils.retry_manager import ResilientHttpClient
from mcpgateway.utils.security_cookies import set_auth_cookie
from mcpgateway.utils.verify_credentials import require_auth, require_basic_auth

# Import the shared logging service from main
# This will be set by main.py when it imports admin_router
logging_service: Optional[LoggingService] = None
LOGGER = None


def set_logging_service(service: LoggingService):
    """Set the logging service instance to use.

    This should be called by main.py to share the same logging service.

    Args:
        service: The LoggingService instance to use
    """
    global logging_service, LOGGER  # pylint: disable=global-statement
    logging_service = service
    LOGGER = logging_service.get_logger("mcpgateway.admin")


# Fallback for testing - create a temporary instance if not set
if logging_service is None:
    logging_service = LoggingService()
    LOGGER = logging_service.get_logger("mcpgateway.admin")

# Initialize services
server_service: ServerService = ServerService()
tool_service: ToolService = ToolService()
prompt_service: PromptService = PromptService()
gateway_service: GatewayService = GatewayService()
resource_service: ResourceService = ResourceService()
root_service: RootService = RootService()
export_service: ExportService = ExportService()
import_service: ImportService = ImportService()
# Initialize A2A service only if A2A features are enabled
a2a_service: Optional[A2AAgentService] = A2AAgentService() if settings.mcpgateway_a2a_enabled else None

# Set up basic authentication

# Rate limiting storage
rate_limit_storage = defaultdict(list)


def rate_limit(requests_per_minute: int = None):
    """Apply rate limiting to admin endpoints.

    Args:
        requests_per_minute: Maximum requests per minute (uses config default if None)

    Returns:
        Decorator function that enforces rate limiting
    """

    def decorator(func):
        """Decorator that wraps the function with rate limiting logic.

        Args:
            func: The function to be wrapped with rate limiting

        Returns:
            The wrapped function with rate limiting applied
        """

        @wraps(func)
        async def wrapper(*args, request: Request = None, **kwargs):
            """Execute the wrapped function with rate limiting enforcement.

            Args:
                *args: Positional arguments to pass to the wrapped function
                request: FastAPI Request object for extracting client IP
                **kwargs: Keyword arguments to pass to the wrapped function

            Returns:
                The result of the wrapped function call

            Raises:
                HTTPException: When rate limit is exceeded (429 status)
            """
            # use configured limit if none provided
            limit = requests_per_minute or settings.validation_max_requests_per_minute

            # request can be None in some edge cases (e.g., tests)
            client_ip = request.client.host if request and request.client else "unknown"
            current_time = time.time()
            minute_ago = current_time - 60

            # prune old timestamps
            rate_limit_storage[client_ip] = [ts for ts in rate_limit_storage[client_ip] if ts > minute_ago]

            # enforce
            if len(rate_limit_storage[client_ip]) >= limit:
                LOGGER.warning(f"Rate limit exceeded for IP {client_ip} on endpoint {func.__name__}")
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded. Maximum {limit} requests per minute.",
                )

            rate_limit_storage[client_ip].append(current_time)

            # IMPORTANT: forward request to the real endpoint
            return await func(*args, request=request, **kwargs)

        return wrapper

    return decorator


admin_router = APIRouter(prefix="/admin", tags=["Admin UI"])

####################
# Admin UI Routes  #
####################


@admin_router.get("/config/passthrough-headers", response_model=GlobalConfigRead)
@rate_limit(requests_per_minute=30)  # Lower limit for config endpoints
async def get_global_passthrough_headers(
    db: Session = Depends(get_db),
    _user: str = Depends(require_auth),
) -> GlobalConfigRead:
    """Get the global passthrough headers configuration.

    Args:
        db: Database session
        _user: Authenticated user

    Returns:
        GlobalConfigRead: The current global passthrough headers configuration

    Examples:
        >>> # Test function exists and has correct name
        >>> from mcpgateway.admin import get_global_passthrough_headers
        >>> get_global_passthrough_headers.__name__
        'get_global_passthrough_headers'
        >>> # Test it's a coroutine function
        >>> import inspect
        >>> inspect.iscoroutinefunction(get_global_passthrough_headers)
        True
    """
    config = db.query(GlobalConfig).first()
    if config:
        passthrough_headers = config.passthrough_headers
    else:
        passthrough_headers = []
    return GlobalConfigRead(passthrough_headers=passthrough_headers)


@admin_router.put("/config/passthrough-headers", response_model=GlobalConfigRead)
@rate_limit(requests_per_minute=20)  # Stricter limit for config updates
async def update_global_passthrough_headers(
    request: Request,  # pylint: disable=unused-argument
    config_update: GlobalConfigUpdate,
    db: Session = Depends(get_db),
    _user: str = Depends(require_auth),
) -> GlobalConfigRead:
    """Update the global passthrough headers configuration.

    Args:
        request: HTTP request object
        config_update: The new configuration
        db: Database session
        _user: Authenticated user

    Raises:
        HTTPException: If there is a conflict or validation error

    Returns:
        GlobalConfigRead: The updated configuration

    Examples:
        >>> # Test function exists and has correct name
        >>> from mcpgateway.admin import update_global_passthrough_headers
        >>> update_global_passthrough_headers.__name__
        'update_global_passthrough_headers'
        >>> # Test it's a coroutine function
        >>> import inspect
        >>> inspect.iscoroutinefunction(update_global_passthrough_headers)
        True
    """
    try:
        config = db.query(GlobalConfig).first()
        if not config:
            config = GlobalConfig(passthrough_headers=config_update.passthrough_headers)
            db.add(config)
        else:
            config.passthrough_headers = config_update.passthrough_headers
        db.commit()
        return GlobalConfigRead(passthrough_headers=config.passthrough_headers)
    except Exception as e:
        if isinstance(e, IntegrityError):
            db.rollback()
            raise HTTPException(status_code=409, detail="Passthrough headers conflict")
        if isinstance(e, ValidationError):
            db.rollback()
            raise HTTPException(status_code=422, detail="Invalid passthrough headers format")
        if isinstance(e, PassthroughHeadersError):
            db.rollback()
            raise HTTPException(status_code=500, detail=str(e))


@admin_router.get("/servers", response_model=List[ServerRead])
async def admin_list_servers(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> List[Dict[str, Any]]:
    """
    List servers for the admin UI with an option to include inactive servers.

    Args:
        include_inactive (bool): Whether to include inactive servers.
        db (Session): The database session dependency.
        user (str): The authenticated user dependency.

    Returns:
        List[ServerRead]: A list of server records.

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from mcpgateway.schemas import ServerRead, ServerMetrics
        >>>
        >>> # Mock dependencies
        >>> mock_db = MagicMock()
        >>> mock_user = "test_user"
        >>>
        >>> # Mock server service
        >>> from datetime import datetime, timezone
        >>> mock_metrics = ServerMetrics(
        ...     total_executions=10,
        ...     successful_executions=8,
        ...     failed_executions=2,
        ...     failure_rate=0.2,
        ...     min_response_time=0.1,
        ...     max_response_time=2.0,
        ...     avg_response_time=0.5,
        ...     last_execution_time=datetime.now(timezone.utc)
        ... )
        >>> mock_server = ServerRead(
        ...     id="server-1",
        ...     name="Test Server",
        ...     description="A test server",
        ...     icon="test-icon.png",
        ...     created_at=datetime.now(timezone.utc),
        ...     updated_at=datetime.now(timezone.utc),
        ...     is_active=True,
        ...     associated_tools=["tool1", "tool2"],
        ...     associated_resources=[1, 2],
        ...     associated_prompts=[1],
        ...     metrics=mock_metrics
        ... )
        >>>
        >>> # Mock the server_service.list_servers method
        >>> original_list_servers = server_service.list_servers
        >>> server_service.list_servers = AsyncMock(return_value=[mock_server])
        >>>
        >>> # Test the function
        >>> async def test_admin_list_servers():
        ...     result = await admin_list_servers(
        ...         include_inactive=False,
        ...         db=mock_db,
        ...         user=mock_user
        ...     )
        ...     return len(result) > 0 and isinstance(result[0], dict)
        >>>
        >>> # Run the test
        >>> asyncio.run(test_admin_list_servers())
        True
        >>>
        >>> # Restore original method
        >>> server_service.list_servers = original_list_servers
        >>>
        >>> # Additional test for empty server list
        >>> server_service.list_servers = AsyncMock(return_value=[])
        >>> async def test_admin_list_servers_empty():
        ...     result = await admin_list_servers(
        ...         include_inactive=True,
        ...         db=mock_db,
        ...         user=mock_user
        ...     )
        ...     return result == []
        >>> asyncio.run(test_admin_list_servers_empty())
        True
        >>> server_service.list_servers = original_list_servers
        >>>
        >>> # Additional test for exception handling
        >>> import pytest
        >>> from fastapi import HTTPException
        >>> async def test_admin_list_servers_exception():
        ...     server_service.list_servers = AsyncMock(side_effect=Exception("Test error"))
        ...     try:
        ...         await admin_list_servers(False, mock_db, mock_user)
        ...     except Exception as e:
        ...         return str(e) == "Test error"
        >>> asyncio.run(test_admin_list_servers_exception())
        True
    """
    LOGGER.debug(f"User {user} requested server list")
    servers = await server_service.list_servers(db, include_inactive=include_inactive)
    return [server.model_dump(by_alias=True) for server in servers]


@admin_router.get("/servers/{server_id}", response_model=ServerRead)
async def admin_get_server(server_id: str, db: Session = Depends(get_db), user: str = Depends(require_auth)) -> Dict[str, Any]:
    """
    Retrieve server details for the admin UI.

    Args:
        server_id (str): The ID of the server to retrieve.
        db (Session): The database session dependency.
        user (str): The authenticated user dependency.

    Returns:
        Dict[str, Any]: The server details.

    Raises:
        HTTPException: If the server is not found.
        Exception: For any other unexpected errors.

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from mcpgateway.schemas import ServerRead, ServerMetrics
        >>> from mcpgateway.services.server_service import ServerNotFoundError
        >>> from fastapi import HTTPException
        >>>
        >>> # Mock dependencies
        >>> mock_db = MagicMock()
        >>> mock_user = "test_user"
        >>> server_id = "test-server-1"
        >>>
        >>> # Mock server response
        >>> from datetime import datetime, timezone
        >>> mock_metrics = ServerMetrics(
        ...     total_executions=5,
        ...     successful_executions=4,
        ...     failed_executions=1,
        ...     failure_rate=0.2,
        ...     min_response_time=0.2,
        ...     max_response_time=1.5,
        ...     avg_response_time=0.8,
        ...     last_execution_time=datetime.now(timezone.utc)
        ... )
        >>> mock_server = ServerRead(
        ...     id=server_id,
        ...     name="Test Server",
        ...     description="A test server",
        ...     icon="test-icon.png",
        ...     created_at=datetime.now(timezone.utc),
        ...     updated_at=datetime.now(timezone.utc),
        ...     is_active=True,
        ...     associated_tools=["tool1"],
        ...     associated_resources=[1],
        ...     associated_prompts=[1],
        ...     metrics=mock_metrics
        ... )
        >>>
        >>> # Mock the server_service.get_server method
        >>> original_get_server = server_service.get_server
        >>> server_service.get_server = AsyncMock(return_value=mock_server)
        >>>
        >>> # Test successful retrieval
        >>> async def test_admin_get_server_success():
        ...     result = await admin_get_server(
        ...         server_id=server_id,
        ...         db=mock_db,
        ...         user=mock_user
        ...     )
        ...     return isinstance(result, dict) and result.get('id') == server_id
        >>>
        >>> # Run the test
        >>> asyncio.run(test_admin_get_server_success())
        True
        >>>
        >>> # Test server not found scenario
        >>> server_service.get_server = AsyncMock(side_effect=ServerNotFoundError("Server not found"))
        >>>
        >>> async def test_admin_get_server_not_found():
        ...     try:
        ...         await admin_get_server(
        ...             server_id="nonexistent",
        ...             db=mock_db,
        ...             user=mock_user
        ...         )
        ...         return False
        ...     except HTTPException as e:
        ...         return e.status_code == 404
        >>>
        >>> # Run the not found test
        >>> asyncio.run(test_admin_get_server_not_found())
        True
        >>>
        >>> # Restore original method
        >>> server_service.get_server = original_get_server
    """
    try:
        LOGGER.debug(f"User {user} requested details for server ID {server_id}")
        server = await server_service.get_server(db, server_id)
        return server.model_dump(by_alias=True)
    except ServerNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        LOGGER.error(f"Error getting gateway {server_id}: {e}")
        raise e


@admin_router.post("/servers", response_model=ServerRead)
async def admin_add_server(request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)) -> JSONResponse:
    """
    Add a new server via the admin UI.

    This endpoint processes form data to create a new server entry in the database.
    It handles exceptions gracefully and logs any errors that occur during server
    registration.

    Expects form fields:
      - name (required): The name of the server
      - description (optional): A description of the server's purpose
      - icon (optional): URL or path to the server's icon
      - associatedTools (optional, comma-separated): Tools associated with this server
      - associatedResources (optional, comma-separated): Resources associated with this server
      - associatedPrompts (optional, comma-separated): Prompts associated with this server

    Args:
        request (Request): FastAPI request containing form data.
        db (Session): Database session dependency
        user (str): Authenticated user dependency

    Returns:
        JSONResponse: A JSON response indicating success or failure of the server creation operation.

    Examples:
        >>> import asyncio
        >>> import uuid
        >>> from datetime import datetime
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from fastapi import Request
        >>> from fastapi.responses import RedirectResponse
        >>> from starlette.datastructures import FormData
        >>>
        >>> # Mock dependencies
        >>> mock_db = MagicMock()
        >>> timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        >>> short_uuid = str(uuid.uuid4())[:8]
        >>> unq_ext = f"{timestamp}-{short_uuid}"
        >>> mock_user = "test_user_" + unq_ext
        >>> # Mock form data for successful server creation
        >>> form_data = FormData([
        ...     ("name", "Test-Server-"+unq_ext ),
        ...     ("description", "A test server"),
        ...     ("icon", "https://raw.githubusercontent.com/github/explore/main/topics/python/python.png"),
        ...     ("associatedTools", "tool1"),
        ...     ("associatedTools", "tool2"),
        ...     ("associatedResources", "resource1"),
        ...     ("associatedPrompts", "prompt1"),
        ...     ("is_inactive_checked", "false")
        ... ])
        >>>
        >>> # Mock request with form data
        >>> mock_request = MagicMock(spec=Request)
        >>> mock_request.form = AsyncMock(return_value=form_data)
        >>> mock_request.scope = {"root_path": "/test"}
        >>>
        >>> # Mock server service
        >>> original_register_server = server_service.register_server
        >>> server_service.register_server = AsyncMock()
        >>>
        >>> # Test successful server addition
        >>> async def test_admin_add_server_success():
        ...     result = await admin_add_server(
        ...         request=mock_request,
        ...         db=mock_db,
        ...         user=mock_user
        ...     )
        ...     # Accept both Successful (200) and JSONResponse (422/409) for error cases
        ...     #print(result.status_code)
        ...     return isinstance(result, JSONResponse) and result.status_code in (200, 409, 422, 500)
        >>>
        >>> asyncio.run(test_admin_add_server_success())
        True
        >>>
        >>> # Test with inactive checkbox checked
        >>> form_data_inactive = FormData([
        ...     ("name", "Test Server"),
        ...     ("description", "A test server"),
        ...     ("is_inactive_checked", "true")
        ... ])
        >>> mock_request.form = AsyncMock(return_value=form_data_inactive)
        >>>
        >>> async def test_admin_add_server_inactive():
        ...     result = await admin_add_server(mock_request, mock_db, mock_user)
        ...     return isinstance(result, JSONResponse) and result.status_code in (200, 409, 422, 500)
        >>>
        >>> #asyncio.run(test_admin_add_server_inactive())
        >>>
        >>> # Test exception handling - should still return redirect
        >>> async def test_admin_add_server_exception():
        ...     server_service.register_server = AsyncMock(side_effect=Exception("Test error"))
        ...     result = await admin_add_server(mock_request, mock_db, mock_user)
        ...     return isinstance(result, JSONResponse) and result.status_code == 500
        >>>
        >>> asyncio.run(test_admin_add_server_exception())
        True
        >>>
        >>> # Test with minimal form data
        >>> form_data_minimal = FormData([("name", "Minimal Server")])
        >>> mock_request.form = AsyncMock(return_value=form_data_minimal)
        >>> server_service.register_server = AsyncMock()
        >>>
        >>> async def test_admin_add_server_minimal():
        ...     result = await admin_add_server(mock_request, mock_db, mock_user)
        ...     #print (result)
        ...     #print (result.status_code)
        ...     return isinstance(result, JSONResponse) and result.status_code==200
        >>>
        >>> asyncio.run(test_admin_add_server_minimal())
        True
        >>>
        >>> # Restore original method
        >>> server_service.register_server = original_register_server
    """
    form = await request.form()
    # root_path = request.scope.get("root_path", "")
    # is_inactive_checked = form.get("is_inactive_checked", "false")

    # Parse tags from comma-separated string
    tags_str = str(form.get("tags", ""))
    tags: list[str] = [tag.strip() for tag in tags_str.split(",") if tag.strip()] if tags_str else []

    try:
        LOGGER.debug(f"User {user} is adding a new server with name: {form['name']}")
        server = ServerCreate(
            name=form.get("name"),
            description=form.get("description"),
            icon=form.get("icon"),
            associated_tools=",".join(form.getlist("associatedTools")),
            associated_resources=form.get("associatedResources"),
            associated_prompts=form.get("associatedPrompts"),
            tags=tags,
        )
    except KeyError as e:
        # Convert KeyError to ValidationError-like response
        return JSONResponse(content={"message": f"Missing required field: {e}", "success": False}, status_code=422)

    try:
        await server_service.register_server(db, server)
        return JSONResponse(
            content={"message": "Server created successfully!", "success": True},
            status_code=200,
        )

    except CoreValidationError as ex:
        return JSONResponse(content={"message": str(ex), "success": False}, status_code=422)
    except ServerError as ex:
        return JSONResponse(content={"message": str(ex), "success": False}, status_code=500)
    except ValueError as ex:
        return JSONResponse(content={"message": str(ex), "success": False}, status_code=400)
    except ValidationError as ex:
        return JSONResponse(content=ErrorFormatter.format_validation_error(ex), status_code=422)
    except IntegrityError as ex:
        return JSONResponse(content=ErrorFormatter.format_database_error(ex), status_code=409)
    except Exception as ex:
        return JSONResponse(content={"message": str(ex), "success": False}, status_code=500)


@admin_router.post("/servers/{server_id}/edit")
async def admin_edit_server(
    server_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> JSONResponse:
    """
    Edit an existing server via the admin UI.

    This endpoint processes form data to update an existing server's properties.
    It handles exceptions gracefully and logs any errors that occur during the
    update operation.

    Expects form fields:
      - name (optional): The updated name of the server
      - description (optional): An updated description of the server's purpose
      - icon (optional): Updated URL or path to the server's icon
      - associatedTools (optional, comma-separated): Updated list of tools associated with this server
      - associatedResources (optional, comma-separated): Updated list of resources associated with this server
      - associatedPrompts (optional, comma-separated): Updated list of prompts associated with this server

    Args:
        server_id (str): The ID of the server to edit
        request (Request): FastAPI request containing form data
        db (Session): Database session dependency
        user (str): Authenticated user dependency

    Returns:
        JSONResponse: A JSON response indicating success or failure of the server update operation.

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from fastapi import Request
        >>> from fastapi.responses import JSONResponse
        >>> from starlette.datastructures import FormData
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = "test_user"
        >>> server_id = "server-to-edit"
        >>>
        >>> # Happy path: Edit server with new name
        >>> form_data_edit = FormData([("name", "Updated Server Name"), ("is_inactive_checked", "false")])
        >>> mock_request_edit = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_edit.form = AsyncMock(return_value=form_data_edit)
        >>> original_update_server = server_service.update_server
        >>> server_service.update_server = AsyncMock()
        >>>
        >>> async def test_admin_edit_server_success():
        ...     result = await admin_edit_server(server_id, mock_request_edit, mock_db, mock_user)
        ...     return isinstance(result, JSONResponse) and result.status_code == 200 and result.body == b'{"message":"Server updated successfully!","success":true}'
        >>>
        >>> asyncio.run(test_admin_edit_server_success())
        True
        >>>
        >>> # Error path: Simulate an exception during update
        >>> form_data_error = FormData([("name", "Error Server")])
        >>> mock_request_error = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_error.form = AsyncMock(return_value=form_data_error)
        >>> server_service.update_server = AsyncMock(side_effect=Exception("Update failed"))
        >>>
        >>> # Restore original method
        >>> server_service.update_server = original_update_server
        >>> # 409 Conflict: ServerNameConflictError
        >>> server_service.update_server = AsyncMock(side_effect=ServerNameConflictError("Name conflict"))
        >>> async def test_admin_edit_server_conflict():
        ...     result = await admin_edit_server(server_id, mock_request_error, mock_db, mock_user)
        ...     return isinstance(result, JSONResponse) and result.status_code == 409 and b'Name conflict' in result.body
        >>> asyncio.run(test_admin_edit_server_conflict())
        True
        >>> # 409 Conflict: IntegrityError
        >>> from sqlalchemy.exc import IntegrityError
        >>> server_service.update_server = AsyncMock(side_effect=IntegrityError("Integrity error", None, None))
        >>> async def test_admin_edit_server_integrity():
        ...     result = await admin_edit_server(server_id, mock_request_error, mock_db, mock_user)
        ...     return isinstance(result, JSONResponse) and result.status_code == 409
        >>> asyncio.run(test_admin_edit_server_integrity())
        True
        >>> # 422 Unprocessable Entity: ValidationError
        >>> from pydantic import ValidationError, BaseModel
        >>> from mcpgateway.schemas import ServerUpdate
        >>> validation_error = ValidationError.from_exception_data("ServerUpdate validation error", [
        ...     {"loc": ("name",), "msg": "Field required", "type": "missing"}
        ... ])
        >>> server_service.update_server = AsyncMock(side_effect=validation_error)
        >>> async def test_admin_edit_server_validation():
        ...     result = await admin_edit_server(server_id, mock_request_error, mock_db, mock_user)
        ...     return isinstance(result, JSONResponse) and result.status_code == 422
        >>> asyncio.run(test_admin_edit_server_validation())
        True
        >>> # 400 Bad Request: ValueError
        >>> server_service.update_server = AsyncMock(side_effect=ValueError("Bad value"))
        >>> async def test_admin_edit_server_valueerror():
        ...     result = await admin_edit_server(server_id, mock_request_error, mock_db, mock_user)
        ...     return isinstance(result, JSONResponse) and result.status_code == 400 and b'Bad value' in result.body
        >>> asyncio.run(test_admin_edit_server_valueerror())
        True
        >>> # 500 Internal Server Error: ServerError
        >>> server_service.update_server = AsyncMock(side_effect=ServerError("Server error"))
        >>> async def test_admin_edit_server_servererror():
        ...     result = await admin_edit_server(server_id, mock_request_error, mock_db, mock_user)
        ...     return isinstance(result, JSONResponse) and result.status_code == 500 and b'Server error' in result.body
        >>> asyncio.run(test_admin_edit_server_servererror())
        True
        >>> # 500 Internal Server Error: RuntimeError
        >>> server_service.update_server = AsyncMock(side_effect=RuntimeError("Runtime error"))
        >>> async def test_admin_edit_server_runtimeerror():
        ...     result = await admin_edit_server(server_id, mock_request_error, mock_db, mock_user)
        ...     return isinstance(result, JSONResponse) and result.status_code == 500 and b'Runtime error' in result.body
        >>> asyncio.run(test_admin_edit_server_runtimeerror())
        True
        >>> # Restore original method
        >>> server_service.update_server = original_update_server
    """
    form = await request.form()

    # Parse tags from comma-separated string
    tags_str = str(form.get("tags", ""))
    tags: list[str] = [tag.strip() for tag in tags_str.split(",") if tag.strip()] if tags_str else []
    try:
        LOGGER.debug(f"User {user} is editing server ID {server_id} with name: {form.get('name')}")
        server = ServerUpdate(
            name=form.get("name"),
            description=form.get("description"),
            icon=form.get("icon"),
            associated_tools=",".join(form.getlist("associatedTools")),
            associated_resources=form.get("associatedResources"),
            associated_prompts=form.get("associatedPrompts"),
            tags=tags,
        )
        await server_service.update_server(db, server_id, server)

        return JSONResponse(
            content={"message": "Server updated successfully!", "success": True},
            status_code=200,
        )
    except (ValidationError, CoreValidationError) as ex:
        # Catch both Pydantic and pydantic_core validation errors
        return JSONResponse(content=ErrorFormatter.format_validation_error(ex), status_code=422)
    except ServerNameConflictError as ex:
        return JSONResponse(content={"message": str(ex), "success": False}, status_code=409)
    except ServerError as ex:
        return JSONResponse(content={"message": str(ex), "success": False}, status_code=500)
    except ValueError as ex:
        return JSONResponse(content={"message": str(ex), "success": False}, status_code=400)
    except RuntimeError as ex:
        return JSONResponse(content={"message": str(ex), "success": False}, status_code=500)
    except IntegrityError as ex:
        return JSONResponse(content=ErrorFormatter.format_database_error(ex), status_code=409)
    except Exception as ex:
        return JSONResponse(content={"message": str(ex), "success": False}, status_code=500)


@admin_router.post("/servers/{server_id}/toggle")
async def admin_toggle_server(
    server_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> RedirectResponse:
    """
    Toggle a server's active status via the admin UI.

    This endpoint processes a form request to activate or deactivate a server.
    It expects a form field 'activate' with value "true" to activate the server
    or "false" to deactivate it. The endpoint handles exceptions gracefully and
    logs any errors that might occur during the status toggle operation.

    Args:
        server_id (str): The ID of the server whose status to toggle.
        request (Request): FastAPI request containing form data with the 'activate' field.
        db (Session): Database session dependency.
        user (str): Authenticated user dependency.

    Returns:
        RedirectResponse: A redirect to the admin dashboard catalog section with a
        status code of 303 (See Other).

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from fastapi import Request
        >>> from fastapi.responses import RedirectResponse
        >>> from starlette.datastructures import FormData
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = "test_user"
        >>> server_id = "server-to-toggle"
        >>>
        >>> # Happy path: Activate server
        >>> form_data_activate = FormData([("activate", "true"), ("is_inactive_checked", "false")])
        >>> mock_request_activate = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_activate.form = AsyncMock(return_value=form_data_activate)
        >>> original_toggle_server_status = server_service.toggle_server_status
        >>> server_service.toggle_server_status = AsyncMock()
        >>>
        >>> async def test_admin_toggle_server_activate():
        ...     result = await admin_toggle_server(server_id, mock_request_activate, mock_db, mock_user)
        ...     return isinstance(result, RedirectResponse) and result.status_code == 303 and "/admin#catalog" in result.headers["location"]
        >>>
        >>> asyncio.run(test_admin_toggle_server_activate())
        True
        >>>
        >>> # Happy path: Deactivate server
        >>> form_data_deactivate = FormData([("activate", "false"), ("is_inactive_checked", "false")])
        >>> mock_request_deactivate = MagicMock(spec=Request, scope={"root_path": "/api"})
        >>> mock_request_deactivate.form = AsyncMock(return_value=form_data_deactivate)
        >>>
        >>> async def test_admin_toggle_server_deactivate():
        ...     result = await admin_toggle_server(server_id, mock_request_deactivate, mock_db, mock_user)
        ...     return isinstance(result, RedirectResponse) and result.status_code == 303 and "/api/admin#catalog" in result.headers["location"]
        >>>
        >>> asyncio.run(test_admin_toggle_server_deactivate())
        True
        >>>
        >>> # Edge case: Toggle with inactive checkbox checked
        >>> form_data_inactive = FormData([("activate", "true"), ("is_inactive_checked", "true")])
        >>> mock_request_inactive = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_inactive.form = AsyncMock(return_value=form_data_inactive)
        >>>
        >>> async def test_admin_toggle_server_inactive_checked():
        ...     result = await admin_toggle_server(server_id, mock_request_inactive, mock_db, mock_user)
        ...     return isinstance(result, RedirectResponse) and result.status_code == 303 and "/admin/?include_inactive=true#catalog" in result.headers["location"]
        >>>
        >>> asyncio.run(test_admin_toggle_server_inactive_checked())
        True
        >>>
        >>> # Error path: Simulate an exception during toggle
        >>> form_data_error = FormData([("activate", "true")])
        >>> mock_request_error = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_error.form = AsyncMock(return_value=form_data_error)
        >>> server_service.toggle_server_status = AsyncMock(side_effect=Exception("Toggle failed"))
        >>>
        >>> async def test_admin_toggle_server_exception():
        ...     result = await admin_toggle_server(server_id, mock_request_error, mock_db, mock_user)
        ...     return isinstance(result, RedirectResponse) and result.status_code == 303 and "/admin#catalog" in result.headers["location"]
        >>>
        >>> asyncio.run(test_admin_toggle_server_exception())
        True
        >>>
        >>> # Restore original method
        >>> server_service.toggle_server_status = original_toggle_server_status
    """
    form = await request.form()
    LOGGER.debug(f"User {user} is toggling server ID {server_id} with activate: {form.get('activate')}")
    activate = str(form.get("activate", "true")).lower() == "true"
    is_inactive_checked = str(form.get("is_inactive_checked", "false"))
    try:
        await server_service.toggle_server_status(db, server_id, activate)
    except Exception as e:
        LOGGER.error(f"Error toggling server status: {e}")

    root_path = request.scope.get("root_path", "")
    if is_inactive_checked.lower() == "true":
        return RedirectResponse(f"{root_path}/admin/?include_inactive=true#catalog", status_code=303)
    return RedirectResponse(f"{root_path}/admin#catalog", status_code=303)


@admin_router.post("/servers/{server_id}/delete")
async def admin_delete_server(server_id: str, request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)) -> RedirectResponse:
    """
    Delete a server via the admin UI.

    This endpoint removes a server from the database by its ID. It handles exceptions
    gracefully and logs any errors that occur during the deletion process.

    Args:
        server_id (str): The ID of the server to delete
        request (Request): FastAPI request object (not used but required by route signature).
        db (Session): Database session dependency
        user (str): Authenticated user dependency

    Returns:
        RedirectResponse: A redirect to the admin dashboard catalog section with a
        status code of 303 (See Other)

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from fastapi import Request
        >>> from fastapi.responses import RedirectResponse
        >>> from starlette.datastructures import FormData
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = "test_user"
        >>> server_id = "server-to-delete"
        >>>
        >>> # Happy path: Delete server
        >>> form_data_delete = FormData([("is_inactive_checked", "false")])
        >>> mock_request_delete = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_delete.form = AsyncMock(return_value=form_data_delete)
        >>> original_delete_server = server_service.delete_server
        >>> server_service.delete_server = AsyncMock()
        >>>
        >>> async def test_admin_delete_server_success():
        ...     result = await admin_delete_server(server_id, mock_request_delete, mock_db, mock_user)
        ...     return isinstance(result, RedirectResponse) and result.status_code == 303 and "/admin#catalog" in result.headers["location"]
        >>>
        >>> asyncio.run(test_admin_delete_server_success())
        True
        >>>
        >>> # Edge case: Delete with inactive checkbox checked
        >>> form_data_inactive = FormData([("is_inactive_checked", "true")])
        >>> mock_request_inactive = MagicMock(spec=Request, scope={"root_path": "/api"})
        >>> mock_request_inactive.form = AsyncMock(return_value=form_data_inactive)
        >>>
        >>> async def test_admin_delete_server_inactive_checked():
        ...     result = await admin_delete_server(server_id, mock_request_inactive, mock_db, mock_user)
        ...     return isinstance(result, RedirectResponse) and result.status_code == 303 and "/api/admin/?include_inactive=true#catalog" in result.headers["location"]
        >>>
        >>> asyncio.run(test_admin_delete_server_inactive_checked())
        True
        >>>
        >>> # Error path: Simulate an exception during deletion
        >>> form_data_error = FormData([])
        >>> mock_request_error = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_error.form = AsyncMock(return_value=form_data_error)
        >>> server_service.delete_server = AsyncMock(side_effect=Exception("Deletion failed"))
        >>>
        >>> async def test_admin_delete_server_exception():
        ...     result = await admin_delete_server(server_id, mock_request_error, mock_db, mock_user)
        ...     return isinstance(result, RedirectResponse) and result.status_code == 303 and "/admin#catalog" in result.headers["location"]
        >>>
        >>> asyncio.run(test_admin_delete_server_exception())
        True
        >>>
        >>> # Restore original method
        >>> server_service.delete_server = original_delete_server
    """
    try:
        LOGGER.debug(f"User {user} is deleting server ID {server_id}")
        await server_service.delete_server(db, server_id)
    except Exception as e:
        LOGGER.error(f"Error deleting server: {e}")

    form = await request.form()
    is_inactive_checked = str(form.get("is_inactive_checked", "false"))
    root_path = request.scope.get("root_path", "")

    if is_inactive_checked.lower() == "true":
        return RedirectResponse(f"{root_path}/admin/?include_inactive=true#catalog", status_code=303)
    return RedirectResponse(f"{root_path}/admin#catalog", status_code=303)


@admin_router.get("/resources", response_model=List[ResourceRead])
async def admin_list_resources(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> List[Dict[str, Any]]:
    """
    List resources for the admin UI with an option to include inactive resources.

    This endpoint retrieves a list of resources from the database, optionally including
    those that are inactive. The inactive filter is useful for administrators who need
    to view or manage resources that have been deactivated but not deleted.

    Args:
        include_inactive (bool): Whether to include inactive resources in the results.
        db (Session): Database session dependency.
        user (str): Authenticated user dependency.

    Returns:
        List[ResourceRead]: A list of resource records formatted with by_alias=True.

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from mcpgateway.schemas import ResourceRead, ResourceMetrics
        >>> from datetime import datetime, timezone
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = "test_user"
        >>>
        >>> # Mock resource data
        >>> mock_resource = ResourceRead(
        ...     id=1,
        ...     uri="test://resource/1",
        ...     name="Test Resource",
        ...     description="A test resource",
        ...     mime_type="text/plain",
        ...     size=100,
        ...     created_at=datetime.now(timezone.utc),
        ...     updated_at=datetime.now(timezone.utc),
        ...     is_active=True,
        ...     metrics=ResourceMetrics(
        ...         total_executions=5, successful_executions=5, failed_executions=0,
        ...         failure_rate=0.0, min_response_time=0.1, max_response_time=0.5,
        ...         avg_response_time=0.3, last_execution_time=datetime.now(timezone.utc)
        ...     ),
        ...     tags=[]
        ... )
        >>>
        >>> # Mock the resource_service.list_resources method
        >>> original_list_resources = resource_service.list_resources
        >>> resource_service.list_resources = AsyncMock(return_value=[mock_resource])
        >>>
        >>> # Test listing active resources
        >>> async def test_admin_list_resources_active():
        ...     result = await admin_list_resources(include_inactive=False, db=mock_db, user=mock_user)
        ...     return len(result) > 0 and isinstance(result[0], dict) and result[0]['name'] == "Test Resource"
        >>>
        >>> asyncio.run(test_admin_list_resources_active())
        True
        >>>
        >>> # Test listing with inactive resources (if mock includes them)
        >>> mock_inactive_resource = ResourceRead(
        ...     id=2, uri="test://resource/2", name="Inactive Resource",
        ...     description="Another test", mime_type="application/json", size=50,
        ...     created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        ...     is_active=False, metrics=ResourceMetrics(
        ...         total_executions=0, successful_executions=0, failed_executions=0,
        ...         failure_rate=0.0, min_response_time=0.0, max_response_time=0.0,
        ...         avg_response_time=0.0, last_execution_time=None),
        ...     tags=[]
        ... )
        >>> resource_service.list_resources = AsyncMock(return_value=[mock_resource, mock_inactive_resource])
        >>> async def test_admin_list_resources_all():
        ...     result = await admin_list_resources(include_inactive=True, db=mock_db, user=mock_user)
        ...     return len(result) == 2 and not result[1]['isActive']
        >>>
        >>> asyncio.run(test_admin_list_resources_all())
        True
        >>>
        >>> # Test empty list
        >>> resource_service.list_resources = AsyncMock(return_value=[])
        >>> async def test_admin_list_resources_empty():
        ...     result = await admin_list_resources(include_inactive=False, db=mock_db, user=mock_user)
        ...     return result == []
        >>>
        >>> asyncio.run(test_admin_list_resources_empty())
        True
        >>>
        >>> # Test exception handling
        >>> resource_service.list_resources = AsyncMock(side_effect=Exception("Resource list error"))
        >>> async def test_admin_list_resources_exception():
        ...     try:
        ...         await admin_list_resources(False, mock_db, mock_user)
        ...         return False
        ...     except Exception as e:
        ...         return str(e) == "Resource list error"
        >>>
        >>> asyncio.run(test_admin_list_resources_exception())
        True
        >>>
        >>> # Restore original method
        >>> resource_service.list_resources = original_list_resources
    """
    LOGGER.debug(f"User {user} requested resource list")
    resources = await resource_service.list_resources(db, include_inactive=include_inactive)
    return [resource.model_dump(by_alias=True) for resource in resources]


@admin_router.get("/prompts", response_model=List[PromptRead])
async def admin_list_prompts(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> List[Dict[str, Any]]:
    """
    List prompts for the admin UI with an option to include inactive prompts.

    This endpoint retrieves a list of prompts from the database, optionally including
    those that are inactive. The inactive filter helps administrators see and manage
    prompts that have been deactivated but not deleted from the system.

    Args:
        include_inactive (bool): Whether to include inactive prompts in the results.
        db (Session): Database session dependency.
        user (str): Authenticated user dependency.

    Returns:
        List[PromptRead]: A list of prompt records formatted with by_alias=True.

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from mcpgateway.schemas import PromptRead, PromptMetrics
        >>> from datetime import datetime, timezone
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = "test_user"
        >>>
        >>> # Mock prompt data
        >>> mock_prompt = PromptRead(
        ...     id=1,
        ...     name="Test Prompt",
        ...     description="A test prompt",
        ...     template="Hello {{name}}!",
        ...     arguments=[{"name": "name", "type": "string"}],
        ...     created_at=datetime.now(timezone.utc),
        ...     updated_at=datetime.now(timezone.utc),
        ...     is_active=True,
        ...     metrics=PromptMetrics(
        ...         total_executions=10, successful_executions=10, failed_executions=0,
        ...         failure_rate=0.0, min_response_time=0.01, max_response_time=0.1,
        ...         avg_response_time=0.05, last_execution_time=datetime.now(timezone.utc)
        ...     ),
        ...     tags=[]
        ... )
        >>>
        >>> # Mock the prompt_service.list_prompts method
        >>> original_list_prompts = prompt_service.list_prompts
        >>> prompt_service.list_prompts = AsyncMock(return_value=[mock_prompt])
        >>>
        >>> # Test listing active prompts
        >>> async def test_admin_list_prompts_active():
        ...     result = await admin_list_prompts(include_inactive=False, db=mock_db, user=mock_user)
        ...     return len(result) > 0 and isinstance(result[0], dict) and result[0]['name'] == "Test Prompt"
        >>>
        >>> asyncio.run(test_admin_list_prompts_active())
        True
        >>>
        >>> # Test listing with inactive prompts (if mock includes them)
        >>> mock_inactive_prompt = PromptRead(
        ...     id=2, name="Inactive Prompt", description="Another test", template="Bye!",
        ...     arguments=[], created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        ...     is_active=False, metrics=PromptMetrics(
        ...         total_executions=0, successful_executions=0, failed_executions=0,
        ...         failure_rate=0.0, min_response_time=0.0, max_response_time=0.0,
        ...         avg_response_time=0.0, last_execution_time=None
        ...     ),
        ...     tags=[]
        ... )
        >>> prompt_service.list_prompts = AsyncMock(return_value=[mock_prompt, mock_inactive_prompt])
        >>> async def test_admin_list_prompts_all():
        ...     result = await admin_list_prompts(include_inactive=True, db=mock_db, user=mock_user)
        ...     return len(result) == 2 and not result[1]['isActive']
        >>>
        >>> asyncio.run(test_admin_list_prompts_all())
        True
        >>>
        >>> # Test empty list
        >>> prompt_service.list_prompts = AsyncMock(return_value=[])
        >>> async def test_admin_list_prompts_empty():
        ...     result = await admin_list_prompts(include_inactive=False, db=mock_db, user=mock_user)
        ...     return result == []
        >>>
        >>> asyncio.run(test_admin_list_prompts_empty())
        True
        >>>
        >>> # Test exception handling
        >>> prompt_service.list_prompts = AsyncMock(side_effect=Exception("Prompt list error"))
        >>> async def test_admin_list_prompts_exception():
        ...     try:
        ...         await admin_list_prompts(False, mock_db, mock_user)
        ...         return False
        ...     except Exception as e:
        ...         return str(e) == "Prompt list error"
        >>>
        >>> asyncio.run(test_admin_list_prompts_exception())
        True
        >>>
        >>> # Restore original method
        >>> prompt_service.list_prompts = original_list_prompts
    """
    LOGGER.debug(f"User {user} requested prompt list")
    prompts = await prompt_service.list_prompts(db, include_inactive=include_inactive)
    return [prompt.model_dump(by_alias=True) for prompt in prompts]


@admin_router.get("/gateways", response_model=List[GatewayRead])
async def admin_list_gateways(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> List[Dict[str, Any]]:
    """
    List gateways for the admin UI with an option to include inactive gateways.

    This endpoint retrieves a list of gateways from the database, optionally
    including those that are inactive. The inactive filter allows administrators
    to view and manage gateways that have been deactivated but not deleted.

    Args:
        include_inactive (bool): Whether to include inactive gateways in the results.
        db (Session): Database session dependency.
        user (str): Authenticated user dependency.

    Returns:
        List[GatewayRead]: A list of gateway records formatted with by_alias=True.

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from mcpgateway.schemas import GatewayRead
        >>> from datetime import datetime, timezone
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = "test_user"
        >>>
        >>> # Mock gateway data
        >>> mock_gateway = GatewayRead(
        ...     id="gateway-1",
        ...     name="Test Gateway",
        ...     url="http://test.com",
        ...     description="A test gateway",
        ...     transport="HTTP",
        ...     created_at=datetime.now(timezone.utc),
        ...     updated_at=datetime.now(timezone.utc),
        ...     is_active=True,
        ...     auth_type=None, auth_username=None, auth_password=None, auth_token=None,
        ...     auth_header_key=None, auth_header_value=None,
        ...     slug="test-gateway"
        ... )
        >>>
        >>> # Mock the gateway_service.list_gateways method
        >>> original_list_gateways = gateway_service.list_gateways
        >>> gateway_service.list_gateways = AsyncMock(return_value=[mock_gateway])
        >>>
        >>> # Test listing active gateways
        >>> async def test_admin_list_gateways_active():
        ...     result = await admin_list_gateways(include_inactive=False, db=mock_db, user=mock_user)
        ...     return len(result) > 0 and isinstance(result[0], dict) and result[0]['name'] == "Test Gateway"
        >>>
        >>> asyncio.run(test_admin_list_gateways_active())
        True
        >>>
        >>> # Test listing with inactive gateways (if mock includes them)
        >>> mock_inactive_gateway = GatewayRead(
        ...     id="gateway-2", name="Inactive Gateway", url="http://inactive.com",
        ...     description="Another test", transport="HTTP", created_at=datetime.now(timezone.utc),
        ...     updated_at=datetime.now(timezone.utc), enabled=False,
        ...     auth_type=None, auth_username=None, auth_password=None, auth_token=None,
        ...     auth_header_key=None, auth_header_value=None,
        ...     slug="test-gateway"
        ... )
        >>> gateway_service.list_gateways = AsyncMock(return_value=[
        ...     mock_gateway, # Return the GatewayRead objects, not pre-dumped dicts
        ...     mock_inactive_gateway # Return the GatewayRead objects, not pre-dumped dicts
        ... ])
        >>> async def test_admin_list_gateways_all():
        ...     result = await admin_list_gateways(include_inactive=True, db=mock_db, user=mock_user)
        ...     return len(result) == 2 and not result[1]['enabled']
        >>>
        >>> asyncio.run(test_admin_list_gateways_all())
        True
        >>>
        >>> # Test empty list
        >>> gateway_service.list_gateways = AsyncMock(return_value=[])
        >>> async def test_admin_list_gateways_empty():
        ...     result = await admin_list_gateways(include_inactive=False, db=mock_db, user=mock_user)
        ...     return result == []
        >>>
        >>> asyncio.run(test_admin_list_gateways_empty())
        True
        >>>
        >>> # Test exception handling
        >>> gateway_service.list_gateways = AsyncMock(side_effect=Exception("Gateway list error"))
        >>> async def test_admin_list_gateways_exception():
        ...     try:
        ...         await admin_list_gateways(False, mock_db, mock_user)
        ...         return False
        ...     except Exception as e:
        ...         return str(e) == "Gateway list error"
        >>>
        >>> asyncio.run(test_admin_list_gateways_exception())
        True
        >>>
        >>> # Restore original method
        >>> gateway_service.list_gateways = original_list_gateways
    """
    LOGGER.debug(f"User {user} requested gateway list")
    gateways = await gateway_service.list_gateways(db, include_inactive=include_inactive)
    return [gateway.model_dump(by_alias=True) for gateway in gateways]


@admin_router.post("/gateways/{gateway_id}/toggle")
async def admin_toggle_gateway(
    gateway_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> RedirectResponse:
    """
    Toggle the active status of a gateway via the admin UI.

    This endpoint allows an admin to toggle the active status of a gateway.
    It expects a form field 'activate' with a value of "true" or "false" to
    determine the new status of the gateway.

    Args:
        gateway_id (str): The ID of the gateway to toggle.
        request (Request): The FastAPI request object containing form data.
        db (Session): The database session dependency.
        user (str): The authenticated user dependency.

    Returns:
        RedirectResponse: A redirect response to the admin dashboard with a
        status code of 303 (See Other).

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from fastapi import Request
        >>> from fastapi.responses import RedirectResponse
        >>> from starlette.datastructures import FormData
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = "test_user"
        >>> gateway_id = "gateway-to-toggle"
        >>>
        >>> # Happy path: Activate gateway
        >>> form_data_activate = FormData([("activate", "true"), ("is_inactive_checked", "false")])
        >>> mock_request_activate = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_activate.form = AsyncMock(return_value=form_data_activate)
        >>> original_toggle_gateway_status = gateway_service.toggle_gateway_status
        >>> gateway_service.toggle_gateway_status = AsyncMock()
        >>>
        >>> async def test_admin_toggle_gateway_activate():
        ...     result = await admin_toggle_gateway(gateway_id, mock_request_activate, mock_db, mock_user)
        ...     return isinstance(result, RedirectResponse) and result.status_code == 303 and "/admin#gateways" in result.headers["location"]
        >>>
        >>> asyncio.run(test_admin_toggle_gateway_activate())
        True
        >>>
        >>> # Happy path: Deactivate gateway
        >>> form_data_deactivate = FormData([("activate", "false"), ("is_inactive_checked", "false")])
        >>> mock_request_deactivate = MagicMock(spec=Request, scope={"root_path": "/api"})
        >>> mock_request_deactivate.form = AsyncMock(return_value=form_data_deactivate)
        >>>
        >>> async def test_admin_toggle_gateway_deactivate():
        ...     result = await admin_toggle_gateway(gateway_id, mock_request_deactivate, mock_db, mock_user)
        ...     return isinstance(result, RedirectResponse) and result.status_code == 303 and "/api/admin#gateways" in result.headers["location"]
        >>>
        >>> asyncio.run(test_admin_toggle_gateway_deactivate())
        True
        >>>
        >>> # Edge case: Toggle with inactive checkbox checked
        >>> form_data_inactive = FormData([("activate", "true"), ("is_inactive_checked", "true")])
        >>> mock_request_inactive = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_inactive.form = AsyncMock(return_value=form_data_inactive)
        >>>
        >>> async def test_admin_toggle_gateway_inactive_checked():
        ...     result = await admin_toggle_gateway(gateway_id, mock_request_inactive, mock_db, mock_user)
        ...     return isinstance(result, RedirectResponse) and result.status_code == 303 and "/admin/?include_inactive=true#gateways" in result.headers["location"]
        >>>
        >>> asyncio.run(test_admin_toggle_gateway_inactive_checked())
        True
        >>>
        >>> # Error path: Simulate an exception during toggle
        >>> form_data_error = FormData([("activate", "true")])
        >>> mock_request_error = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_error.form = AsyncMock(return_value=form_data_error)
        >>> gateway_service.toggle_gateway_status = AsyncMock(side_effect=Exception("Toggle failed"))
        >>>
        >>> async def test_admin_toggle_gateway_exception():
        ...     result = await admin_toggle_gateway(gateway_id, mock_request_error, mock_db, mock_user)
        ...     return isinstance(result, RedirectResponse) and result.status_code == 303 and "/admin#gateways" in result.headers["location"]
        >>>
        >>> asyncio.run(test_admin_toggle_gateway_exception())
        True
        >>>
        >>> # Restore original method
        >>> gateway_service.toggle_gateway_status = original_toggle_gateway_status
    """
    LOGGER.debug(f"User {user} is toggling gateway ID {gateway_id}")
    form = await request.form()
    activate = str(form.get("activate", "true")).lower() == "true"
    is_inactive_checked = str(form.get("is_inactive_checked", "false"))

    try:
        await gateway_service.toggle_gateway_status(db, gateway_id, activate)
    except Exception as e:
        LOGGER.error(f"Error toggling gateway status: {e}")

    root_path = request.scope.get("root_path", "")
    if is_inactive_checked.lower() == "true":
        return RedirectResponse(f"{root_path}/admin/?include_inactive=true#gateways", status_code=303)
    return RedirectResponse(f"{root_path}/admin#gateways", status_code=303)


@admin_router.get("/", name="admin_home", response_class=HTMLResponse)
async def admin_ui(
    request: Request,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    user: str = Depends(require_basic_auth),
    jwt_token: str = Depends(get_jwt_token),
) -> Any:
    """
    Render the admin dashboard HTML page.

    This endpoint serves as the main entry point to the admin UI. It fetches data for
    servers, tools, resources, prompts, gateways, and roots from their respective
    services, then renders the admin dashboard template with this data.

    The endpoint also sets a JWT token as a cookie for authentication in subsequent
    requests. This token is HTTP-only for security reasons.

    Args:
        request (Request): FastAPI request object.
        include_inactive (bool): Whether to include inactive items in all listings.
        db (Session): Database session dependency.
        user (str): Authenticated user from basic auth dependency.
        jwt_token (str): JWT token for authentication.

    Returns:
        Any: Rendered HTML template for the admin dashboard.

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock, patch
        >>> from fastapi import Request
        >>> from fastapi.responses import HTMLResponse
        >>> from mcpgateway.schemas import ServerRead, ToolRead, ResourceRead, PromptRead, GatewayRead, ServerMetrics, ToolMetrics, ResourceMetrics, PromptMetrics
        >>> from datetime import datetime, timezone
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = "admin_user"
        >>> mock_jwt = "fake.jwt.token"
        >>>
        >>> # Mock services to return empty lists for simplicity in doctest
        >>> original_list_servers = server_service.list_servers
        >>> original_list_tools = tool_service.list_tools
        >>> original_list_resources = resource_service.list_resources
        >>> original_list_prompts = prompt_service.list_prompts
        >>> original_list_gateways = gateway_service.list_gateways
        >>> original_list_roots = root_service.list_roots
        >>>
        >>> server_service.list_servers = AsyncMock(return_value=[])
        >>> tool_service.list_tools = AsyncMock(return_value=[])
        >>> resource_service.list_resources = AsyncMock(return_value=[])
        >>> prompt_service.list_prompts = AsyncMock(return_value=[])
        >>> gateway_service.list_gateways = AsyncMock(return_value=[])
        >>> root_service.list_roots = AsyncMock(return_value=[])
        >>>
        >>> # Mock request and template rendering
        >>> mock_request = MagicMock(spec=Request, scope={"root_path": "/admin_prefix"})
        >>> mock_request.app.state.templates = MagicMock()
        >>> mock_template_response = HTMLResponse("<html>Admin UI</html>")
        >>> mock_request.app.state.templates.TemplateResponse.return_value = mock_template_response
        >>>
        >>> # Test basic rendering
        >>> async def test_admin_ui_basic_render():
        ...     response = await admin_ui(mock_request, False, mock_db, mock_user, mock_jwt)
        ...     return isinstance(response, HTMLResponse) and response.status_code == 200 and "jwt_token" in response.headers.get("set-cookie", "")
        >>>
        >>> asyncio.run(test_admin_ui_basic_render())
        True
        >>>
        >>> # Test with include_inactive=True
        >>> async def test_admin_ui_include_inactive():
        ...     response = await admin_ui(mock_request, True, mock_db, mock_user, mock_jwt)
        ...     # Verify list methods were called with include_inactive=True
        ...     server_service.list_servers.assert_called_with(mock_db, include_inactive=True)
        ...     return isinstance(response, HTMLResponse)
        >>>
        >>> asyncio.run(test_admin_ui_include_inactive())
        True
        >>>
        >>> # Test with populated data (mocking a few items)
        >>> mock_server = ServerRead(id="s1", name="S1", description="d", created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc), is_active=True, associated_tools=[], associated_resources=[], associated_prompts=[], icon="i", metrics=ServerMetrics(total_executions=0, successful_executions=0, failed_executions=0, failure_rate=0.0, min_response_time=0.0, max_response_time=0.0, avg_response_time=0.0, last_execution_time=None))
        >>> mock_tool = ToolRead(
        ...     id="t1", name="T1", original_name="T1", url="http://t1.com", description="d",
        ...     created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        ...     enabled=True, reachable=True, gateway_slug="default", custom_name_slug="t1",
        ...     request_type="GET", integration_type="MCP", headers={}, input_schema={},
        ...     annotations={}, jsonpath_filter=None, auth=None, execution_count=0,
        ...     metrics=ToolMetrics(
        ...         total_executions=0, successful_executions=0, failed_executions=0,
        ...         failure_rate=0.0, min_response_time=0.0, max_response_time=0.0,
        ...         avg_response_time=0.0, last_execution_time=None
        ...     ),
        ...     gateway_id=None,
        ...     customName="T1",
        ...     tags=[]
        ... )
        >>> server_service.list_servers = AsyncMock(return_value=[mock_server])
        >>> tool_service.list_tools = AsyncMock(return_value=[mock_tool])
        >>>
        >>> async def test_admin_ui_with_data():
        ...     response = await admin_ui(mock_request, False, mock_db, mock_user, mock_jwt)
        ...     # Check if template context was populated (indirectly via mock calls)
        ...     assert mock_request.app.state.templates.TemplateResponse.call_count >= 1
        ...     context = mock_request.app.state.templates.TemplateResponse.call_args[0][2]
        ...     return len(context['servers']) == 1 and len(context['tools']) == 1
        >>>
        >>> asyncio.run(test_admin_ui_with_data())
        True
        >>>
        >>> # Test exception handling during data fetching
        >>> server_service.list_servers = AsyncMock(side_effect=Exception("DB error"))
        >>> async def test_admin_ui_exception_handled():
        ...     try:
        ...         response = await admin_ui(mock_request, False, mock_db, mock_user, mock_jwt)
        ...         return False  # Should not reach here if exception is properly raised
        ...     except Exception as e:
        ...         return str(e) == "DB error"
        >>>
        >>> asyncio.run(test_admin_ui_exception_handled())
        True
        >>>
        >>> # Restore original methods
        >>> server_service.list_servers = original_list_servers
        >>> tool_service.list_tools = original_list_tools
        >>> resource_service.list_resources = original_list_resources
        >>> prompt_service.list_prompts = original_list_prompts
        >>> gateway_service.list_gateways = original_list_gateways
        >>> root_service.list_roots = original_list_roots
    """
    LOGGER.debug(f"User {user} accessed the admin UI")
    tools = [
        tool.model_dump(by_alias=True) for tool in sorted(await tool_service.list_tools(db, include_inactive=include_inactive), key=lambda t: ((t.url or "").lower(), (t.original_name or "").lower()))
    ]
    servers = [server.model_dump(by_alias=True) for server in await server_service.list_servers(db, include_inactive=include_inactive)]
    resources = [resource.model_dump(by_alias=True) for resource in await resource_service.list_resources(db, include_inactive=include_inactive)]
    prompts = [prompt.model_dump(by_alias=True) for prompt in await prompt_service.list_prompts(db, include_inactive=include_inactive)]
    gateways_raw = await gateway_service.list_gateways(db, include_inactive=include_inactive)
    gateways = [gateway.model_dump(by_alias=True) for gateway in gateways_raw]

    roots = [root.model_dump(by_alias=True) for root in await root_service.list_roots()]

    # Load A2A agents if enabled
    a2a_agents = []
    if a2a_service and settings.mcpgateway_a2a_enabled:
        a2a_agents_raw = await a2a_service.list_agents(db, include_inactive=include_inactive)
        a2a_agents = [agent.model_dump(by_alias=True) for agent in a2a_agents_raw]

    root_path = settings.app_root_path
    max_name_length = settings.validation_max_name_length
    response = request.app.state.templates.TemplateResponse(
        request,
        "admin.html",
        {
            "request": request,
            "servers": servers,
            "tools": tools,
            "resources": resources,
            "prompts": prompts,
            "gateways": gateways,
            "a2a_agents": a2a_agents,
            "roots": roots,
            "include_inactive": include_inactive,
            "root_path": root_path,
            "max_name_length": max_name_length,
            "gateway_tool_name_separator": settings.gateway_tool_name_separator,
            "bulk_import_max_tools": settings.mcpgateway_bulk_import_max_tools,
            "a2a_enabled": settings.mcpgateway_a2a_enabled,
        },
    )

    # Use secure cookie utility for proper security attributes
    set_auth_cookie(response, jwt_token, remember_me=False)
    return response


@admin_router.get("/tools", response_model=List[ToolRead])
async def admin_list_tools(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> List[Dict[str, Any]]:
    """
    List tools for the admin UI with an option to include inactive tools.

    This endpoint retrieves a list of tools from the database, optionally including
    those that are inactive. The inactive filter helps administrators manage tools
    that have been deactivated but not deleted from the system.

    Args:
        include_inactive (bool): Whether to include inactive tools in the results.
        db (Session): Database session dependency.
        user (str): Authenticated user dependency.

    Returns:
        List[ToolRead]: A list of tool records formatted with by_alias=True.

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from mcpgateway.schemas import ToolRead, ToolMetrics
        >>> from datetime import datetime, timezone
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = "test_user"
        >>>
        >>> # Mock tool data
    >>> mock_tool = ToolRead(
    ...     id="tool-1",
    ...     name="Test Tool",
    ...     original_name="TestTool",
    ...     url="http://test.com/tool",
    ...     description="A test tool",
    ...     request_type="HTTP",
    ...     integration_type="MCP",
    ...     headers={},
    ...     input_schema={},
    ...     annotations={},
    ...     jsonpath_filter=None,
    ...     auth=None,
    ...     created_at=datetime.now(timezone.utc),
    ...     updated_at=datetime.now(timezone.utc),
    ...     enabled=True,
    ...     reachable=True,
    ...     gateway_id=None,
    ...     execution_count=0,
    ...     metrics=ToolMetrics(
    ...         total_executions=5, successful_executions=5, failed_executions=0,
    ...         failure_rate=0.0, min_response_time=0.1, max_response_time=0.5,
    ...         avg_response_time=0.3, last_execution_time=datetime.now(timezone.utc)
    ...     ),
    ...     gateway_slug="default",
    ...     custom_name_slug="test-tool",
    ...     customName="Test Tool",
    ...     tags=[]
    ... )  #  Added gateway_id=None
        >>>
        >>> # Mock the tool_service.list_tools method
        >>> original_list_tools = tool_service.list_tools
        >>> tool_service.list_tools = AsyncMock(return_value=[mock_tool])
        >>>
        >>> # Test listing active tools
        >>> async def test_admin_list_tools_active():
        ...     result = await admin_list_tools(include_inactive=False, db=mock_db, user=mock_user)
        ...     return len(result) > 0 and isinstance(result[0], dict) and result[0]['name'] == "Test Tool"
        >>>
        >>> asyncio.run(test_admin_list_tools_active())
        True
        >>>
        >>> # Test listing with inactive tools (if mock includes them)
        >>> mock_inactive_tool = ToolRead(
        ...     id="tool-2", name="Inactive Tool", original_name="InactiveTool", url="http://inactive.com",
        ...     description="Another test", request_type="HTTP", integration_type="MCP",
        ...     headers={}, input_schema={}, annotations={}, jsonpath_filter=None, auth=None,
        ...     created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        ...     enabled=False, reachable=False, gateway_id=None, execution_count=0,
        ...     metrics=ToolMetrics(
        ...         total_executions=0, successful_executions=0, failed_executions=0,
        ...         failure_rate=0.0, min_response_time=0.0, max_response_time=0.0,
        ...         avg_response_time=0.0, last_execution_time=None
        ...     ),
        ...     gateway_slug="default", custom_name_slug="inactive-tool",
        ...     customName="Inactive Tool",
        ...     tags=[]
        ... )
        >>> tool_service.list_tools = AsyncMock(return_value=[mock_tool, mock_inactive_tool])
        >>> async def test_admin_list_tools_all():
        ...     result = await admin_list_tools(include_inactive=True, db=mock_db, user=mock_user)
        ...     return len(result) == 2 and not result[1]['enabled']
        >>>
        >>> asyncio.run(test_admin_list_tools_all())
        True
        >>>
        >>> # Test empty list
        >>> tool_service.list_tools = AsyncMock(return_value=[])
        >>> async def test_admin_list_tools_empty():
        ...     result = await admin_list_tools(include_inactive=False, db=mock_db, user=mock_user)
        ...     return result == []
        >>>
        >>> asyncio.run(test_admin_list_tools_empty())
        True
        >>>
        >>> # Test exception handling
        >>> tool_service.list_tools = AsyncMock(side_effect=Exception("Tool list error"))
        >>> async def test_admin_list_tools_exception():
        ...     try:
        ...         await admin_list_tools(False, mock_db, mock_user)
        ...         return False
        ...     except Exception as e:
        ...         return str(e) == "Tool list error"
        >>>
        >>> asyncio.run(test_admin_list_tools_exception())
        True
        >>>
        >>> # Restore original method
        >>> tool_service.list_tools = original_list_tools
    """
    LOGGER.debug(f"User {user} requested tool list")
    tools = await tool_service.list_tools(db, include_inactive=include_inactive)

    return [tool.model_dump(by_alias=True) for tool in tools]


@admin_router.get("/tools/{tool_id}", response_model=ToolRead)
async def admin_get_tool(tool_id: str, db: Session = Depends(get_db), user: str = Depends(require_auth)) -> Dict[str, Any]:
    """
    Retrieve specific tool details for the admin UI.

    This endpoint fetches the details of a specific tool from the database
    by its ID. It provides access to all information about the tool for
    viewing and management purposes.

    Args:
        tool_id (str): The ID of the tool to retrieve.
        db (Session): Database session dependency.
        user (str): Authenticated user dependency.

    Returns:
        ToolRead: The tool details formatted with by_alias=True.

    Raises:
        HTTPException: If the tool is not found.
        Exception: For any other unexpected errors.

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from mcpgateway.schemas import ToolRead, ToolMetrics
        >>> from datetime import datetime, timezone
        >>> from mcpgateway.services.tool_service import ToolNotFoundError # Added import
        >>> from fastapi import HTTPException
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = "test_user"
        >>> tool_id = "test-tool-id"
        >>>
        >>> # Mock tool data
        >>> mock_tool = ToolRead(
        ...     id=tool_id, name="Get Tool", original_name="GetTool", url="http://get.com",
        ...     description="Tool for getting", request_type="GET", integration_type="REST",
        ...     headers={}, input_schema={}, annotations={}, jsonpath_filter=None, auth=None,
        ...     created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        ...     enabled=True, reachable=True, gateway_id=None, execution_count=0,
        ...     metrics=ToolMetrics(
        ...         total_executions=0, successful_executions=0, failed_executions=0,
        ...         failure_rate=0.0, min_response_time=0.0, max_response_time=0.0, avg_response_time=0.0,
        ...         last_execution_time=None
        ...     ),
        ...     gateway_slug="default", custom_name_slug="get-tool",
        ...     customName="Get Tool",
        ...     tags=[]
        ... )
        >>>
        >>> # Mock the tool_service.get_tool method
        >>> original_get_tool = tool_service.get_tool
        >>> tool_service.get_tool = AsyncMock(return_value=mock_tool)
        >>>
        >>> # Test successful retrieval
        >>> async def test_admin_get_tool_success():
        ...     result = await admin_get_tool(tool_id, mock_db, mock_user)
        ...     return isinstance(result, dict) and result['id'] == tool_id
        >>>
        >>> asyncio.run(test_admin_get_tool_success())
        True
        >>>
        >>> # Test tool not found
        >>> tool_service.get_tool = AsyncMock(side_effect=ToolNotFoundError("Tool not found"))
        >>> async def test_admin_get_tool_not_found():
        ...     try:
        ...         await admin_get_tool("nonexistent", mock_db, mock_user)
        ...         return False
        ...     except HTTPException as e:
        ...         return e.status_code == 404 and "Tool not found" in e.detail
        >>>
        >>> asyncio.run(test_admin_get_tool_not_found())
        True
        >>>
        >>> # Test generic exception
        >>> tool_service.get_tool = AsyncMock(side_effect=Exception("Generic error"))
        >>> async def test_admin_get_tool_exception():
        ...     try:
        ...         await admin_get_tool(tool_id, mock_db, mock_user)
        ...         return False
        ...     except Exception as e:
        ...         return str(e) == "Generic error"
        >>>
        >>> asyncio.run(test_admin_get_tool_exception())
        True
        >>>
        >>> # Restore original method
        >>> tool_service.get_tool = original_get_tool
    """
    LOGGER.debug(f"User {user} requested details for tool ID {tool_id}")
    try:
        tool = await tool_service.get_tool(db, tool_id)
        return tool.model_dump(by_alias=True)
    except ToolNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        # Catch any other unexpected errors and re-raise or log as needed
        LOGGER.error(f"Error getting tool {tool_id}: {e}")
        raise e  # Re-raise for now, or return a 500 JSONResponse if preferred for API consistency


@admin_router.post("/tools/")
@admin_router.post("/tools")
async def admin_add_tool(
    request: Request,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> JSONResponse:
    """
    Add a tool via the admin UI with error handling.

    Expects form fields:
      - name
      - url
      - description (optional)
      - requestType (mapped to request_type; defaults to "SSE")
      - integrationType (mapped to integration_type; defaults to "MCP")
      - headers (JSON string)
      - input_schema (JSON string)
      - jsonpath_filter (optional)
      - auth_type (optional)
      - auth_username (optional)
      - auth_password (optional)
      - auth_token (optional)
      - auth_header_key (optional)
      - auth_header_value (optional)

    Logs the raw form data and assembled tool_data for debugging.

    Args:
        request (Request): the FastAPI request object containing the form data.
        db (Session): the SQLAlchemy database session.
        user (str): identifier of the authenticated user.

    Returns:
        JSONResponse: a JSON response with `{"message": ..., "success": ...}` and an appropriate HTTP status code.

    Examples:
        Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from fastapi import Request
        >>> from fastapi.responses import JSONResponse
        >>> from starlette.datastructures import FormData
        >>> from sqlalchemy.exc import IntegrityError
        >>> from mcpgateway.utils.error_formatter import ErrorFormatter
        >>> import json

        >>> mock_db = MagicMock()
        >>> mock_user = "test_user"

        >>> # Happy path: Add a new tool successfully
        >>> form_data_success = FormData([
        ...     ("name", "New_Tool"),
        ...     ("url", "http://new.tool.com"),
        ...     ("requestType", "GET"),
        ...     ("integrationType", "REST"),
        ...     ("headers", '{"X-Api-Key": "abc"}')
        ... ])
        >>> mock_request_success = MagicMock(spec=Request)
        >>> mock_request_success.form = AsyncMock(return_value=form_data_success)
        >>> original_register_tool = tool_service.register_tool
        >>> tool_service.register_tool = AsyncMock()

        >>> async def test_admin_add_tool_success():
        ...     response = await admin_add_tool(mock_request_success, mock_db, mock_user)
        ...     return isinstance(response, JSONResponse) and response.status_code == 200 and json.loads(response.body.decode())["success"] is True

        >>> asyncio.run(test_admin_add_tool_success())
        True

        >>> # Error path: Tool name conflict via IntegrityError
        >>> form_data_conflict = FormData([
        ...     ("name", "Existing_Tool"),
        ...     ("url", "http://existing.com"),
        ...     ("requestType", "GET"),
        ...     ("integrationType", "REST")
        ... ])
        >>> mock_request_conflict = MagicMock(spec=Request)
        >>> mock_request_conflict.form = AsyncMock(return_value=form_data_conflict)
        >>> fake_integrity_error = IntegrityError("Mock Integrity Error", {}, None)
        >>> tool_service.register_tool = AsyncMock(side_effect=fake_integrity_error)

        >>> async def test_admin_add_tool_integrity_error():
        ...     response = await admin_add_tool(mock_request_conflict, mock_db, mock_user)
        ...     return isinstance(response, JSONResponse) and response.status_code == 409 and json.loads(response.body.decode())["success"] is False

        >>> asyncio.run(test_admin_add_tool_integrity_error())
        True

        >>> # Error path: Missing required field (Pydantic ValidationError)
        >>> form_data_missing = FormData([
        ...     ("url", "http://missing.com"),
        ...     ("requestType", "GET"),
        ...     ("integrationType", "REST")
        ... ])
        >>> mock_request_missing = MagicMock(spec=Request)
        >>> mock_request_missing.form = AsyncMock(return_value=form_data_missing)

        >>> async def test_admin_add_tool_validation_error():
        ...     response = await admin_add_tool(mock_request_missing, mock_db, mock_user)
        ...     return isinstance(response, JSONResponse) and response.status_code == 422 and json.loads(response.body.decode())["success"] is False

        >>> asyncio.run(test_admin_add_tool_validation_error())  # doctest: +ELLIPSIS
        True

        >>> # Error path: Unexpected exception
        >>> form_data_generic_error = FormData([
        ...     ("name", "Generic_Error_Tool"),
        ...     ("url", "http://generic.com"),
        ...     ("requestType", "GET"),
        ...     ("integrationType", "REST")
        ... ])
        >>> mock_request_generic_error = MagicMock(spec=Request)
        >>> mock_request_generic_error.form = AsyncMock(return_value=form_data_generic_error)
        >>> tool_service.register_tool = AsyncMock(side_effect=Exception("Unexpected error"))

        >>> async def test_admin_add_tool_generic_exception():
        ...     response = await admin_add_tool(mock_request_generic_error, mock_db, mock_user)
        ...     return isinstance(response, JSONResponse) and response.status_code == 500 and json.loads(response.body.decode())["success"] is False

        >>> asyncio.run(test_admin_add_tool_generic_exception())
        True

        >>> # Restore original method
        >>> tool_service.register_tool = original_register_tool

    """
    LOGGER.debug(f"User {user} is adding a new tool")
    form = await request.form()
    LOGGER.debug(f"Received form data: {dict(form)}")

    integration_type = form.get("integrationType", "REST")
    request_type = form.get("requestType")

    if request_type is None:
        if integration_type == "REST":
            request_type = "GET"  # or any valid REST method default
        elif integration_type == "MCP":
            request_type = "SSE"
        else:
            request_type = "GET"

    # Parse tags from comma-separated string
    tags_str = str(form.get("tags", ""))
    tags: list[str] = [tag.strip() for tag in tags_str.split(",") if tag.strip()] if tags_str else []

    tool_data: dict[str, Any] = {
        "name": form.get("name"),
        "url": form.get("url"),
        "description": form.get("description"),
        "request_type": request_type,
        "integration_type": integration_type,
        "headers": json.loads(form.get("headers") or "{}"),
        "input_schema": json.loads(form.get("input_schema") or "{}"),
        "annotations": json.loads(form.get("annotations") or "{}"),
        "jsonpath_filter": form.get("jsonpath_filter", ""),
        "auth_type": form.get("auth_type", ""),
        "auth_username": form.get("auth_username", ""),
        "auth_password": form.get("auth_password", ""),
        "auth_token": form.get("auth_token", ""),
        "auth_header_key": form.get("auth_header_key", ""),
        "auth_header_value": form.get("auth_header_value", ""),
        "tags": tags,
    }
    LOGGER.debug(f"Tool data built: {tool_data}")
    try:
        tool = ToolCreate(**tool_data)
        LOGGER.debug(f"Validated tool data: {tool.model_dump(by_alias=True)}")

        # Extract creation metadata
        metadata = MetadataCapture.extract_creation_metadata(request, user)

        await tool_service.register_tool(
            db,
            tool,
            created_by=metadata["created_by"],
            created_from_ip=metadata["created_from_ip"],
            created_via=metadata["created_via"],
            created_user_agent=metadata["created_user_agent"],
            import_batch_id=metadata["import_batch_id"],
            federation_source=metadata["federation_source"],
        )
        return JSONResponse(
            content={"message": "Tool registered successfully!", "success": True},
            status_code=200,
        )
    except IntegrityError as ex:
        error_message = ErrorFormatter.format_database_error(ex)
        LOGGER.error(f"IntegrityError in admin_add_resource: {error_message}")
        return JSONResponse(status_code=409, content=error_message)
    except ToolError as ex:
        return JSONResponse(content={"message": str(ex), "success": False}, status_code=500)
    except ValidationError as ex:  # This block should catch ValidationError
        LOGGER.error(f"ValidationError in admin_add_tool: {str(ex)}")
        return JSONResponse(content=ErrorFormatter.format_validation_error(ex), status_code=422)
    except Exception as ex:
        LOGGER.error(f"Unexpected error in admin_add_tool: {str(ex)}")
        return JSONResponse(content={"message": str(ex), "success": False}, status_code=500)


@admin_router.post("/tools/{tool_id}/edit/", response_model=None)
@admin_router.post("/tools/{tool_id}/edit", response_model=None)
async def admin_edit_tool(
    tool_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> Response:
    """
    Edit a tool via the admin UI.

    Expects form fields:
      - name
      - url
      - description (optional)
      - requestType (to be mapped to request_type)
      - integrationType (to be mapped to integration_type)
      - headers (as a JSON string)
      - input_schema (as a JSON string)
      - jsonpathFilter (optional)
      - auth_type (optional, string: "basic", "bearer", or empty)
      - auth_username (optional, for basic auth)
      - auth_password (optional, for basic auth)
      - auth_token (optional, for bearer auth)
      - auth_header_key (optional, for headers auth)
      - auth_header_value (optional, for headers auth)

    Assembles the tool_data dictionary by remapping form keys into the
    snake-case keys expected by the schemas.

    Args:
        tool_id (str): The ID of the tool to edit.
        request (Request): FastAPI request containing form data.
        db (Session): Database session dependency.
        user (str): Authenticated user dependency.

    Returns:
        Response: A redirect response to the tools section of the admin
            dashboard with a status code of 303 (See Other), or a JSON response with
            an error message if the update fails.

    Examples:
            Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from fastapi import Request
        >>> from fastapi.responses import RedirectResponse, JSONResponse
        >>> from starlette.datastructures import FormData
        >>> from sqlalchemy.exc import IntegrityError
        >>> from mcpgateway.services.tool_service import ToolError
        >>> from pydantic import ValidationError
        >>> from mcpgateway.utils.error_formatter import ErrorFormatter
        >>> import json

        >>> mock_db = MagicMock()
        >>> mock_user = "test_user"
        >>> tool_id = "tool-to-edit"

        >>> # Happy path: Edit tool successfully
        >>> form_data_success = FormData([
        ...     ("name", "Updated_Tool"),
        ...     ("customName", "ValidToolName"),
        ...     ("url", "http://updated.com"),
        ...     ("requestType", "GET"),
        ...     ("integrationType", "REST"),
        ...     ("headers", '{"X-Api-Key": "abc"}'),
        ...     ("input_schema", '{}'),  # ✅ Required field
        ...     ("description", "Sample tool")
        ... ])
        >>> mock_request_success = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_success.form = AsyncMock(return_value=form_data_success)
        >>> original_update_tool = tool_service.update_tool
        >>> tool_service.update_tool = AsyncMock()

        >>> async def test_admin_edit_tool_success():
        ...     response = await admin_edit_tool(tool_id, mock_request_success, mock_db, mock_user)
        ...     return isinstance(response, JSONResponse) and response.status_code == 200 and json.loads(response.body.decode())["success"] is True

        >>> asyncio.run(test_admin_edit_tool_success())
        True

        >>> # Edge case: Edit tool with inactive checkbox checked
        >>> form_data_inactive = FormData([
        ...     ("name", "Inactive_Edit"),
        ...     ("customName", "ValidToolName"),
        ...     ("url", "http://inactive.com"),
        ...     ("is_inactive_checked", "true"),
        ...     ("requestType", "GET"),
        ...     ("integrationType", "REST")
        ... ])
        >>> mock_request_inactive = MagicMock(spec=Request, scope={"root_path": "/api"})
        >>> mock_request_inactive.form = AsyncMock(return_value=form_data_inactive)

        >>> async def test_admin_edit_tool_inactive_checked():
        ...     response = await admin_edit_tool(tool_id, mock_request_inactive, mock_db, mock_user)
        ...     return isinstance(response, JSONResponse) and response.status_code == 200 and json.loads(response.body.decode())["success"] is True

        >>> asyncio.run(test_admin_edit_tool_inactive_checked())
        True

        >>> # Error path: Tool name conflict (simulated with IntegrityError)
        >>> form_data_conflict = FormData([
        ...     ("name", "Conflicting_Name"),
        ...     ("customName", "Conflicting_Name"),
        ...     ("url", "http://conflict.com"),
        ...     ("requestType", "GET"),
        ...     ("integrationType", "REST")
        ... ])
        >>> mock_request_conflict = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_conflict.form = AsyncMock(return_value=form_data_conflict)
        >>> tool_service.update_tool = AsyncMock(side_effect=IntegrityError("Conflict", {}, None))

        >>> async def test_admin_edit_tool_integrity_error():
        ...     response = await admin_edit_tool(tool_id, mock_request_conflict, mock_db, mock_user)
        ...     return isinstance(response, JSONResponse) and response.status_code == 409 and json.loads(response.body.decode())["success"] is False

        >>> asyncio.run(test_admin_edit_tool_integrity_error())
        True

        >>> # Error path: ToolError raised
        >>> form_data_tool_error = FormData([
        ...     ("name", "Tool_Error"),
        ...     ("customName", "Tool_Error"),
        ...     ("url", "http://toolerror.com"),
        ...     ("requestType", "GET"),
        ...     ("integrationType", "REST")
        ... ])
        >>> mock_request_tool_error = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_tool_error.form = AsyncMock(return_value=form_data_tool_error)
        >>> tool_service.update_tool = AsyncMock(side_effect=ToolError("Tool specific error"))

        >>> async def test_admin_edit_tool_tool_error():
        ...     response = await admin_edit_tool(tool_id, mock_request_tool_error, mock_db, mock_user)
        ...     return isinstance(response, JSONResponse) and response.status_code == 500 and json.loads(response.body.decode())["success"] is False

        >>> asyncio.run(test_admin_edit_tool_tool_error())
        True

        >>> # Error path: Pydantic Validation Error
        >>> form_data_validation_error = FormData([
        ...     ("name", "Bad_URL"),
        ...     ("customName","Bad_Custom_Name"),
        ...     ("url", "not-a-valid-url"),
        ...     ("requestType", "GET"),
        ...     ("integrationType", "REST")
        ... ])
        >>> mock_request_validation_error = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_validation_error.form = AsyncMock(return_value=form_data_validation_error)

        >>> async def test_admin_edit_tool_validation_error():
        ...     response = await admin_edit_tool(tool_id, mock_request_validation_error, mock_db, mock_user)
        ...     return isinstance(response, JSONResponse) and response.status_code == 422 and json.loads(response.body.decode())["success"] is False

        >>> asyncio.run(test_admin_edit_tool_validation_error())
        True

        >>> # Error path: Unexpected exception
        >>> form_data_unexpected = FormData([
        ...     ("name", "Crash_Tool"),
        ...     ("customName", "Crash_Tool"),
        ...     ("url", "http://crash.com"),
        ...     ("requestType", "GET"),
        ...     ("integrationType", "REST")
        ... ])
        >>> mock_request_unexpected = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_unexpected.form = AsyncMock(return_value=form_data_unexpected)
        >>> tool_service.update_tool = AsyncMock(side_effect=Exception("Unexpected server crash"))

        >>> async def test_admin_edit_tool_unexpected_error():
        ...     response = await admin_edit_tool(tool_id, mock_request_unexpected, mock_db, mock_user)
        ...     return isinstance(response, JSONResponse) and response.status_code == 500 and json.loads(response.body.decode())["success"] is False

        >>> asyncio.run(test_admin_edit_tool_unexpected_error())
        True

        >>> # Restore original method
        >>> tool_service.update_tool = original_update_tool

    """
    LOGGER.debug(f"User {user} is editing tool ID {tool_id}")
    form = await request.form()
    # Parse tags from comma-separated string
    tags_str = str(form.get("tags", ""))
    tags: list[str] = [tag.strip() for tag in tags_str.split(",") if tag.strip()] if tags_str else []

    tool_data: dict[str, Any] = {
        "name": form.get("name"),
        "custom_name": form.get("customName"),
        "url": form.get("url"),
        "description": form.get("description"),
        "headers": json.loads(form.get("headers") or "{}"),
        "input_schema": json.loads(form.get("input_schema") or "{}"),
        "annotations": json.loads(form.get("annotations") or "{}"),
        "jsonpath_filter": form.get("jsonpathFilter", ""),
        "auth_type": form.get("auth_type", ""),
        "auth_username": form.get("auth_username", ""),
        "auth_password": form.get("auth_password", ""),
        "auth_token": form.get("auth_token", ""),
        "auth_header_key": form.get("auth_header_key", ""),
        "auth_header_value": form.get("auth_header_value", ""),
        "tags": tags,
    }
    # Only include integration_type if it's provided (not disabled in form)
    if "integrationType" in form:
        tool_data["integration_type"] = form.get("integrationType")
    # Only include request_type if it's provided (not disabled in form)
    if "requestType" in form:
        tool_data["request_type"] = form.get("requestType")
    LOGGER.debug(f"Tool update data built: {tool_data}")
    try:
        tool = ToolUpdate(**tool_data)  # Pydantic validation happens here

        # Get current tool to extract current version
        current_tool = db.get(DbTool, tool_id)
        current_version = getattr(current_tool, "version", 0) if current_tool else 0

        # Extract modification metadata
        mod_metadata = MetadataCapture.extract_modification_metadata(request, user, current_version)

        await tool_service.update_tool(
            db,
            tool_id,
            tool,
            modified_by=mod_metadata["modified_by"],
            modified_from_ip=mod_metadata["modified_from_ip"],
            modified_via=mod_metadata["modified_via"],
            modified_user_agent=mod_metadata["modified_user_agent"],
        )
        return JSONResponse(content={"message": "Edit tool successfully", "success": True}, status_code=200)
    except IntegrityError as ex:
        error_message = ErrorFormatter.format_database_error(ex)
        LOGGER.error(f"IntegrityError in admin_tool_resource: {error_message}")
        return JSONResponse(status_code=409, content=error_message)
    except ToolError as ex:
        LOGGER.error(f"ToolError in admin_edit_tool: {str(ex)}")
        return JSONResponse(content={"message": str(ex), "success": False}, status_code=500)
    except ValidationError as ex:  # Catch Pydantic validation errors
        LOGGER.error(f"ValidationError in admin_edit_tool: {str(ex)}")
        return JSONResponse(content=ErrorFormatter.format_validation_error(ex), status_code=422)
    except Exception as ex:  # Generic catch-all for unexpected errors
        LOGGER.error(f"Unexpected error in admin_edit_tool: {str(ex)}")
        return JSONResponse(content={"message": str(ex), "success": False}, status_code=500)


@admin_router.post("/tools/{tool_id}/delete")
async def admin_delete_tool(tool_id: str, request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)) -> RedirectResponse:
    """
    Delete a tool via the admin UI.

    This endpoint permanently removes a tool from the database using its ID.
    It is irreversible and should be used with caution. The operation is logged,
    and the user must be authenticated to access this route.

    Args:
        tool_id (str): The ID of the tool to delete.
        request (Request): FastAPI request object (not used directly, but required by route signature).
        db (Session): Database session dependency.
        user (str): Authenticated user dependency.

    Returns:
        RedirectResponse: A redirect response to the tools section of the admin
        dashboard with a status code of 303 (See Other).

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from fastapi import Request
        >>> from fastapi.responses import RedirectResponse
        >>> from starlette.datastructures import FormData
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = "test_user"
        >>> tool_id = "tool-to-delete"
        >>>
        >>> # Happy path: Delete tool
        >>> form_data_delete = FormData([("is_inactive_checked", "false")])
        >>> mock_request_delete = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_delete.form = AsyncMock(return_value=form_data_delete)
        >>> original_delete_tool = tool_service.delete_tool
        >>> tool_service.delete_tool = AsyncMock()
        >>>
        >>> async def test_admin_delete_tool_success():
        ...     result = await admin_delete_tool(tool_id, mock_request_delete, mock_db, mock_user)
        ...     return isinstance(result, RedirectResponse) and result.status_code == 303 and "/admin#tools" in result.headers["location"]
        >>>
        >>> asyncio.run(test_admin_delete_tool_success())
        True
        >>>
        >>> # Edge case: Delete with inactive checkbox checked
        >>> form_data_inactive = FormData([("is_inactive_checked", "true")])
        >>> mock_request_inactive = MagicMock(spec=Request, scope={"root_path": "/api"})
        >>> mock_request_inactive.form = AsyncMock(return_value=form_data_inactive)
        >>>
        >>> async def test_admin_delete_tool_inactive_checked():
        ...     result = await admin_delete_tool(tool_id, mock_request_inactive, mock_db, mock_user)
        ...     return isinstance(result, RedirectResponse) and result.status_code == 303 and "/api/admin/?include_inactive=true#tools" in result.headers["location"]
        >>>
        >>> asyncio.run(test_admin_delete_tool_inactive_checked())
        True
        >>>
        >>> # Error path: Simulate an exception during deletion
        >>> form_data_error = FormData([])
        >>> mock_request_error = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_error.form = AsyncMock(return_value=form_data_error)
        >>> tool_service.delete_tool = AsyncMock(side_effect=Exception("Deletion failed"))
        >>>
        >>> async def test_admin_delete_tool_exception():
        ...     result = await admin_delete_tool(tool_id, mock_request_error, mock_db, mock_user)
        ...     return isinstance(result, RedirectResponse) and result.status_code == 303 and "/admin#tools" in result.headers["location"]
        >>>
        >>> asyncio.run(test_admin_delete_tool_exception())
        True
        >>>
        >>> # Restore original method
        >>> tool_service.delete_tool = original_delete_tool
    """
    LOGGER.debug(f"User {user} is deleting tool ID {tool_id}")
    try:
        await tool_service.delete_tool(db, tool_id)
    except Exception as e:
        LOGGER.error(f"Error deleting tool: {e}")

    form = await request.form()
    is_inactive_checked = str(form.get("is_inactive_checked", "false"))
    root_path = request.scope.get("root_path", "")

    if is_inactive_checked.lower() == "true":
        return RedirectResponse(f"{root_path}/admin/?include_inactive=true#tools", status_code=303)
    return RedirectResponse(f"{root_path}/admin#tools", status_code=303)


@admin_router.post("/tools/{tool_id}/toggle")
async def admin_toggle_tool(
    tool_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> RedirectResponse:
    """
    Toggle a tool's active status via the admin UI.

    This endpoint processes a form request to activate or deactivate a tool.
    It expects a form field 'activate' with value "true" to activate the tool
    or "false" to deactivate it. The endpoint handles exceptions gracefully and
    logs any errors that might occur during the status toggle operation.

    Args:
        tool_id (str): The ID of the tool whose status to toggle.
        request (Request): FastAPI request containing form data with the 'activate' field.
        db (Session): Database session dependency.
        user (str): Authenticated user dependency.

    Returns:
        RedirectResponse: A redirect to the admin dashboard tools section with a
        status code of 303 (See Other).

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from fastapi import Request
        >>> from fastapi.responses import RedirectResponse
        >>> from starlette.datastructures import FormData
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = "test_user"
        >>> tool_id = "tool-to-toggle"
        >>>
        >>> # Happy path: Activate tool
        >>> form_data_activate = FormData([("activate", "true"), ("is_inactive_checked", "false")])
        >>> mock_request_activate = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_activate.form = AsyncMock(return_value=form_data_activate)
        >>> original_toggle_tool_status = tool_service.toggle_tool_status
        >>> tool_service.toggle_tool_status = AsyncMock()
        >>>
        >>> async def test_admin_toggle_tool_activate():
        ...     result = await admin_toggle_tool(tool_id, mock_request_activate, mock_db, mock_user)
        ...     return isinstance(result, RedirectResponse) and result.status_code == 303 and "/admin#tools" in result.headers["location"]
        >>>
        >>> asyncio.run(test_admin_toggle_tool_activate())
        True
        >>>
        >>> # Happy path: Deactivate tool
        >>> form_data_deactivate = FormData([("activate", "false"), ("is_inactive_checked", "false")])
        >>> mock_request_deactivate = MagicMock(spec=Request, scope={"root_path": "/api"})
        >>> mock_request_deactivate.form = AsyncMock(return_value=form_data_deactivate)
        >>>
        >>> async def test_admin_toggle_tool_deactivate():
        ...     result = await admin_toggle_tool(tool_id, mock_request_deactivate, mock_db, mock_user)
        ...     return isinstance(result, RedirectResponse) and result.status_code == 303 and "/api/admin#tools" in result.headers["location"]
        >>>
        >>> asyncio.run(test_admin_toggle_tool_deactivate())
        True
        >>>
        >>> # Edge case: Toggle with inactive checkbox checked
        >>> form_data_inactive = FormData([("activate", "true"), ("is_inactive_checked", "true")])
        >>> mock_request_inactive = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_inactive.form = AsyncMock(return_value=form_data_inactive)
        >>>
        >>> async def test_admin_toggle_tool_inactive_checked():
        ...     result = await admin_toggle_tool(tool_id, mock_request_inactive, mock_db, mock_user)
        ...     return isinstance(result, RedirectResponse) and result.status_code == 303 and "/admin/?include_inactive=true#tools" in result.headers["location"]
        >>>
        >>> asyncio.run(test_admin_toggle_tool_inactive_checked())
        True
        >>>
        >>> # Error path: Simulate an exception during toggle
        >>> form_data_error = FormData([("activate", "true")])
        >>> mock_request_error = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_error.form = AsyncMock(return_value=form_data_error)
        >>> tool_service.toggle_tool_status = AsyncMock(side_effect=Exception("Toggle failed"))
        >>>
        >>> async def test_admin_toggle_tool_exception():
        ...     result = await admin_toggle_tool(tool_id, mock_request_error, mock_db, mock_user)
        ...     return isinstance(result, RedirectResponse) and result.status_code == 303 and "/admin#tools" in result.headers["location"]
        >>>
        >>> asyncio.run(test_admin_toggle_tool_exception())
        True
        >>>
        >>> # Restore original method
        >>> tool_service.toggle_tool_status = original_toggle_tool_status
    """
    LOGGER.debug(f"User {user} is toggling tool ID {tool_id}")
    form = await request.form()
    activate = str(form.get("activate", "true")).lower() == "true"
    is_inactive_checked = str(form.get("is_inactive_checked", "false"))
    try:
        await tool_service.toggle_tool_status(db, tool_id, activate, reachable=activate)
    except Exception as e:
        LOGGER.error(f"Error toggling tool status: {e}")

    root_path = request.scope.get("root_path", "")
    if is_inactive_checked.lower() == "true":
        return RedirectResponse(f"{root_path}/admin/?include_inactive=true#tools", status_code=303)
    return RedirectResponse(f"{root_path}/admin#tools", status_code=303)


@admin_router.get("/gateways/{gateway_id}", response_model=GatewayRead)
async def admin_get_gateway(gateway_id: str, db: Session = Depends(get_db), user: str = Depends(require_auth)) -> Dict[str, Any]:
    """Get gateway details for the admin UI.

    Args:
        gateway_id: Gateway ID.
        db: Database session.
        user: Authenticated user.

    Returns:
        Gateway details.

    Raises:
        HTTPException: If the gateway is not found.
        Exception: For any other unexpected errors.

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from mcpgateway.schemas import GatewayRead
        >>> from datetime import datetime, timezone
        >>> from mcpgateway.services.gateway_service import GatewayNotFoundError # Added import
        >>> from fastapi import HTTPException
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = "test_user"
        >>> gateway_id = "test-gateway-id"
        >>>
        >>> # Mock gateway data
        >>> mock_gateway = GatewayRead(
        ...     id=gateway_id, name="Get Gateway", url="http://get.com",
        ...     description="Gateway for getting", transport="HTTP",
        ...     created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        ...     enabled=True, auth_type=None, auth_username=None, auth_password=None,
        ...     auth_token=None, auth_header_key=None, auth_header_value=None,
        ...     slug="test-gateway"
        ... )
        >>>
        >>> # Mock the gateway_service.get_gateway method
        >>> original_get_gateway = gateway_service.get_gateway
        >>> gateway_service.get_gateway = AsyncMock(return_value=mock_gateway)
        >>>
        >>> # Test successful retrieval
        >>> async def test_admin_get_gateway_success():
        ...     result = await admin_get_gateway(gateway_id, mock_db, mock_user)
        ...     return isinstance(result, dict) and result['id'] == gateway_id
        >>>
        >>> asyncio.run(test_admin_get_gateway_success())
        True
        >>>
        >>> # Test gateway not found
        >>> gateway_service.get_gateway = AsyncMock(side_effect=GatewayNotFoundError("Gateway not found"))
        >>> async def test_admin_get_gateway_not_found():
        ...     try:
        ...         await admin_get_gateway("nonexistent", mock_db, mock_user)
        ...         return False
        ...     except HTTPException as e:
        ...         return e.status_code == 404 and "Gateway not found" in e.detail
        >>>
        >>> asyncio.run(test_admin_get_gateway_not_found())
        True
        >>>
        >>> # Test generic exception
        >>> gateway_service.get_gateway = AsyncMock(side_effect=Exception("Generic error"))
        >>> async def test_admin_get_gateway_exception():
        ...     try:
        ...         await admin_get_gateway(gateway_id, mock_db, mock_user)
        ...         return False
        ...     except Exception as e:
        ...         return str(e) == "Generic error"
        >>>
        >>> asyncio.run(test_admin_get_gateway_exception())
        True
        >>>
        >>> # Restore original method
        >>> gateway_service.get_gateway = original_get_gateway
    """
    LOGGER.debug(f"User {user} requested details for gateway ID {gateway_id}")
    try:
        gateway = await gateway_service.get_gateway(db, gateway_id)
        return gateway.model_dump(by_alias=True)
    except GatewayNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        LOGGER.error(f"Error getting gateway {gateway_id}: {e}")
        raise e


@admin_router.post("/gateways")
async def admin_add_gateway(request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)) -> JSONResponse:
    """Add a gateway via the admin UI.

    Expects form fields:
      - name
      - url
      - description (optional)
      - tags (optional, comma-separated)

    Args:
        request: FastAPI request containing form data.
        db: Database session.
        user: Authenticated user.

    Returns:
        A redirect response to the admin dashboard.

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from fastapi import Request
        >>> from fastapi.responses import JSONResponse
        >>> from starlette.datastructures import FormData
        >>> from mcpgateway.services.gateway_service import GatewayConnectionError
        >>> from pydantic import ValidationError
        >>> from sqlalchemy.exc import IntegrityError
        >>> from mcpgateway.utils.error_formatter import ErrorFormatter
        >>> import json # Added import for json.loads
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = "test_user"
        >>>
        >>> # Happy path: Add a new gateway successfully with basic auth details
        >>> form_data_success = FormData([
        ...     ("name", "New Gateway"),
        ...     ("url", "http://new.gateway.com"),
        ...     ("transport", "HTTP"),
        ...     ("auth_type", "basic"), # Valid auth_type
        ...     ("auth_username", "user"), # Required for basic auth
        ...     ("auth_password", "pass")  # Required for basic auth
        ... ])
        >>> mock_request_success = MagicMock(spec=Request)
        >>> mock_request_success.form = AsyncMock(return_value=form_data_success)
        >>> original_register_gateway = gateway_service.register_gateway
        >>> gateway_service.register_gateway = AsyncMock()
        >>>
        >>> async def test_admin_add_gateway_success():
        ...     response = await admin_add_gateway(mock_request_success, mock_db, mock_user)
        ...     # Corrected: Access body and then parse JSON
        ...     return isinstance(response, JSONResponse) and response.status_code == 200 and json.loads(response.body)["success"] is True
        >>>
        >>> asyncio.run(test_admin_add_gateway_success())
        True
        >>>
        >>> # Error path: Gateway connection error
        >>> form_data_conn_error = FormData([("name", "Bad Gateway"), ("url", "http://bad.com"), ("auth_type", "bearer"), ("auth_token", "abc")]) # Added auth_type and token
        >>> mock_request_conn_error = MagicMock(spec=Request)
        >>> mock_request_conn_error.form = AsyncMock(return_value=form_data_conn_error)
        >>> gateway_service.register_gateway = AsyncMock(side_effect=GatewayConnectionError("Connection failed"))
        >>>
        >>> async def test_admin_add_gateway_connection_error():
        ...     response = await admin_add_gateway(mock_request_conn_error, mock_db, mock_user)
        ...     return isinstance(response, JSONResponse) and response.status_code == 502 and json.loads(response.body)["success"] is False
        >>>
        >>> asyncio.run(test_admin_add_gateway_connection_error())
        True
        >>>
        >>> # Error path: Validation error (e.g., missing name)
        >>> form_data_validation_error = FormData([("url", "http://no-name.com"), ("auth_type", "headers"), ("auth_header_key", "X-Key"), ("auth_header_value", "val")]) # 'name' is missing, added auth_type
        >>> mock_request_validation_error = MagicMock(spec=Request)
        >>> mock_request_validation_error.form = AsyncMock(return_value=form_data_validation_error)
        >>> # No need to mock register_gateway, ValidationError happens during GatewayCreate()
        >>>
        >>> async def test_admin_add_gateway_validation_error():
        ...     response = await admin_add_gateway(mock_request_validation_error, mock_db, mock_user)
        ...     return isinstance(response, JSONResponse) and response.status_code == 422 and json.loads(response.body.decode())["success"] is False
        >>>
        >>> asyncio.run(test_admin_add_gateway_validation_error())
        True
        >>>
        >>> # Error path: Integrity error (e.g., duplicate name)
        >>> from sqlalchemy.exc import IntegrityError
        >>> form_data_integrity_error = FormData([("name", "Duplicate Gateway"), ("url", "http://duplicate.com"), ("auth_type", "basic"), ("auth_username", "u"), ("auth_password", "p")]) # Added auth_type and creds
        >>> mock_request_integrity_error = MagicMock(spec=Request)
        >>> mock_request_integrity_error.form = AsyncMock(return_value=form_data_integrity_error)
        >>> gateway_service.register_gateway = AsyncMock(side_effect=IntegrityError("Duplicate entry", {}, {}))
        >>>
        >>> async def test_admin_add_gateway_integrity_error():
        ...     response = await admin_add_gateway(mock_request_integrity_error, mock_db, mock_user)
        ...     return isinstance(response, JSONResponse) and response.status_code == 409 and json.loads(response.body.decode())["success"] is False
        >>>
        >>> asyncio.run(test_admin_add_gateway_integrity_error())
        True
        >>>
        >>> # Error path: Generic RuntimeError
        >>> form_data_runtime_error = FormData([("name", "Runtime Error Gateway"), ("url", "http://runtime.com"), ("auth_type", "basic"), ("auth_username", "u"), ("auth_password", "p")]) # Added auth_type and creds
        >>> mock_request_runtime_error = MagicMock(spec=Request)
        >>> mock_request_runtime_error.form = AsyncMock(return_value=form_data_runtime_error)
        >>> gateway_service.register_gateway = AsyncMock(side_effect=RuntimeError("Unexpected runtime issue"))
        >>>
        >>> async def test_admin_add_gateway_runtime_error():
        ...     response = await admin_add_gateway(mock_request_runtime_error, mock_db, mock_user)
        ...     return isinstance(response, JSONResponse) and response.status_code == 500 and json.loads(response.body.decode())["success"] is False
        >>>
        >>> asyncio.run(test_admin_add_gateway_runtime_error())
        True
        >>>
        >>> # Restore original method
        >>> gateway_service.register_gateway = original_register_gateway
    """
    LOGGER.debug(f"User {user} is adding a new gateway")
    form = await request.form()
    try:
        # Parse tags from comma-separated string
        tags_str = str(form.get("tags", ""))
        tags: list[str] = [tag.strip() for tag in tags_str.split(",") if tag.strip()] if tags_str else []

        # Parse auth_headers JSON if present
        auth_headers_json = str(form.get("auth_headers"))
        auth_headers: list[dict[str, Any]] = []
        if auth_headers_json:
            try:
                auth_headers = json.loads(auth_headers_json)
            except (json.JSONDecodeError, ValueError):
                auth_headers = []

        # Parse OAuth configuration if present
        oauth_config_json = str(form.get("oauth_config"))
        oauth_config: Optional[dict[str, Any]] = None
        if oauth_config_json and oauth_config_json != "None":
            try:
                oauth_config = json.loads(oauth_config_json)
                # Encrypt the client secret if present
                if oauth_config and "client_secret" in oauth_config:
                    encryption = get_oauth_encryption(settings.auth_encryption_secret)
                    oauth_config["client_secret"] = encryption.encrypt_secret(oauth_config["client_secret"])
            except (json.JSONDecodeError, ValueError) as e:
                LOGGER.error(f"Failed to parse OAuth config: {e}")
                oauth_config = None

        # Handle passthrough_headers
        passthrough_headers = str(form.get("passthrough_headers"))
        if passthrough_headers and passthrough_headers.strip():
            try:
                passthrough_headers = json.loads(passthrough_headers)
            except (json.JSONDecodeError, ValueError):
                # Fallback to comma-separated parsing
                passthrough_headers = [h.strip() for h in passthrough_headers.split(",") if h.strip()]
        else:
            passthrough_headers = None

        gateway = GatewayCreate(
            name=str(form["name"]),
            url=str(form["url"]),
            description=str(form.get("description")),
            tags=tags,
            transport=str(form.get("transport", "SSE")),
            auth_type=str(form.get("auth_type", "")),
            auth_username=str(form.get("auth_username", "")),
            auth_password=str(form.get("auth_password", "")),
            auth_token=str(form.get("auth_token", "")),
            auth_header_key=str(form.get("auth_header_key", "")),
            auth_header_value=str(form.get("auth_header_value", "")),
            auth_headers=auth_headers if auth_headers else None,
            oauth_config=oauth_config,
            passthrough_headers=passthrough_headers,
        )
    except KeyError as e:
        # Convert KeyError to ValidationError-like response
        return JSONResponse(content={"message": f"Missing required field: {e}", "success": False}, status_code=422)

    except ValidationError as ex:
        # --- Getting only the custom message from the ValueError ---
        error_ctx = [str(err["ctx"]["error"]) for err in ex.errors()]
        return JSONResponse(content={"success": False, "message": "; ".join(error_ctx)}, status_code=422)

    try:
        # Extract creation metadata
        metadata = MetadataCapture.extract_creation_metadata(request, user)

        await gateway_service.register_gateway(
            db,
            gateway,
            created_by=metadata["created_by"],
            created_from_ip=metadata["created_from_ip"],
            created_via=metadata["created_via"],
            created_user_agent=metadata["created_user_agent"],
        )

        # Provide specific guidance for OAuth Authorization Code flow
        message = "Gateway registered successfully!"
        if oauth_config and oauth_config.get("grant_type") == "authorization_code":
            message = (
                "Gateway registered successfully! 🎉\n\n"
                "⚠️  IMPORTANT: This gateway uses OAuth Authorization Code flow.\n"
                "You must complete the OAuth authorization before tools will work:\n\n"
                "1. Go to the Gateways list\n"
                "2. Click the '🔐 Authorize' button for this gateway\n"
                "3. Complete the OAuth consent flow\n"
                "4. Return to the admin panel\n\n"
                "Tools will not work until OAuth authorization is completed."
            )
        return JSONResponse(
            content={"message": message, "success": True},
            status_code=200,
        )

    except GatewayConnectionError as ex:
        return JSONResponse(content={"message": str(ex), "success": False}, status_code=502)
    except ValueError as ex:
        return JSONResponse(content={"message": str(ex), "success": False}, status_code=400)
    except RuntimeError as ex:
        return JSONResponse(content={"message": str(ex), "success": False}, status_code=500)
    except ValidationError as ex:
        return JSONResponse(content=ErrorFormatter.format_validation_error(ex), status_code=422)
    except IntegrityError as ex:
        return JSONResponse(content=ErrorFormatter.format_database_error(ex), status_code=409)
    except Exception as ex:
        return JSONResponse(content={"message": str(ex), "success": False}, status_code=500)


# OAuth callback is now handled by the dedicated OAuth router at /oauth/callback
# This route has been removed to avoid conflicts with the complete implementation


@admin_router.post("/gateways/{gateway_id}/edit")
async def admin_edit_gateway(
    gateway_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> JSONResponse:
    """Edit a gateway via the admin UI.

    Expects form fields:
      - name
      - url
      - description (optional)
      - tags (optional, comma-separated)

    Args:
        gateway_id: Gateway ID.
        request: FastAPI request containing form data.
        db: Database session.
        user: Authenticated user.

    Returns:
        A redirect response to the admin dashboard.

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from fastapi import Request
        >>> from fastapi.responses import RedirectResponse
        >>> from starlette.datastructures import FormData
        >>> from pydantic import ValidationError
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = "test_user"
        >>> gateway_id = "gateway-to-edit"
        >>>
        >>> # Happy path: Edit gateway successfully
        >>> form_data_success = FormData([
        ...  ("name", "Updated Gateway"),
        ...  ("url", "http://updated.com"),
        ...  ("is_inactive_checked", "false"),
        ...  ("auth_type", "basic"),
        ...  ("auth_username", "user"),
        ...  ("auth_password", "pass")
        ... ])
        >>> mock_request_success = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_success.form = AsyncMock(return_value=form_data_success)
        >>> original_update_gateway = gateway_service.update_gateway
        >>> gateway_service.update_gateway = AsyncMock()
        >>>
        >>> async def test_admin_edit_gateway_success():
        ...     response = await admin_edit_gateway(gateway_id, mock_request_success, mock_db, mock_user)
        ...     return isinstance(response, JSONResponse) and response.status_code == 200 and json.loads(response.body)["success"] is True
        >>>
        >>> asyncio.run(test_admin_edit_gateway_success())
        True
        >>>
        # >>> # Edge case: Edit gateway with inactive checkbox checked
        # >>> form_data_inactive = FormData([("name", "Inactive Edit"), ("url", "http://inactive.com"), ("is_inactive_checked", "true"), ("auth_type", "basic"), ("auth_username", "user"),
        # ...     ("auth_password", "pass")]) # Added auth_type
        # >>> mock_request_inactive = MagicMock(spec=Request, scope={"root_path": "/api"})
        # >>> mock_request_inactive.form = AsyncMock(return_value=form_data_inactive)
        # >>>
        # >>> async def test_admin_edit_gateway_inactive_checked():
        # ...     response = await admin_edit_gateway(gateway_id, mock_request_inactive, mock_db, mock_user)
        # ...     return isinstance(response, RedirectResponse) and response.status_code == 303 and "/api/admin/?include_inactive=true#gateways" in response.headers["location"]
        # >>>
        # >>> asyncio.run(test_admin_edit_gateway_inactive_checked())
        # True
        # >>>
        >>> # Error path: Simulate an exception during update
        >>> form_data_error = FormData([("name", "Error Gateway"), ("url", "http://error.com"), ("auth_type", "basic"),("auth_username", "user"),
        ...     ("auth_password", "pass")]) # Added auth_type
        >>> mock_request_error = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_error.form = AsyncMock(return_value=form_data_error)
        >>> gateway_service.update_gateway = AsyncMock(side_effect=Exception("Update failed"))
        >>>
        >>> async def test_admin_edit_gateway_exception():
        ...     response = await admin_edit_gateway(gateway_id, mock_request_error, mock_db, mock_user)
        ...     return (
        ...         isinstance(response, JSONResponse)
        ...         and response.status_code == 500
        ...         and json.loads(response.body)["success"] is False
        ...         and "Update failed" in json.loads(response.body)["message"]
        ...     )
        >>>
        >>> asyncio.run(test_admin_edit_gateway_exception())
        True
        >>>
        >>> # Error path: Pydantic Validation Error (e.g., invalid URL format)
        >>> form_data_validation_error = FormData([("name", "Bad URL Gateway"), ("url", "invalid-url"), ("auth_type", "basic"),("auth_username", "user"),
        ...     ("auth_password", "pass")]) # Added auth_type
        >>> mock_request_validation_error = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_validation_error.form = AsyncMock(return_value=form_data_validation_error)
        >>>
        >>> async def test_admin_edit_gateway_validation_error():
        ...     response = await admin_edit_gateway(gateway_id, mock_request_validation_error, mock_db, mock_user)
        ...     body = json.loads(response.body.decode())
        ...     return isinstance(response, JSONResponse) and response.status_code in (422,400) and body["success"] is False
        >>>
        >>> asyncio.run(test_admin_edit_gateway_validation_error())
        True
        >>>
        >>> # Restore original method
        >>> gateway_service.update_gateway = original_update_gateway
    """
    LOGGER.debug(f"User {user} is editing gateway ID {gateway_id}")
    form = await request.form()
    try:
        # Parse tags from comma-separated string
        tags_str = str(form.get("tags", ""))
        tags: List[str] = [tag.strip() for tag in tags_str.split(",") if tag.strip()] if tags_str else []

        # Parse auth_headers JSON if present
        auth_headers_json = str(form.get("auth_headers"))
        auth_headers = []
        if auth_headers_json:
            try:
                auth_headers = json.loads(auth_headers_json)
            except (json.JSONDecodeError, ValueError):
                auth_headers = []

        # Handle passthrough_headers
        passthrough_headers = str(form.get("passthrough_headers"))
        if passthrough_headers and passthrough_headers.strip():
            try:
                passthrough_headers = json.loads(passthrough_headers)
            except (json.JSONDecodeError, ValueError):
                # Fallback to comma-separated parsing
                passthrough_headers = [h.strip() for h in passthrough_headers.split(",") if h.strip()]
        else:
            passthrough_headers = None

        gateway = GatewayUpdate(  # Pydantic validation happens here
            name=str(form.get("name")),
            url=str(form["url"]),
            description=str(form.get("description")),
            transport=str(form.get("transport", "SSE")),
            tags=tags,
            auth_type=str(form.get("auth_type", "")),
            auth_username=str(form.get("auth_username", "")),
            auth_password=str(form.get("auth_password", "")),
            auth_token=str(form.get("auth_token", "")),
            auth_header_key=str(form.get("auth_header_key", "")),
            auth_header_value=str(form.get("auth_header_value", "")),
            auth_value=str(form.get("auth_value", "")),
            auth_headers=auth_headers if auth_headers else None,
            passthrough_headers=passthrough_headers,
        )
        await gateway_service.update_gateway(db, gateway_id, gateway)
        return JSONResponse(
            content={"message": "Gateway updated successfully!", "success": True},
            status_code=200,
        )
    except Exception as ex:
        if isinstance(ex, GatewayConnectionError):
            return JSONResponse(content={"message": str(ex), "success": False}, status_code=502)
        if isinstance(ex, ValueError):
            return JSONResponse(content={"message": str(ex), "success": False}, status_code=400)
        if isinstance(ex, RuntimeError):
            return JSONResponse(content={"message": str(ex), "success": False}, status_code=500)
        if isinstance(ex, ValidationError):
            return JSONResponse(content=ErrorFormatter.format_validation_error(ex), status_code=422)
        if isinstance(ex, IntegrityError):
            return JSONResponse(status_code=409, content=ErrorFormatter.format_database_error(ex))
        return JSONResponse(content={"message": str(ex), "success": False}, status_code=500)


@admin_router.post("/gateways/{gateway_id}/delete")
async def admin_delete_gateway(gateway_id: str, request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)) -> RedirectResponse:
    """
    Delete a gateway via the admin UI.

    This endpoint removes a gateway from the database by its ID. The deletion is
    permanent and cannot be undone. It requires authentication and logs the
    operation for auditing purposes.

    Args:
        gateway_id (str): The ID of the gateway to delete.
        request (Request): FastAPI request object (not used directly but required by the route signature).
        db (Session): Database session dependency.
        user (str): Authenticated user dependency.

    Returns:
        RedirectResponse: A redirect response to the gateways section of the admin
        dashboard with a status code of 303 (See Other).

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from fastapi import Request
        >>> from fastapi.responses import RedirectResponse
        >>> from starlette.datastructures import FormData
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = "test_user"
        >>> gateway_id = "gateway-to-delete"
        >>>
        >>> # Happy path: Delete gateway
        >>> form_data_delete = FormData([("is_inactive_checked", "false")])
        >>> mock_request_delete = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_delete.form = AsyncMock(return_value=form_data_delete)
        >>> original_delete_gateway = gateway_service.delete_gateway
        >>> gateway_service.delete_gateway = AsyncMock()
        >>>
        >>> async def test_admin_delete_gateway_success():
        ...     result = await admin_delete_gateway(gateway_id, mock_request_delete, mock_db, mock_user)
        ...     return isinstance(result, RedirectResponse) and result.status_code == 303 and "/admin#gateways" in result.headers["location"]
        >>>
        >>> asyncio.run(test_admin_delete_gateway_success())
        True
        >>>
        >>> # Edge case: Delete with inactive checkbox checked
        >>> form_data_inactive = FormData([("is_inactive_checked", "true")])
        >>> mock_request_inactive = MagicMock(spec=Request, scope={"root_path": "/api"})
        >>> mock_request_inactive.form = AsyncMock(return_value=form_data_inactive)
        >>>
        >>> async def test_admin_delete_gateway_inactive_checked():
        ...     result = await admin_delete_gateway(gateway_id, mock_request_inactive, mock_db, mock_user)
        ...     return isinstance(result, RedirectResponse) and result.status_code == 303 and "/api/admin/?include_inactive=true#gateways" in result.headers["location"]
        >>>
        >>> asyncio.run(test_admin_delete_gateway_inactive_checked())
        True
        >>>
        >>> # Error path: Simulate an exception during deletion
        >>> form_data_error = FormData([])
        >>> mock_request_error = MagicMock(spec=Request, scope={"root_path": ""})
        >>> mock_request_error.form = AsyncMock(return_value=form_data_error)
        >>> gateway_service.delete_gateway = AsyncMock(side_effect=Exception("Deletion failed"))
        >>>
        >>> async def test_admin_delete_gateway_exception():
        ...     result = await admin_delete_gateway(gateway_id, mock_request_error, mock_db, mock_user)
        ...     return isinstance(result, RedirectResponse) and result.status_code == 303 and "/admin#gateways" in result.headers["location"]
        >>>
        >>> asyncio.run(test_admin_delete_gateway_exception())
        True
        >>>
        >>> # Restore original method
        >>> gateway_service.delete_gateway = original_delete_gateway
    """
    LOGGER.debug(f"User {user} is deleting gateway ID {gateway_id}")
    try:
        await gateway_service.delete_gateway(db, gateway_id)
    except Exception as e:
        LOGGER.error(f"Error deleting gateway: {e}")

    form = await request.form()
    is_inactive_checked = str(form.get("is_inactive_checked", "false"))
    root_path = request.scope.get("root_path", "")

    if is_inactive_checked.lower() == "true":
        return RedirectResponse(f"{root_path}/admin/?include_inactive=true#gateways", status_code=303)
    return RedirectResponse(f"{root_path}/admin#gateways", status_code=303)


@admin_router.get("/resources/{uri:path}")
async def admin_get_resource(uri: str, db: Session = Depends(get_db), user: str = Depends(require_auth)) -> Dict[str, Any]:
    """Get resource details for the admin UI.

    Args:
        uri: Resource URI.
        db: Database session.
        user: Authenticated user.

    Returns:
        A dictionary containing resource details and its content.

    Raises:
        HTTPException: If the resource is not found.
        Exception: For any other unexpected errors.

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from mcpgateway.schemas import ResourceRead, ResourceMetrics, ResourceContent
        >>> from datetime import datetime, timezone
        >>> from mcpgateway.services.resource_service import ResourceNotFoundError # Added import
        >>> from fastapi import HTTPException
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = "test_user"
        >>> resource_uri = "test://resource/get"
        >>>
        >>> # Mock resource data
        >>> mock_resource = ResourceRead(
        ...     id=1, uri=resource_uri, name="Get Resource", description="Test",
        ...     mime_type="text/plain", size=10, created_at=datetime.now(timezone.utc),
        ...     updated_at=datetime.now(timezone.utc), is_active=True, metrics=ResourceMetrics(
        ...         total_executions=0, successful_executions=0, failed_executions=0,
        ...         failure_rate=0.0, min_response_time=0.0, max_response_time=0.0, avg_response_time=0.0,
        ...         last_execution_time=None
        ...     ),
        ...     tags=[]
        ... )
        >>> mock_content = ResourceContent(type="resource", uri=resource_uri, mime_type="text/plain", text="Hello content")
        >>>
        >>> # Mock service methods
        >>> original_get_resource_by_uri = resource_service.get_resource_by_uri
        >>> original_read_resource = resource_service.read_resource
        >>> resource_service.get_resource_by_uri = AsyncMock(return_value=mock_resource)
        >>> resource_service.read_resource = AsyncMock(return_value=mock_content)
        >>>
        >>> # Test successful retrieval
        >>> async def test_admin_get_resource_success():
        ...     result = await admin_get_resource(resource_uri, mock_db, mock_user)
        ...     return isinstance(result, dict) and result['resource']['uri'] == resource_uri and result['content'].text == "Hello content" # Corrected to .text
        >>>
        >>> asyncio.run(test_admin_get_resource_success())
        True
        >>>
        >>> # Test resource not found
        >>> resource_service.get_resource_by_uri = AsyncMock(side_effect=ResourceNotFoundError("Resource not found"))
        >>> async def test_admin_get_resource_not_found():
        ...     try:
        ...         await admin_get_resource("nonexistent://uri", mock_db, mock_user)
        ...         return False
        ...     except HTTPException as e:
        ...         return e.status_code == 404 and "Resource not found" in e.detail
        >>>
        >>> asyncio.run(test_admin_get_resource_not_found())
        True
        >>>
        >>> # Test exception during content read (resource found but content fails)
        >>> resource_service.get_resource_by_uri = AsyncMock(return_value=mock_resource) # Resource found
        >>> resource_service.read_resource = AsyncMock(side_effect=Exception("Content read error"))
        >>> async def test_admin_get_resource_content_error():
        ...     try:
        ...         await admin_get_resource(resource_uri, mock_db, mock_user)
        ...         return False
        ...     except Exception as e:
        ...         return str(e) == "Content read error"
        >>>
        >>> asyncio.run(test_admin_get_resource_content_error())
        True
        >>>
        >>> # Restore original methods
        >>> resource_service.get_resource_by_uri = original_get_resource_by_uri
        >>> resource_service.read_resource = original_read_resource
    """
    LOGGER.debug(f"User {user} requested details for resource URI {uri}")
    try:
        resource = await resource_service.get_resource_by_uri(db, uri)
        content = await resource_service.read_resource(db, uri)
        return {"resource": resource.model_dump(by_alias=True), "content": content}
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        LOGGER.error(f"Error getting resource {uri}: {e}")
        raise e


@admin_router.post("/resources")
async def admin_add_resource(request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)) -> Response:
    """
    Add a resource via the admin UI.

    Expects form fields:
      - uri
      - name
      - description (optional)
      - mime_type (optional)
      - content

    Args:
        request: FastAPI request containing form data.
        db: Database session.
        user: Authenticated user.

    Returns:
        A redirect response to the admin dashboard.

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from fastapi import Request
        >>> from fastapi.responses import RedirectResponse
        >>> from starlette.datastructures import FormData
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = "test_user"
        >>> form_data = FormData([
        ...     ("uri", "test://resource1"),
        ...     ("name", "Test Resource"),
        ...     ("description", "A test resource"),
        ...     ("mimeType", "text/plain"),
        ...     ("content", "Sample content"),
        ... ])
        >>> mock_request = MagicMock(spec=Request)
        >>> mock_request.form = AsyncMock(return_value=form_data)
        >>> mock_request.scope = {"root_path": ""}
        >>>
        >>> original_register_resource = resource_service.register_resource
        >>> resource_service.register_resource = AsyncMock()
        >>>
        >>> async def test_admin_add_resource():
        ...     response = await admin_add_resource(mock_request, mock_db, mock_user)
        ...     return isinstance(response, JSONResponse) and response.status_code == 200 and response.body.decode() == '{"message":"Add resource registered successfully!","success":true}'
        >>>
        >>> import asyncio; asyncio.run(test_admin_add_resource())
        True
        >>> resource_service.register_resource = original_register_resource
    """
    LOGGER.debug(f"User {user} is adding a new resource")
    form = await request.form()

    # Parse tags from comma-separated string
    tags_str = str(form.get("tags", ""))
    tags: List[str] = [tag.strip() for tag in tags_str.split(",") if tag.strip()] if tags_str else []

    try:
        resource = ResourceCreate(
            uri=str(form["uri"]),
            name=str(form["name"]),
            description=str(form.get("description", "")),
            mime_type=str(form.get("mimeType", "")),
            template=cast(str | None, form.get("template")),
            content=str(form["content"]),
            tags=tags,
        )

        metadata = MetadataCapture.extract_creation_metadata(request, user)

        await resource_service.register_resource(
            db,
            resource,
            created_by=metadata["created_by"],
            created_from_ip=metadata["created_from_ip"],
            created_via=metadata["created_via"],
            created_user_agent=metadata["created_user_agent"],
            import_batch_id=metadata["import_batch_id"],
            federation_source=metadata["federation_source"],
        )
        return JSONResponse(
            content={"message": "Add resource registered successfully!", "success": True},
            status_code=200,
        )
    except Exception as ex:
        if isinstance(ex, ValidationError):
            LOGGER.error(f"ValidationError in admin_add_resource: {ErrorFormatter.format_validation_error(ex)}")
            return JSONResponse(content=ErrorFormatter.format_validation_error(ex), status_code=422)
        if isinstance(ex, IntegrityError):
            error_message = ErrorFormatter.format_database_error(ex)
            LOGGER.error(f"IntegrityError in admin_add_resource: {error_message}")
            return JSONResponse(status_code=409, content=error_message)

        LOGGER.error(f"Error in admin_add_resource: {ex}")
        return JSONResponse(content={"message": str(ex), "success": False}, status_code=500)


@admin_router.post("/resources/{uri:path}/edit")
async def admin_edit_resource(
    uri: str,
    request: Request,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> JSONResponse:
    """
    Edit a resource via the admin UI.

    Expects form fields:
      - name
      - description (optional)
      - mime_type (optional)
      - content

    Args:
        uri: Resource URI.
        request: FastAPI request containing form data.
        db: Database session.
        user: Authenticated user.

    Returns:
        JSONResponse: A JSON response indicating success or failure of the resource update operation.

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from fastapi import Request
        >>> from fastapi.responses import RedirectResponse
        >>> from starlette.datastructures import FormData
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = "test_user"
        >>> form_data = FormData([
        ...     ("name", "Updated Resource"),
        ...     ("description", "Updated description"),
        ...     ("mimeType", "text/plain"),
        ...     ("content", "Updated content"),
        ... ])
        >>> mock_request = MagicMock(spec=Request)
        >>> mock_request.form = AsyncMock(return_value=form_data)
        >>> mock_request.scope = {"root_path": ""}
        >>>
        >>> original_update_resource = resource_service.update_resource
        >>> resource_service.update_resource = AsyncMock()
        >>>
        >>> # Test successful update
        >>> async def test_admin_edit_resource():
        ...     response = await admin_edit_resource("test://resource1", mock_request, mock_db, mock_user)
        ...     return isinstance(response, JSONResponse) and response.status_code == 200 and response.body == b'{"message":"Resource updated successfully!","success":true}'
        >>>
        >>> asyncio.run(test_admin_edit_resource())
        True
        >>>
        >>> # Test validation error
        >>> from pydantic import ValidationError
        >>> validation_error = ValidationError.from_exception_data("Resource validation error", [
        ...     {"loc": ("name",), "msg": "Field required", "type": "missing"}
        ... ])
        >>> resource_service.update_resource = AsyncMock(side_effect=validation_error)
        >>> async def test_admin_edit_resource_validation():
        ...     response = await admin_edit_resource("test://resource1", mock_request, mock_db, mock_user)
        ...     return isinstance(response, JSONResponse) and response.status_code == 422
        >>>
        >>> asyncio.run(test_admin_edit_resource_validation())
        True
        >>>
        >>> # Test integrity error (e.g., duplicate resource)
        >>> from sqlalchemy.exc import IntegrityError
        >>> integrity_error = IntegrityError("Duplicate entry", None, None)
        >>> resource_service.update_resource = AsyncMock(side_effect=integrity_error)
        >>> async def test_admin_edit_resource_integrity():
        ...     response = await admin_edit_resource("test://resource1", mock_request, mock_db, mock_user)
        ...     return isinstance(response, JSONResponse) and response.status_code == 409
        >>>
        >>> asyncio.run(test_admin_edit_resource_integrity())
        True
        >>>
        >>> # Test unknown error
        >>> resource_service.update_resource = AsyncMock(side_effect=Exception("Unknown error"))
        >>> async def test_admin_edit_resource_unknown():
        ...     response = await admin_edit_resource("test://resource1", mock_request, mock_db, mock_user)
        ...     return isinstance(response, JSONResponse) and response.status_code == 500 and b'Unknown error' in response.body
        >>>
        >>> asyncio.run(test_admin_edit_resource_unknown())
        True
        >>>
        >>> # Reset mock
        >>> resource_service.update_resource = original_update_resource
    """
    LOGGER.debug(f"User {user} is editing resource URI {uri}")
    form = await request.form()

    # Parse tags from comma-separated string
    tags_str = str(form.get("tags", ""))
    tags: List[str] = [tag.strip() for tag in tags_str.split(",") if tag.strip()] if tags_str else []

    try:
        resource = ResourceUpdate(
            name=str(form["name"]),
            description=str(form.get("description")),
            mime_type=str(form.get("mimeType")),
            content=str(form["content"]),
            template=str(form.get("template")),
            tags=tags,
        )
        await resource_service.update_resource(db, uri, resource)
        return JSONResponse(
            content={"message": "Resource updated successfully!", "success": True},
            status_code=200,
        )
    except Exception as ex:
        if isinstance(ex, ValidationError):
            LOGGER.error(f"ValidationError in admin_edit_resource: {ErrorFormatter.format_validation_error(ex)}")
            return JSONResponse(content=ErrorFormatter.format_validation_error(ex), status_code=422)
        if isinstance(ex, IntegrityError):
            error_message = ErrorFormatter.format_database_error(ex)
            LOGGER.error(f"IntegrityError in admin_edit_resource: {error_message}")
            return JSONResponse(status_code=409, content=error_message)
        LOGGER.error(f"Error in admin_edit_resource: {ex}")
        return JSONResponse(content={"message": str(ex), "success": False}, status_code=500)


@admin_router.post("/resources/{uri:path}/delete")
async def admin_delete_resource(uri: str, request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)) -> RedirectResponse:
    """
    Delete a resource via the admin UI.

    This endpoint permanently removes a resource from the database using its URI.
    The operation is irreversible and should be used with caution. It requires
    user authentication and logs the deletion attempt.

    Args:
        uri (str): The URI of the resource to delete.
        request (Request): FastAPI request object (not used directly but required by the route signature).
        db (Session): Database session dependency.
        user (str): Authenticated user dependency.

    Returns:
        RedirectResponse: A redirect response to the resources section of the admin
        dashboard with a status code of 303 (See Other).

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from fastapi import Request
        >>> from fastapi.responses import RedirectResponse
        >>> from starlette.datastructures import FormData
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = "test_user"
        >>> mock_request = MagicMock(spec=Request)
        >>> form_data = FormData([("is_inactive_checked", "false")])
        >>> mock_request.form = AsyncMock(return_value=form_data)
        >>> mock_request.scope = {"root_path": ""}
        >>>
        >>> original_delete_resource = resource_service.delete_resource
        >>> resource_service.delete_resource = AsyncMock()
        >>>
        >>> async def test_admin_delete_resource():
        ...     response = await admin_delete_resource("test://resource1", mock_request, mock_db, mock_user)
        ...     return isinstance(response, RedirectResponse) and response.status_code == 303
        >>>
        >>> import asyncio; asyncio.run(test_admin_delete_resource())
        True
        >>>
        >>> # Test with inactive checkbox checked
        >>> form_data_inactive = FormData([("is_inactive_checked", "true")])
        >>> mock_request.form = AsyncMock(return_value=form_data_inactive)
        >>>
        >>> async def test_admin_delete_resource_inactive():
        ...     response = await admin_delete_resource("test://resource1", mock_request, mock_user)
        ...     return isinstance(response, RedirectResponse) and "include_inactive=true" in response.headers["location"]
        >>>
        >>> asyncio.run(test_admin_delete_resource_inactive())
        True
        >>> resource_service.delete_resource = original_delete_resource
    """
    LOGGER.debug(f"User {user} is deleting resource URI {uri}")
    await resource_service.delete_resource(db, uri)
    form = await request.form()
    is_inactive_checked: str = str(form.get("is_inactive_checked", "false"))
    root_path = request.scope.get("root_path", "")
    if is_inactive_checked.lower() == "true":
        return RedirectResponse(f"{root_path}/admin/?include_inactive=true#resources", status_code=303)
    return RedirectResponse(f"{root_path}/admin#resources", status_code=303)


@admin_router.post("/resources/{resource_id}/toggle")
async def admin_toggle_resource(
    resource_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> RedirectResponse:
    """
    Toggle a resource's active status via the admin UI.

    This endpoint processes a form request to activate or deactivate a resource.
    It expects a form field 'activate' with value "true" to activate the resource
    or "false" to deactivate it. The endpoint handles exceptions gracefully and
    logs any errors that might occur during the status toggle operation.

    Args:
        resource_id (int): The ID of the resource whose status to toggle.
        request (Request): FastAPI request containing form data with the 'activate' field.
        db (Session): Database session dependency.
        user (str): Authenticated user dependency.

    Returns:
        RedirectResponse: A redirect to the admin dashboard resources section with a
        status code of 303 (See Other).

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from fastapi import Request
        >>> from fastapi.responses import RedirectResponse
        >>> from starlette.datastructures import FormData
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = "test_user"
        >>> mock_request = MagicMock(spec=Request)
        >>> form_data = FormData([
        ...     ("activate", "true"),
        ...     ("is_inactive_checked", "false")
        ... ])
        >>> mock_request.form = AsyncMock(return_value=form_data)
        >>> mock_request.scope = {"root_path": ""}
        >>>
        >>> original_toggle_resource_status = resource_service.toggle_resource_status
        >>> resource_service.toggle_resource_status = AsyncMock()
        >>>
        >>> async def test_admin_toggle_resource():
        ...     response = await admin_toggle_resource(1, mock_request, mock_db, mock_user)
        ...     return isinstance(response, RedirectResponse) and response.status_code == 303
        >>>
        >>> asyncio.run(test_admin_toggle_resource())
        True
        >>>
        >>> # Test with activate=false
        >>> form_data_deactivate = FormData([
        ...     ("activate", "false"),
        ...     ("is_inactive_checked", "false")
        ... ])
        >>> mock_request.form = AsyncMock(return_value=form_data_deactivate)
        >>>
        >>> async def test_admin_toggle_resource_deactivate():
        ...     response = await admin_toggle_resource(1, mock_request, mock_db, mock_user)
        ...     return isinstance(response, RedirectResponse) and response.status_code == 303
        >>>
        >>> asyncio.run(test_admin_toggle_resource_deactivate())
        True
        >>>
        >>> # Test with inactive checkbox checked
        >>> form_data_inactive = FormData([
        ...     ("activate", "true"),
        ...     ("is_inactive_checked", "true")
        ... ])
        >>> mock_request.form = AsyncMock(return_value=form_data_inactive)
        >>>
        >>> async def test_admin_toggle_resource_inactive():
        ...     response = await admin_toggle_resource(1, mock_request, mock_db, mock_user)
        ...     return isinstance(response, RedirectResponse) and "include_inactive=true" in response.headers["location"]
        >>>
        >>> asyncio.run(test_admin_toggle_resource_inactive())
        True
        >>>
        >>> # Test exception handling
        >>> resource_service.toggle_resource_status = AsyncMock(side_effect=Exception("Test error"))
        >>> form_data_error = FormData([
        ...     ("activate", "true"),
        ...     ("is_inactive_checked", "false")
        ... ])
        >>> mock_request.form = AsyncMock(return_value=form_data_error)
        >>>
        >>> async def test_admin_toggle_resource_exception():
        ...     response = await admin_toggle_resource(1, mock_request, mock_db, mock_user)
        ...     return isinstance(response, RedirectResponse) and response.status_code == 303
        >>>
        >>> asyncio.run(test_admin_toggle_resource_exception())
        True
        >>> resource_service.toggle_resource_status = original_toggle_resource_status
    """
    LOGGER.debug(f"User {user} is toggling resource ID {resource_id}")
    form = await request.form()
    activate = str(form.get("activate", "true")).lower() == "true"
    is_inactive_checked = str(form.get("is_inactive_checked", "false"))
    try:
        await resource_service.toggle_resource_status(db, resource_id, activate)
    except Exception as e:
        LOGGER.error(f"Error toggling resource status: {e}")

    root_path = request.scope.get("root_path", "")
    if is_inactive_checked.lower() == "true":
        return RedirectResponse(f"{root_path}/admin/?include_inactive=true#resources", status_code=303)
    return RedirectResponse(f"{root_path}/admin#resources", status_code=303)


@admin_router.get("/prompts/{name}")
async def admin_get_prompt(name: str, db: Session = Depends(get_db), user: str = Depends(require_auth)) -> Dict[str, Any]:
    """Get prompt details for the admin UI.

    Args:
        name: Prompt name.
        db: Database session.
        user: Authenticated user.

    Returns:
        A dictionary with prompt details.

    Raises:
        HTTPException: If the prompt is not found.
        Exception: For any other unexpected errors.

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from mcpgateway.schemas import PromptRead, PromptMetrics
        >>> from datetime import datetime, timezone
        >>> from mcpgateway.services.prompt_service import PromptNotFoundError # Added import
        >>> from fastapi import HTTPException
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = "test_user"
        >>> prompt_name = "test-prompt"
        >>>
        >>> # Mock prompt details
        >>> mock_metrics = PromptMetrics(
        ...     total_executions=3,
        ...     successful_executions=3,
        ...     failed_executions=0,
        ...     failure_rate=0.0,
        ...     min_response_time=0.1,
        ...     max_response_time=0.5,
        ...     avg_response_time=0.3,
        ...     last_execution_time=datetime.now(timezone.utc)
        ... )
        >>> mock_prompt_details = {
        ...     "id": 1,
        ...     "name": prompt_name,
        ...     "description": "A test prompt",
        ...     "template": "Hello {{name}}!",
        ...     "arguments": [{"name": "name", "type": "string"}],
        ...     "created_at": datetime.now(timezone.utc),
        ...     "updated_at": datetime.now(timezone.utc),
        ...     "is_active": True,
        ...     "metrics": mock_metrics,
        ...     "tags": []
        ... }
        >>>
        >>> original_get_prompt_details = prompt_service.get_prompt_details
        >>> prompt_service.get_prompt_details = AsyncMock(return_value=mock_prompt_details)
        >>>
        >>> async def test_admin_get_prompt():
        ...     result = await admin_get_prompt(prompt_name, mock_db, mock_user)
        ...     return isinstance(result, dict) and result.get("name") == prompt_name
        >>>
        >>> asyncio.run(test_admin_get_prompt())
        True
        >>>
        >>> # Test prompt not found
        >>> prompt_service.get_prompt_details = AsyncMock(side_effect=PromptNotFoundError("Prompt not found"))
        >>> async def test_admin_get_prompt_not_found():
        ...     try:
        ...         await admin_get_prompt("nonexistent", mock_db, mock_user)
        ...         return False
        ...     except HTTPException as e:
        ...         return e.status_code == 404 and "Prompt not found" in e.detail
        >>>
        >>> asyncio.run(test_admin_get_prompt_not_found())
        True
        >>>
        >>> # Test generic exception
        >>> prompt_service.get_prompt_details = AsyncMock(side_effect=Exception("Generic error"))
        >>> async def test_admin_get_prompt_exception():
        ...     try:
        ...         await admin_get_prompt(prompt_name, mock_db, mock_user)
        ...         return False
        ...     except Exception as e:
        ...         return str(e) == "Generic error"
        >>>
        >>> asyncio.run(test_admin_get_prompt_exception())
        True
        >>>
        >>> prompt_service.get_prompt_details = original_get_prompt_details
    """
    LOGGER.debug(f"User {user} requested details for prompt name {name}")
    try:
        prompt_details = await prompt_service.get_prompt_details(db, name)
        prompt = PromptRead.model_validate(prompt_details)
        return prompt.model_dump(by_alias=True)
    except PromptNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        LOGGER.error(f"Error getting prompt {name}: {e}")
        raise e


@admin_router.post("/prompts")
async def admin_add_prompt(request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)) -> JSONResponse:
    """Add a prompt via the admin UI.

    Expects form fields:
      - name
      - description (optional)
      - template
      - arguments (as a JSON string representing a list)

    Args:
        request: FastAPI request containing form data.
        db: Database session.
        user: Authenticated user.

    Returns:
        A redirect response to the admin dashboard.

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from fastapi import Request
        >>> from fastapi.responses import RedirectResponse
        >>> from starlette.datastructures import FormData
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = "test_user"
        >>> form_data = FormData([
        ...     ("name", "Test Prompt"),
        ...     ("description", "A test prompt"),
        ...     ("template", "Hello {{name}}!"),
        ...     ("arguments", '[{"name": "name", "type": "string"}]'),
        ... ])
        >>> mock_request = MagicMock(spec=Request)
        >>> mock_request.form = AsyncMock(return_value=form_data)
        >>> mock_request.scope = {"root_path": ""}
        >>>
        >>> original_register_prompt = prompt_service.register_prompt
        >>> prompt_service.register_prompt = AsyncMock()
        >>>
        >>> async def test_admin_add_prompt():
        ...     response = await admin_add_prompt(mock_request, mock_db, mock_user)
        ...     return isinstance(response, JSONResponse) and response.status_code == 200 and response.body == b'{"message":"Prompt registered successfully!","success":true}'
        >>>
        >>> asyncio.run(test_admin_add_prompt())
        True

        >>> prompt_service.register_prompt = original_register_prompt
    """
    LOGGER.debug(f"User {user} is adding a new prompt")
    form = await request.form()

    # Parse tags from comma-separated string
    tags_str = str(form.get("tags", ""))
    tags: List[str] = [tag.strip() for tag in tags_str.split(",") if tag.strip()] if tags_str else []

    try:
        args_json = "[]"
        args_value = form.get("arguments")
        if isinstance(args_value, str) and args_value.strip():
            args_json = args_value
        arguments = json.loads(args_json)
        prompt = PromptCreate(
            name=str(form["name"]),
            description=str(form.get("description")),
            template=str(form["template"]),
            arguments=arguments,
            tags=tags,
        )
        # Extract creation metadata
        metadata = MetadataCapture.extract_creation_metadata(request, user)

        await prompt_service.register_prompt(
            db,
            prompt,
            created_by=metadata["created_by"],
            created_from_ip=metadata["created_from_ip"],
            created_via=metadata["created_via"],
            created_user_agent=metadata["created_user_agent"],
            import_batch_id=metadata["import_batch_id"],
            federation_source=metadata["federation_source"],
        )
        return JSONResponse(
            content={"message": "Prompt registered successfully!", "success": True},
            status_code=200,
        )
    except Exception as ex:
        if isinstance(ex, ValidationError):
            LOGGER.error(f"ValidationError in admin_add_prompt: {ErrorFormatter.format_validation_error(ex)}")
            return JSONResponse(content=ErrorFormatter.format_validation_error(ex), status_code=422)
        if isinstance(ex, IntegrityError):
            error_message = ErrorFormatter.format_database_error(ex)
            LOGGER.error(f"IntegrityError in admin_add_prompt: {error_message}")
            return JSONResponse(status_code=409, content=error_message)
        LOGGER.error(f"Error in admin_add_prompt: {ex}")
        return JSONResponse(content={"message": str(ex), "success": False}, status_code=500)


@admin_router.post("/prompts/{name}/edit")
async def admin_edit_prompt(
    name: str,
    request: Request,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> Response:
    """Edit a prompt via the admin UI.

    Expects form fields:
      - name
      - description (optional)
      - template
      - arguments (as a JSON string representing a list)

    Args:
        name: Prompt name.
        request: FastAPI request containing form data.
        db: Database session.
        user: Authenticated user.

    Returns:
         Response: A JSON response indicating success or failure of the server update operation.

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from fastapi import Request
        >>> from fastapi.responses import RedirectResponse
        >>> from starlette.datastructures import FormData
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = "test_user"
        >>> prompt_name = "test-prompt"
        >>> form_data = FormData([
        ...     ("name", "Updated Prompt"),
        ...     ("description", "Updated description"),
        ...     ("template", "Hello {{name}}, welcome!"),
        ...     ("arguments", '[{"name": "name", "type": "string"}]'),
        ...     ("is_inactive_checked", "false")
        ... ])
        >>> mock_request = MagicMock(spec=Request)
        >>> mock_request.form = AsyncMock(return_value=form_data)
        >>> mock_request.scope = {"root_path": ""}
        >>>
        >>> original_update_prompt = prompt_service.update_prompt
        >>> prompt_service.update_prompt = AsyncMock()
        >>>
        >>> async def test_admin_edit_prompt():
        ...     response = await admin_edit_prompt(prompt_name, mock_request, mock_db, mock_user)
        ...     return isinstance(response, JSONResponse) and response.status_code == 200 and response.body == b'{"message":"Prompt updated successfully!","success":true}'
        >>>
        >>> asyncio.run(test_admin_edit_prompt())
        True
        >>>
        >>> # Test with inactive checkbox checked
        >>> form_data_inactive = FormData([
        ...     ("name", "Updated Prompt"),
        ...     ("template", "Hello {{name}}!"),
        ...     ("arguments", "[]"),
        ...     ("is_inactive_checked", "true")
        ... ])
        >>> mock_request.form = AsyncMock(return_value=form_data_inactive)
        >>>
        >>> async def test_admin_edit_prompt_inactive():
        ...     response = await admin_edit_prompt(prompt_name, mock_request, mock_db, mock_user)
        ...     return isinstance(response, RedirectResponse) and "include_inactive=true" in response.headers["location"]
        >>>
        >>> asyncio.run(test_admin_edit_prompt_inactive())
        True
        >>> prompt_service.update_prompt = original_update_prompt
    """
    LOGGER.debug(f"User {user} is editing prompt name {name}")
    form = await request.form()

    args_json: str = str(form.get("arguments")) or "[]"
    arguments = json.loads(args_json)
    # Parse tags from comma-separated string
    tags_str = str(form.get("tags", ""))
    tags: List[str] = [tag.strip() for tag in tags_str.split(",") if tag.strip()] if tags_str else []
    try:
        prompt = PromptUpdate(
            name=str(form["name"]),
            description=str(form.get("description")),
            template=str(form["template"]),
            arguments=arguments,
            tags=tags,
        )
        await prompt_service.update_prompt(db, name, prompt)

        root_path = request.scope.get("root_path", "")
        is_inactive_checked: str = str(form.get("is_inactive_checked", "false"))
        if is_inactive_checked.lower() == "true":
            return RedirectResponse(f"{root_path}/admin/?include_inactive=true#prompts", status_code=303)
        # return RedirectResponse(f"{root_path}/admin#prompts", status_code=303)
        return JSONResponse(
            content={"message": "Prompt updated successfully!", "success": True},
            status_code=200,
        )
    except Exception as ex:
        if isinstance(ex, ValidationError):
            LOGGER.error(f"ValidationError in admin_edit_prompt: {ErrorFormatter.format_validation_error(ex)}")
            return JSONResponse(content=ErrorFormatter.format_validation_error(ex), status_code=422)
        if isinstance(ex, IntegrityError):
            error_message = ErrorFormatter.format_database_error(ex)
            LOGGER.error(f"IntegrityError in admin_edit_prompt: {error_message}")
            return JSONResponse(status_code=409, content=error_message)
        LOGGER.error(f"Error in admin_edit_prompt: {ex}")
        return JSONResponse(content={"message": str(ex), "success": False}, status_code=500)


@admin_router.post("/prompts/{name}/delete")
async def admin_delete_prompt(name: str, request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)) -> RedirectResponse:
    """
    Delete a prompt via the admin UI.

    This endpoint permanently deletes a prompt from the database using its name.
    Deletion is irreversible and requires authentication. All actions are logged
    for administrative auditing.

    Args:
        name (str): The name of the prompt to delete.
        request (Request): FastAPI request object (not used directly but required by the route signature).
        db (Session): Database session dependency.
        user (str): Authenticated user dependency.

    Returns:
        RedirectResponse: A redirect response to the prompts section of the admin
        dashboard with a status code of 303 (See Other).

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from fastapi import Request
        >>> from fastapi.responses import RedirectResponse
        >>> from starlette.datastructures import FormData
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = "test_user"
        >>> mock_request = MagicMock(spec=Request)
        >>> form_data = FormData([("is_inactive_checked", "false")])
        >>> mock_request.form = AsyncMock(return_value=form_data)
        >>> mock_request.scope = {"root_path": ""}
        >>>
        >>> original_delete_prompt = prompt_service.delete_prompt
        >>> prompt_service.delete_prompt = AsyncMock()
        >>>
        >>> async def test_admin_delete_prompt():
        ...     response = await admin_delete_prompt("test-prompt", mock_request, mock_db, mock_user)
        ...     return isinstance(response, RedirectResponse) and response.status_code == 303
        >>>
        >>> asyncio.run(test_admin_delete_prompt())
        True
        >>>
        >>> # Test with inactive checkbox checked
        >>> form_data_inactive = FormData([("is_inactive_checked", "true")])
        >>> mock_request.form = AsyncMock(return_value=form_data_inactive)
        >>>
        >>> async def test_admin_delete_prompt_inactive():
        ...     response = await admin_delete_prompt("test-prompt", mock_request, mock_db, mock_user)
        ...     return isinstance(response, RedirectResponse) and "include_inactive=true" in response.headers["location"]
        >>>
        >>> asyncio.run(test_admin_delete_prompt_inactive())
        True
        >>> prompt_service.delete_prompt = original_delete_prompt
    """
    LOGGER.debug(f"User {user} is deleting prompt name {name}")
    await prompt_service.delete_prompt(db, name)
    form = await request.form()
    is_inactive_checked: str = str(form.get("is_inactive_checked", "false"))
    root_path = request.scope.get("root_path", "")
    if is_inactive_checked.lower() == "true":
        return RedirectResponse(f"{root_path}/admin/?include_inactive=true#prompts", status_code=303)
    return RedirectResponse(f"{root_path}/admin#prompts", status_code=303)


@admin_router.post("/prompts/{prompt_id}/toggle")
async def admin_toggle_prompt(
    prompt_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> RedirectResponse:
    """
    Toggle a prompt's active status via the admin UI.

    This endpoint processes a form request to activate or deactivate a prompt.
    It expects a form field 'activate' with value "true" to activate the prompt
    or "false" to deactivate it. The endpoint handles exceptions gracefully and
    logs any errors that might occur during the status toggle operation.

    Args:
        prompt_id (int): The ID of the prompt whose status to toggle.
        request (Request): FastAPI request containing form data with the 'activate' field.
        db (Session): Database session dependency.
        user (str): Authenticated user dependency.

    Returns:
        RedirectResponse: A redirect to the admin dashboard prompts section with a
        status code of 303 (See Other).

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from fastapi import Request
        >>> from fastapi.responses import RedirectResponse
        >>> from starlette.datastructures import FormData
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = "test_user"
        >>> mock_request = MagicMock(spec=Request)
        >>> form_data = FormData([
        ...     ("activate", "true"),
        ...     ("is_inactive_checked", "false")
        ... ])
        >>> mock_request.form = AsyncMock(return_value=form_data)
        >>> mock_request.scope = {"root_path": ""}
        >>>
        >>> original_toggle_prompt_status = prompt_service.toggle_prompt_status
        >>> prompt_service.toggle_prompt_status = AsyncMock()
        >>>
        >>> async def test_admin_toggle_prompt():
        ...     response = await admin_toggle_prompt(1, mock_request, mock_db, mock_user)
        ...     return isinstance(response, RedirectResponse) and response.status_code == 303
        >>>
        >>> asyncio.run(test_admin_toggle_prompt())
        True
        >>>
        >>> # Test with activate=false
        >>> form_data_deactivate = FormData([
        ...     ("activate", "false"),
        ...     ("is_inactive_checked", "false")
        ... ])
        >>> mock_request.form = AsyncMock(return_value=form_data_deactivate)
        >>>
        >>> async def test_admin_toggle_prompt_deactivate():
        ...     response = await admin_toggle_prompt(1, mock_request, mock_db, mock_user)
        ...     return isinstance(response, RedirectResponse) and response.status_code == 303
        >>>
        >>> asyncio.run(test_admin_toggle_prompt_deactivate())
        True
        >>>
        >>> # Test with inactive checkbox checked
        >>> form_data_inactive = FormData([
        ...     ("activate", "true"),
        ...     ("is_inactive_checked", "true")
        ... ])
        >>> mock_request.form = AsyncMock(return_value=form_data_inactive)
        >>>
        >>> async def test_admin_toggle_prompt_inactive():
        ...     response = await admin_toggle_prompt(1, mock_request, mock_db, mock_user)
        ...     return isinstance(response, RedirectResponse) and "include_inactive=true" in response.headers["location"]
        >>>
        >>> asyncio.run(test_admin_toggle_prompt_inactive())
        True
        >>>
        >>> # Test exception handling
        >>> prompt_service.toggle_prompt_status = AsyncMock(side_effect=Exception("Test error"))
        >>> form_data_error = FormData([
        ...     ("activate", "true"),
        ...     ("is_inactive_checked", "false")
        ... ])
        >>> mock_request.form = AsyncMock(return_value=form_data_error)
        >>>
        >>> async def test_admin_toggle_prompt_exception():
        ...     response = await admin_toggle_prompt(1, mock_request, mock_db, mock_user)
        ...     return isinstance(response, RedirectResponse) and response.status_code == 303
        >>>
        >>> asyncio.run(test_admin_toggle_prompt_exception())
        True
        >>> prompt_service.toggle_prompt_status = original_toggle_prompt_status
    """
    LOGGER.debug(f"User {user} is toggling prompt ID {prompt_id}")
    form = await request.form()
    activate: bool = str(form.get("activate", "true")).lower() == "true"
    is_inactive_checked: str = str(form.get("is_inactive_checked", "false"))
    try:
        await prompt_service.toggle_prompt_status(db, prompt_id, activate)
    except Exception as e:
        LOGGER.error(f"Error toggling prompt status: {e}")

    root_path = request.scope.get("root_path", "")
    if is_inactive_checked.lower() == "true":
        return RedirectResponse(f"{root_path}/admin/?include_inactive=true#prompts", status_code=303)
    return RedirectResponse(f"{root_path}/admin#prompts", status_code=303)


@admin_router.post("/roots")
async def admin_add_root(request: Request, user: str = Depends(require_auth)) -> RedirectResponse:
    """Add a new root via the admin UI.

    Expects form fields:
      - path
      - name (optional)

    Args:
        request: FastAPI request containing form data.
        user: Authenticated user.

    Returns:
        RedirectResponse: A redirect response to the admin dashboard.

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from fastapi import Request
        >>> from fastapi.responses import RedirectResponse
        >>> from starlette.datastructures import FormData
        >>>
        >>> mock_user = "test_user"
        >>> mock_request = MagicMock(spec=Request)
        >>> form_data = FormData([
        ...     ("uri", "test://root1"),
        ...     ("name", "Test Root"),
        ... ])
        >>> mock_request.form = AsyncMock(return_value=form_data)
        >>> mock_request.scope = {"root_path": ""}
        >>>
        >>> original_add_root = root_service.add_root
        >>> root_service.add_root = AsyncMock()
        >>>
        >>> async def test_admin_add_root():
        ...     response = await admin_add_root(mock_request, mock_user)
        ...     return isinstance(response, RedirectResponse) and response.status_code == 303
        >>>
        >>> asyncio.run(test_admin_add_root())
        True
        >>> root_service.add_root = original_add_root
    """
    LOGGER.debug(f"User {user} is adding a new root")
    form = await request.form()
    uri = str(form["uri"])
    name_value = form.get("name")
    name: str | None = None
    if isinstance(name_value, str):
        name = name_value
    await root_service.add_root(uri, name)
    root_path = request.scope.get("root_path", "")
    return RedirectResponse(f"{root_path}/admin#roots", status_code=303)


@admin_router.post("/roots/{uri:path}/delete")
async def admin_delete_root(uri: str, request: Request, user: str = Depends(require_auth)) -> RedirectResponse:
    """
    Delete a root via the admin UI.

    This endpoint removes a registered root URI from the system. The deletion is
    permanent and cannot be undone. It requires authentication and logs the
    operation for audit purposes.

    Args:
        uri (str): The URI of the root to delete.
        request (Request): FastAPI request object (not used directly but required by the route signature).
        user (str): Authenticated user dependency.

    Returns:
        RedirectResponse: A redirect response to the roots section of the admin
        dashboard with a status code of 303 (See Other).

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from fastapi import Request
        >>> from fastapi.responses import RedirectResponse
        >>> from starlette.datastructures import FormData
        >>>
        >>> mock_user = "test_user"
        >>> mock_request = MagicMock(spec=Request)
        >>> form_data = FormData([("is_inactive_checked", "false")])
        >>> mock_request.form = AsyncMock(return_value=form_data)
        >>> mock_request.scope = {"root_path": ""}
        >>>
        >>> original_remove_root = root_service.remove_root
        >>> root_service.remove_root = AsyncMock()
        >>>
        >>> async def test_admin_delete_root():
        ...     response = await admin_delete_root("test://root1", mock_request, mock_user)
        ...     return isinstance(response, RedirectResponse) and response.status_code == 303
        >>>
        >>> asyncio.run(test_admin_delete_root())
        True
        >>>
        >>> # Test with inactive checkbox checked
        >>> form_data_inactive = FormData([("is_inactive_checked", "true")])
        >>> mock_request.form = AsyncMock(return_value=form_data_inactive)
        >>>
        >>> async def test_admin_delete_root_inactive():
        ...     response = await admin_delete_root("test://root1", mock_request, mock_user)
        ...     return isinstance(response, RedirectResponse) and "include_inactive=true" in response.headers["location"]
        >>>
        >>> asyncio.run(test_admin_delete_root_inactive())
        True
        >>> root_service.remove_root = original_remove_root
    """
    LOGGER.debug(f"User {user} is deleting root URI {uri}")
    await root_service.remove_root(uri)
    form = await request.form()
    root_path = request.scope.get("root_path", "")
    is_inactive_checked: str = str(form.get("is_inactive_checked", "false"))
    if is_inactive_checked.lower() == "true":
        return RedirectResponse(f"{root_path}/admin/?include_inactive=true#roots", status_code=303)
    return RedirectResponse(f"{root_path}/admin#roots", status_code=303)


# Metrics
MetricsDict = Dict[str, Union[ToolMetrics, ResourceMetrics, ServerMetrics, PromptMetrics]]


# @admin_router.get("/metrics", response_model=MetricsDict)
# async def admin_get_metrics(
#     db: Session = Depends(get_db),
#     user: str = Depends(require_auth),
# ) -> MetricsDict:
#     """
#     Retrieve aggregate metrics for all entity types via the admin UI.

#     This endpoint collects and returns usage metrics for tools, resources, servers,
#     and prompts. The metrics are retrieved by calling the aggregate_metrics method
#     on each respective service, which compiles statistics about usage patterns,
#     success rates, and other relevant metrics for administrative monitoring
#     and analysis purposes.

#     Args:
#         db (Session): Database session dependency.
#         user (str): Authenticated user dependency.

#     Returns:
#         MetricsDict: A dictionary containing the aggregated metrics for tools,
#         resources, servers, and prompts. Each value is a Pydantic model instance
#         specific to the entity type.
#     """
#     LOGGER.debug(f"User {user} requested aggregate metrics")
#     tool_metrics = await tool_service.aggregate_metrics(db)
#     resource_metrics = await resource_service.aggregate_metrics(db)
#     server_metrics = await server_service.aggregate_metrics(db)
#     prompt_metrics = await prompt_service.aggregate_metrics(db)

#     # Return actual Pydantic model instances
#     return {
#         "tools": tool_metrics,
#         "resources": resource_metrics,
#         "servers": server_metrics,
#         "prompts": prompt_metrics,
#     }


@admin_router.get("/metrics")
async def get_aggregated_metrics(
    db: Session = Depends(get_db),
    _user: str = Depends(require_auth),
) -> Dict[str, Any]:
    """Retrieve aggregated metrics and top performers for all entity types.

    This endpoint collects usage metrics and top-performing entities for tools,
    resources, prompts, and servers by calling the respective service methods.
    The results are compiled into a dictionary for administrative monitoring.

    Args:
        db (Session): Database session dependency for querying metrics.

    Returns:
        Dict[str, Any]: A dictionary containing aggregated metrics and top performers
            for tools, resources, prompts, and servers. The structure includes:
            - 'tools': Metrics for tools.
            - 'resources': Metrics for resources.
            - 'prompts': Metrics for prompts.
            - 'servers': Metrics for servers.
            - 'topPerformers': A nested dictionary with top 5 tools, resources, prompts,
              and servers.
    """
    metrics = {
        "tools": await tool_service.aggregate_metrics(db),
        "resources": await resource_service.aggregate_metrics(db),
        "prompts": await prompt_service.aggregate_metrics(db),
        "servers": await server_service.aggregate_metrics(db),
        "topPerformers": {
            "tools": await tool_service.get_top_tools(db, limit=5),
            "resources": await resource_service.get_top_resources(db, limit=5),
            "prompts": await prompt_service.get_top_prompts(db, limit=5),
            "servers": await server_service.get_top_servers(db, limit=5),
        },
    }
    return metrics


@admin_router.post("/metrics/reset", response_model=Dict[str, object])
async def admin_reset_metrics(db: Session = Depends(get_db), user: str = Depends(require_auth)) -> Dict[str, object]:
    """
    Reset all metrics for tools, resources, servers, and prompts.
    Each service must implement its own reset_metrics method.

    Args:
        db (Session): Database session dependency.
        user (str): Authenticated user dependency.

    Returns:
        Dict[str, object]: A dictionary containing a success message and status.

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>>
        >>> mock_db = MagicMock()
        >>> mock_user = "test_user"
        >>>
        >>> original_reset_metrics_tool = tool_service.reset_metrics
        >>> original_reset_metrics_resource = resource_service.reset_metrics
        >>> original_reset_metrics_server = server_service.reset_metrics
        >>> original_reset_metrics_prompt = prompt_service.reset_metrics
        >>>
        >>> tool_service.reset_metrics = AsyncMock()
        >>> resource_service.reset_metrics = AsyncMock()
        >>> server_service.reset_metrics = AsyncMock()
        >>> prompt_service.reset_metrics = AsyncMock()
        >>>
        >>> async def test_admin_reset_metrics():
        ...     result = await admin_reset_metrics(mock_db, mock_user)
        ...     return result == {"message": "All metrics reset successfully", "success": True}
        >>>
        >>> import asyncio; asyncio.run(test_admin_reset_metrics())
        True
        >>>
        >>> tool_service.reset_metrics = original_reset_metrics_tool
        >>> resource_service.reset_metrics = original_reset_metrics_resource
        >>> server_service.reset_metrics = original_reset_metrics_server
        >>> prompt_service.reset_metrics = original_reset_metrics_prompt
    """
    LOGGER.debug(f"User {user} requested to reset all metrics")
    await tool_service.reset_metrics(db)
    await resource_service.reset_metrics(db)
    await server_service.reset_metrics(db)
    await prompt_service.reset_metrics(db)
    return {"message": "All metrics reset successfully", "success": True}


@admin_router.post("/gateways/test", response_model=GatewayTestResponse)
async def admin_test_gateway(request: GatewayTestRequest, user: str = Depends(require_auth)) -> GatewayTestResponse:
    """
    Test a gateway by sending a request to its URL.
    This endpoint allows administrators to test the connectivity and response

    Args:
        request (GatewayTestRequest): The request object containing the gateway URL and request details.
        user (str): Authenticated user dependency.

    Returns:
        GatewayTestResponse: The response from the gateway, including status code, latency, and body

    Examples:
        >>> import asyncio
        >>> from unittest.mock import AsyncMock, MagicMock
        >>> from mcpgateway.schemas import GatewayTestRequest, GatewayTestResponse
        >>> from fastapi import Request
        >>> import httpx
        >>>
        >>> mock_user = "test_user"
        >>> mock_request = GatewayTestRequest(
        ...     base_url="https://api.example.com",
        ...     path="/test",
        ...     method="GET",
        ...     headers={},
        ...     body=None
        ... )
        >>>
        >>> # Mock ResilientHttpClient to simulate a successful response
        >>> class MockResponse:
        ...     def __init__(self):
        ...         self.status_code = 200
        ...         self._json = {"message": "success"}
        ...     def json(self):
        ...         return self._json
        ...     @property
        ...     def text(self):
        ...         return str(self._json)
        >>>
        >>> class MockClient:
        ...     async def __aenter__(self):
        ...         return self
        ...     async def __aexit__(self, exc_type, exc, tb):
        ...         pass
        ...     async def request(self, method, url, headers=None, json=None):
        ...         return MockResponse()
        >>>
        >>> from unittest.mock import patch
        >>>
        >>> async def test_admin_test_gateway():
        ...     with patch('mcpgateway.admin.ResilientHttpClient') as mock_client_class:
        ...         mock_client_class.return_value = MockClient()
        ...         response = await admin_test_gateway(mock_request, mock_user)
        ...         return isinstance(response, GatewayTestResponse) and response.status_code == 200
        >>>
        >>> result = asyncio.run(test_admin_test_gateway())
        >>> result
        True
        >>>
        >>> # Test with JSON decode error
        >>> class MockResponseTextOnly:
        ...     def __init__(self):
        ...         self.status_code = 200
        ...         self.text = "plain text response"
        ...     def json(self):
        ...         raise json.JSONDecodeError("Invalid JSON", "doc", 0)
        >>>
        >>> class MockClientTextOnly:
        ...     async def __aenter__(self):
        ...         return self
        ...     async def __aexit__(self, exc_type, exc, tb):
        ...         pass
        ...     async def request(self, method, url, headers=None, json=None):
        ...         return MockResponseTextOnly()
        >>>
        >>> async def test_admin_test_gateway_text_response():
        ...     with patch('mcpgateway.admin.ResilientHttpClient') as mock_client_class:
        ...         mock_client_class.return_value = MockClientTextOnly()
        ...         response = await admin_test_gateway(mock_request, mock_user)
        ...         return isinstance(response, GatewayTestResponse) and response.body.get("details") == "plain text response"
        >>>
        >>> asyncio.run(test_admin_test_gateway_text_response())
        True
        >>>
        >>> # Test with network error
        >>> class MockClientError:
        ...     async def __aenter__(self):
        ...         return self
        ...     async def __aexit__(self, exc_type, exc, tb):
        ...         pass
        ...     async def request(self, method, url, headers=None, json=None):
        ...         raise httpx.RequestError("Network error")
        >>>
        >>> async def test_admin_test_gateway_network_error():
        ...     with patch('mcpgateway.admin.ResilientHttpClient') as mock_client_class:
        ...         mock_client_class.return_value = MockClientError()
        ...         response = await admin_test_gateway(mock_request, mock_user)
        ...         return response.status_code == 502 and "Network error" in str(response.body)
        >>>
        >>> asyncio.run(test_admin_test_gateway_network_error())
        True
        >>>
        >>> # Test with POST method and body
        >>> mock_request_post = GatewayTestRequest(
        ...     base_url="https://api.example.com",
        ...     path="/test",
        ...     method="POST",
        ...     headers={"Content-Type": "application/json"},
        ...     body={"test": "data"}
        ... )
        >>>
        >>> async def test_admin_test_gateway_post():
        ...     with patch('mcpgateway.admin.ResilientHttpClient') as mock_client_class:
        ...         mock_client_class.return_value = MockClient()
        ...         response = await admin_test_gateway(mock_request_post, mock_user)
        ...         return isinstance(response, GatewayTestResponse) and response.status_code == 200
        >>>
        >>> asyncio.run(test_admin_test_gateway_post())
        True
        >>>
        >>> # Test URL path handling with trailing slashes
        >>> mock_request_trailing = GatewayTestRequest(
        ...     base_url="https://api.example.com/",
        ...     path="/test/",
        ...     method="GET",
        ...     headers={},
        ...     body=None
        ... )
        >>>
        >>> async def test_admin_test_gateway_trailing_slash():
        ...     with patch('mcpgateway.admin.ResilientHttpClient') as mock_client_class:
        ...         mock_client_class.return_value = MockClient()
        ...         response = await admin_test_gateway(mock_request_trailing, mock_user)
        ...         return isinstance(response, GatewayTestResponse) and response.status_code == 200
        >>>
        >>> asyncio.run(test_admin_test_gateway_trailing_slash())
        True
    """
    full_url = str(request.base_url).rstrip("/") + "/" + request.path.lstrip("/")
    full_url = full_url.rstrip("/")
    LOGGER.debug(f"User {user} testing server at {request.base_url}.")
    try:
        start_time: float = time.monotonic()
        async with ResilientHttpClient(client_args={"timeout": settings.federation_timeout, "verify": not settings.skip_ssl_verify}) as client:
            response: httpx.Response = await client.request(method=request.method.upper(), url=full_url, headers=request.headers, json=request.body)
        latency_ms = int((time.monotonic() - start_time) * 1000)
        try:
            response_body: Union[Dict[str, Any], str] = response.json()
        except json.JSONDecodeError:
            response_body = {"details": response.text}

        return GatewayTestResponse(status_code=response.status_code, latency_ms=latency_ms, body=response_body)

    except httpx.RequestError as e:
        LOGGER.warning(f"Gateway test failed: {e}")
        latency_ms = int((time.monotonic() - start_time) * 1000)
        return GatewayTestResponse(status_code=502, latency_ms=latency_ms, body={"error": "Request failed", "details": str(e)})


####################
# Admin Tag Routes #
####################


@admin_router.get("/tags", response_model=List[Dict[str, Any]])
async def admin_list_tags(
    entity_types: Optional[str] = None,
    include_entities: bool = False,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> List[Dict[str, Any]]:
    """
    List all unique tags with statistics for the admin UI.

    Args:
        entity_types: Comma-separated list of entity types to filter by
                     (e.g., "tools,resources,prompts,servers,gateways").
                     If not provided, returns tags from all entity types.
        include_entities: Whether to include the list of entities that have each tag
        db: Database session
        user: Authenticated user

    Returns:
        List of tag information with statistics

    Raises:
        HTTPException: If tag retrieval fails

    Examples:
        >>> # Test function exists and has correct name
        >>> from mcpgateway.admin import admin_list_tags
        >>> admin_list_tags.__name__
        'admin_list_tags'
        >>> # Test it's a coroutine function
        >>> import inspect
        >>> inspect.iscoroutinefunction(admin_list_tags)
        True
    """
    tag_service = TagService()

    # Parse entity types parameter if provided
    entity_types_list = None
    if entity_types:
        entity_types_list = [et.strip().lower() for et in entity_types.split(",") if et.strip()]

    LOGGER.debug(f"Admin user {user} is retrieving tags for entity types: {entity_types_list}, include_entities: {include_entities}")

    try:
        tags = await tag_service.get_all_tags(db, entity_types=entity_types_list, include_entities=include_entities)

        # Convert to list of dicts for admin UI
        result: List[Dict[str, Any]] = []
        for tag in tags:
            tag_dict: Dict[str, Any] = {
                "name": tag.name,
                "tools": tag.stats.tools,
                "resources": tag.stats.resources,
                "prompts": tag.stats.prompts,
                "servers": tag.stats.servers,
                "gateways": tag.stats.gateways,
                "total": tag.stats.total,
            }

            # Include entities if requested
            if include_entities and tag.entities:
                tag_dict["entities"] = [
                    {
                        "id": entity.id,
                        "name": entity.name,
                        "type": entity.type,
                        "description": entity.description,
                    }
                    for entity in tag.entities
                ]

            result.append(tag_dict)

        return result
    except Exception as e:
        LOGGER.error(f"Failed to retrieve tags for admin: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve tags: {str(e)}")


@admin_router.post("/tools/import/")
@admin_router.post("/tools/import")
@rate_limit(requests_per_minute=settings.mcpgateway_bulk_import_rate_limit)
async def admin_import_tools(
    request: Request,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> JSONResponse:
    """Bulk import multiple tools in a single request.

    Accepts a JSON array of tool definitions and registers them individually.
    Provides per-item validation and error reporting without failing the entire batch.

    Args:
        request: FastAPI Request containing the tools data
        db: Database session
        user: Authenticated username

    Returns:
        JSONResponse with success status, counts, and details of created/failed tools

    Raises:
        HTTPException: For authentication or rate limiting failures
    """
    # Check if bulk import is enabled
    if not settings.mcpgateway_bulk_import_enabled:
        LOGGER.warning("Bulk import attempted but feature is disabled")
        raise HTTPException(status_code=403, detail="Bulk import feature is disabled. Enable MCPGATEWAY_BULK_IMPORT_ENABLED to use this endpoint.")

    LOGGER.debug("bulk tool import: user=%s", user)
    try:
        # ---------- robust payload parsing ----------
        ctype = (request.headers.get("content-type") or "").lower()
        if "application/json" in ctype:
            try:
                payload = await request.json()
            except Exception as ex:
                LOGGER.exception("Invalid JSON body")
                return JSONResponse({"success": False, "message": f"Invalid JSON: {ex}"}, status_code=422)
        else:
            try:
                form = await request.form()
            except Exception as ex:
                LOGGER.exception("Invalid form body")
                return JSONResponse({"success": False, "message": f"Invalid form data: {ex}"}, status_code=422)
            # Check for file upload first
            if "tools_file" in form:
                file = form["tools_file"]
                if hasattr(file, "file"):
                    content = await file.read()
                    try:
                        payload = json.loads(content.decode("utf-8"))
                    except (json.JSONDecodeError, UnicodeDecodeError) as ex:
                        LOGGER.exception("Invalid JSON file")
                        return JSONResponse({"success": False, "message": f"Invalid JSON file: {ex}"}, status_code=422)
                else:
                    return JSONResponse({"success": False, "message": "Invalid file upload"}, status_code=422)
            else:
                # Check for JSON in form fields
                raw = form.get("tools") or form.get("tools_json") or form.get("json") or form.get("payload")
                if not raw:
                    return JSONResponse({"success": False, "message": "Missing tools/tools_json/json/payload form field."}, status_code=422)
                try:
                    payload = json.loads(raw)
                except Exception as ex:
                    LOGGER.exception("Invalid JSON in form field")
                    return JSONResponse({"success": False, "message": f"Invalid JSON: {ex}"}, status_code=422)

        if not isinstance(payload, list):
            return JSONResponse({"success": False, "message": "Payload must be a JSON array of tools."}, status_code=422)

        max_batch = settings.mcpgateway_bulk_import_max_tools
        if len(payload) > max_batch:
            return JSONResponse({"success": False, "message": f"Too many tools ({len(payload)}). Max {max_batch}."}, status_code=413)

        created, errors = [], []

        # ---------- import loop ----------
        # Generate import batch ID for this bulk operation
        import_batch_id = str(uuid.uuid4())

        # Extract base metadata for bulk import
        base_metadata = MetadataCapture.extract_creation_metadata(request, user, import_batch_id=import_batch_id)

        for i, item in enumerate(payload):
            name = (item or {}).get("name")
            try:
                tool = ToolCreate(**item)  # pydantic validation
                await tool_service.register_tool(
                    db,
                    tool,
                    created_by=base_metadata["created_by"],
                    created_from_ip=base_metadata["created_from_ip"],
                    created_via="import",  # Override to show this is bulk import
                    created_user_agent=base_metadata["created_user_agent"],
                    import_batch_id=import_batch_id,
                    federation_source=base_metadata["federation_source"],
                )
                created.append({"index": i, "name": name})
            except IntegrityError as ex:
                # The formatter can itself throw; guard it.
                try:
                    formatted = ErrorFormatter.format_database_error(ex)
                except Exception:
                    formatted = {"message": str(ex)}
                errors.append({"index": i, "name": name, "error": formatted})
            except (ValidationError, CoreValidationError) as ex:
                # Ditto: guard the formatter
                try:
                    formatted = ErrorFormatter.format_validation_error(ex)
                except Exception:
                    formatted = {"message": str(ex)}
                errors.append({"index": i, "name": name, "error": formatted})
            except ToolError as ex:
                errors.append({"index": i, "name": name, "error": {"message": str(ex)}})
            except Exception as ex:
                LOGGER.exception("Unexpected error importing tool %r at index %d", name, i)
                errors.append({"index": i, "name": name, "error": {"message": str(ex)}})

        # Format response to match both frontend and test expectations
        response_data = {
            "success": len(errors) == 0,
            # New format for frontend
            "imported": len(created),
            "failed": len(errors),
            "total": len(payload),
            # Original format for tests
            "created_count": len(created),
            "failed_count": len(errors),
            "created": created,
            "errors": errors,
            # Detailed format for frontend
            "details": {
                "success": [item["name"] for item in created if item.get("name")],
                "failed": [{"name": item["name"], "error": item["error"].get("message", str(item["error"]))} for item in errors],
            },
        }

        if len(errors) == 0:
            response_data["message"] = f"Successfully imported all {len(created)} tools"
        else:
            response_data["message"] = f"Imported {len(created)} of {len(payload)} tools. {len(errors)} failed."

        return JSONResponse(
            response_data,
            status_code=200,  # Always return 200, success field indicates if all succeeded
        )

    except HTTPException:
        # let FastAPI semantics (e.g., auth) pass through
        raise
    except Exception as ex:
        # absolute catch-all: report instead of crashing
        LOGGER.exception("Fatal error in admin_import_tools")
        return JSONResponse({"success": False, "message": str(ex)}, status_code=500)


####################
# Log Endpoints
####################


@admin_router.get("/logs")
async def admin_get_logs(
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    level: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    request_id: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    order: str = "desc",
    user: str = Depends(require_auth),  # pylint: disable=unused-argument
) -> Dict[str, Any]:
    """Get filtered log entries from the in-memory buffer.

    Args:
        entity_type: Filter by entity type (tool, resource, server, gateway)
        entity_id: Filter by entity ID
        level: Minimum log level (debug, info, warning, error, critical)
        start_time: ISO format start time
        end_time: ISO format end time
        request_id: Filter by request ID
        search: Search in message text
        limit: Maximum number of results (default 100, max 1000)
        offset: Number of results to skip
        order: Sort order (asc or desc)
        user: Authenticated user

    Returns:
        Dictionary with logs and metadata

    Raises:
        HTTPException: If validation fails or service unavailable
    """
    # Get log storage from logging service
    storage = logging_service.get_storage()
    if not storage:
        return {"logs": [], "total": 0, "stats": {}}

    # Parse timestamps if provided
    start_dt = None
    end_dt = None
    if start_time:
        try:
            start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(400, f"Invalid start_time format: {start_time}")

    if end_time:
        try:
            end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(400, f"Invalid end_time format: {end_time}")

    # Parse log level
    log_level = None
    if level:
        try:
            log_level = LogLevel(level.lower())
        except ValueError:
            raise HTTPException(400, f"Invalid log level: {level}")

    # Limit max results
    limit = min(limit, 1000)

    # Get filtered logs
    logs = await storage.get_logs(
        entity_type=entity_type,
        entity_id=entity_id,
        level=log_level,
        start_time=start_dt,
        end_time=end_dt,
        request_id=request_id,
        search=search,
        limit=limit,
        offset=offset,
        order=order,
    )

    # Get statistics
    stats = storage.get_stats()

    return {
        "logs": logs,
        "total": stats.get("total_logs", 0),
        "stats": stats,
    }


@admin_router.get("/logs/stream")
async def admin_stream_logs(
    request: Request,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    level: Optional[str] = None,
    user: str = Depends(require_auth),  # pylint: disable=unused-argument
):
    """Stream real-time log updates via Server-Sent Events.

    Args:
        request: FastAPI request object
        entity_type: Filter by entity type
        entity_id: Filter by entity ID
        level: Minimum log level
        user: Authenticated user

    Returns:
        SSE response with real-time log updates

    Raises:
        HTTPException: If log level is invalid or service unavailable
    """
    # Get log storage from logging service
    storage = logging_service.get_storage()
    if not storage:
        raise HTTPException(503, "Log storage not available")

    # Parse log level filter
    min_level = None
    if level:
        try:
            min_level = LogLevel(level.lower())
        except ValueError:
            raise HTTPException(400, f"Invalid log level: {level}")

    async def generate():
        """Generate SSE events for log streaming.

        Yields:
            Formatted SSE events containing log data
        """
        try:
            async for event in storage.subscribe():
                # Check if client disconnected
                if await request.is_disconnected():
                    break

                # Apply filters
                log_data = event.get("data", {})

                # Entity type filter
                if entity_type and log_data.get("entity_type") != entity_type:
                    continue

                # Entity ID filter
                if entity_id and log_data.get("entity_id") != entity_id:
                    continue

                # Level filter
                if min_level:
                    log_level = log_data.get("level")
                    if log_level:
                        try:
                            if not storage._meets_level_threshold(LogLevel(log_level), min_level):  # pylint: disable=protected-access
                                continue
                        except ValueError:
                            continue

                # Send SSE event
                yield f"data: {json.dumps(event)}\n\n"

        except Exception as e:
            LOGGER.error(f"Error in log streaming: {e}")
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable Nginx buffering
        },
    )


@admin_router.get("/logs/file")
async def admin_get_log_file(
    filename: Optional[str] = None,
    user: str = Depends(require_auth),  # pylint: disable=unused-argument
):
    """Download log file.

    Args:
        filename: Specific log file to download (optional)
        user: Authenticated user

    Returns:
        File download response or list of available files

    Raises:
        HTTPException: If file doesn't exist or access denied
    """
    # Check if file logging is enabled
    if not settings.log_to_file or not settings.log_file:
        raise HTTPException(404, "File logging is not enabled")

    # Determine log directory
    log_dir = Path(settings.log_folder) if settings.log_folder else Path(".")

    if filename:
        # Download specific file
        file_path = log_dir / filename

        # Security: Ensure file is within log directory
        try:
            file_path = file_path.resolve()
            log_dir_resolved = log_dir.resolve()
            if not str(file_path).startswith(str(log_dir_resolved)):
                raise HTTPException(403, "Access denied")
        except Exception:
            raise HTTPException(400, "Invalid file path")

        # Check if file exists
        if not file_path.exists() or not file_path.is_file():
            raise HTTPException(404, f"Log file not found: {filename}")

        # Check if it's a log file
        if not (file_path.suffix in [".log", ".jsonl", ".json"] or file_path.stem.startswith(Path(settings.log_file).stem)):
            raise HTTPException(403, "Not a log file")

        # Return file for download
        return FileResponse(
            path=file_path,
            filename=file_path.name,
            media_type="application/octet-stream",
        )

    # List available log files
    log_files = []

    try:
        # Main log file
        main_log = log_dir / settings.log_file
        if main_log.exists():
            stat = main_log.stat()
            log_files.append(
                {
                    "name": main_log.name,
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "type": "main",
                }
            )

            # Rotated log files
            if settings.log_rotation_enabled:
                pattern = f"{Path(settings.log_file).stem}.*"
                for file in log_dir.glob(pattern):
                    if file.is_file():
                        stat = file.stat()
                        log_files.append(
                            {
                                "name": file.name,
                                "size": stat.st_size,
                                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                                "type": "rotated",
                            }
                        )

            # Storage log file (JSON lines)
            storage_log = log_dir / f"{Path(settings.log_file).stem}_storage.jsonl"
            if storage_log.exists():
                stat = storage_log.stat()
                log_files.append(
                    {
                        "name": storage_log.name,
                        "size": stat.st_size,
                        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        "type": "storage",
                    }
                )

        # Sort by modified time (newest first)
        log_files.sort(key=lambda x: x["modified"], reverse=True)

    except Exception as e:
        LOGGER.error(f"Error listing log files: {e}")
        raise HTTPException(500, f"Error listing log files: {e}")

    return {
        "log_directory": str(log_dir),
        "files": log_files,
        "total": len(log_files),
    }


@admin_router.get("/logs/export")
async def admin_export_logs(
    export_format: str = "json",
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    level: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    request_id: Optional[str] = None,
    search: Optional[str] = None,
    user: str = Depends(require_auth),  # pylint: disable=unused-argument
):
    """Export filtered logs in JSON or CSV format.

    Args:
        export_format: Export format (json or csv)
        entity_type: Filter by entity type
        entity_id: Filter by entity ID
        level: Minimum log level
        start_time: ISO format start time
        end_time: ISO format end time
        request_id: Filter by request ID
        search: Search in message text
        user: Authenticated user

    Returns:
        File download response with exported logs

    Raises:
        HTTPException: If validation fails or export format invalid
    """
    # Standard
    # Validate format
    if export_format not in ["json", "csv"]:
        raise HTTPException(400, f"Invalid format: {export_format}. Use 'json' or 'csv'")

    # Get log storage from logging service
    storage = logging_service.get_storage()
    if not storage:
        raise HTTPException(503, "Log storage not available")

    # Parse timestamps if provided
    start_dt = None
    end_dt = None
    if start_time:
        try:
            start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(400, f"Invalid start_time format: {start_time}")

    if end_time:
        try:
            end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(400, f"Invalid end_time format: {end_time}")

    # Parse log level
    log_level = None
    if level:
        try:
            log_level = LogLevel(level.lower())
        except ValueError:
            raise HTTPException(400, f"Invalid log level: {level}")

    # Get all matching logs (no pagination for export)
    logs = await storage.get_logs(
        entity_type=entity_type,
        entity_id=entity_id,
        level=log_level,
        start_time=start_dt,
        end_time=end_dt,
        request_id=request_id,
        search=search,
        limit=10000,  # Reasonable max for export
        offset=0,
        order="desc",
    )

    # Generate filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"logs_export_{timestamp}.{export_format}"

    if export_format == "json":
        # Export as JSON
        content = json.dumps(logs, indent=2, default=str)
        return Response(
            content=content,
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )

    # CSV format
    # Create CSV content
    output = io.StringIO()

    if logs:
        # Use first log to determine columns
        fieldnames = [
            "timestamp",
            "level",
            "entity_type",
            "entity_id",
            "entity_name",
            "message",
            "logger",
            "request_id",
        ]

        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()

        for log in logs:
            # Flatten the log entry for CSV
            row = {k: log.get(k, "") for k in fieldnames}
            writer.writerow(row)

    content = output.getvalue()

    return Response(
        content=content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


# Configuration Export/Import Endpoints
@admin_router.get("/export/configuration")
async def admin_export_configuration(
    types: Optional[str] = None,
    exclude_types: Optional[str] = None,
    tags: Optional[str] = None,
    include_inactive: bool = False,
    include_dependencies: bool = True,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
):
    """
    Export gateway configuration via Admin UI.

    Args:
        types: Comma-separated entity types to include
        exclude_types: Comma-separated entity types to exclude
        tags: Comma-separated tags to filter by
        include_inactive: Include inactive entities
        include_dependencies: Include dependent entities
        db: Database session
        user: Authenticated user

    Returns:
        JSON file download with configuration export

    Raises:
        HTTPException: If export fails
    """
    try:
        LOGGER.info(f"Admin user {user} requested configuration export")

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

        # Generate filename
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"mcpgateway-config-export-{timestamp}.json"

        # Return as downloadable file
        content = json.dumps(export_data, indent=2, ensure_ascii=False)
        return Response(
            content=content,
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )

    except ExportError as e:
        LOGGER.error(f"Admin export failed for user {user}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        LOGGER.error(f"Unexpected admin export error for user {user}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")


@admin_router.post("/export/selective")
async def admin_export_selective(request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    """
    Export selected entities via Admin UI with entity selection.

    Args:
        request: FastAPI request object
        db: Database session
        user: Authenticated user

    Returns:
        JSON file download with selective export data

    Raises:
        HTTPException: If export fails

    Expects JSON body with entity selections:
    {
        "entity_selections": {
            "tools": ["tool1", "tool2"],
            "servers": ["server1"]
        },
        "include_dependencies": true
    }
    """
    try:
        LOGGER.info(f"Admin user {user} requested selective configuration export")

        body = await request.json()
        entity_selections = body.get("entity_selections", {})
        include_dependencies = body.get("include_dependencies", True)

        # Extract username from user (which could be string or dict with token)
        username = user if isinstance(user, str) else user.get("username", "unknown")

        # Perform selective export
        export_data = await export_service.export_selective(db=db, entity_selections=entity_selections, include_dependencies=include_dependencies, exported_by=username)

        # Generate filename
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"mcpgateway-selective-export-{timestamp}.json"

        # Return as downloadable file
        content = json.dumps(export_data, indent=2, ensure_ascii=False)
        return Response(
            content=content,
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )

    except ExportError as e:
        LOGGER.error(f"Admin selective export failed for user {user}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        LOGGER.error(f"Unexpected admin selective export error for user {user}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")


@admin_router.post("/import/configuration")
async def admin_import_configuration(request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    """
    Import configuration via Admin UI.

    Args:
        request: FastAPI request object
        db: Database session
        user: Authenticated user

    Returns:
        JSON response with import status

    Raises:
        HTTPException: If import fails

    Expects JSON body with import data and options:
    {
        "import_data": { ... },
        "conflict_strategy": "update",
        "dry_run": false,
        "rekey_secret": "optional-new-secret",
        "selected_entities": { ... }
    }
    """
    try:
        LOGGER.info(f"Admin user {user} requested configuration import")

        body = await request.json()
        import_data = body.get("import_data")
        if not import_data:
            raise HTTPException(status_code=400, detail="Missing import_data in request body")

        conflict_strategy_str = body.get("conflict_strategy", "update")
        dry_run = body.get("dry_run", False)
        rekey_secret = body.get("rekey_secret")
        selected_entities = body.get("selected_entities")

        # Validate conflict strategy
        try:
            conflict_strategy = ConflictStrategy(conflict_strategy_str.lower())
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid conflict strategy. Must be one of: {[s.value for s in ConflictStrategy]}")

        # Extract username from user (which could be string or dict with token)
        username = user if isinstance(user, str) else user.get("username", "unknown")

        # Perform import
        status = await import_service.import_configuration(
            db=db, import_data=import_data, conflict_strategy=conflict_strategy, dry_run=dry_run, rekey_secret=rekey_secret, imported_by=username, selected_entities=selected_entities
        )

        return JSONResponse(content=status.to_dict())

    except ImportServiceError as e:
        LOGGER.error(f"Admin import failed for user {user}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        LOGGER.error(f"Unexpected admin import error for user {user}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}")


@admin_router.get("/import/status/{import_id}")
async def admin_get_import_status(import_id: str, user: str = Depends(require_auth)):
    """Get import status via Admin UI.

    Args:
        import_id: Import operation ID
        user: Authenticated user

    Returns:
        JSON response with import status

    Raises:
        HTTPException: If import not found
    """
    LOGGER.debug(f"Admin user {user} requested import status for {import_id}")

    status = import_service.get_import_status(import_id)
    if not status:
        raise HTTPException(status_code=404, detail=f"Import {import_id} not found")

    return JSONResponse(content=status.to_dict())


@admin_router.get("/import/status")
async def admin_list_import_statuses(user: str = Depends(require_auth)):
    """List all import statuses via Admin UI.

    Args:
        user: Authenticated user

    Returns:
        JSON response with list of import statuses
    """
    LOGGER.debug(f"Admin user {user} requested all import statuses")

    statuses = import_service.list_import_statuses()
    return JSONResponse(content=[status.to_dict() for status in statuses])


# ============================================================================ #
#                             A2A AGENT ADMIN ROUTES                          #
# ============================================================================ #


@admin_router.get("/a2a")
async def admin_list_a2a_agents(
    include_inactive: bool = False,
    tags: Optional[str] = None,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> HTMLResponse:
    """List A2A agents for admin UI.

    Args:
        include_inactive: Whether to include inactive agents
        tags: Comma-separated list of tags to filter by
        db: Database session
        user: Authenticated user

    Returns:
        HTML response with agents list

    Raises:
        HTTPException: If A2A features are disabled
    """
    if not a2a_service or not settings.mcpgateway_a2a_enabled:
        return HTMLResponse(content='<div class="text-center py-8"><p class="text-gray-500">A2A features are disabled. Set MCPGATEWAY_A2A_ENABLED=true to enable.</p></div>', status_code=200)
    # Parse tags parameter if provided
    tags_list = None
    if tags:
        tags_list = [tag.strip() for tag in tags.split(",") if tag.strip()]

    LOGGER.debug(f"Admin user {user} requested A2A agent list with tags={tags_list}")
    agents = await a2a_service.list_agents(db, include_inactive=include_inactive, tags=tags_list)

    # Convert to template format
    agent_items = []
    for agent in agents:
        agent_items.append(
            {
                "id": agent.id,
                "name": agent.name,
                "description": agent.description or "",
                "endpoint_url": agent.endpoint_url,
                "agent_type": agent.agent_type,
                "protocol_version": agent.protocol_version,
                "auth_type": agent.auth_type or "None",
                "enabled": agent.enabled,
                "reachable": agent.reachable,
                "tags": agent.tags,
                "created_at": agent.created_at.isoformat(),
                "last_interaction": agent.last_interaction.isoformat() if agent.last_interaction else None,
                "execution_count": agent.metrics.total_executions,
                "success_rate": f"{100 - agent.metrics.failure_rate:.1f}%" if agent.metrics.total_executions > 0 else "N/A",
            }
        )

    # Generate HTML for agents list
    html_content = ""
    for agent in agent_items:
        status_class = "bg-green-100 text-green-800" if agent["enabled"] else "bg-red-100 text-red-800"
        reachable_class = "bg-green-100 text-green-800" if agent["reachable"] else "bg-yellow-100 text-yellow-800"
        active_text = "Active" if agent["enabled"] else "Inactive"
        reachable_text = "Reachable" if agent["reachable"] else "Unreachable"

        # Generate tags HTML separately
        tags_html = ""
        if agent["tags"]:
            tag_spans = []
            for tag in agent["tags"]:
                tag_spans.append(f'<span class="inline-flex items-center px-2 py-1 rounded text-xs bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300">{tag}</span>')
            tags_html = f'<div class="mt-2 flex flex-wrap gap-1">{" ".join(tag_spans)}</div>'

        # Generate last interaction HTML
        last_interaction_html = ""
        if agent["last_interaction"]:
            last_interaction_html = f"<div>Last Interaction: {agent['last_interaction'][:19]}</div>"

        # Generate button classes
        toggle_class = "text-green-700 bg-green-100 hover:bg-green-200" if not agent["enabled"] else "text-red-700 bg-red-100 hover:bg-red-200"
        toggle_text = "Activate" if not agent["enabled"] else "Deactivate"
        toggle_action = "true" if not agent["enabled"] else "false"

        html_content += f"""
        <div class="border border-gray-200 dark:border-gray-600 rounded-lg p-4 space-y-3">
          <div class="flex items-start justify-between">
            <div class="flex-1">
              <h4 class="text-lg font-medium text-gray-900 dark:text-gray-200">{agent["name"]}</h4>
              <p class="text-sm text-gray-600 dark:text-gray-400">{agent["description"]}</p>
              <div class="mt-2 flex flex-wrap gap-2">
                <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium {status_class}">
                  {active_text}
                </span>
                <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium {reachable_class}">
                  {reachable_text}
                </span>
                <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800">
                  {agent["agent_type"]}
                </span>
                <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-800">
                  Auth: {agent["auth_type"]}
                </span>
              </div>
              <div class="mt-2 text-xs text-gray-500 dark:text-gray-400">
                <div>Endpoint: {agent["endpoint_url"]}</div>
                <div>Executions: {agent["execution_count"]} | Success Rate: {agent["success_rate"]}</div>
                <div>Created: {agent["created_at"][:19]}</div>
                {last_interaction_html}
              </div>
              {tags_html}
            </div>
            <div class="flex space-x-2">
              <button
                hx-post="{{ root_path }}/admin/a2a/{agent["id"]}/toggle"
                hx-vals='{{"activate": "{toggle_action}"}}'
                hx-target="#a2a-agents-list"
                hx-trigger="click"
                class="px-3 py-1 text-sm font-medium {toggle_class} rounded-md focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500"
              >
                {toggle_text}
              </button>
              <button
                hx-post="{{ root_path }}/admin/a2a/{agent["id"]}/delete"
                hx-target="#a2a-agents-list"
                hx-trigger="click"
                hx-confirm="Are you sure you want to delete this A2A agent?"
                class="px-3 py-1 text-sm font-medium text-red-700 bg-red-100 hover:bg-red-200 rounded-md focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500"
              >
                Delete
              </button>
            </div>
          </div>
        </div>
        """

    return HTMLResponse(content=html_content)


@admin_router.post("/a2a")
async def admin_add_a2a_agent(
    request: Request,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> RedirectResponse:
    """Add a new A2A agent via admin UI.

    Args:
        request: FastAPI request object
        db: Database session
        user: Authenticated user

    Returns:
        HTML response with success/error status

    Raises:
        HTTPException: If A2A features are disabled
    """
    LOGGER.info(f"A2A agent creation request from user {user}")

    if not a2a_service or not settings.mcpgateway_a2a_enabled:
        LOGGER.warning("A2A agent creation attempted but A2A features are disabled")
        return HTMLResponse(content='<div class="text-red-500">A2A features are disabled</div>', status_code=403)

    try:
        form = await request.form()
        LOGGER.info(f"A2A agent creation form data: {dict(form)}")

        # Process tags
        tags_str = form.get("tags", "")
        tags = [tag.strip() for tag in tags_str.split(",") if tag.strip()] if tags_str else []

        agent_data = A2AAgentCreate(
            name=form["name"],
            description=form.get("description"),
            endpoint_url=form["endpoint_url"],
            agent_type=form.get("agent_type", "generic"),
            auth_type=form.get("auth_type") if form.get("auth_type") else None,
            auth_value=form.get("auth_value") if form.get("auth_value") else None,
            tags=tags,
        )

        LOGGER.info(f"Creating A2A agent: {agent_data.name} at {agent_data.endpoint_url}")

        # Extract metadata from request
        metadata = MetadataCapture.extract_creation_metadata(request, user)

        await a2a_service.register_agent(
            db,
            agent_data,
            created_by=metadata["created_by"],
            created_from_ip=metadata["created_from_ip"],
            created_via=metadata["created_via"],
            created_user_agent=metadata["created_user_agent"],
            import_batch_id=metadata["import_batch_id"],
            federation_source=metadata["federation_source"],
        )

        # Return redirect to admin page with A2A tab
        root_path = request.scope.get("root_path", "")
        return RedirectResponse(f"{root_path}/admin#a2a-agents", status_code=303)

    except A2AAgentNameConflictError as e:
        LOGGER.error(f"A2A agent name conflict: {e}")
        root_path = request.scope.get("root_path", "")
        return RedirectResponse(f"{root_path}/admin#a2a-agents", status_code=303)
    except A2AAgentError as e:
        LOGGER.error(f"A2A agent error: {e}")
        root_path = request.scope.get("root_path", "")
        return RedirectResponse(f"{root_path}/admin#a2a-agents", status_code=303)
    except ValidationError as e:
        LOGGER.error(f"Validation error while creating A2A agent: {e}")
        root_path = request.scope.get("root_path", "")
        return RedirectResponse(f"{root_path}/admin#a2a-agents", status_code=303)
    except Exception as e:
        LOGGER.error(f"Error creating A2A agent: {e}")
        root_path = request.scope.get("root_path", "")
        return RedirectResponse(f"{root_path}/admin#a2a-agents", status_code=303)


@admin_router.post("/a2a/{agent_id}/toggle")
async def admin_toggle_a2a_agent(
    agent_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),  # pylint: disable=unused-argument
) -> RedirectResponse:
    """Toggle A2A agent status via admin UI.

    Args:
        agent_id: Agent ID
        request: FastAPI request object
        db: Database session
        user: Authenticated user

    Returns:
        Redirect response to admin page with A2A tab

    Raises:
        HTTPException: If A2A features are disabled
    """
    if not a2a_service or not settings.mcpgateway_a2a_enabled:
        root_path = request.scope.get("root_path", "")
        return RedirectResponse(f"{root_path}/admin#a2a-agents", status_code=303)

    try:
        form = await request.form()
        activate = form.get("activate", "false").lower() == "true"

        await a2a_service.toggle_agent_status(db, agent_id, activate)
        root_path = request.scope.get("root_path", "")
        return RedirectResponse(f"{root_path}/admin#a2a-agents", status_code=303)

    except A2AAgentNotFoundError as e:
        LOGGER.error(f"A2A agent toggle failed - not found: {e}")
        root_path = request.scope.get("root_path", "")
        return RedirectResponse(f"{root_path}/admin#a2a-agents", status_code=303)
    except Exception as e:
        LOGGER.error(f"Error toggling A2A agent: {e}")
        root_path = request.scope.get("root_path", "")
        return RedirectResponse(f"{root_path}/admin#a2a-agents", status_code=303)


@admin_router.post("/a2a/{agent_id}/delete")
async def admin_delete_a2a_agent(
    agent_id: str,
    request: Request,  # pylint: disable=unused-argument
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),  # pylint: disable=unused-argument
) -> RedirectResponse:
    """Delete A2A agent via admin UI.

    Args:
        agent_id: Agent ID
        request: FastAPI request object
        db: Database session
        user: Authenticated user

    Returns:
        Redirect response to admin page with A2A tab

    Raises:
        HTTPException: If A2A features are disabled
    """
    if not a2a_service or not settings.mcpgateway_a2a_enabled:
        root_path = request.scope.get("root_path", "")
        return RedirectResponse(f"{root_path}/admin#a2a-agents", status_code=303)

    try:
        await a2a_service.delete_agent(db, agent_id)
        root_path = request.scope.get("root_path", "")
        return RedirectResponse(f"{root_path}/admin#a2a-agents", status_code=303)

    except A2AAgentNotFoundError as e:
        LOGGER.error(f"A2A agent delete failed - not found: {e}")
        root_path = request.scope.get("root_path", "")
        return RedirectResponse(f"{root_path}/admin#a2a-agents", status_code=303)
    except Exception as e:
        LOGGER.error(f"Error deleting A2A agent: {e}")
        root_path = request.scope.get("root_path", "")
        return RedirectResponse(f"{root_path}/admin#a2a-agents", status_code=303)


@admin_router.post("/a2a/{agent_id}/test")
async def admin_test_a2a_agent(
    agent_id: str,
    request: Request,  # pylint: disable=unused-argument
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),  # pylint: disable=unused-argument
) -> JSONResponse:
    """Test A2A agent via admin UI.

    Args:
        agent_id: Agent ID
        request: FastAPI request object
        db: Database session
        user: Authenticated user

    Returns:
        JSON response with test results

    Raises:
        HTTPException: If A2A features are disabled
    """
    if not a2a_service or not settings.mcpgateway_a2a_enabled:
        return JSONResponse(content={"success": False, "error": "A2A features are disabled"}, status_code=403)

    try:
        # Get the agent by ID
        agent = await a2a_service.get_agent(db, agent_id)

        # Prepare test parameters based on agent type and endpoint
        if agent.agent_type in ["generic", "jsonrpc"] or agent.endpoint_url.endswith("/"):
            # JSONRPC format for agents that expect it
            test_params = {
                "method": "message/send",
                "params": {"message": {"messageId": f"admin-test-{int(time.time())}", "role": "user", "parts": [{"type": "text", "text": "Hello from MCP Gateway Admin UI test!"}]}},
            }
        else:
            # Generic test format
            test_params = {"message": "Hello from MCP Gateway Admin UI test!", "test": True, "timestamp": int(time.time())}

        # Invoke the agent
        result = await a2a_service.invoke_agent(db, agent.name, test_params, "admin_test")

        return JSONResponse(content={"success": True, "result": result, "agent_name": agent.name, "test_timestamp": time.time()})

    except Exception as e:
        LOGGER.error(f"Error testing A2A agent {agent_id}: {e}")
        return JSONResponse(content={"success": False, "error": str(e), "agent_id": agent_id}, status_code=500)
