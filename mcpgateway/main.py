# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/main.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

MCP Gateway - Main FastAPI Application.

This module creates and configures the core FastAPI application for the Model Context Protocol (MCP) Gateway.
It serves as the entry point for handling all HTTP, WebSocket, and SSE traffic with comprehensive service management.

Core Functions:
- create_app() -> FastAPI: Creates configured FastAPI application instance
- configure_middleware(app: FastAPI) -> None: Sets up CORS, auth, and proxy middleware
- configure_exception_handlers(app: FastAPI) -> None: Registers global error handlers
- configure_routes(app: FastAPI) -> None: Mounts API routers and endpoints
- configure_ui(app: FastAPI) -> None: Sets up static files and admin interface
- configure_health_endpoints(app: FastAPI) -> None: Adds health check endpoints
- lifespan(app: FastAPI) -> AsyncIterator[None]: Manages service lifecycle

Features and Responsibilities:
- Service orchestration with dependency injection pattern
- Multi-transport protocol support (HTTP, WebSocket, SSE, stdio)
- Authentication via JWT Bearer tokens and HTTP Basic Auth
- CORS configuration with configurable origins
- Admin UI with HTMX-based frontend (optional)
- Database connection management with health checks
- Plugin system integration with lifecycle management
- Comprehensive error handling and logging
- Redis-backed caching and session management
- Graceful startup/shutdown with proper resource cleanup

Configuration:
- Uses environment variables and .env files via settings
- Supports SQLite and PostgreSQL databases
- Configurable middleware stack and security settings
- Feature flags for UI and admin API enablement

Exports:
- app: FastAPI application instance for WSGI servers (Gunicorn)
- create_app(): Factory function for programmatic use

