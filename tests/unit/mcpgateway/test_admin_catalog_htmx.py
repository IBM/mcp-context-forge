# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_admin_catalog_htmx.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for HTMX functionality in catalog server registration endpoint.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import Request
from fastapi.responses import HTMLResponse

from mcpgateway.admin import register_catalog_server
from mcpgateway.schemas import (
    CatalogServerRegisterRequest,
    CatalogServerRegisterResponse,
)


@pytest.fixture
def mock_request():
    """Create a mock FastAPI Request object."""
    request = MagicMock(spec=Request)
    request.headers = {}
    return request


@pytest.fixture
def mock_db():
    """Create a mock database session."""
    return MagicMock()


@pytest.fixture
def mock_user():
    """Create a mock authenticated user."""
    return MagicMock()


@pytest.fixture
def mock_catalog_service():
    """Create a mock catalog service."""
    with patch("mcpgateway.admin.catalog_service") as mock:
        yield mock


@pytest.mark.asyncio
async def test_register_catalog_server_htmx_success(
    mock_request, mock_db, mock_user, mock_catalog_service
):
    """Test HTMX request returns HTML for successful registration."""
    # Setup HTMX request
    mock_request.headers = {"HX-Request": "true"}

    # Mock successful registration
    mock_result = CatalogServerRegisterResponse(
        success=True,
        server_id="test-id",
        message="Successfully registered Test Server with 5 tools discovered",
        error=None,
    )
    mock_catalog_service.register_catalog_server = AsyncMock(return_value=mock_result)

    # Call endpoint
    with patch("mcpgateway.admin.settings") as mock_settings:
        mock_settings.mcpgateway_catalog_enabled = True
        mock_settings.app_root_path = ""

        response = await register_catalog_server(
            server_id="test-server",
            http_request=mock_request,
            request=None,
            db=mock_db,
            _user=mock_user,
        )

    # Verify HTML response
    assert isinstance(response, HTMLResponse)
    assert "Registered Successfully" in response.body.decode()
    assert "bg-green-600" in response.body.decode()
    assert "disabled" in response.body.decode()


@pytest.mark.asyncio
async def test_register_catalog_server_htmx_oauth(
    mock_request, mock_db, mock_user, mock_catalog_service
):
    """Test HTMX request returns HTML for OAuth server requiring configuration."""
    # Setup HTMX request
    mock_request.headers = {"HX-Request": "true"}

    # Mock OAuth server registration
    mock_result = CatalogServerRegisterResponse(
        success=True,
        server_id="oauth-id",
        message="Successfully registered OAuth Server - OAuth configuration required before activation",
        error=None,
    )
    mock_catalog_service.register_catalog_server = AsyncMock(return_value=mock_result)

    # Call endpoint
    with patch("mcpgateway.admin.settings") as mock_settings:
        mock_settings.mcpgateway_catalog_enabled = True
        mock_settings.app_root_path = ""

        response = await register_catalog_server(
            server_id="oauth-server",
            http_request=mock_request,
            request=None,
            db=mock_db,
            _user=mock_user,
        )

    # Verify HTML response for OAuth
    assert isinstance(response, HTMLResponse)
    assert "OAuth Config Required" in response.body.decode()
    assert "bg-yellow-600" in response.body.decode()
    assert "disabled" in response.body.decode()


@pytest.mark.asyncio
async def test_register_catalog_server_htmx_error(
    mock_request, mock_db, mock_user, mock_catalog_service
):
    """Test HTMX request returns HTML for failed registration with retry button."""
    # Setup HTMX request
    mock_request.headers = {"HX-Request": "true"}

    # Mock failed registration
    mock_result = CatalogServerRegisterResponse(
        success=False,
        server_id="",
        message="Registration failed",
        error="Server is offline or unreachable",
    )
    mock_catalog_service.register_catalog_server = AsyncMock(return_value=mock_result)

    # Call endpoint
    with patch("mcpgateway.admin.settings") as mock_settings:
        mock_settings.mcpgateway_catalog_enabled = True
        mock_settings.app_root_path = ""

        response = await register_catalog_server(
            server_id="failed-server",
            http_request=mock_request,
            request=None,
            db=mock_db,
            _user=mock_user,
        )

    # Verify HTML response for error
    assert isinstance(response, HTMLResponse)
    assert "Failed - Click to Retry" in response.body.decode()
    assert "bg-red-600" in response.body.decode()
    assert "hx-post" in response.body.decode()
    assert "Server is offline or unreachable" in response.body.decode()


