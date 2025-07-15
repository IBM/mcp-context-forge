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
import asyncio
from contextlib import asynccontextmanager
import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional, Union

# Third-Party
from fastapi import (
    APIRouter,
    Body,
    Depends,
    FastAPI,
    HTTPException,
    Request,
    status,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.background import BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError


# First-Party
from mcpgateway import __version__
from mcpgateway.admin import admin_router
from mcpgateway.bootstrap_db import main as bootstrap_db
from mcpgateway.cache import ResourceCache, SessionRegistry
from mcpgateway.config import jsonpath_modifier, settings
from mcpgateway.db import refresh_slugs_on_startup, SessionLocal
from mcpgateway.handlers.sampling import SamplingHandler
from mcpgateway.models import (
    InitializeRequest,
    InitializeResult,
    ListResourceTemplatesResult,
    LogLevel,
    ResourceContent,
    Root,
)
from mcpgateway.schemas import (
    GatewayCreate,
    GatewayRead,
    GatewayUpdate,
    JsonPathModifier,
    PromptCreate,
    PromptRead,
    PromptUpdate,
    ResourceCreate,
    ResourceRead,
    ResourceUpdate,
    ServerCreate,
    ServerRead,
    ServerUpdate,
    ToolCreate,
    ToolRead,
    ToolUpdate,
)
from mcpgateway.services.completion_service import CompletionService
from mcpgateway.services.gateway_service import GatewayConnectionError, GatewayService
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.prompt_service import (
    PromptError,
    PromptNameConflictError,
    PromptNotFoundError,
    PromptService,
)
from mcpgateway.services.resource_service import (
    ResourceError,
    ResourceNotFoundError,
    ResourceService,
    ResourceURIConflictError,
)
from mcpgateway.services.root_service import RootService
from mcpgateway.services.server_service import (
    ServerError,
    ServerNameConflictError,
    ServerNotFoundError,
    ServerService,
)
from mcpgateway.services.tool_service import (
    ToolError,
    ToolNameConflictError,
    ToolService,
)
from mcpgateway.transports.sse_transport import SSETransport
from mcpgateway.transports.streamablehttp_transport import (
    SessionManagerWrapper,
    streamable_http_auth,
)
from mcpgateway.utils.db_isready import wait_for_db_ready
from mcpgateway.utils.redis_isready import wait_for_redis_ready
from mcpgateway.utils.retry_manager import ResilientHttpClient
from mcpgateway.utils.verify_credentials import require_auth, require_auth_override
from mcpgateway.validation.jsonrpc import (
    JSONRPCError,
    validate_request,
)

from mcpgateway.utils.error_formatter import ErrorFormatter

# Import the admin routes from the new module
from mcpgateway.version import router as version_router

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger("mcpgateway")

# Configure root logger level
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

# Wait for database to be ready before creating tables
wait_for_db_ready(max_tries=int(settings.db_max_retries), interval=int(settings.db_retry_interval_ms) / 1000, sync=True)  # Converting ms to s

# Create database tables
try:
    loop = asyncio.get_running_loop()
except RuntimeError:
    asyncio.run(bootstrap_db())
else:
    loop.create_task(bootstrap_db())


# Initialize services
tool_service = ToolService()
resource_service = ResourceService()
prompt_service = PromptService()
gateway_service = GatewayService()
root_service = RootService()
completion_service = CompletionService()
sampling_handler = SamplingHandler()
server_service = ServerService()

# Initialize session manager for Streamable HTTP transport
streamable_http_session = SessionManagerWrapper()

# Wait for redis to be ready
if settings.cache_type == "redis":
    wait_for_redis_ready(redis_url=settings.redis_url, max_retries=int(settings.redis_max_retries), retry_interval_ms=int(settings.redis_retry_interval_ms), sync=True)

# Initialize session registry
session_registry = SessionRegistry(
    backend=settings.cache_type,
    redis_url=settings.redis_url if settings.cache_type == "redis" else None,
    database_url=settings.database_url if settings.cache_type == "database" else None,
    session_ttl=settings.session_ttl,
    message_ttl=settings.message_ttl,
)

# Initialize cache
resource_cache = ResourceCache(max_size=settings.resource_cache_size, ttl=settings.resource_cache_ttl)


####################
# Startup/Shutdown #
####################
@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """
    Manage the application's startup and shutdown lifecycle.

    The function initialises every core service on entry and then
    shuts them down in reverse order on exit.

    Args:
        _app (FastAPI): FastAPI app

    Yields:
        None

    Raises:
        Exception: Any unhandled error that occurs during service
            initialisation or shutdown is re-raised to the caller.
    """
    logger.info("Starting MCP Gateway services")
    try:
        await tool_service.initialize()
        await resource_service.initialize()
        await prompt_service.initialize()
        await gateway_service.initialize()
        await root_service.initialize()
        await completion_service.initialize()
        await logging_service.initialize()
        await sampling_handler.initialize()
        await resource_cache.initialize()
        await streamable_http_session.initialize()
        refresh_slugs_on_startup()

        logger.info("All services initialized successfully")
        yield
    except Exception as e:
        logger.error(f"Error during startup: {str(e)}")
        raise
    finally:
        logger.info("Shutting down MCP Gateway services")
        # await stop_streamablehttp()
        for service in [resource_cache, sampling_handler, logging_service, completion_service, root_service, gateway_service, prompt_service, resource_service, tool_service, streamable_http_session]:
            try:
                await service.shutdown()
            except Exception as e:
                logger.error(f"Error shutting down {service.__class__.__name__}: {str(e)}")
        logger.info("Shutdown complete")


# Initialize FastAPI app
app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="A FastAPI-based MCP Gateway with federation support",
    root_path=settings.app_root_path,
    lifespan=lifespan,
)


# Global exceptions handlers

@app.exception_handler(ValidationError)
async def validation_exception_handler(request: Request, exc: ValidationError):
    return JSONResponse(
        status_code=422,
        content=ErrorFormatter.format_validation_error(exc)
    )


@app.exception_handler(IntegrityError)
async def database_exception_handler(request: Request, exc: IntegrityError):
    return JSONResponse(
        status_code=409,
        content=ErrorFormatter.format_database_error(exc)
    )


class DocsAuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware to protect FastAPI's auto-generated documentation routes
    (/docs, /redoc, and /openapi.json) using Bearer token authentication.

    If a request to one of these paths is made without a valid token,
    the request is rejected with a 401 or 403 error.
    """

    async def dispatch(self, request: Request, call_next):
        """
        Intercepts incoming requests to check if they are accessing protected documentation routes.
        If so, it requires a valid Bearer token; otherwise, it allows the request to proceed.

        Args:
            request (Request): The incoming HTTP request.
            call_next (Callable): The function to call the next middleware or endpoint.

        Returns:
            Response: Either the standard route response or a 401/403 error response.
        """
        protected_paths = ["/docs", "/redoc", "/openapi.json"]

        if any(request.url.path.startswith(p) for p in protected_paths):
            try:
                token = request.headers.get("Authorization")
                cookie_token = request.cookies.get("jwt_token")

                # Simulate what Depends(require_auth) would do
                await require_auth_override(token, cookie_token)
            except HTTPException as e:
                return JSONResponse(status_code=e.status_code, content={"detail": e.detail}, headers=e.headers if e.headers else None)

        # Proceed to next middleware or route
        return await call_next(request)


class MCPPathRewriteMiddleware:
    """
    Supports requests like '/servers/<server_id>/mcp' by rewriting the path to '/mcp'.

    - Only rewrites paths ending with '/mcp' but not exactly '/mcp'.
    - Performs authentication before rewriting.
    - Passes rewritten requests to `streamable_http_session`.
    - All other requests are passed through without change.
    """

    def __init__(self, application):
        """
        Initialize the middleware with the ASGI application.

        Args:
            application (Callable): The next ASGI application in the middleware stack.
        """
        self.application = application

    async def __call__(self, scope, receive, send):
        """
        Intercept and potentially rewrite the incoming HTTP request path.

        Args:
            scope (dict): The ASGI connection scope.
            receive (Callable): Awaitable that yields events from the client.
            send (Callable): Awaitable used to send events to the client.
        """
        # Only handle HTTP requests, HTTPS uses scope["type"] == "http" in ASGI
        if scope["type"] != "http":
            await self.application(scope, receive, send)
            return

        # Call auth check first
        auth_ok = await streamable_http_auth(scope, receive, send)
        if not auth_ok:
            return

        original_path = scope.get("path", "")
        scope["modified_path"] = original_path
        if (original_path.endswith("/mcp") and original_path != "/mcp") or (original_path.endswith("/mcp/") and original_path != "/mcp/"):
            # Rewrite path so mounted app at /mcp handles it
            scope["path"] = "/mcp"
            await streamable_http_session.handle_streamable_http(scope, receive, send)
            return
        await self.application(scope, receive, send)


# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if not settings.allowed_origins else list(settings.allowed_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Type", "Content-Length"],
)


# Add custom DocsAuthMiddleware
app.add_middleware(DocsAuthMiddleware)

# Add streamable HTTP middleware for /mcp routes
app.add_middleware(MCPPathRewriteMiddleware)


# Set up Jinja2 templates and store in app state for later use
templates = Jinja2Templates(directory=str(settings.templates_dir))
app.state.templates = templates

# Create API routers
protocol_router = APIRouter(prefix="/protocol", tags=["Protocol"])
tool_router = APIRouter(prefix="/tools", tags=["Tools"])
resource_router = APIRouter(prefix="/resources", tags=["Resources"])
prompt_router = APIRouter(prefix="/prompts", tags=["Prompts"])
gateway_router = APIRouter(prefix="/gateways", tags=["Gateways"])
root_router = APIRouter(prefix="/roots", tags=["Roots"])
utility_router = APIRouter(tags=["Utilities"])
server_router = APIRouter(prefix="/servers", tags=["Servers"])
metrics_router = APIRouter(prefix="/metrics", tags=["Metrics"])

# Basic Auth setup


# Database dependency
def get_db():
    """
    Dependency function to provide a database session.

    Yields:
        Session: A SQLAlchemy session object for interacting with the database.

    Ensures:
        The database session is closed after the request completes, even in the case of an exception.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def require_api_key(api_key: str) -> None:
    """
    Validates the provided API key.

    This function checks if the provided API key matches the expected one
    based on the settings. If the validation fails, it raises an HTTPException
    with a 401 Unauthorized status.

    Args:
        api_key (str): The API key provided by the user or client.

    Raises:
        HTTPException: If the API key is invalid, a 401 Unauthorized error is raised.
    """
    if settings.auth_required:
        expected = f"{settings.basic_auth_user}:{settings.basic_auth_password}"
        if api_key != expected:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


async def invalidate_resource_cache(uri: Optional[str] = None) -> None:
    """
    Invalidates the resource cache.

    If a specific URI is provided, only that resource will be removed from the cache.
    If no URI is provided, the entire resource cache will be cleared.

    Args:
        uri (Optional[str]): The URI of the resource to invalidate from the cache. If None, the entire cache is cleared.
    """
    if uri:
        resource_cache.delete(uri)
    else:
        resource_cache.clear()


# Protocol APIs #
@protocol_router.post("/initialize")
async def initialize(request: Request, user: str = Depends(require_auth)) -> InitializeResult:
    """
    Initialize a protocol.

    This endpoint handles the initialization process of a protocol by accepting
    a JSON request body and processing it. The `require_auth` dependency ensures that
    the user is authenticated before proceeding.

    Args:
        request (Request): The incoming request object containing the JSON body.
        user (str): The authenticated user (from `require_auth` dependency).

    Returns:
        InitializeResult: The result of the initialization process.

    Raises:
        HTTPException: If the request body contains invalid JSON, a 400 Bad Request error is raised.
    """
    try:
        body = await request.json()

        logger.debug(f"Authenticated user {user} is initializing the protocol.")
        return await session_registry.handle_initialize_logic(body)

    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON in request body",
        )


@protocol_router.post("/ping")
async def ping(request: Request, user: str = Depends(require_auth)) -> JSONResponse:
    """
    Handle a ping request according to the MCP specification.

    This endpoint expects a JSON-RPC request with the method "ping" and responds
    with a JSON-RPC response containing an empty result, as required by the protocol.

    Args:
        request (Request): The incoming FastAPI request.
        user (str): The authenticated user (dependency injection).

    Returns:
        JSONResponse: A JSON-RPC response with an empty result or an error response.

    Raises:
        HTTPException: If the request method is not "ping".
    """
    try:
        body: dict = await request.json()
        if body.get("method") != "ping":
            raise HTTPException(status_code=400, detail="Invalid method")
        req_id: str = body.get("id")
        logger.debug(f"Authenticated user {user} sent ping request.")
        # Return an empty result per the MCP ping specification.
        response: dict = {"jsonrpc": "2.0", "id": req_id, "result": {}}
        return JSONResponse(content=response)
    except Exception as e:
        error_response: dict = {
            "jsonrpc": "2.0",
            "id": body.get("id") if "body" in locals() else None,
            "error": {"code": -32603, "message": "Internal error", "data": str(e)},
        }
        return JSONResponse(status_code=500, content=error_response)