Dependencies:
- FastAPI for web framework
- SQLAlchemy for database operations
- Pydantic for data validation
- Uvicorn/Gunicorn for ASGI/WSGI serving
"""

# Standard
import asyncio
from contextlib import asynccontextmanager
import logging
from typing import AsyncIterator

# Third-Party
from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    HTTPException,
    Request,
    status,
)
from fastapi.exception_handlers import request_validation_exception_handler as fastapi_default_validation_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

# First-Party
from mcpgateway import __version__
from mcpgateway.admin import admin_router
from mcpgateway.bootstrap_db import main as bootstrap_db
from mcpgateway.config import settings
from mcpgateway.db import get_db, refresh_slugs_on_startup

# Import dependency injection functions
from mcpgateway.dependencies import (
    get_a2a_agent_service,
    get_completion_service,
    get_cors_origins,
    get_export_service,
    get_gateway_service,
    get_import_service,
    get_logging_service,
    get_prompt_service,
    get_resource_cache,
    get_resource_service,
    get_root_service,
    get_sampling_handler,
    get_server_service,
    get_streamable_http_session,
    get_tag_service,
    get_tool_service,
)

# middleware imports
from mcpgateway.middleware.docs_auth_middleware import DocsAuthMiddleware
from mcpgateway.middleware.experimental_access import ExperimentalAccessMiddleware
from mcpgateway.middleware.legacy_deprecation_middleware import LegacyDeprecationMiddleware
from mcpgateway.middleware.mcp_path_rewrite_middleware import MCPPathRewriteMiddleware
from mcpgateway.middleware.security_headers import SecurityHeadersMiddleware
from mcpgateway.observability import init_telemetry
from mcpgateway.plugins.framework import PluginManager
from mcpgateway.routers.current import handle_notification, handle_rpc, initialize

# from v1 routes
from mcpgateway.routers.setup_routes import (
    setup_experimental_routes,
    setup_legacy_deprecation_routes,
    setup_v1_routes,
)
from mcpgateway.utils.db_isready import wait_for_db_ready
from mcpgateway.utils.error_formatter import ErrorFormatter
from mcpgateway.utils.passthrough_headers import set_global_passthrough_headers
from mcpgateway.utils.redis_isready import wait_for_redis_ready

# Import the admin routes from the new module
from mcpgateway.version import router as version_router

# Initialize logging service first
logging_service = get_logging_service()
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

# Initialize plugin manager as a singleton.
plugin_manager: PluginManager | None = PluginManager(settings.plugin_config_file) if settings.plugins_enabled else None

# Get service instances via dependency injection
tool_service = get_tool_service()
resource_service = get_resource_service()
prompt_service = get_prompt_service()
gateway_service = get_gateway_service()
root_service = get_root_service()
completion_service = get_completion_service()
sampling_handler = get_sampling_handler()
resource_cache = get_resource_cache()
server_service = get_server_service()
tag_service = get_tag_service()
export_service = get_export_service()
import_service = get_import_service()

# Initialize A2A service only if A2A features are enabled
a2a_service = get_a2a_agent_service() if settings.mcpgateway_a2a_enabled else None

# Initialize session manager for Streamable HTTP transport
streamable_http_session = get_streamable_http_session()

# Wait for redis to be ready
if settings.cache_type == "redis":
    wait_for_redis_ready(redis_url=settings.redis_url, max_retries=int(settings.redis_max_retries), retry_interval_ms=int(settings.redis_retry_interval_ms), sync=True)

# Set up Jinja2 templates
templates = Jinja2Templates(directory=str(settings.templates_dir))


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
    # Initialize logging service FIRST to ensure all logging goes to dual output
    await logging_service.initialize()
    logger.info("Starting MCP Gateway services")

    # Initialize observability (Phoenix tracing)
    init_telemetry()
    logger.info("Observability initialized")

    try:
        if plugin_manager:
            await plugin_manager.initialize()
            logger.info(f"Plugin manager initialized with {plugin_manager.plugin_count} plugins")

        if settings.enable_header_passthrough:
            db_gen = get_db()
            db = next(db_gen)  # pylint: disable=stop-iteration-return
            try:
                await set_global_passthrough_headers(db)
            finally:
                db.close()

        await tool_service.initialize()
        await resource_service.initialize()
        await prompt_service.initialize()
        await gateway_service.initialize()
        await root_service.initialize()
        await completion_service.initialize()
        await sampling_handler.initialize()
        await export_service.initialize()
        await import_service.initialize()
        if a2a_service:
            await a2a_service.initialize()
        await resource_cache.initialize()
        await streamable_http_session.initialize()
        refresh_slugs_on_startup()

        logger.info("All services initialized successfully")

        # Reconfigure uvicorn loggers after startup to capture access logs in dual output
        logging_service.configure_uvicorn_after_startup()

        yield
    except Exception as e:
        logger.error(f"Error during startup: {str(e)}")
        raise
    finally:
        # Shutdown plugin manager
        if plugin_manager:
            try:
                await plugin_manager.shutdown()
                logger.info("Plugin manager shutdown complete")
            except Exception as e:
                logger.error(f"Error shutting down plugin manager: {str(e)}")
        logger.info("Shutting down MCP Gateway services")
        # await stop_streamablehttp()
        # Build service list conditionally
        services_to_shutdown = [
            resource_cache,
            sampling_handler,
            import_service,
            export_service,
            logging_service,
            completion_service,
            root_service,
            gateway_service,
            prompt_service,
            resource_service,
            tool_service,
            streamable_http_session,
        ]

        if a2a_service:
            services_to_shutdown.insert(4, a2a_service)  # Insert after export_service

        for service in services_to_shutdown:
            try:
                await service.shutdown()
            except Exception as e:
                logger.error(f"Error shutting down {service.__class__.__name__}: {str(e)}")
        logger.info("Shutdown complete")


def require_api_key(api_key: str) -> None:
    """Validates the provided API key.

    This function checks if the provided API key matches the expected one
    based on the settings. If the validation fails, it raises an HTTPException
    with a 401 Unauthorized status.

    Args:
        api_key (str): The API key provided by the user or client.

    Raises:
        HTTPException: If the API key is invalid, a 401 Unauthorized error is raised.

    Examples:
        >>> from mcpgateway.config import settings
        >>> settings.auth_required = True
        >>> settings.basic_auth_user = "admin"
        >>> settings.basic_auth_password = "secret"
        >>>
        >>> # Valid API key
        >>> require_api_key("admin:secret")  # Should not raise
        >>>
        >>> # Invalid API key
        >>> try:
        ...     require_api_key("wrong:key")
        ... except HTTPException as e:
        ...     e.status_code
        401
    """
    if settings.auth_required:
        expected = f"{settings.basic_auth_user}:{settings.basic_auth_password}"
        if api_key != expected:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


# Create the FastAPI application instance
def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        FastAPI: Configured FastAPI application instance
    """
    # Initialize FastAPI app
    fastapi_app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description="A FastAPI-based MCP Gateway with federation support",
        root_path=settings.app_root_path,
        lifespan=lifespan,
    )

    # Configure middleware (order matters - last added is executed first)
    configure_middleware(fastapi_app)

    # Configure exception handlers
    configure_exception_handlers(fastapi_app)

    # Configure routes
    configure_routes(fastapi_app)

    # Configure static files and UI
    configure_ui(fastapi_app)

    return fastapi_app