@pytest.mark.asyncio
async def test_register_catalog_server_json_response(
    mock_request, mock_db, mock_user, mock_catalog_service
):
    """Test non-HTMX request returns JSON response."""
    # Setup non-HTMX request (no HX-Request header)
    mock_request.headers = {}

    # Mock successful registration
    mock_result = CatalogServerRegisterResponse(
        success=True,
        server_id="test-id",
        message="Successfully registered Test Server",
        error=None,
    )
    mock_catalog_service.register_catalog_server = AsyncMock(return_value=mock_result)

    # Call endpoint
    with patch("mcpgateway.admin.settings") as mock_settings:
        mock_settings.mcpgateway_catalog_enabled = True

        response = await register_catalog_server(
            server_id="test-server",
            http_request=mock_request,
            request=None,
            db=mock_db,
            _user=mock_user,
        )

    # Verify JSON response
    assert isinstance(response, CatalogServerRegisterResponse)
    assert response.success is True
    assert response.server_id == "test-id"
    assert "Successfully registered" in response.message


@pytest.mark.asyncio
async def test_register_catalog_server_htmx_with_api_key(
    mock_request, mock_db, mock_user, mock_catalog_service
):
    """Test HTMX request with API key registration."""
    # Setup HTMX request
    mock_request.headers = {"HX-Request": "true"}

    # Create registration request with API key
    register_request = CatalogServerRegisterRequest(
        server_id="api-server",
        name="API Server",
        api_key="secret-key",
    )

    # Mock successful registration
    mock_result = CatalogServerRegisterResponse(
        success=True,
        server_id="api-id",
        message="Successfully registered API Server with 3 tools discovered",
        error=None,
    )
    mock_catalog_service.register_catalog_server = AsyncMock(return_value=mock_result)

    # Call endpoint
    with patch("mcpgateway.admin.settings") as mock_settings:
        mock_settings.mcpgateway_catalog_enabled = True
        mock_settings.app_root_path = ""

        response = await register_catalog_server(
            server_id="api-server",
            http_request=mock_request,
            request=register_request,
            db=mock_db,
            _user=mock_user,
        )

    # Verify HTML response
    assert isinstance(response, HTMLResponse)
    assert "Registered Successfully" in response.body.decode()
    assert "bg-green-600" in response.body.decode()


@pytest.mark.asyncio
async def test_register_catalog_server_htmx_error_escaping(
    mock_request, mock_db, mock_user, mock_catalog_service
):
    """Test that error messages with quotes are properly escaped in HTML."""
    # Setup HTMX request
    mock_request.headers = {"HX-Request": "true"}

    # Mock failed registration with quotes in error message
    mock_result = CatalogServerRegisterResponse(
        success=False,
        server_id="",
        message="Registration failed",
        error='Server returned "Invalid credentials" error',
    )
    mock_catalog_service.register_catalog_server = AsyncMock(return_value=mock_result)

    # Call endpoint
    with patch("mcpgateway.admin.settings") as mock_settings:
        mock_settings.mcpgateway_catalog_enabled = True
        mock_settings.app_root_path = ""

        response = await register_catalog_server(
            server_id="failed-server",
            http_request=mock_request,
            request=None,
            db=mock_db,
            _user=mock_user,
        )

    # Verify HTML response has escaped quotes
    html_content = response.body.decode()
    assert "Failed - Click to Retry" in html_content
    assert "&quot;" in html_content  # Quotes should be escaped
    assert 'Server returned &quot;Invalid credentials&quot; error' in html_content


@pytest.mark.asyncio
async def test_register_catalog_server_htmx_retry_button_attributes(
    mock_request, mock_db, mock_user, mock_catalog_service
):
    """Test that retry button has correct HTMX attributes."""
    # Setup HTMX request
    mock_request.headers = {"HX-Request": "true"}

    # Mock failed registration
    mock_result = CatalogServerRegisterResponse(
        success=False,
        server_id="",
        message="Registration failed",
        error="Connection timeout",
    )
    mock_catalog_service.register_catalog_server = AsyncMock(return_value=mock_result)

    # Call endpoint
    with patch("mcpgateway.admin.settings") as mock_settings:
        mock_settings.mcpgateway_catalog_enabled = True
        mock_settings.app_root_path = "/api"

        response = await register_catalog_server(
            server_id="timeout-server",
            http_request=mock_request,
            request=None,
            db=mock_db,
            _user=mock_user,
        )

    # Verify retry button has correct HTMX attributes
    html_content = response.body.decode()
    assert 'hx-post="/api/admin/mcp-registry/timeout-server/register"' in html_content
    assert 'hx-target="#timeout-server-button-container"' in html_content
    assert 'hx-swap="innerHTML"' in html_content
    assert 'hx-disabled-elt="this"' in html_content
    assert 'hx-on::before-request' in html_content
    assert 'hx-on::after-request' in html_content
