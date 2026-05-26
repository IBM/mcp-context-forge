# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/middleware/test_password_change_enforcement.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for PasswordChangeEnforcementMiddleware.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

# First-Party
from mcpgateway.db import EmailUser
from mcpgateway.middleware.password_change_enforcement import PasswordChangeEnforcementMiddleware


@pytest.fixture
def app():
    """Create a test FastAPI application."""
    app = FastAPI()

    @app.get("/admin/overview")
    async def admin_overview():
        return {"message": "Admin overview"}

    @app.get("/admin/change-password-required")
    async def change_password_page():
        return {"message": "Change password page"}

    @app.post("/auth/email/change-password")
    async def change_password():
        return {"message": "Password changed"}

    @app.get("/auth/email/logout")
    async def logout():
        return {"message": "Logged out"}

    @app.get("/mcp/tools")
    async def mcp_tools():
        return {"message": "MCP tools"}

    return app


@pytest.fixture
def middleware(app):
    """Add middleware to the test app."""
    app.add_middleware(PasswordChangeEnforcementMiddleware)
    return app


@pytest.fixture
def mock_user():
    """Create a mock EmailUser."""
    user = MagicMock(spec=EmailUser)
    user.email = "test@example.com"
    user.password_change_required = False
    return user


@pytest.mark.asyncio
async def test_middleware_allows_access_when_no_password_change_required(middleware, mock_user):
    """Test that middleware allows access when password change is not required."""
    from starlette.testclient import TestClient

    with patch("mcpgateway.config.settings.password_change_enforcement_enabled", True):
        client = TestClient(middleware)

        # Mock request state
        with patch.object(Request, "state", create=True) as mock_state:
            mock_state.user = mock_user
            mock_state.auth_method = "jwt"

            response = client.get("/admin/overview")
            assert response.status_code == 200
            assert response.json() == {"message": "Admin overview"}


@pytest.mark.asyncio
async def test_middleware_redirects_when_password_change_required(middleware, mock_user):
    """Test that middleware redirects when password change is required."""
    from starlette.testclient import TestClient

    mock_user.password_change_required = True

    with patch("mcpgateway.config.settings.password_change_enforcement_enabled", True):
        client = TestClient(middleware)

        # Mock request state
        with patch.object(Request, "state", create=True) as mock_state:
            mock_state.user = mock_user
            mock_state.auth_method = "jwt"

            response = client.get("/admin/overview", follow_redirects=False)
            assert response.status_code == 303
            assert response.headers["location"] == "/admin/change-password-required"


@pytest.mark.asyncio
async def test_middleware_allows_exempt_paths(middleware, mock_user):
    """Test that middleware allows access to exempt paths even when password change is required."""
    from starlette.testclient import TestClient

    mock_user.password_change_required = True

    with patch("mcpgateway.config.settings.password_change_enforcement_enabled", True):
        client = TestClient(middleware)

        # Mock request state
        with patch.object(Request, "state", create=True) as mock_state:
            mock_state.user = mock_user
            mock_state.auth_method = "jwt"

            # Test exempt paths
            exempt_paths = [
                "/admin/change-password-required",
                "/auth/email/change-password",
                "/auth/email/logout",
            ]

            for path in exempt_paths:
                response = client.get(path) if path.startswith("/admin") else client.post(path) if "change-password" in path else client.get(path)
                assert response.status_code != 303, f"Path {path} should be exempt but got redirect"


@pytest.mark.asyncio
async def test_middleware_skips_non_admin_routes(middleware, mock_user):
    """Test that middleware does not enforce on non-admin routes."""
    from starlette.testclient import TestClient

    mock_user.password_change_required = True

    with patch("mcpgateway.config.settings.password_change_enforcement_enabled", True):
        client = TestClient(middleware)

        # Mock request state
        with patch.object(Request, "state", create=True) as mock_state:
            mock_state.user = mock_user
            mock_state.auth_method = "jwt"

            response = client.get("/mcp/tools")
            assert response.status_code == 200
            assert response.json() == {"message": "MCP tools"}


@pytest.mark.asyncio
async def test_middleware_skips_api_tokens(middleware, mock_user):
    """Test that middleware does not enforce for API tokens."""
    from starlette.testclient import TestClient

    mock_user.password_change_required = True

    with patch("mcpgateway.config.settings.password_change_enforcement_enabled", True):
        client = TestClient(middleware)

        # Mock request state with API token auth
        with patch.object(Request, "state", create=True) as mock_state:
            mock_state.user = mock_user
            mock_state.auth_method = "api_token"

            response = client.get("/admin/overview")
            assert response.status_code == 200
            assert response.json() == {"message": "Admin overview"}