def configure_middleware(fastapi_app: FastAPI) -> None:
    """Configure application middleware stack.

    Sets up middleware in reverse order (last added executes first):
    1. CORS - Cross-origin resource sharing with configurable origins
    2. ExperimentalAccess - Control access to experimental API features
    3. LegacyDeprecation - Handle legacy API deprecation warnings
    4. DocsAuth - Authentication protection for API documentation
    5. MCPPathRewrite - Path rewriting for MCP protocol routes
    6. ProxyHeaders - Trust proxy headers for correct client IP detection

    Args:
        fastapi_app: FastAPI application instance to configure

    """
    # Trust all proxies (or lock down with a list of host patterns)
    fastapi_app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

    # Add streamable HTTP middleware for /mcp routes
    fastapi_app.add_middleware(MCPPathRewriteMiddleware)

    # Add custom DocsAuthMiddleware
    fastapi_app.add_middleware(DocsAuthMiddleware)

    # Add legacy deprecation middleware
    fastapi_app.add_middleware(LegacyDeprecationMiddleware)

    # Add experimental access middleware
    fastapi_app.add_middleware(ExperimentalAccessMiddleware)

    # Add Security Headers Middleware
    fastapi_app.add_middleware(SecurityHeadersMiddleware)

    default_expose = {"Content-Type", "Content-Length", "X-Request-ID"}
    configured_expose = set(getattr(settings, "cors_expose_headers", []))
    expose_headers = sorted(default_expose | configured_expose)

    # Configure CORS with environment-aware origins
    cors_origins = get_cors_origins()

    # Ensure we never use wildcard in production
    if settings.environment == "production" and not cors_origins:
        logger.warning("No CORS origins configured for production environment. CORS will be disabled.")
        cors_origins = []

    # Configure CORS
    fastapi_app.add_middleware(CORSMiddleware, allow_origins=cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"], expose_headers=expose_headers)


def configure_exception_handlers(fastapi_app: FastAPI) -> None:
    """Configure global exception handlers for consistent error responses.

    Registers handlers for:
    - ValidationError: Pydantic validation errors (422 status)
    - RequestValidationError: FastAPI request parsing errors (422 status)
    - IntegrityError: Database constraint violations (409 status)

    Args:
        fastapi_app: FastAPI application instance to configure

    """

    @fastapi_app.exception_handler(ValidationError)
    async def validation_exception_handler(_request: Request, exc: ValidationError):
        """Handle Pydantic validation errors globally.

        Args:
            _request: The HTTP request that caused the validation error
            exc: The Pydantic validation error

        Returns:
            JSONResponse: HTTP 422 response with formatted validation error
        """
        return JSONResponse(status_code=422, content=ErrorFormatter.format_validation_error(exc))

    @fastapi_app.exception_handler(RequestValidationError)
    async def request_validation_exception_handler(_request: Request, exc: RequestValidationError):
        """Handle FastAPI request validation errors.

        Args:
            _request: The HTTP request that caused the validation error
            exc: The FastAPI request validation error

        Returns:
            JSONResponse: HTTP 422 response with formatted validation error
        """
        if _request.url.path.startswith("/tools"):
            error_details = []
            for error in exc.errors():
                loc = error.get("loc", [])
                msg = error.get("msg", "Unknown error")
                ctx = error.get("ctx", {"error": {}})
                type_ = error.get("type", "value_error")
                # Ensure ctx is JSON serializable
                if isinstance(ctx, dict):
                    ctx_serializable = {k: (str(v) if isinstance(v, Exception) else v) for k, v in ctx.items()}
                else:
                    ctx_serializable = str(ctx)
                error_detail = {"type": type_, "loc": loc, "msg": msg, "ctx": ctx_serializable}
                error_details.append(error_detail)
            return JSONResponse(status_code=422, content={"detail": error_details})
        return await fastapi_default_validation_handler(_request, exc)

    @fastapi_app.exception_handler(IntegrityError)
    async def database_exception_handler(_request: Request, exc: IntegrityError):
        """Handle SQLAlchemy database integrity constraint violations.

        Args:
            _request: The HTTP request that caused the database error
            exc: The SQLAlchemy integrity error

        Returns:
            JSONResponse: HTTP 409 response with formatted database error
        """
        return JSONResponse(status_code=409, content=ErrorFormatter.format_database_error(exc))


def configure_routes(fastapi_app: FastAPI) -> None:
    """Configure application routes and API endpoints.

    Sets up:
    - /v1/* - Versioned API routes (tools, resources, prompts, etc.)
    - /experimental/* - Experimental API features
    - /admin/* - Admin UI and management API (conditional)
    - /mcp/* - Streamable HTTP transport mount
    - /health, /ready - Health check endpoints
    - /rpc, /rpc/ - Root-level RPC endpoints for backward compatibility
    - Legacy deprecation routes with migration guidance

    Args:
        fastapi_app: FastAPI application instance to configure

    """
    logger.info("Configuring application routes")

    # API version routers
    v1_router = APIRouter()
    setup_v1_routes(v1_router)
    fastapi_app.include_router(v1_router, prefix="/v1")

    # Root-level routes for backward compatibility
    setup_v1_routes(fastapi_app)
    logger.info("V1 routes configured at both /v1 and root level")

    # Version endpoint
    fastapi_app.include_router(version_router)
    logger.info("Version routes configured")

    exp_router = APIRouter()
    setup_experimental_routes(exp_router)
    fastapi_app.include_router(exp_router, prefix="/experimental")
    logger.info("Experimental routes configured")

    # Legacy deprecation routes
    setup_legacy_deprecation_routes(fastapi_app)
    logger.info("Legacy deprecation routes configured")

    # Admin API (conditional)
    if settings.mcpgateway_admin_api_enabled:
        logger.info("Including admin_router - Admin API enabled")
        fastapi_app.include_router(admin_router)
    else:
        logger.warning("Admin API routes not mounted - Admin API disabled")

    # Streamable HTTP mount
    fastapi_app.mount("/mcp", app=streamable_http_session.handle_streamable_http)
    logger.info("Streamable HTTP mount configured")

    # Health endpoints
    configure_health_endpoints(fastapi_app)
    logger.info("Health endpoints configured")

    fastapi_app.post("/rpc/")(handle_rpc)
    fastapi_app.post("/initialize")(initialize)
    fastapi_app.post("/notifications")(handle_notification)
    logger.info("RPC endpoints, initialize, notifications configured")

    # Log all registered routes for debugging
    logger.info("Registered routes:")
    for route in fastapi_app.routes:
        if hasattr(route, "path"):
            logger.info(f"  {route.methods if hasattr(route, 'methods') else 'MOUNT'} {route.path}")


def configure_health_endpoints(fastapi_app: FastAPI) -> None:
    """Configure health check and readiness endpoints.

    Adds:
    - GET /health - Basic database connectivity check
    - GET /ready - Readiness probe for container orchestration

    Args:
        fastapi_app: FastAPI application instance to configure

    """

    @fastapi_app.get("/health")
    async def healthcheck(db: Session = Depends(get_db)):
        """Basic health check.

        Args:
            db: The database session used to check health.

        Returns:
            dict: Status dictionary with health information
        """
        try:
            db.execute(text("SELECT 1"))
            return {"status": "healthy"}
        except Exception as e:
            logger.error(f"Database connection error: {str(e)}")
            return {"status": "unhealthy", "error": str(e)}

    @fastapi_app.get("/ready")
    async def readiness_check(db: Session = Depends(get_db)):
        """Readiness check.

        Args:
            db: The database session used to check readiness.

        Returns:
            JSONResponse: HTTP 200 response if ready, HTTP 503 response if not ready
        """
        try:
            await asyncio.to_thread(db.execute, text("SELECT 1"))
            return JSONResponse(content={"status": "ready"}, status_code=200)
        except Exception as e:
            logger.error(f"Readiness check failed: {str(e)}")
            return JSONResponse(content={"status": "not ready", "error": str(e)}, status_code=503)


def configure_ui(fastapi_app: FastAPI) -> None:
    """Configure user interface and static file serving.

    Sets up:
    - Jinja2 templates for server-side rendering
    - Static file mounting for CSS, JS, images (if UI enabled)
    - Root path routing (redirect to /admin or API info)
    - Admin UI integration with HTMX frontend

    Behavior depends on MCPGATEWAY_UI_ENABLED setting:
    - True: Serves admin UI with static files and redirects
    - False: Returns API information at root path

    Args:
        fastapi_app: FastAPI application instance to configure

    """
    # Set up Jinja2 templates
    fastapi_app.state.templates = templates

    if settings.mcpgateway_ui_enabled:
        # Mount static files
        try:
            fastapi_app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")
            logger.info("Static assets served from %s", settings.static_dir)
        except RuntimeError as exc:
            logger.warning("Static dir %s not found - Admin UI disabled (%s)", settings.static_dir, exc)

        # Root redirect to admin UI
        @fastapi_app.get("/")
        async def root_redirect(request: Request):
            """Redirect root path to admin UI.

            Args:
                request: The incoming FastAPI request.

            Returns:
                RedirectResponse: Redirects to /admin path
            """
            logger.debug("Redirecting root path to /admin")
            root_path = request.scope.get("root_path", "")
            return RedirectResponse(f"{root_path}/admin", status_code=303)

    else:
        # API info at root when UI is disabled
        @fastapi_app.get("/")
        async def root_info():
            """Return API information when UI is disabled.

            Returns:
                dict: API information dictionary
            """
            logger.info("UI disabled, serving API info at root path")
            return {
                "name": settings.app_name,
                "version": __version__,
                "description": f"{settings.app_name} API - UI is disabled",
                "ui_enabled": False,
                "admin_api_enabled": settings.mcpgateway_admin_api_enabled,
            }


# Create the app instance
app = create_app()
