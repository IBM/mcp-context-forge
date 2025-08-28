"""Route setup and configuration module.

This module provides centralized route configuration functions for the MCP Gateway.
It organizes API endpoints into versioned groups and handles legacy route deprecation.
"""

# Third-Party
from fastapi import FastAPI

# First-Party
from mcpgateway.config import settings
from mcpgateway.dependencies import get_logging_service
from mcpgateway.routers.current import (  # noqa: F401
    a2a_router,
    export_import_router,
    gateway_router,
    metrics_router,
    oauth_router,
    prompt_router,
    protocol_router,
    resource_router,
    reverse_proxy_router,
    root_router,
    server_router,
    tag_router,
    tool_router,
    utility_router,
    version_router,
    well_known_router,
)

# Initialize logging service first
logging_service = get_logging_service()
logger = logging_service.get_logger("setup routes")


def setup_v1_routes(app: FastAPI) -> None:
    """Configure all v1 API routes.

    Args:
        app: FastAPI application instance to configure
    """
    app.include_router(tool_router)
    app.include_router(protocol_router)
    app.include_router(resource_router)
    app.include_router(prompt_router)
    app.include_router(gateway_router)
    app.include_router(root_router)
    app.include_router(utility_router)
    app.include_router(server_router)
    app.include_router(metrics_router)
    app.include_router(tag_router)
    app.include_router(export_import_router)

    # Conditionally include A2A router if A2A features are enabled
    if settings.mcpgateway_a2a_enabled:
        app.include_router(a2a_router)
        logger.info("A2A router included - A2A features enabled")
    else:
        logger.info("A2A router not included - A2A features disabled")

    app.include_router(well_known_router)

    # Include OAuth router
    try:
        app.include_router(oauth_router)
        logger.info("OAuth router included")
    except ImportError:
        logger.debug("OAuth router not available")

    # Include reverse proxy router if enabled
    try:
        app.include_router(reverse_proxy_router)
        logger.info("Reverse proxy router included")
    except ImportError:
        logger.debug("Reverse proxy router not available")


def setup_version_routes(_app: FastAPI) -> None:
    """Configure version endpoint.

    Args:
        _app: FastAPI application instance to configure
    """
    # register version router


def setup_experimental_routes(_app: FastAPI) -> None:
    """Configure experimental API routes.

    Args:
        _app: FastAPI application instance to configure
    """
    # Register experimental routers here


def setup_legacy_deprecation_routes(_app: FastAPI) -> None:
    """Configure legacy route deprecation warnings.

    Args:
        _app: FastAPI application instance to configure
    """

    # Legacy routes are now handled by middleware instead of conflicting endpoints