@pytest.mark.asyncio
async def test_middleware_disabled_when_feature_flag_off(middleware, mock_user):
    """Test that middleware is disabled when password_change_enforcement_enabled is False."""
    from starlette.testclient import TestClient

    mock_user.password_change_required = True

    with patch("mcpgateway.config.settings.password_change_enforcement_enabled", False):
        client = TestClient(middleware)

        # Mock request state
        with patch.object(Request, "state", create=True) as mock_state:
            mock_state.user = mock_user
            mock_state.auth_method = "jwt"

            response = client.get("/admin/overview")
            assert response.status_code == 200
            assert response.json() == {"message": "Admin overview"}


@pytest.mark.asyncio
async def test_middleware_allows_unauthenticated_requests(middleware):
    """Test that middleware allows unauthenticated requests to proceed."""
    from starlette.testclient import TestClient

    with patch("mcpgateway.config.settings.password_change_enforcement_enabled", True):
        client = TestClient(middleware)

        # Mock request state with no user
        with patch.object(Request, "state", create=True) as mock_state:
            mock_state.user = None

            response = client.get("/admin/overview")
            # Should proceed to route handler (which will handle auth)
            assert response.status_code == 200


@pytest.mark.asyncio
async def test_middleware_handles_missing_auth_method(middleware, mock_user):
    """Test that middleware handles missing auth_method gracefully."""
    from starlette.testclient import TestClient

    mock_user.password_change_required = True

    with patch("mcpgateway.config.settings.password_change_enforcement_enabled", True):
        client = TestClient(middleware)

        # Mock request state without auth_method
        with patch.object(Request, "state", create=True) as mock_state:
            mock_state.user = mock_user
            # No auth_method set - should default to "jwt"

            response = client.get("/admin/overview", follow_redirects=False)
            assert response.status_code == 303
            assert response.headers["location"] == "/admin/change-password-required"


@pytest.mark.asyncio
async def test_middleware_handles_missing_password_change_required_flag(middleware, mock_user):
    """Test that middleware handles missing password_change_required flag gracefully."""
    from starlette.testclient import TestClient

    # Remove the password_change_required attribute
    delattr(mock_user, "password_change_required")

    with patch("mcpgateway.config.settings.password_change_enforcement_enabled", True):
        client = TestClient(middleware)

        # Mock request state
        with patch.object(Request, "state", create=True) as mock_state:
            mock_state.user = mock_user
            mock_state.auth_method = "jwt"

            response = client.get("/admin/overview")
            # Should allow access when flag is missing (defaults to False)
            assert response.status_code == 200
            assert response.json() == {"message": "Admin overview"}


@pytest.mark.asyncio
async def test_exempt_paths_constant():
    """Test that EXEMPT_PATHS constant contains expected paths."""
    expected_paths = {
        "/admin/change-password-required",
        "/admin/login",
        "/auth/email/change-password",
        "/auth/email/logout",
    }

    assert PasswordChangeEnforcementMiddleware.EXEMPT_PATHS == expected_paths


@pytest.mark.asyncio
async def test_middleware_logs_blocked_access(middleware, mock_user, caplog):
    """Test that middleware logs when blocking access."""
    from starlette.testclient import TestClient

    mock_user.password_change_required = True

    with patch("mcpgateway.config.settings.password_change_enforcement_enabled", True):
        client = TestClient(middleware)

        # Mock request state
        with patch.object(Request, "state", create=True) as mock_state:
            mock_state.user = mock_user
            mock_state.auth_method = "jwt"

            with caplog.at_level("INFO"):
                response = client.get("/admin/overview", follow_redirects=False)
                assert response.status_code == 303

                # Check that log message was created
                assert any("password change required" in record.message.lower() for record in caplog.records)


@pytest.mark.asyncio
async def test_middleware_logs_api_token_skip(middleware, mock_user, caplog):
    """Test that middleware logs when skipping API token enforcement."""
    from starlette.testclient import TestClient

    mock_user.password_change_required = True

    with patch("mcpgateway.config.settings.password_change_enforcement_enabled", True):
        client = TestClient(middleware)

        # Mock request state with API token
        with patch.object(Request, "state", create=True) as mock_state:
            mock_state.user = mock_user
            mock_state.auth_method = "api_token"

            with caplog.at_level("DEBUG"):
                response = client.get("/admin/overview")
                assert response.status_code == 200

                # Check that log message was created
                assert any("skipping password change enforcement for api token" in record.message.lower() for record in caplog.records)
