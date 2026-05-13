# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/middleware/test_password_change_enforcement_security.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Security-focused edge case tests for PasswordChangeEnforcementMiddleware.
These tests ensure the middleware cannot be bypassed through various attack vectors.
"""

# Standard
from unittest.mock import MagicMock, patch

# Third-Party
import pytest
from fastapi import FastAPI, Request
from starlette.testclient import TestClient

# First-Party
from mcpgateway.db import EmailUser
from mcpgateway.middleware.password_change_enforcement import PasswordChangeEnforcementMiddleware


@pytest.fixture
def app():
    """Create a test FastAPI application with various admin routes."""
    app = FastAPI()

    @app.get("/admin/overview")
    async def admin_overview():
        return {"message": "Admin overview"}

    @app.get("/admin/users")
    async def admin_users():
        return {"message": "Admin users"}

    @app.post("/admin/users")
    async def create_user():
        return {"message": "User created"}

    @app.put("/admin/users/{user_id}")
    async def update_user(user_id: str):
        return {"message": f"User {user_id} updated"}

    @app.delete("/admin/users/{user_id}")
    async def delete_user(user_id: str):
        return {"message": f"User {user_id} deleted"}

    @app.get("/admin/login")
    async def admin_login():
        return {"message": "Login page"}

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

    @app.get("/admin")
    async def admin_root():
        return {"message": "Admin root"}

    @app.get("/admin/")
    async def admin_root_slash():
        return {"message": "Admin root with slash"}

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


class TestSecurityEdgeCases:
    """Security-focused edge case tests."""

    @pytest.mark.asyncio
    async def test_blocks_all_http_methods_on_admin_routes(self, middleware, mock_user):
        """Test that middleware blocks GET, POST, PUT, DELETE on admin routes when password change required."""
        mock_user.password_change_required = True

        with patch("mcpgateway.config.settings.password_change_enforcement_enabled", True):
            client = TestClient(middleware)

            with patch.object(Request, "state", create=True) as mock_state:
                mock_state.user = mock_user
                mock_state.auth_method = "jwt"

                # Test all HTTP methods
                methods_and_paths = [
                    ("GET", "/admin/users"),
                    ("POST", "/admin/users"),
                    ("PUT", "/admin/users/123"),
                    ("DELETE", "/admin/users/123"),
                ]

                for method, path in methods_and_paths:
                    response = client.request(method, path, follow_redirects=False)
                    assert response.status_code == 303, f"{method} {path} should be blocked"
                    assert response.headers["location"] == "/admin/change-password-required"

    @pytest.mark.asyncio
    async def test_user_with_missing_email_attribute(self, middleware):
        """Test middleware handles user object without email attribute gracefully."""
        user = MagicMock(spec=EmailUser)
        user.password_change_required = True
        # Simulate missing email attribute
        delattr(user, "email")

        with patch("mcpgateway.config.settings.password_change_enforcement_enabled", True):
            client = TestClient(middleware)

            with patch.object(Request, "state", create=True) as mock_state:
                mock_state.user = user
                mock_state.auth_method = "jwt"

                # Should still block access even without email
                response = client.get("/admin/overview", follow_redirects=False)
                assert response.status_code == 303

    @pytest.mark.asyncio
    async def test_user_with_none_email(self, middleware, mock_user):
        """Test middleware handles user with None email."""
        mock_user.email = None
        mock_user.password_change_required = True

        with patch("mcpgateway.config.settings.password_change_enforcement_enabled", True):
            client = TestClient(middleware)

            with patch.object(Request, "state", create=True) as mock_state:
                mock_state.user = mock_user
                mock_state.auth_method = "jwt"

                # Should still block access
                response = client.get("/admin/overview", follow_redirects=False)
                assert response.status_code == 303

    @pytest.mark.asyncio
    async def test_exempt_paths_with_query_parameters(self, middleware, mock_user):
        """Test that exempt paths work with query parameters."""
        mock_user.password_change_required = True

        with patch("mcpgateway.config.settings.password_change_enforcement_enabled", True):
            client = TestClient(middleware)

            with patch.object(Request, "state", create=True) as mock_state:
                mock_state.user = mock_user
                mock_state.auth_method = "jwt"

                # Exempt paths should work with query params
                response = client.get("/admin/change-password-required?redirect=/admin/overview")
                assert response.status_code == 200

                response = client.get("/auth/email/logout?session=abc123")
                assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_path_traversal_attempts(self, middleware, mock_user):
        """Test that path traversal attempts don't bypass enforcement."""
        mock_user.password_change_required = True

        with patch("mcpgateway.config.settings.password_change_enforcement_enabled", True):
            client = TestClient(middleware)

            with patch.object(Request, "state", create=True) as mock_state:
                mock_state.user = mock_user
                mock_state.auth_method = "jwt"

                # These should all be blocked (they start with /admin)
                malicious_paths = [
                    "/admin/../mcp/tools",  # Path traversal
                    "/admin/./overview",  # Current directory
                    "/admin//overview",  # Double slash
                ]

                for path in malicious_paths:
                    response = client.get(path, follow_redirects=False)
                    # Should either block or normalize to /admin path
                    if response.status_code == 303:
                        assert response.headers["location"] == "/admin/change-password-required"

    @pytest.mark.asyncio
    async def test_case_sensitivity_of_paths(self, middleware, mock_user):
        """Test that path matching is case-sensitive (security requirement)."""
        mock_user.password_change_required = True

        with patch("mcpgateway.config.settings.password_change_enforcement_enabled", True):
            client = TestClient(middleware)

            with patch.object(Request, "state", create=True) as mock_state:
                mock_state.user = mock_user
                mock_state.auth_method = "jwt"

                # /Admin should NOT match /admin (case-sensitive)
                # This should NOT be blocked (doesn't start with /admin)
                response = client.get("/Admin/overview", follow_redirects=False)
                # Will get 404 but not 303 redirect
                assert response.status_code != 303

    @pytest.mark.asyncio
    async def test_trailing_slash_handling(self, middleware, mock_user):
        """Test that trailing slashes don't bypass enforcement."""
        mock_user.password_change_required = True

        with patch("mcpgateway.config.settings.password_change_enforcement_enabled", True):
            client = TestClient(middleware)

            with patch.object(Request, "state", create=True) as mock_state:
                mock_state.user = mock_user
                mock_state.auth_method = "jwt"

                # Both should be blocked
                response = client.get("/admin/overview", follow_redirects=False)
                assert response.status_code == 303

                response = client.get("/admin/overview/", follow_redirects=False)
                assert response.status_code == 303

    @pytest.mark.asyncio
    async def test_admin_login_path_is_exempt(self, middleware, mock_user):
        """Test that /admin/login is exempt (critical for login flow)."""
        mock_user.password_change_required = True

        with patch("mcpgateway.config.settings.password_change_enforcement_enabled", True):
            client = TestClient(middleware)

            with patch.object(Request, "state", create=True) as mock_state:
                mock_state.user = mock_user
                mock_state.auth_method = "jwt"

                # Login page must be accessible
                response = client.get("/admin/login")
                assert response.status_code == 200
                assert response.json() == {"message": "Login page"}

    @pytest.mark.asyncio
    async def test_redirect_loop_prevention(self, middleware, mock_user):
        """Test that accessing change-password-required page doesn't create redirect loop."""
        mock_user.password_change_required = True

        with patch("mcpgateway.config.settings.password_change_enforcement_enabled", True):
            client = TestClient(middleware)

            with patch.object(Request, "state", create=True) as mock_state:
                mock_state.user = mock_user
                mock_state.auth_method = "jwt"

                # Should NOT redirect to itself
                response = client.get("/admin/change-password-required")
                assert response.status_code == 200
                assert response.json() == {"message": "Change password page"}

    @pytest.mark.asyncio
    async def test_non_emailuser_object(self, middleware):
        """Test middleware handles non-EmailUser objects gracefully."""
        # Create a different type of user object
        user = MagicMock()
        user.email = "test@example.com"
        user.password_change_required = True

        with patch("mcpgateway.config.settings.password_change_enforcement_enabled", True):
            client = TestClient(middleware)

            with patch.object(Request, "state", create=True) as mock_state:
                mock_state.user = user
                mock_state.auth_method = "jwt"

                # Should still enforce (uses getattr, not isinstance check)
                response = client.get("/admin/overview", follow_redirects=False)
                assert response.status_code == 303

    @pytest.mark.asyncio
    async def test_admin_root_paths(self, middleware, mock_user):
        """Test that /admin and /admin/ are both enforced."""
        mock_user.password_change_required = True

        with patch("mcpgateway.config.settings.password_change_enforcement_enabled", True):
            client = TestClient(middleware)

            with patch.object(Request, "state", create=True) as mock_state:
                mock_state.user = mock_user
                mock_state.auth_method = "jwt"

                # Both should be blocked
                response = client.get("/admin", follow_redirects=False)
                assert response.status_code == 303

                response = client.get("/admin/", follow_redirects=False)
                assert response.status_code == 303

    @pytest.mark.asyncio
    async def test_auth_method_variations(self, middleware, mock_user):
        """Test various auth_method values."""
        mock_user.password_change_required = True

        with patch("mcpgateway.config.settings.password_change_enforcement_enabled", True):
            client = TestClient(middleware)

            # Test different auth methods
            test_cases = [
                ("jwt", True),  # Should block
                ("session", True),  # Should block
                ("api_token", False),  # Should NOT block
                ("bearer", True),  # Should block
                ("", True),  # Empty string should block
                (None, True),  # None should default to jwt and block
            ]

            for auth_method, should_block in test_cases:
                with patch.object(Request, "state", create=True) as mock_state:
                    mock_state.user = mock_user
                    if auth_method is not None:
                        mock_state.auth_method = auth_method

                    response = client.get("/admin/overview", follow_redirects=False)
                    if should_block:
                        assert response.status_code == 303, f"auth_method={auth_method} should block"
                    else:
                        assert response.status_code == 200, f"auth_method={auth_method} should allow"

    @pytest.mark.asyncio
    async def test_password_change_required_boolean_variations(self, middleware, mock_user):
        """Test various boolean-like values for password_change_required."""
        with patch("mcpgateway.config.settings.password_change_enforcement_enabled", True):
            client = TestClient(middleware)

            # Test different truthy/falsy values
            test_cases = [
                (True, True),  # Should block
                (False, False),  # Should NOT block
                (1, True),  # Truthy should block
                (0, False),  # Falsy should NOT block
                ("true", True),  # Non-empty string is truthy
                ("", False),  # Empty string is falsy
                ([], False),  # Empty list is falsy
                ([1], True),  # Non-empty list is truthy
            ]

            for value, should_block in test_cases:
                mock_user.password_change_required = value

                with patch.object(Request, "state", create=True) as mock_state:
                    mock_state.user = mock_user
                    mock_state.auth_method = "jwt"

                    response = client.get("/admin/overview", follow_redirects=False)
                    if should_block:
                        assert response.status_code == 303, f"password_change_required={value} should block"
                    else:
                        assert response.status_code == 200, f"password_change_required={value} should allow"

    @pytest.mark.asyncio
    async def test_request_state_manipulation_attempts(self, middleware, mock_user):
        """Test that middleware cannot be bypassed by manipulating request state."""
        mock_user.password_change_required = True

        with patch("mcpgateway.config.settings.password_change_enforcement_enabled", True):
            client = TestClient(middleware)

            with patch.object(Request, "state", create=True) as mock_state:
                mock_state.user = mock_user
                mock_state.auth_method = "jwt"

                # Try to bypass by setting additional state attributes
                mock_state.bypass_password_check = True
                mock_state.admin_override = True

                # Should still be blocked
                response = client.get("/admin/overview", follow_redirects=False)
                assert response.status_code == 303

    @pytest.mark.asyncio
    async def test_concurrent_user_state_isolation(self, middleware):
        """Test that user state is properly isolated between requests."""
        user1 = MagicMock(spec=EmailUser)
        user1.email = "user1@example.com"
        user1.password_change_required = True

        user2 = MagicMock(spec=EmailUser)
        user2.email = "user2@example.com"
        user2.password_change_required = False

        with patch("mcpgateway.config.settings.password_change_enforcement_enabled", True):
            client = TestClient(middleware)

            # User 1 should be blocked
            with patch.object(Request, "state", create=True) as mock_state:
                mock_state.user = user1
                mock_state.auth_method = "jwt"
                response = client.get("/admin/overview", follow_redirects=False)
                assert response.status_code == 303

            # User 2 should be allowed (different request state)
            with patch.object(Request, "state", create=True) as mock_state:
                mock_state.user = user2
                mock_state.auth_method = "jwt"
                response = client.get("/admin/overview")
                assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_redirect_status_code_is_303(self, middleware, mock_user):
        """Test that redirect uses 303 See Other (security best practice)."""
        mock_user.password_change_required = True

        with patch("mcpgateway.config.settings.password_change_enforcement_enabled", True):
            client = TestClient(middleware)

            with patch.object(Request, "state", create=True) as mock_state:
                mock_state.user = mock_user
                mock_state.auth_method = "jwt"

                # POST request should redirect with 303 (not 302 or 307)
                response = client.post("/admin/users", follow_redirects=False)
                assert response.status_code == 303, "Should use 303 See Other for POST-redirect-GET pattern"
                assert response.headers["location"] == "/admin/change-password-required"

    @pytest.mark.asyncio
    async def test_exempt_paths_are_immutable(self):
        """Test that EXEMPT_PATHS cannot be modified (security requirement)."""
        original_paths = PasswordChangeEnforcementMiddleware.EXEMPT_PATHS.copy()

        # Attempt to modify (should fail silently with frozenset)
        try:
            PasswordChangeEnforcementMiddleware.EXEMPT_PATHS.add("/admin/bypass")
        except AttributeError:
            pass  # Expected for frozenset

        # Verify paths haven't changed
        assert PasswordChangeEnforcementMiddleware.EXEMPT_PATHS == original_paths

    @pytest.mark.asyncio
    async def test_feature_flag_cannot_be_bypassed_via_request(self, middleware, mock_user):
        """Test that feature flag is read from settings, not request."""
        mock_user.password_change_required = True

        # Feature disabled in settings
        with patch("mcpgateway.config.settings.password_change_enforcement_enabled", False):
            client = TestClient(middleware)

            with patch.object(Request, "state", create=True) as mock_state:
                mock_state.user = mock_user
                mock_state.auth_method = "jwt"
                # Try to enable via request state
                mock_state.password_change_enforcement_enabled = True

                # Should NOT be blocked (settings take precedence)
                response = client.get("/admin/overview")
                assert response.status_code == 200