@protocol_router.post("/notifications")
async def handle_notification(request: Request, user: str = Depends(require_auth)) -> None:
    """
    Handles incoming notifications from clients. Depending on the notification method,
    different actions are taken (e.g., logging initialization, cancellation, or messages).

    Args:
        request (Request): The incoming request containing the notification data.
        user (str): The authenticated user making the request.
    """
    body = await request.json()
    logger.debug(f"User {user} sent a notification")
    if body.get("method") == "notifications/initialized":
        logger.info("Client initialized")
        await logging_service.notify("Client initialized", LogLevel.INFO)
    elif body.get("method") == "notifications/cancelled":
        request_id = body.get("params", {}).get("requestId")
        logger.info(f"Request cancelled: {request_id}")
        await logging_service.notify(f"Request cancelled: {request_id}", LogLevel.INFO)
    elif body.get("method") == "notifications/message":
        params = body.get("params", {})
        await logging_service.notify(
            params.get("data"),
            LogLevel(params.get("level", "info")),
            params.get("logger"),
        )


@protocol_router.post("/completion/complete")
async def handle_completion(request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    """
    Handles the completion of tasks by processing a completion request.

    Args:
        request (Request): The incoming request with completion data.
        db (Session): The database session used to interact with the data store.
        user (str): The authenticated user making the request.

    Returns:
        The result of the completion process.
    """
    body = await request.json()
    logger.debug(f"User {user} sent a completion request")
    return await completion_service.handle_completion(db, body)


@protocol_router.post("/sampling/createMessage")
async def handle_sampling(request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    """
    Handles the creation of a new message for sampling.

    Args:
        request (Request): The incoming request with sampling data.
        db (Session): The database session used to interact with the data store.
        user (str): The authenticated user making the request.

    Returns:
        The result of the message creation process.
    """
    logger.debug(f"User {user} sent a sampling request")
    body = await request.json()
    return await sampling_handler.create_message(db, body)


###############
# Server APIs #
###############
@server_router.get("", response_model=List[ServerRead])
@server_router.get("/", response_model=List[ServerRead])
async def list_servers(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> List[ServerRead]:
    """
    Lists all servers in the system, optionally including inactive ones.

    Args:
        include_inactive (bool): Whether to include inactive servers in the response.
        db (Session): The database session used to interact with the data store.
        user (str): The authenticated user making the request.

    Returns:
        List[ServerRead]: A list of server objects.
    """
    logger.debug(f"User {user} requested server list")
    return await server_service.list_servers(db, include_inactive=include_inactive)


@server_router.get("/{server_id}", response_model=ServerRead)
async def get_server(server_id: str, db: Session = Depends(get_db), user: str = Depends(require_auth)) -> ServerRead:
    """
    Retrieves a server by its ID.

    Args:
        server_id (str): The ID of the server to retrieve.
        db (Session): The database session used to interact with the data store.
        user (str): The authenticated user making the request.

    Returns:
        ServerRead: The server object with the specified ID.

    Raises:
        HTTPException: If the server is not found.
    """
    try:
        logger.debug(f"User {user} requested server with ID {server_id}")
        return await server_service.get_server(db, server_id)
    except ServerNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@server_router.post("", response_model=ServerRead, status_code=201)
@server_router.post("/", response_model=ServerRead, status_code=201)
async def create_server(
    server: ServerCreate,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> ServerRead:
    """
    Creates a new server.

    Args:
        server (ServerCreate): The data for the new server.
        db (Session): The database session used to interact with the data store.
        user (str): The authenticated user making the request.

    Returns:
        ServerRead: The created server object.

    Raises:
        HTTPException: If there is a conflict with the server name or other errors.
    """
    try:
        logger.debug(f"User {user} is creating a new server")
        return await server_service.register_server(db, server)
    except ServerNameConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ServerError as e:
        raise HTTPException(status_code=400, detail=str(e))


@server_router.put("/{server_id}", response_model=ServerRead)
async def update_server(
    server_id: str,
    server: ServerUpdate,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> ServerRead:
    """
    Updates the information of an existing server.

    Args:
        server_id (str): The ID of the server to update.
        server (ServerUpdate): The updated server data.
        db (Session): The database session used to interact with the data store.
        user (str): The authenticated user making the request.

    Returns:
        ServerRead: The updated server object.

    Raises:
        HTTPException: If the server is not found, there is a name conflict, or other errors.
    """
    try:
        logger.debug(f"User {user} is updating server with ID {server_id}")
        return await server_service.update_server(db, server_id, server)
    except ServerNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ServerNameConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ServerError as e:
        raise HTTPException(status_code=400, detail=str(e))


@server_router.post("/{server_id}/toggle", response_model=ServerRead)
async def toggle_server_status(
    server_id: str,
    activate: bool = True,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> ServerRead:
    """
    Toggles the status of a server (activate or deactivate).

    Args:
        server_id (str): The ID of the server to toggle.
        activate (bool): Whether to activate or deactivate the server.
        db (Session): The database session used to interact with the data store.
        user (str): The authenticated user making the request.

    Returns:
        ServerRead: The server object after the status change.

    Raises:
        HTTPException: If the server is not found or there is an error.
    """
    try:
        logger.debug(f"User {user} is toggling server with ID {server_id} to {'active' if activate else 'inactive'}")
        return await server_service.toggle_server_status(db, server_id, activate)
    except ServerNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ServerError as e:
        raise HTTPException(status_code=400, detail=str(e))


@server_router.delete("/{server_id}", response_model=Dict[str, str])
async def delete_server(server_id: str, db: Session = Depends(get_db), user: str = Depends(require_auth)) -> Dict[str, str]:
    """
    Deletes a server by its ID.

    Args:
        server_id (str): The ID of the server to delete.
        db (Session): The database session used to interact with the data store.
        user (str): The authenticated user making the request.

    Returns:
        Dict[str, str]: A success message indicating the server was deleted.

    Raises:
        HTTPException: If the server is not found or there is an error.
    """
    try:
        logger.debug(f"User {user} is deleting server with ID {server_id}")
        await server_service.delete_server(db, server_id)
        return {
            "status": "success",
            "message": f"Server {server_id} deleted successfully",
        }
    except ServerNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ServerError as e:
        raise HTTPException(status_code=400, detail=str(e))


@server_router.get("/{server_id}/sse")
async def sse_endpoint(request: Request, server_id: str, user: str = Depends(require_auth)):
    """
    Establishes a Server-Sent Events (SSE) connection for real-time updates about a server.

    Args:
        request (Request): The incoming request.
        server_id (str): The ID of the server for which updates are received.
        user (str): The authenticated user making the request.

    Returns:
        The SSE response object for the established connection.

    Raises:
        HTTPException: If there is an error in establishing the SSE connection.
    """
    try:
        logger.debug(f"User {user} is establishing SSE connection for server {server_id}")
        base_url = str(request.base_url).rstrip("/")
        server_sse_url = f"{base_url}/servers/{server_id}"
        transport = SSETransport(base_url=server_sse_url)
        await transport.connect()
        await session_registry.add_session(transport.session_id, transport)
        response = await transport.create_sse_response(request)

        asyncio.create_task(session_registry.respond(server_id, user, session_id=transport.session_id, base_url=base_url))

        tasks = BackgroundTasks()
        tasks.add_task(session_registry.remove_session, transport.session_id)
        response.background = tasks
        logger.info(f"SSE connection established: {transport.session_id}")
        return response
    except Exception as e:
        logger.error(f"SSE connection error: {e}")
        raise HTTPException(status_code=500, detail="SSE connection failed")


@server_router.post("/{server_id}/message")
async def message_endpoint(request: Request, server_id: str, user: str = Depends(require_auth)):
    """
    Handles incoming messages for a specific server.

    Args:
        request (Request): The incoming message request.
        server_id (str): The ID of the server receiving the message.
        user (str): The authenticated user making the request.

    Returns:
        JSONResponse: A success status after processing the message.

    Raises:
        HTTPException: If there are errors processing the message.
    """
    try:
        logger.debug(f"User {user} sent a message to server {server_id}")
        session_id = request.query_params.get("session_id")
        if not session_id:
            logger.error("Missing session_id in message request")
            raise HTTPException(status_code=400, detail="Missing session_id")

        message = await request.json()

        await session_registry.broadcast(
            session_id=session_id,
            message=message,
        )

        return JSONResponse(content={"status": "success"}, status_code=202)
    except ValueError as e:
        logger.error(f"Invalid message format: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Message handling error: {e}")
        raise HTTPException(status_code=500, detail="Failed to process message")


@server_router.get("/{server_id}/tools", response_model=List[ToolRead])
async def server_get_tools(
    server_id: str,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> List[ToolRead]:
    """
    List tools for the server  with an option to include inactive tools.

    This endpoint retrieves a list of tools from the database, optionally including
    those that are inactive. The inactive filter helps administrators manage tools
    that have been deactivated but not deleted from the system.

    Args:
        server_id (str): ID of the server
        include_inactive (bool): Whether to include inactive tools in the results.
        db (Session): Database session dependency.
        user (str): Authenticated user dependency.

    Returns:
        List[ToolRead]: A list of tool records formatted with by_alias=True.
    """
    logger.debug(f"User: {user} has listed tools for the server_id: {server_id}")
    tools = await tool_service.list_server_tools(db, server_id=server_id, include_inactive=include_inactive)
    return [tool.model_dump(by_alias=True) for tool in tools]


@server_router.get("/{server_id}/resources", response_model=List[ResourceRead])
async def server_get_resources(
    server_id: str,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> List[ResourceRead]:
    """
    List resources for the server with an option to include inactive resources.

    This endpoint retrieves a list of resources from the database, optionally including
    those that are inactive. The inactive filter is useful for administrators who need
    to view or manage resources that have been deactivated but not deleted.

    Args:
        server_id (str): ID of the server
        include_inactive (bool): Whether to include inactive resources in the results.
        db (Session): Database session dependency.
        user (str): Authenticated user dependency.

    Returns:
        List[ResourceRead]: A list of resource records formatted with by_alias=True.
    """
    logger.debug(f"User: {user} has listed resources for the server_id: {server_id}")
    resources = await resource_service.list_server_resources(db, server_id=server_id, include_inactive=include_inactive)
    return [resource.model_dump(by_alias=True) for resource in resources]


@server_router.get("/{server_id}/prompts", response_model=List[PromptRead])
async def server_get_prompts(
    server_id: str,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> List[PromptRead]:
    """
    List prompts for the server with an option to include inactive prompts.

    This endpoint retrieves a list of prompts from the database, optionally including
    those that are inactive. The inactive filter helps administrators see and manage
    prompts that have been deactivated but not deleted from the system.

    Args:
        server_id (str): ID of the server
        include_inactive (bool): Whether to include inactive prompts in the results.
        db (Session): Database session dependency.
        user (str): Authenticated user dependency.

    Returns:
        List[PromptRead]: A list of prompt records formatted with by_alias=True.
    """
    logger.debug(f"User: {user} has listed prompts for the server_id: {server_id}")
    prompts = await prompt_service.list_server_prompts(db, server_id=server_id, include_inactive=include_inactive)
    return [prompt.model_dump(by_alias=True) for prompt in prompts]


#############
# Tool APIs #
#############
@tool_router.get("", response_model=Union[List[ToolRead], List[Dict], Dict, List])
@tool_router.get("/", response_model=Union[List[ToolRead], List[Dict], Dict, List])
async def list_tools(
    cursor: Optional[str] = None,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    apijsonpath: JsonPathModifier = Body(None),
    _: str = Depends(require_auth),
) -> Union[List[ToolRead], List[Dict], Dict]:
    """List all registered tools with pagination support.

    Args:
        cursor: Pagination cursor for fetching the next set of results
        include_inactive: Whether to include inactive tools in the results
        db: Database session
        apijsonpath: JSON path modifier to filter or transform the response
        _: Authenticated user

    Returns:
        List of tools or modified result based on jsonpath
    """

    # For now just pass the cursor parameter even if not used
    data = await tool_service.list_tools(db, cursor=cursor, include_inactive=include_inactive)

    if apijsonpath is None:
        return data

    tools_dict_list = [tool.to_dict(use_alias=True) for tool in data]

    return jsonpath_modifier(tools_dict_list, apijsonpath.jsonpath, apijsonpath.mapping)


@tool_router.post("", response_model=ToolRead)
@tool_router.post("/", response_model=ToolRead)
async def create_tool(tool: ToolCreate, db: Session = Depends(get_db), user: str = Depends(require_auth)) -> ToolRead:
    """
    Creates a new tool in the system.

    Args:
        tool (ToolCreate): The data needed to create the tool.
        db (Session): The database session dependency.
        user (str): The authenticated user making the request.

    Returns:
        ToolRead: The created tool data.

    Raises:
        HTTPException: If the tool name already exists or other validation errors occur.
    """
    try:
        logger.debug(f"User {user} is creating a new tool")
        return await tool_service.register_tool(db, tool)
    except ToolNameConflictError as e:
        if not e.enabled and e.tool_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Tool name already exists but is inactive. Consider activating it with ID: {e.tool_id}",
            )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ToolError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@tool_router.get("/{tool_id}", response_model=Union[ToolRead, Dict])
async def get_tool(
    tool_id: str,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
    apijsonpath: JsonPathModifier = Body(None),
) -> Union[ToolRead, Dict]:
    """
    Retrieve a tool by ID, optionally applying a JSONPath post-filter.

    Args:
        tool_id: The numeric ID of the tool.
        db:     Active SQLAlchemy session (dependency).
        user:   Authenticated username (dependency).
        apijsonpath: Optional JSON-Path modifier supplied in the body.

    Returns:
        The raw ``ToolRead`` model **or** a JSON-transformed ``dict`` if
        a JSONPath filter/mapping was supplied.

    Raises:
        HTTPException: If the tool does not exist or the transformation fails.
    """
    try:
        logger.debug(f"User {user} is retrieving tool with ID {tool_id}")
        data = await tool_service.get_tool(db, tool_id)
        if apijsonpath is None:
            return data

        data_dict = data.to_dict(use_alias=True)

        return jsonpath_modifier(data_dict, apijsonpath.jsonpath, apijsonpath.mapping)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@tool_router.put("/{tool_id}", response_model=ToolRead)
async def update_tool(
    tool_id: str,
    tool: ToolUpdate,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> ToolRead:
    """
    Updates an existing tool with new data.

    Args:
        tool_id (str): The ID of the tool to update.
        tool (ToolUpdate): The updated tool information.
        db (Session): The database session dependency.
        user (str): The authenticated user making the request.

    Returns:
        ToolRead: The updated tool data.

    Raises:
        HTTPException: If an error occurs during the update.
    """
    try:
        logger.debug(f"User {user} is updating tool with ID {tool_id}")
        return await tool_service.update_tool(db, tool_id, tool)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@tool_router.delete("/{tool_id}")
async def delete_tool(tool_id: str, db: Session = Depends(get_db), user: str = Depends(require_auth)) -> Dict[str, str]:
    """
    Permanently deletes a tool by ID.

    Args:
        tool_id (str): The ID of the tool to delete.
        db (Session): The database session dependency.
        user (str): The authenticated user making the request.

    Returns:
        Dict[str, str]: A confirmation message upon successful deletion.

    Raises:
        HTTPException: If an error occurs during deletion.
    """
    try:
        logger.debug(f"User {user} is deleting tool with ID {tool_id}")
        await tool_service.delete_tool(db, tool_id)
        return {"status": "success", "message": f"Tool {tool_id} permanently deleted"}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@tool_router.post("/{tool_id}/toggle")
async def toggle_tool_status(
    tool_id: str,
    activate: bool = True,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> Dict[str, Any]:
    """
    Activates or deactivates a tool.

    Args:
        tool_id (str): The ID of the tool to toggle.
        activate (bool): Whether to activate (`True`) or deactivate (`False`) the tool.
        db (Session): The database session dependency.
        user (str): The authenticated user making the request.

    Returns:
        Dict[str, Any]: The status, message, and updated tool data.

    Raises:
        HTTPException: If an error occurs during status toggling.
    """
    try:
        logger.debug(f"User {user} is toggling tool with ID {tool_id} to {'active' if activate else 'inactive'}")
        tool = await tool_service.toggle_tool_status(db, tool_id, activate, reachable=activate)
        return {
            "status": "success",
            "message": f"Tool {tool_id} {'activated' if activate else 'deactivated'}",
            "tool": tool.model_dump(),
        }
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


#################
# Resource APIs #
#################
# --- Resource templates endpoint - MUST come before variable paths ---
@resource_router.get("/templates/list", response_model=ListResourceTemplatesResult)
async def list_resource_templates(
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> ListResourceTemplatesResult:
    """
    List all available resource templates.

    Args:
        db (Session): Database session.
        user (str): Authenticated user.

    Returns:
        ListResourceTemplatesResult: A paginated list of resource templates.
    """
    logger.debug(f"User {user} requested resource templates")
    resource_templates = await resource_service.list_resource_templates(db)
    # For simplicity, we're not implementing real pagination here
    return ListResourceTemplatesResult(_meta={}, resource_templates=resource_templates, next_cursor=None)  # No pagination for now


@resource_router.post("/{resource_id}/toggle")
async def toggle_resource_status(
    resource_id: int,
    activate: bool = True,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> Dict[str, Any]:
    """
    Activate or deactivate a resource by its ID.

    Args:
        resource_id (int): The ID of the resource.
        activate (bool): True to activate, False to deactivate.
        db (Session): Database session.
        user (str): Authenticated user.

    Returns:
        Dict[str, Any]: Status message and updated resource data.

    Raises:
        HTTPException: If toggling fails.
    """
    logger.debug(f"User {user} is toggling resource with ID {resource_id} to {'active' if activate else 'inactive'}")
    try:
        resource = await resource_service.toggle_resource_status(db, resource_id, activate)
        return {
            "status": "success",
            "message": f"Resource {resource_id} {'activated' if activate else 'deactivated'}",
            "resource": resource.model_dump(),
        }
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@resource_router.get("", response_model=List[ResourceRead])
@resource_router.get("/", response_model=List[ResourceRead])
async def list_resources(
    cursor: Optional[str] = None,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> List[ResourceRead]:
    """
    Retrieve a list of resources.

    Args:
        cursor (Optional[str]): Optional cursor for pagination.
        include_inactive (bool): Whether to include inactive resources.
        db (Session): Database session.
        user (str): Authenticated user.

    Returns:
        List[ResourceRead]: List of resources.
    """
    logger.debug(f"User {user} requested resource list with cursor {cursor} and include_inactive={include_inactive}")
    if cached := resource_cache.get("resource_list"):
        return cached
    # Pass the cursor parameter
    resources = await resource_service.list_resources(db, include_inactive=include_inactive)
    resource_cache.set("resource_list", resources)
    return resources


@resource_router.post("", response_model=ResourceRead)
@resource_router.post("/", response_model=ResourceRead)
async def create_resource(
    resource: ResourceCreate,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> ResourceRead:
    """
    Create a new resource.

    Args:
        resource (ResourceCreate): Data for the new resource.
        db (Session): Database session.
        user (str): Authenticated user.

    Returns:
        ResourceRead: The created resource.

    Raises:
        HTTPException: On conflict or validation errors.
    """
    logger.debug(f"User {user} is creating a new resource")
    try:
        result = await resource_service.register_resource(db, resource)
        return result
    except ResourceURIConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ResourceError as e:
        raise HTTPException(status_code=400, detail=str(e))


@resource_router.get("/{uri:path}")
async def read_resource(uri: str, db: Session = Depends(get_db), user: str = Depends(require_auth)) -> ResourceContent:
    """
    Read a resource by its URI.

    Args:
        uri (str): URI of the resource.
        db (Session): Database session.
        user (str): Authenticated user.

    Returns:
        ResourceContent: The content of the resource.

    Raises:
        HTTPException: If the resource cannot be found or read.
    """
    logger.debug(f"User {user} requested resource with URI {uri}")
    if cached := resource_cache.get(uri):
        return cached
    try:
        content: ResourceContent = await resource_service.read_resource(db, uri)
    except (ResourceNotFoundError, ResourceError) as exc:
        # Translate to FastAPI HTTP error
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    resource_cache.set(uri, content)
    return content


@resource_router.put("/{uri:path}", response_model=ResourceRead)
async def update_resource(
    uri: str,
    resource: ResourceUpdate,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> ResourceRead:
    """
    Update a resource identified by its URI.

    Args:
        uri (str): URI of the resource.
        resource (ResourceUpdate): New resource data.
        db (Session): Database session.
        user (str): Authenticated user.

    Returns:
        ResourceRead: The updated resource.

    Raises:
        HTTPException: If the resource is not found or update fails.
    """
    try:
        logger.debug(f"User {user} is updating resource with URI {uri}")
        result = await resource_service.update_resource(db, uri, resource)
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    await invalidate_resource_cache(uri)
    return result


@resource_router.delete("/{uri:path}")
async def delete_resource(uri: str, db: Session = Depends(get_db), user: str = Depends(require_auth)) -> Dict[str, str]:
    """
    Delete a resource by its URI.

    Args:
        uri (str): URI of the resource to delete.
        db (Session): Database session.
        user (str): Authenticated user.

    Returns:
        Dict[str, str]: Status message indicating deletion success.

    Raises:
        HTTPException: If the resource is not found or deletion fails.
    """
    try:
        logger.debug(f"User {user} is deleting resource with URI {uri}")
        await resource_service.delete_resource(db, uri)
        await invalidate_resource_cache(uri)
        return {"status": "success", "message": f"Resource {uri} deleted"}
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ResourceError as e:
        raise HTTPException(status_code=400, detail=str(e))


@resource_router.post("/subscribe/{uri:path}")
async def subscribe_resource(uri: str, user: str = Depends(require_auth)) -> StreamingResponse:
    """
    Subscribe to server-sent events (SSE) for a specific resource.

    Args:
        uri (str): URI of the resource to subscribe to.
        user (str): Authenticated user.

    Returns:
        StreamingResponse: A streaming response with event updates.
    """
    logger.debug(f"User {user} is subscribing to resource with URI {uri}")
    return StreamingResponse(resource_service.subscribe_events(uri), media_type="text/event-stream")


###############
# Prompt APIs #
###############
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
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> List[PromptRead]:
    """
    List prompts with optional pagination and inclusion of inactive items.

    Args:
        cursor: Cursor for pagination.
        include_inactive: Include inactive prompts.
        db: Database session.
        user: Authenticated user.

    Returns:
        List of prompt records.
    """
    logger.debug(f"User: {user} requested prompt list with include_inactive={include_inactive}, cursor={cursor}")
    return await prompt_service.list_prompts(db, cursor=cursor, include_inactive=include_inactive)


@prompt_router.post("", response_model=PromptRead)
@prompt_router.post("/", response_model=PromptRead)
async def create_prompt(
    prompt: PromptCreate,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> PromptRead:
    """
    Create a new prompt.

    Args:
        prompt (PromptCreate): Payload describing the prompt to create.
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
        return await prompt_service.register_prompt(db, prompt)
    except PromptNameConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except PromptError as e:
        raise HTTPException(status_code=400, detail=str(e))


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
    """
    logger.debug(f"User: {user} requested prompt: {name} with args={args}")
    return await prompt_service.get_prompt(db, name, args)


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
    """
    logger.debug(f"User: {user} requested prompt: {name} with no arguments")
    return await prompt_service.get_prompt(db, name, {})


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
    logger.debug(f"User: {user} requested to update prompt: {name} with data={prompt}")
    try:
        return await prompt_service.update_prompt(db, name, prompt)
    except PromptNameConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except PromptError as e:
        raise HTTPException(status_code=400, detail=str(e))


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
    """
    logger.debug(f"User: {user} requested deletion of prompt {name}")
    try:
        await prompt_service.delete_prompt(db, name)
        return {"status": "success", "message": f"Prompt {name} deleted"}
    except PromptNotFoundError as e:
        return {"status": "error", "message": str(e)}
    except PromptError as e:
        return {"status": "error", "message": str(e)}


################
# Gateway APIs #
################
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
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
) -> GatewayRead:
    """
    Register a new gateway.

    Args:
        gateway: Gateway creation data.
        db: Database session.
        user: Authenticated user.

    Returns:
        Created gateway.
    """
    logger.debug(f"User '{user}' requested to register gateway: {gateway}")
    try:
        return await gateway_service.register_gateway(db, gateway)
    except Exception as ex:
        if isinstance(ex, GatewayConnectionError):
            return JSONResponse(content={"message": "Unable to connect to gateway"}, status_code=502)
        if isinstance(ex, ValueError):
            return JSONResponse(content={"message": "Unable to process input"}, status_code=400)
        if isinstance(ex, RuntimeError):
            return JSONResponse(content={"message": "Error during execution"}, status_code=500)
        return JSONResponse(content={"message": "Unexpected error"}, status_code=500)


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
    return await gateway_service.update_gateway(db, gateway_id, gateway)


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


##############
# Root APIs  #
##############
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


##################
# Utility Routes #
##################
@utility_router.post("/rpc/")
@utility_router.post("/rpc")
async def handle_rpc(request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)):  # revert this back
    """Handle RPC requests.

    Args:
        request (Request): The incoming FastAPI request.
        db (Session): Database session.
        user (str): The authenticated user.

    Returns:
        Response with the RPC result or error.
    """
    try:
        logger.debug(f"User {user} made an RPC request")
        body = await request.json()
        validate_request(body)
        method = body["method"]
        # rpc_id = body.get("id")
        params = body.get("params", {})
        cursor = params.get("cursor")  # Extract cursor parameter

        if method == "tools/list":
            tools = await tool_service.list_tools(db, cursor=cursor)
            result = [t.model_dump(by_alias=True, exclude_none=True) for t in tools]
        elif method == "list_tools":  # Legacy endpoint
            tools = await tool_service.list_tools(db, cursor=cursor)
            result = [t.model_dump(by_alias=True, exclude_none=True) for t in tools]
        elif method == "initialize":
            result = initialize(
                InitializeRequest(
                    protocol_version=params.get("protocolVersion") or params.get("protocol_version", ""),
                    capabilities=params.get("capabilities", {}),
                    client_info=params.get("clientInfo") or params.get("client_info", {}),
                ),
                user,
            ).model_dump(by_alias=True, exclude_none=True)
        elif method == "list_gateways":
            gateways = await gateway_service.list_gateways(db, include_inactive=False)
            result = [g.model_dump(by_alias=True, exclude_none=True) for g in gateways]
        elif method == "list_roots":
            roots = await root_service.list_roots()
            result = [r.model_dump(by_alias=True, exclude_none=True) for r in roots]
        elif method == "resources/list":
            resources = await resource_service.list_resources(db)
            result = [r.model_dump(by_alias=True, exclude_none=True) for r in resources]
        elif method == "prompts/list":
            prompts = await prompt_service.list_prompts(db, cursor=cursor)
            result = [p.model_dump(by_alias=True, exclude_none=True) for p in prompts]
        elif method == "prompts/get":
            name = params.get("name")
            arguments = params.get("arguments", {})
            if not name:
                raise JSONRPCError(-32602, "Missing prompt name in parameters", params)
            result = await prompt_service.get_prompt(db, name, arguments)
            if hasattr(result, "model_dump"):
                result = result.model_dump(by_alias=True, exclude_none=True)
        elif method == "ping":
            # Per the MCP spec, a ping returns an empty result.
            result = {}
        else:
            try:
                result = await tool_service.invoke_tool(db=db, name=method, arguments=params)
                if hasattr(result, "model_dump"):
                    result = result.model_dump(by_alias=True, exclude_none=True)
            except ValueError:
                result = await gateway_service.forward_request(db, method, params)
                if hasattr(result, "model_dump"):
                    result = result.model_dump(by_alias=True, exclude_none=True)

        response = result
        return response

    except JSONRPCError as e:
        return e.to_dict()
    except Exception as e:
        logger.error(f"RPC error: {str(e)}")
        return {
            "jsonrpc": "2.0",
            "error": {"code": -32000, "message": "Internal error", "data": str(e)},
            "id": body.get("id") if "body" in locals() else None,
        }


@utility_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    Handle WebSocket connection to relay JSON-RPC requests to the internal RPC endpoint.

    Accepts incoming text messages, parses them as JSON-RPC requests, sends them to /rpc,
    and returns the result to the client over the same WebSocket.

    Args:
        websocket: The WebSocket connection instance.
    """
    try:
        await websocket.accept()
        while True:
            try:
                data = await websocket.receive_text()
                client_args = {"timeout": settings.federation_timeout, "verify": not settings.skip_ssl_verify}
                async with ResilientHttpClient(client_args=client_args) as client:
                    response = await client.post(
                        f"http://localhost:{settings.port}/rpc",
                        json=json.loads(data),
                        headers={"Content-Type": "application/json"},
                    )
                    await websocket.send_text(response.text)
            except JSONRPCError as e:
                await websocket.send_text(json.dumps(e.to_dict()))
            except json.JSONDecodeError:
                await websocket.send_text(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "error": {"code": -32700, "message": "Parse error"},
                            "id": None,
                        }
                    )
                )
            except Exception as e:
                logger.error(f"WebSocket error: {str(e)}")
                await websocket.close(code=1011)
                break
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket connection error: {str(e)}")
        try:
            await websocket.close(code=1011)
        except Exception as er:
            logger.error(f"Error while closing WebSocket: {er}")


@utility_router.get("/sse")
async def utility_sse_endpoint(request: Request, user: str = Depends(require_auth)):
    """
    Establish a Server-Sent Events (SSE) connection for real-time updates.

    Args:
        request (Request): The incoming HTTP request.
        user (str): Authenticated username.

    Returns:
        StreamingResponse: A streaming response that keeps the connection
        open and pushes events to the client.

    Raises:
        HTTPException: Returned with **500 Internal Server Error** if the SSE connection cannot be established or an unexpected error occurs while creating the transport.
    """
    try:
        logger.debug("User %s requested SSE connection", user)
        base_url = str(request.base_url).rstrip("/")
        transport = SSETransport(base_url=base_url)
        await transport.connect()
        await session_registry.add_session(transport.session_id, transport)

        asyncio.create_task(session_registry.respond(None, user, session_id=transport.session_id, base_url=base_url))

        response = await transport.create_sse_response(request)
        tasks = BackgroundTasks()
        tasks.add_task(session_registry.remove_session, transport.session_id)
        response.background = tasks
        logger.info("SSE connection established: %s", transport.session_id)
        return response
    except Exception as e:
        logger.error("SSE connection error: %s", e)
        raise HTTPException(status_code=500, detail="SSE connection failed")


@utility_router.post("/message")
async def utility_message_endpoint(request: Request, user: str = Depends(require_auth)):
    """
    Handle a JSON-RPC message directed to a specific SSE session.

    Args:
        request (Request): Incoming request containing the JSON-RPC payload.
        user (str): Authenticated user.

    Returns:
        JSONResponse: ``{"status": "success"}`` with HTTP 202 on success.

    Raises:
        HTTPException: * **400 Bad Request** - ``session_id`` query parameter is missing or the payload cannot be parsed as JSON.
            * **500 Internal Server Error** - An unexpected error occurs while broadcasting the message.
    """
    try:
        logger.debug("User %s sent a message to SSE session", user)

        session_id = request.query_params.get("session_id")
        if not session_id:
            logger.error("Missing session_id in message request")
            raise HTTPException(status_code=400, detail="Missing session_id")

        message = await request.json()

        await session_registry.broadcast(
            session_id=session_id,
            message=message,
        )

        return JSONResponse(content={"status": "success"}, status_code=202)

    except ValueError as e:
        logger.error("Invalid message format: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Message handling error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to process message")


@utility_router.post("/logging/setLevel")
async def set_log_level(request: Request, user: str = Depends(require_auth)) -> None:
    """
    Update the server's log level at runtime.

    Args:
        request: HTTP request with log level JSON body.
        user: Authenticated user.

    Returns:
        None
    """
    logger.debug(f"User {user} requested to set log level")
    body = await request.json()
    level = LogLevel(body["level"])
    await logging_service.set_level(level)
    return None


####################
# Metrics          #
####################
@metrics_router.get("", response_model=dict)
async def get_metrics(db: Session = Depends(get_db), user: str = Depends(require_auth)) -> dict:
    """
    Retrieve aggregated metrics for all entity types (Tools, Resources, Servers, Prompts).

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
    return {
        "tools": tool_metrics,
        "resources": resource_metrics,
        "servers": server_metrics,
        "prompts": prompt_metrics,
    }


@metrics_router.post("/reset", response_model=dict)
async def reset_metrics(entity: Optional[str] = None, entity_id: Optional[int] = None, db: Session = Depends(get_db), user: str = Depends(require_auth)) -> dict:
    """
    Reset metrics for a specific entity type and optionally a specific entity ID,
    or perform a global reset if no entity is specified.

    Args:
        entity: One of "tool", "resource", "server", "prompt", or None for global reset.
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
    elif entity.lower() == "tool":
        await tool_service.reset_metrics(db, entity_id)
    elif entity.lower() == "resource":
        await resource_service.reset_metrics(db)
    elif entity.lower() == "server":
        await server_service.reset_metrics(db)
    elif entity.lower() == "prompt":
        await prompt_service.reset_metrics(db)
    else:
        raise HTTPException(status_code=400, detail="Invalid entity type for metrics reset")
    return {"status": "success", "message": f"Metrics reset for {entity if entity else 'all entities'}"}


####################
# Healthcheck      #
####################
@app.get("/health")
async def healthcheck(db: Session = Depends(get_db)):
    """
    Perform a basic health check to verify database connectivity.

    Args:
        db: SQLAlchemy session dependency.

    Returns:
        A dictionary with the health status and optional error message.
    """
    try:
        # Execute the query using text() for an explicit textual SQL expression.
        db.execute(text("SELECT 1"))
    except Exception as e:
        error_message = f"Database connection error: {str(e)}"
        logger.error(error_message)
        return {"status": "unhealthy", "error": error_message}
    return {"status": "healthy"}


@app.get("/ready")
async def readiness_check(db: Session = Depends(get_db)):
    """
    Perform a readiness check to verify if the application is ready to receive traffic.

    Args:
        db: SQLAlchemy session dependency.

    Returns:
        JSONResponse with status 200 if ready, 503 if not.
    """
    try:
        # Run the blocking DB check in a thread to avoid blocking the event loop
        await asyncio.to_thread(db.execute, text("SELECT 1"))
        return JSONResponse(content={"status": "ready"}, status_code=200)
    except Exception as e:
        error_message = f"Readiness check failed: {str(e)}"
        logger.error(error_message)
        return JSONResponse(content={"status": "not ready", "error": error_message}, status_code=503)


# Mount static files
# app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")

# Include routers
app.include_router(version_router)
app.include_router(protocol_router)
app.include_router(tool_router)
app.include_router(resource_router)
app.include_router(prompt_router)
app.include_router(gateway_router)
app.include_router(root_router)
app.include_router(utility_router)
app.include_router(server_router)
app.include_router(metrics_router)


# Feature flags for admin UI and API
UI_ENABLED = settings.mcpgateway_ui_enabled
ADMIN_API_ENABLED = settings.mcpgateway_admin_api_enabled
logger.info(f"Admin UI enabled: {UI_ENABLED}")
logger.info(f"Admin API enabled: {ADMIN_API_ENABLED}")

# Conditional UI and admin API handling
if ADMIN_API_ENABLED:
    logger.info("Including admin_router - Admin API enabled")
    app.include_router(admin_router)  # Admin routes imported from admin.py
else:
    logger.warning("Admin API routes not mounted - Admin API disabled via MCPGATEWAY_ADMIN_API_ENABLED=False")

# Streamable http Mount
app.mount("/mcp", app=streamable_http_session.handle_streamable_http)

# Conditional static files mounting and root redirect
if UI_ENABLED:
    # Mount static files for UI
    logger.info("Mounting static files - UI enabled")
    try:
        app.mount(
            "/static",
            StaticFiles(directory=str(settings.static_dir)),
            name="static",
        )
        logger.info("Static assets served from %s", settings.static_dir)
    except RuntimeError as exc:
        logger.warning(
            "Static dir %s not found - Admin UI disabled (%s)",
            settings.static_dir,
            exc,
        )

    # Redirect root path to admin UI
    @app.get("/")
    async def root_redirect(request: Request):
        """
        Redirects the root path ("/") to "/admin".

        Logs a debug message before redirecting.

        Args:
            request (Request): The incoming HTTP request (used only to build the
                target URL via :pymeth:`starlette.requests.Request.url_for`).

        Returns:
            RedirectResponse: Redirects to /admin.
        """
        logger.debug("Redirecting root path to /admin")
        root_path = request.scope.get("root_path", "")
        return RedirectResponse(f"{root_path}/admin", status_code=303)
        # return RedirectResponse(request.url_for("admin_home"))

else:
    # If UI is disabled, provide API info at root
    logger.warning("Static files not mounted - UI disabled via MCPGATEWAY_UI_ENABLED=False")

    @app.get("/")
    async def root_info():
        """
        Returns basic API information at the root path.

        Logs an info message indicating UI is disabled and provides details
        about the app, including its name, version, and whether the UI and
        admin API are enabled.

        Returns:
            dict: API info with app name, version, and UI/admin API status.
        """
        logger.info("UI disabled, serving API info at root path")
        return {"name": settings.app_name, "version": __version__, "description": f"{settings.app_name} API - UI is disabled", "ui_enabled": False, "admin_api_enabled": ADMIN_API_ENABLED}


# Expose some endpoints at the root level as well
app.post("/initialize")(initialize)
app.post("/notifications")(handle_notification)
