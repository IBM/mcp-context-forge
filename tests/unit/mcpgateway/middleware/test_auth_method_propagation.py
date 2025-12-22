# -*- coding: utf-8 -*-
"""Test auth_method propagation from plugin to RBAC.

This test verifies that when a plugin authenticates a user via the
HTTP_AUTH_RESOLVE_USER hook, the auth_method metadata flows through
the system correctly:

1. Plugin returns metadata with auth_method in PluginResult
2. get_current_user stores it in request.state.auth_method
3. get_current_user_with_permissions reads it and includes in user_context
4. RBAC permission check hook receives it in HttpAuthCheckPermissionPayload
"""

# Standard
import logging
from unittest.mock import AsyncMock, MagicMock, patch

# Enable debug logging for auth module
logging.getLogger("mcpgateway.auth").setLevel(logging.DEBUG)

# Third-Party
import pytest
from fastapi import Request
from fastapi.security import HTTPAuthorizationCredentials

# First-Party
from mcpgateway.auth import get_current_user
from mcpgateway.middleware.rbac import get_current_user_with_permissions
from mcpgateway.plugins.framework import PluginResult


@pytest.mark.asyncio
async def test_auth_method_propagation_from_plugin():
    """Test that auth_method flows from plugin through to user_context."""
    # Create a mock request with a real object for state (not a MagicMock)
    # This is needed because we set attributes directly on request.state
    # Don't use spec=Request because it prevents setting custom attributes
    class MockState:
        pass

    mock_request = MagicMock()  # No spec= to allow custom attributes
    mock_request.state = MockState()
    mock_request.client = MagicMock()
    mock_request.client.host = "127.0.0.1"
    mock_request.headers = {"user-agent": "TestAgent"}

    # Create mock credentials
    mock_credentials = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials="test-token-123",
    )

    # Mock the plugin manager to return a successful auth with metadata
    mock_plugin_result = PluginResult(
        modified_payload={
            "email": "test@example.com",
            "full_name": "Test User",
            "is_admin": False,
            "is_active": True,
        },
        metadata={"auth_method": "simple_token"},
        continue_processing=True,
    )

    # Patch both the framework module and auth module since auth imports from framework
    with patch("mcpgateway.plugins.framework.get_plugin_manager") as mock_get_pm_framework:
        with patch("mcpgateway.auth.get_plugin_manager") as mock_get_pm_auth:
            mock_pm = MagicMock()
            mock_pm.invoke_hook = AsyncMock(return_value=(mock_plugin_result, None))
            mock_get_pm_framework.return_value = mock_pm
            mock_get_pm_auth.return_value = mock_pm

            # Call get_current_user - should authenticate via plugin
            # Note: get_current_user no longer takes db parameter (uses fresh sessions internally)
            user = await get_current_user(
                credentials=mock_credentials,
                request=mock_request,
            )

            # Verify user was created
            assert user.email == "test@example.com"
            assert user.full_name == "Test User"

            # Verify auth_method was stored in request.state
            assert hasattr(mock_request.state, "auth_method")
            assert mock_request.state.auth_method == "simple_token"


@pytest.mark.asyncio
async def test_auth_method_in_user_context():
    """Test that get_current_user_with_permissions includes auth_method from request.state."""
    # Create a mock request with a real object for state
    class MockState:
        pass

    mock_request = MagicMock()
    mock_request.state = MockState()
    mock_request.state.auth_method = "simple_token"
    mock_request.state.request_id = "test-request-id"
    mock_request.client = MagicMock()
    mock_request.client.host = "127.0.0.1"
    mock_request.headers = {"user-agent": "TestAgent"}
    mock_request.cookies = {"jwt_token": "test-token"}

    # Create mock database session
    mock_db = MagicMock()

    # Create mock user
    mock_user = MagicMock()
    mock_user.email = "test@example.com"
    mock_user.full_name = "Test User"
    mock_user.is_admin = False

    # Mock get_current_user to return the mock user
    with patch("mcpgateway.middleware.rbac.get_current_user", new_callable=AsyncMock) as mock_get_user:
        mock_get_user.return_value = mock_user

        # Mock the database dependency
        with patch("mcpgateway.middleware.rbac.get_db") as mock_get_db:
            mock_get_db.return_value = mock_db

            # Call get_current_user_with_permissions
            user_context = await get_current_user_with_permissions(
                request=mock_request,
                credentials=None,
                jwt_token="test-token",
                db=mock_db,
            )

            # Verify user_context includes auth_method and request_id
            assert user_context["auth_method"] == "simple_token"
            assert user_context["request_id"] == "test-request-id"
            assert user_context["email"] == "test@example.com"
            assert user_context["full_name"] == "Test User"
            assert user_context["is_admin"] is False
            assert user_context["ip_address"] == "127.0.0.1"
            assert user_context["user_agent"] == "TestAgent"
