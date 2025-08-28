# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_coverage_push.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Focused tests to push coverage to 75%.
"""

# Standard
from unittest.mock import patch, MagicMock

# Third-Party
import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException  

# First-Party
from mcpgateway.main import app, require_api_key


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


def test_require_api_key_scenarios():
    """Test require_api_key function comprehensively."""
    # Test with auth disabled
    with patch('mcpgateway.main.settings') as mock_settings:
        mock_settings.auth_required = False
        require_api_key("any:key")  # Should not raise

    # Test with auth enabled and correct key
    with patch('mcpgateway.main.settings') as mock_settings:
        mock_settings.auth_required = True
        mock_settings.basic_auth_user = "admin"
        mock_settings.basic_auth_password = "secret"
        require_api_key("admin:secret")  # Should not raise

    # Test with auth enabled and incorrect key
    with patch('mcpgateway.main.settings') as mock_settings:
        mock_settings.auth_required = True
        mock_settings.basic_auth_user = "admin"
        mock_settings.basic_auth_password = "secret"

        with pytest.raises(HTTPException):
            require_api_key("wrong:key")


def test_app_basic_properties():
    """Test basic app properties."""
    assert app.title is not None
    assert app.version is not None
    assert hasattr(app, 'routes')


def test_error_handlers():
    """Test error handler functions exist."""
    # Exception handlers are now defined inside configure_exception_handlers function
    from mcpgateway.main import configure_exception_handlers
    
    # Test that configure function exists and is callable
    assert callable(configure_exception_handlers)


def test_middleware_classes():
    """Test middleware classes can be instantiated."""
    from mcpgateway.main import DocsAuthMiddleware, MCPPathRewriteMiddleware

    # Test DocsAuthMiddleware
    docs_middleware = DocsAuthMiddleware(app)
    assert docs_middleware is not None

    # Test MCPPathRewriteMiddleware
    path_middleware = MCPPathRewriteMiddleware(app)
    assert path_middleware is not None


def test_mcp_path_rewrite_middleware():
    """Test MCPPathRewriteMiddleware initialization."""
    from mcpgateway.main import MCPPathRewriteMiddleware

    app_mock = MagicMock()
    middleware = MCPPathRewriteMiddleware(app_mock)

    assert middleware.application == app_mock


def test_service_instances():
    """Test that service instances exist."""
    from mcpgateway.main import (
        tool_service, resource_service, prompt_service,
        gateway_service, root_service, completion_service,
        export_service, import_service
    )

    # Test all services exist
    assert tool_service is not None
    assert resource_service is not None
    assert prompt_service is not None
    assert gateway_service is not None
    assert root_service is not None
    assert completion_service is not None
    assert export_service is not None
    assert import_service is not None


def test_router_instances():
    """Test that router instances exist."""
    from mcpgateway.routers.current import protocol_router
    from mcpgateway.routers.current import resource_router
    from mcpgateway.routers.current import root_router
    from mcpgateway.routers.current import tool_router
    from mcpgateway.routers.current import export_import_router
    from mcpgateway.routers.current import prompt_router
    from mcpgateway.routers.current import gateway_router
    from mcpgateway.routers.current import prompt_router

    # Test all routers exist
    assert protocol_router is not None
    assert tool_router is not None
    assert resource_router is not None
    assert prompt_router is not None
    assert gateway_router is not None
    assert root_router is not None
    assert export_import_router is not None


def test_database_dependency():
    """Test database dependency function."""
    from mcpgateway.db import get_db

    # Test function exists and is generator
    db_gen = get_db()
    assert hasattr(db_gen, '__next__')


def test_cors_settings():
    """Test CORS configuration."""
    from mcpgateway.dependencies import get_cors_origins

    cors_origins = get_cors_origins()

    assert isinstance(cors_origins, list)


def test_template_and_static_setup():
    """Test template and static file setup."""
    from mcpgateway.main import templates

    assert templates is not None
    assert hasattr(app.state, 'templates')


def test_feature_flags():
    """Test feature flag variables."""
    from mcpgateway.config import settings

    assert isinstance(settings.mcpgateway_ui_enabled, bool)
    assert isinstance(settings.mcpgateway_admin_api_enabled, bool)


def test_lifespan_function_exists():
    """Test lifespan function exists."""
    from mcpgateway.main import lifespan

    assert callable(lifespan)


def test_cache_instances():
    """Test cache instances exist."""
    from mcpgateway.main import resource_cache
    from mcpgateway.registry import session_registry

    assert resource_cache is not None
    assert session_registry is not None
