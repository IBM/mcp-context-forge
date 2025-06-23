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

import json
import logging
from typing import Any, Dict, List, Union

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from mcpgateway.config import settings
from mcpgateway.db import get_db
from mcpgateway.schemas import (
    GatewayCreate,
    GatewayRead,
    GatewayUpdate,
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
from mcpgateway.services.gateway_service import GatewayConnectionError, GatewayService
from mcpgateway.services.prompt_service import PromptService
from mcpgateway.services.resource_service import ResourceService
from mcpgateway.services.root_service import RootService
from mcpgateway.services.server_service import ServerNotFoundError, ServerService
from mcpgateway.services.tool_service import (
    ToolError,
    ToolNameConflictError,
    ToolService,
)
from mcpgateway.utils.create_jwt_token import get_jwt_token
from mcpgateway.utils.verify_credentials import require_auth, require_basic_auth

# Initialize services
server_service = ServerService()
tool_service = ToolService()
prompt_service = PromptService()
gateway_service = GatewayService()
resource_service = ResourceService()
root_service = RootService()

# Set up basic authentication
logger = logging.getLogger("mcpgateway")

admin_router = APIRouter(prefix="/admin", tags=["Admin UI"])

####################
# Admin UI Routes  #
####################


@admin_router.get("/servers", response_model=List[ServerRead])
async def admin_list_servers(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> List[ServerRead]:
    """
    List servers for the admin UI with an option to include inactive servers.

    Args:
        include_inactive (bool): Whether to include inactive servers.
        db (Session): The database session dependency.
        user (str): The authenticated user dependency.

    Returns:
        List[ServerRead]: A list of server records.
    """
    logger.debug(f"User {user} requested server list")
    servers = await server_service.list_servers(db, include_inactive=include_inactive)
    return [server.dict(by_alias=True) for server in servers]


@admin_router.get("/servers/{server_id}", response_model=ServerRead)
async def admin_get_server(server_id: int, db: Session = Depends(get_db), user: str = Depends(require_auth)) -> ServerRead:
    """
    Retrieve server details for the admin UI.

    Args:
        server_id (int): The ID of the server to retrieve.
        db (Session): The database session dependency.
        user (str): The authenticated user dependency.

    Returns:
        ServerRead: The server details.

    Raises:
        HTTPException: If the server is not found.
    """
    try:
        logger.debug(f"User {user} requested details for server ID {server_id}")
        server = await server_service.get_server(db, server_id)
        return server.dict(by_alias=True)
    except ServerNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@admin_router.post("/servers", response_model=ServerRead)
async def admin_add_server(request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)) -> RedirectResponse:
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
        RedirectResponse: A redirect to the admin dashboard catalog section
    """
    form = await request.form()
    try:
        logger.debug(f"User {user} is adding a new server with name: {form['name']}")
        server = ServerCreate(
            name=form["name"],
            description=form.get("description"),
            icon=form.get("icon"),
            associated_tools=form.get("associatedTools"),
            associated_resources=form.get("associatedResources"),
            associated_prompts=form.get("associatedPrompts"),
        )
        await server_service.register_server(db, server)

        root_path = request.scope.get("root_path", "")
        return RedirectResponse(f"{root_path}/admin#catalog", status_code=303)
    except Exception as e:
        logger.error(f"Error adding server: {e}")

        root_path = request.scope.get("root_path", "")
        return RedirectResponse(f"{root_path}/admin#catalog", status_code=303)


@admin_router.post("/servers/{server_id}/edit")
async def admin_edit_server(
    server_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> RedirectResponse:
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
        server_id (int): The ID of the server to edit
        request (Request): FastAPI request containing form data
        db (Session): Database session dependency
        user (str): Authenticated user dependency

    Returns:
        RedirectResponse: A redirect to the admin dashboard catalog section with a status code of 303
    """
    form = await request.form()
    try:
        logger.debug(f"User {user} is editing server ID {server_id} with name: {form.get('name')}")
        server = ServerUpdate(
            name=form.get("name"),
            description=form.get("description"),
            icon=form.get("icon"),
            associated_tools=form.get("associatedTools"),
            associated_resources=form.get("associatedResources"),
            associated_prompts=form.get("associatedPrompts"),
        )
        await server_service.update_server(db, server_id, server)

        root_path = request.scope.get("root_path", "")
        return RedirectResponse(f"{root_path}/admin#catalog", status_code=303)
    except Exception as e:
        logger.error(f"Error editing server: {e}")

        root_path = request.scope.get("root_path", "")
        return RedirectResponse(f"{root_path}/admin#catalog", status_code=303)


@admin_router.post("/servers/{server_id}/toggle")
async def admin_toggle_server(
    server_id: int,
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
        server_id (int): The ID of the server whose status to toggle.
        request (Request): FastAPI request containing form data with the 'activate' field.
        db (Session): Database session dependency.
        user (str): Authenticated user dependency.

    Returns:
        RedirectResponse: A redirect to the admin dashboard catalog section with a
        status code of 303 (See Other).
    """
    form = await request.form()
    logger.debug(f"User {user} is toggling server ID {server_id} with activate: {form.get('activate')}")
    activate = form.get("activate", "true").lower() == "true"
    try:
        await server_service.toggle_server_status(db, server_id, activate)
    except Exception as e:
        logger.error(f"Error toggling server status: {e}")

    root_path = request.scope.get("root_path", "")
    return RedirectResponse(f"{root_path}/admin#catalog", status_code=303)


@admin_router.post("/servers/{server_id}/delete")
async def admin_delete_server(server_id: int, request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)) -> RedirectResponse:
    """
    Delete a server via the admin UI.

    This endpoint removes a server from the database by its ID. It handles exceptions
    gracefully and logs any errors that occur during the deletion process.

    Args:
        server_id (int): The ID of the server to delete
        request (Request): FastAPI request object (not used but required by route signature).
        db (Session): Database session dependency
        user (str): Authenticated user dependency

    Returns:
        RedirectResponse: A redirect to the admin dashboard catalog section with a
        status code of 303 (See Other)
    """
    try:
        logger.debug(f"User {user} is deleting server ID {server_id}")
        await server_service.delete_server(db, server_id)
    except Exception as e:
        logger.error(f"Error deleting server: {e}")

    root_path = request.scope.get("root_path", "")
    return RedirectResponse(f"{root_path}/admin#catalog", status_code=303)


@admin_router.get("/resources", response_model=List[ResourceRead])
async def admin_list_resources(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> List[ResourceRead]:
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
    """
    logger.debug(f"User {user} requested resource list")
    resources = await resource_service.list_resources(db, include_inactive=include_inactive)
    return [resource.dict(by_alias=True) for resource in resources]


@admin_router.get("/prompts", response_model=List[PromptRead])
async def admin_list_prompts(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> List[PromptRead]:
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
    """
    logger.debug(f"User {user} requested prompt list")
    prompts = await prompt_service.list_prompts(db, include_inactive=include_inactive)
    return [prompt.dict(by_alias=True) for prompt in prompts]


@admin_router.get("/gateways", response_model=List[GatewayRead])
async def admin_list_gateways(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> List[GatewayRead]:
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
    """
    logger.debug(f"User {user} requested gateway list")
    gateways = await gateway_service.list_gateways(db, include_inactive=include_inactive)
    return [gateway.dict(by_alias=True) for gateway in gateways]


@admin_router.post("/gateways/{gateway_id}/toggle")
async def admin_toggle_gateway(
    gateway_id: int,
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
        gateway_id (int): The ID of the gateway to toggle.
        request (Request): The FastAPI request object containing form data.
        db (Session): The database session dependency.
        user (str): The authenticated user dependency.

    Returns:
        RedirectResponse: A redirect response to the admin dashboard with a
        status code of 303 (See Other).
    """
    logger.debug(f"User {user} is toggling gateway ID {gateway_id}")
    form = await request.form()
    activate = form.get("activate", "true").lower() == "true"
    try:
        await gateway_service.toggle_gateway_status(db, gateway_id, activate)
    except Exception as e:
        logger.error(f"Error toggling gateway status: {e}")

    root_path = request.scope.get("root_path", "")
    return RedirectResponse(f"{root_path}/admin#gateways", status_code=303)


@admin_router.get("/", name="admin_home", response_class=HTMLResponse)
async def admin_ui(
    request: Request,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    user: str = Depends(require_basic_auth),
    jwt_token: str = Depends(get_jwt_token),
) -> HTMLResponse:
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
        HTMLResponse: Rendered HTML template for the admin dashboard.
    """
    logger.debug(f"User {user} accessed the admin UI")
    servers = [server.dict(by_alias=True) for server in await server_service.list_servers(db, include_inactive=include_inactive)]
    tools = [tool.dict(by_alias=True) for tool in await tool_service.list_tools(db, include_inactive=include_inactive)]
    resources = [resource.dict(by_alias=True) for resource in await resource_service.list_resources(db, include_inactive=include_inactive)]
    prompts = [prompt.dict(by_alias=True) for prompt in await prompt_service.list_prompts(db, include_inactive=include_inactive)]
    gateways = [gateway.dict(by_alias=True) for gateway in await gateway_service.list_gateways(db, include_inactive=include_inactive)]
    roots = [root.dict(by_alias=True) for root in await root_service.list_roots()]
    root_path = settings.app_root_path
    response = request.app.state.templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "servers": servers,
            "tools": tools,
            "resources": resources,
            "prompts": prompts,
            "gateways": gateways,
            "roots": roots,
            "include_inactive": include_inactive,
            "root_path": root_path,
        },
    )

    response.set_cookie(key="jwt_token", value=jwt_token, httponly=True, secure=False, samesite="Strict")  # JavaScript CAN'T read it  # only over HTTPS  # or "Lax" per your needs
    return response


@admin_router.get("/tools", response_model=List[ToolRead])
async def admin_list_tools(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> List[ToolRead]:
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
    """
    logger.debug(f"User {user} requested tool list")
    tools = await tool_service.list_tools(db, include_inactive=include_inactive)
    return [tool.dict(by_alias=True) for tool in tools]


@admin_router.get("/tools/{tool_id}", response_model=ToolRead)
async def admin_get_tool(tool_id: int, db: Session = Depends(get_db), user: str = Depends(require_auth)) -> ToolRead:
    """
    Retrieve specific tool details for the admin UI.

    This endpoint fetches the details of a specific tool from the database
    by its ID. It provides access to all information about the tool for
    viewing and management purposes.

    Args:
        tool_id (int): The ID of the tool to retrieve.
        db (Session): Database session dependency.
        user (str): Authenticated user dependency.

    Returns:
        ToolRead: The tool details formatted with by_alias=True.
    """
    logger.debug(f"User {user} requested details for tool ID {tool_id}")
    tool = await tool_service.get_tool(db, tool_id)
    return tool.dict(by_alias=True)


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
    """
    logger.debug(f"User {user} is adding a new tool")
    form = await request.form()
    logger.debug(f"Received form data: {dict(form)}")

    tool_data = {
        "name": form["name"],
        "url": form["url"],
        "description": form.get("description"),
        "request_type": form.get("requestType", "SSE"),
        "integration_type": form.get("integrationType", "MCP"),
        "headers": json.loads(form.get("headers") or "{}"),
        "input_schema": json.loads(form.get("input_schema") or "{}"),
        "jsonpath_filter": form.get("jsonpath_filter", ""),
        "auth_type": form.get("auth_type", ""),
        "auth_username": form.get("auth_username", ""),
        "auth_password": form.get("auth_password", ""),
        "auth_token": form.get("auth_token", ""),
        "auth_header_key": form.get("auth_header_key", ""),
        "auth_header_value": form.get("auth_header_value", ""),
    }
    logger.debug(f"Tool data built: {tool_data}")
    try:
        tool = ToolCreate(**tool_data)
        logger.debug(f"Validated tool data: {tool.dict()}")
        await tool_service.register_tool(db, tool)
        return JSONResponse(
            content={"message": "Tool registered successfully!", "success": True},
            status_code=200,
        )
    except ToolNameConflictError as e:
        logger.error(f"ToolNameConflictError: {str(e)}")
        return JSONResponse(content={"message": str(e), "success": False}, status_code=400)
    except Exception as e:
        logger.error(f"Error in admin_add_tool: {str(e)}")
        return JSONResponse(content={"message": str(e), "success": False}, status_code=500)


@admin_router.post("/tools/{tool_id}/edit/")
@admin_router.post("/tools/{tool_id}/edit")
async def admin_edit_tool(
    tool_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> RedirectResponse:
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
        tool_id (int): The ID of the tool to edit.
        request (Request): FastAPI request containing form data.
        db (Session): Database session dependency.
        user (str): Authenticated user dependency.

    Returns:
        RedirectResponse: A redirect response to the tools section of the admin
        dashboard with a status code of 303 (See Other), or a JSON response with
        an error message if the update fails.
    """
    logger.debug(f"User {user} is editing tool ID {tool_id}")
    form = await request.form()
    tool_data = {
        "name": form["name"],
        "url": form["url"],
        "description": form.get("description"),
        "request_type": form.get("requestType", "SSE"),
        "integration_type": form.get("integrationType", "MCP"),
        "headers": json.loads(form.get("headers") or "{}"),
        "input_schema": json.loads(form.get("input_schema") or "{}"),
        "jsonpath_filter": form.get("jsonpathFilter", ""),
        "auth_type": form.get("auth_type", ""),
        "auth_username": form.get("auth_username", ""),
        "auth_password": form.get("auth_password", ""),
        "auth_token": form.get("auth_token", ""),
        "auth_header_key": form.get("auth_header_key", ""),
        "auth_header_value": form.get("auth_header_value", ""),
    }
    logger.info(f"Tool update data built: {tool_data}")
    tool = ToolUpdate(**tool_data)
    try:
        await tool_service.update_tool(db, tool_id, tool)

        root_path = request.scope.get("root_path", "")
        return RedirectResponse(f"{root_path}/admin#tools", status_code=303)
    except ToolNameConflictError as e:
        return JSONResponse(content={"message": str(e), "success": False}, status_code=400)
    except ToolError as e:
        return JSONResponse(content={"message": str(e), "success": False}, status_code=500)


@admin_router.post("/tools/{tool_id}/delete")
async def admin_delete_tool(tool_id: int, request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)) -> RedirectResponse:
    """
    Delete a tool via the admin UI.

    This endpoint permanently removes a tool from the database using its ID.
    It is irreversible and should be used with caution. The operation is logged,
    and the user must be authenticated to access this route.

    Args:
        tool_id (int): The ID of the tool to delete.
        request (Request): FastAPI request object (not used directly, but required by route signature).
        db (Session): Database session dependency.
        user (str): Authenticated user dependency.

    Returns:
        RedirectResponse: A redirect response to the tools section of the admin
        dashboard with a status code of 303 (See Other).
    """
    logger.debug(f"User {user} is deleting tool ID {tool_id}")
    await tool_service.delete_tool(db, tool_id)

    root_path = request.scope.get("root_path", "")
    return RedirectResponse(f"{root_path}/admin#tools", status_code=303)


@admin_router.post("/tools/{tool_id}/toggle")
async def admin_toggle_tool(
    tool_id: int,
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
        tool_id (int): The ID of the tool whose status to toggle.
        request (Request): FastAPI request containing form data with the 'activate' field.
        db (Session): Database session dependency.
        user (str): Authenticated user dependency.

    Returns:
        RedirectResponse: A redirect to the admin dashboard tools section with a
        status code of 303 (See Other).
    """
    logger.debug(f"User {user} is toggling tool ID {tool_id}")
    form = await request.form()
    activate = form.get("activate", "true").lower() == "true"
    try:
        await tool_service.toggle_tool_status(db, tool_id, activate)
    except Exception as e:
        logger.error(f"Error toggling tool status: {e}")

    root_path = request.scope.get("root_path", "")
    return RedirectResponse(f"{root_path}/admin#tools", status_code=303)


@admin_router.get("/gateways/{gateway_id}", response_model=GatewayRead)
async def admin_get_gateway(gateway_id: int, db: Session = Depends(get_db), user: str = Depends(require_auth)) -> GatewayRead:
    """Get gateway details for the admin UI.

    Args:
        gateway_id: Gateway ID.
        db: Database session.
        user: Authenticated user.

    Returns:
        Gateway details.
    """
    logger.debug(f"User {user} requested details for gateway ID {gateway_id}")
    gateway = await gateway_service.get_gateway(db, gateway_id)
    return gateway.dict(by_alias=True)


@admin_router.post("/gateways")
async def admin_add_gateway(request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)) -> RedirectResponse:
    """Add a gateway via the admin UI.

    Expects form fields:
      - name
      - url
      - description (optional)

    Args:
        request: FastAPI request containing form data.
        db: Database session.
        user: Authenticated user.

    Returns:
        A redirect response to the admin dashboard.
    """
    logger.debug(f"User {user} is adding a new gateway")
    form = await request.form()
    gateway = GatewayCreate(
        name=form["name"],
        url=form["url"],
        description=form.get("description"),
        transport=form.get("transport", "SSE"),
        auth_type=form.get("auth_type", ""),
        auth_username=form.get("auth_username", ""),
        auth_password=form.get("auth_password", ""),
        auth_token=form.get("auth_token", ""),
        auth_header_key=form.get("auth_header_key", ""),
        auth_header_value=form.get("auth_header_value", ""),
    )
    root_path = request.scope.get("root_path", "")
    try:
        await gateway_service.register_gateway(db, gateway)
        return RedirectResponse(f"{root_path}/admin#gateways", status_code=303)
    except Exception as ex:
        if isinstance(ex, GatewayConnectionError):
            return RedirectResponse(f"{root_path}/admin#gateways", status_code=502)
        if isinstance(ex, ValueError):
            return RedirectResponse(f"{root_path}/admin#gateways", status_code=400)
        if isinstance(ex, RuntimeError):
            return RedirectResponse(f"{root_path}/admin#gateways", status_code=500)

        return RedirectResponse(f"{root_path}/admin#gateways", status_code=500)


@admin_router.post("/gateways/{gateway_id}/edit")
async def admin_edit_gateway(
    gateway_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> RedirectResponse:
    """Edit a gateway via the admin UI.

    Expects form fields:
      - name
      - url
      - description (optional)

    Args:
        gateway_id: Gateway ID.
        request: FastAPI request containing form data.
        db: Database session.
        user: Authenticated user.

    Returns:
        A redirect response to the admin dashboard.
    """
    logger.debug(f"User {user} is editing gateway ID {gateway_id}")
    form = await request.form()
    gateway = GatewayUpdate(
        name=form["name"],
        url=form["url"],
        description=form.get("description"),
        transport=form.get("transport", "SSE"),
        auth_type=form.get("auth_type", None),
        auth_username=form.get("auth_username", None),
        auth_password=form.get("auth_password", None),
        auth_token=form.get("auth_token", None),
        auth_header_key=form.get("auth_header_key", None),
        auth_header_value=form.get("auth_header_value", None),
    )
    await gateway_service.update_gateway(db, gateway_id, gateway)

    root_path = request.scope.get("root_path", "")
    return RedirectResponse(f"{root_path}/admin#gateways", status_code=303)


@admin_router.post("/gateways/{gateway_id}/delete")
async def admin_delete_gateway(gateway_id: int, request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)) -> RedirectResponse:
    """
    Delete a gateway via the admin UI.

    This endpoint removes a gateway from the database by its ID. The deletion is
    permanent and cannot be undone. It requires authentication and logs the
    operation for auditing purposes.

    Args:
        gateway_id (int): The ID of the gateway to delete.
        request (Request): FastAPI request object (not used directly but required by the route signature).
        db (Session): Database session dependency.
        user (str): Authenticated user dependency.

    Returns:
        RedirectResponse: A redirect response to the gateways section of the admin
        dashboard with a status code of 303 (See Other).
    """
    logger.debug(f"User {user} is deleting gateway ID {gateway_id}")
    await gateway_service.delete_gateway(db, gateway_id)

    root_path = request.scope.get("root_path", "")
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
    """
    logger.debug(f"User {user} requested details for resource URI {uri}")
    resource = await resource_service.get_resource_by_uri(db, uri)
    content = await resource_service.read_resource(db, uri)
    return {"resource": resource.dict(by_alias=True), "content": content}


@admin_router.post("/resources")
async def admin_add_resource(request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)) -> RedirectResponse:
    """Add a resource via the admin UI.

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
    """
    logger.debug(f"User {user} is adding a new resource")
    form = await request.form()
    resource = ResourceCreate(
        uri=form["uri"],
        name=form["name"],
        description=form.get("description"),
        mime_type=form.get("mimeType"),
        template=form.get("template"),  # defaults to None if not provided
        content=form["content"],
    )
    await resource_service.register_resource(db, resource)

    root_path = request.scope.get("root_path", "")
    return RedirectResponse(f"{root_path}/admin#resources", status_code=303)


@admin_router.post("/resources/{uri:path}/edit")
async def admin_edit_resource(
    uri: str,
    request: Request,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> RedirectResponse:
    """Edit a resource via the admin UI.

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
        A redirect response to the admin dashboard.
    """
    logger.debug(f"User {user} is editing resource URI {uri}")
    form = await request.form()
    resource = ResourceUpdate(
        name=form["name"],
        description=form.get("description"),
        mime_type=form.get("mimeType"),
        content=form["content"],
    )
    await resource_service.update_resource(db, uri, resource)

    root_path = request.scope.get("root_path", "")
    return RedirectResponse(f"{root_path}/admin#resources", status_code=303)


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
    """
    logger.debug(f"User {user} is deleting resource URI {uri}")
    await resource_service.delete_resource(db, uri)

    root_path = request.scope.get("root_path", "")
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
    """
    logger.debug(f"User {user} is toggling resource ID {resource_id}")
    form = await request.form()
    activate = form.get("activate", "true").lower() == "true"
    try:
        await resource_service.toggle_resource_status(db, resource_id, activate)
    except Exception as e:
        logger.error(f"Error toggling resource status: {e}")

    root_path = request.scope.get("root_path", "")
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
    """
    logger.debug(f"User {user} requested details for prompt name {name}")
    prompt_details = await prompt_service.get_prompt_details(db, name)

    prompt = PromptRead.model_validate(prompt_details)
    return prompt.dict(by_alias=True)


@admin_router.post("/prompts")
async def admin_add_prompt(request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)) -> RedirectResponse:
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
    """
    logger.debug(f"User {user} is adding a new prompt")
    form = await request.form()
    args_json = form.get("arguments") or "[]"
    arguments = json.loads(args_json)
    prompt = PromptCreate(
        name=form["name"],
        description=form.get("description"),
        template=form["template"],
        arguments=arguments,
    )
    await prompt_service.register_prompt(db, prompt)

    root_path = request.scope.get("root_path", "")
    return RedirectResponse(f"{root_path}/admin#prompts", status_code=303)


@admin_router.post("/prompts/{name}/edit")
async def admin_edit_prompt(
    name: str,
    request: Request,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> RedirectResponse:
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
        A redirect response to the admin dashboard.
    """
    logger.debug(f"User {user} is editing prompt name {name}")
    form = await request.form()
    args_json = form.get("arguments") or "[]"
    arguments = json.loads(args_json)
    prompt = PromptUpdate(
        name=form["name"],
        description=form.get("description"),
        template=form["template"],
        arguments=arguments,
    )
    await prompt_service.update_prompt(db, name, prompt)

    root_path = request.scope.get("root_path", "")
    return RedirectResponse(f"{root_path}/admin#prompts", status_code=303)


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
    """
    logger.debug(f"User {user} is deleting prompt name {name}")
    await prompt_service.delete_prompt(db, name)

    root_path = request.scope.get("root_path", "")
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
    """
    logger.debug(f"User {user} is toggling prompt ID {prompt_id}")
    form = await request.form()
    activate = form.get("activate", "true").lower() == "true"
    try:
        await prompt_service.toggle_prompt_status(db, prompt_id, activate)
    except Exception as e:
        logger.error(f"Error toggling prompt status: {e}")

    root_path = request.scope.get("root_path", "")
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
        A redirect response to the admin dashboard.
    """
    logger.debug(f"User {user} is adding a new root")
    form = await request.form()
    uri = form["uri"]
    name = form.get("name")
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
    """
    logger.debug(f"User {user} is deleting root URI {uri}")
    await root_service.remove_root(uri)

    root_path = request.scope.get("root_path", "")
    return RedirectResponse(f"{root_path}/admin#roots", status_code=303)


# Metrics
MetricsDict = Dict[str, Union[ToolMetrics, ResourceMetrics, ServerMetrics, PromptMetrics]]


@admin_router.get("/metrics", response_model=MetricsDict)
async def admin_get_metrics(
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> MetricsDict:
    """
    Retrieve aggregate metrics for all entity types via the admin UI.

    This endpoint collects and returns usage metrics for tools, resources, servers,
    and prompts. The metrics are retrieved by calling the aggregate_metrics method
    on each respective service, which compiles statistics about usage patterns,
    success rates, and other relevant metrics for administrative monitoring
    and analysis purposes.

    Args:
        db (Session): Database session dependency.
        user (str): Authenticated user dependency.

    Returns:
        MetricsDict: A dictionary containing the aggregated metrics for tools,
        resources, servers, and prompts. Each value is a Pydantic model instance
        specific to the entity type.
    """
    logger.debug(f"User {user} requested aggregate metrics")
    tool_metrics = await tool_service.aggregate_metrics(db)
    resource_metrics = await resource_service.aggregate_metrics(db)
    server_metrics = await server_service.aggregate_metrics(db)
    prompt_metrics = await prompt_service.aggregate_metrics(db)

    # Return actual Pydantic model instances
    return {
        "tools": tool_metrics,
        "resources": resource_metrics,
        "servers": server_metrics,
        "prompts": prompt_metrics,
    }


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
    """
    logger.debug(f"User {user} requested to reset all metrics")
    await tool_service.reset_metrics(db)
    await resource_service.reset_metrics(db)
    await server_service.reset_metrics(db)
    await prompt_service.reset_metrics(db)
    return {"message": "All metrics reset successfully", "success": True}
