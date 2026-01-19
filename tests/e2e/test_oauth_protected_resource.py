# -*- coding: utf-8 -*-
"""Location: ./tests/e2e/test_oauth_protected_resource.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

End-to-end tests for virtual server well-known endpoints.

This module tests the /servers/{server_id}/.well-known/* endpoints including:
- oauth-protected-resource (RFC 9728 OAuth Protected Resource Metadata)
- robots.txt, security.txt, ai.txt, dnt-policy.txt

OAuth Protected Resource Metadata Test Scenarios:
1. Server WITHOUT oauth_enabled or oauth_config -> 404
2. Server WITH oauth_enabled=True and valid oauth_config -> 200 + RFC 9728 JSON
3. Server with oauth_enabled=False (even with oauth_config) -> 404
4. Server with visibility="private" (non-public) -> 404
5. Disabled server (enabled=False) -> 404
6. Non-existent server ID -> 404
7. Server with multiple authorization_servers -> 200 + list of auth servers
8. Request WITHOUT auth headers (per RFC 9728, endpoint is public) -> 200

Well-Known Files Test Scenarios:
1. robots.txt on public server -> 200 with configured content
2. Private server well-known files -> 404
3. Disabled server well-known files -> 404
4. Non-existent server well-known files -> 404
5. Non-existent well-known file -> 404
"""

# Standard Library
import os
import tempfile
import time
from typing import AsyncGenerator
from unittest.mock import MagicMock
from unittest.mock import patch as mock_patch

# Third-Party
import jwt
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
# Replace RBAC decorators with no-ops BEFORE importing app
import mcpgateway.middleware.rbac as rbac_module


def noop_decorator(*args, **kwargs):
    """No-op decorator that just returns the function unchanged."""

    def decorator(func):
        return func

    if len(args) == 1 and callable(args[0]) and not kwargs:
        return args[0]
    else:
        return decorator


rbac_module.require_permission = noop_decorator  # pyrefly: ignore[bad-assignment]
rbac_module.require_admin_permission = noop_decorator  # pyrefly: ignore[bad-assignment]
rbac_module.require_any_permission = noop_decorator  # pyrefly: ignore[bad-assignment]

# Now import app after patching RBAC
with mock_patch("mcpgateway.bootstrap_db.main"):
    # First-Party
    from mcpgateway.config import settings
    from mcpgateway.db import Base
    from mcpgateway.db import get_db as db_get_db
    from mcpgateway.main import app, get_db


# Test Configuration
TEST_USER = "testuser"


def generate_test_jwt():
    """Generate a valid JWT token for testing."""
    payload = {
        "sub": "test_user",
        "exp": int(time.time()) + 3600,
        "teams": [],
    }
    secret = settings.jwt_secret_key.get_secret_value()
    algorithm = settings.jwt_algorithm
    return jwt.encode(payload, secret, algorithm=algorithm)


TEST_AUTH_HEADER = {"Authorization": f"Bearer {generate_test_jwt()}"}


@pytest_asyncio.fixture
async def oauth_test_db():
    """Create a temporary SQLite database for OAuth testing.

    This fixture creates a fresh database for each test, ensuring complete
    isolation between tests.
    """
    db_fd, db_path = tempfile.mkstemp(suffix=".db")

    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(bind=engine)

    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    # Override authentication for server creation (which requires auth)
    # First-Party
    from mcpgateway.auth import get_current_user
    from mcpgateway.middleware.rbac import get_current_user_with_permissions
    from mcpgateway.utils.create_jwt_token import get_jwt_token
    from mcpgateway.utils.verify_credentials import require_admin_auth, require_auth

    # Local
    from tests.utils.rbac_mocks import create_mock_email_user, create_mock_user_context, MockPermissionService

    def override_auth():
        return TEST_USER

    mock_email_user = create_mock_email_user(email="testuser@example.com", full_name="Test User", is_admin=True, is_active=True)

    async def mock_require_admin_auth():
        return "testuser@example.com"

    async def mock_get_jwt_token():
        return generate_test_jwt()

    test_user_context = create_mock_user_context(email="testuser@example.com", full_name="Test User", is_admin=True)
    test_user_context["db"] = TestSessionLocal()

    async def simple_mock_user_with_permissions():
        return test_user_context

    # First-Party
    from mcpgateway.middleware.rbac import get_permission_service

    def mock_get_permission_service(*args, **kwargs):
        return MockPermissionService(always_grant=True)

    app.dependency_overrides[require_auth] = override_auth
    app.dependency_overrides[get_current_user] = lambda: mock_email_user
    app.dependency_overrides[require_admin_auth] = mock_require_admin_auth
    app.dependency_overrides[get_jwt_token] = mock_get_jwt_token
    app.dependency_overrides[get_current_user_with_permissions] = simple_mock_user_with_permissions
    app.dependency_overrides[get_permission_service] = mock_get_permission_service
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[db_get_db] = override_get_db  # Also override the db module's get_db

    # Mock security_logger to prevent database access issues
    mock_sec_logger = MagicMock()
    mock_sec_logger.log_authentication_attempt = MagicMock(return_value=None)
    mock_sec_logger.log_security_event = MagicMock(return_value=None)
    sec_patcher = mock_patch("mcpgateway.middleware.auth_middleware.security_logger", mock_sec_logger)
    sec_patcher.start()

    yield engine

    # Cleanup
    sec_patcher.stop()
    app.dependency_overrides.clear()
    os.close(db_fd)
    os.unlink(db_path)


@pytest_asyncio.fixture
async def client(oauth_test_db) -> AsyncGenerator[AsyncClient, None]:
    """Create an async test client with the test database."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestOAuthProtectedResourceMetadata:
    """Tests for RFC 9728 OAuth Protected Resource Metadata endpoint."""

    async def _create_server(self, client: AsyncClient, payload: dict) -> str:
        """Helper to create a server and return its ID."""
        response = await client.post("/servers", json=payload, headers=TEST_AUTH_HEADER)
        assert response.status_code == 201, f"Failed to create server: {response.text}"
        return response.json()["id"]

    async def _disable_server(self, client: AsyncClient, server_id: str):
        """Helper to disable a server using the toggle endpoint."""
        response = await client.post(f"/servers/{server_id}/state?activate=false", headers=TEST_AUTH_HEADER)
        assert response.status_code == 200, f"Failed to disable server: {response.text}"

    async def test_server_without_oauth_returns_404(self, client: AsyncClient):
        """Scenario 1: Server WITHOUT oauth_enabled or oauth_config returns 404."""
        server_id = await self._create_server(
            client,
            {
                "server": {
                    "name": "server_no_oauth",
                    "description": "Server without OAuth configuration",
                },
                "team_id": None,
                "visibility": "public",
            },
        )

        response = await client.get(f"/servers/{server_id}/.well-known/oauth-protected-resource")
        assert response.status_code == 404
        assert "OAuth not enabled" in response.json()["detail"]

    async def test_server_with_oauth_enabled_returns_metadata(self, client: AsyncClient):
        """Scenario 2: Server WITH oauth_enabled=True and valid oauth_config returns 200 + RFC 9728 JSON."""
        server_id = await self._create_server(
            client,
            {
                "server": {
                    "name": "server_with_oauth",
                    "description": "Server with OAuth configuration",
                    "oauth_enabled": True,
                    "oauth_config": {
                        "authorization_server": "https://idp.example.com",
                        "token_endpoint": "https://idp.example.com/oauth/token",
                        "scopes_supported": ["openid", "profile", "email"],
                    },
                },
                "team_id": None,
                "visibility": "public",
            },
        )

        response = await client.get(f"/servers/{server_id}/.well-known/oauth-protected-resource")
        assert response.status_code == 200

        # Verify RFC 9728 required fields
        data = response.json()
        assert "resource" in data
        assert server_id in data["resource"]
        assert "authorization_servers" in data
        assert isinstance(data["authorization_servers"], list)
        assert "https://idp.example.com" in data["authorization_servers"]
        assert "bearer_methods_supported" in data
        assert "header" in data["bearer_methods_supported"]

        # Verify optional scopes field
        assert "scopes_supported" in data
        assert "openid" in data["scopes_supported"]
        assert "profile" in data["scopes_supported"]
        assert "email" in data["scopes_supported"]

        # Verify headers
        assert "application/json" in response.headers["content-type"]
        assert "public" in response.headers.get("cache-control", "")

    async def test_server_with_oauth_disabled_returns_404(self, client: AsyncClient):
        """Scenario 3: Server with oauth_enabled=False (even with oauth_config) returns 404."""
        server_id = await self._create_server(
            client,
            {
                "server": {
                    "name": "server_oauth_disabled",
                    "description": "Server with OAuth disabled",
                    "oauth_enabled": False,
                    "oauth_config": {
                        "authorization_server": "https://idp.example.com",
                    },
                },
                "team_id": None,
                "visibility": "public",
            },
        )

        response = await client.get(f"/servers/{server_id}/.well-known/oauth-protected-resource")
        assert response.status_code == 404
        assert "OAuth not enabled" in response.json()["detail"]

    async def test_private_server_returns_404(self, client: AsyncClient):
        """Scenario 4: Server with visibility="private" (non-public) returns 404."""
        server_id = await self._create_server(
            client,
            {
                "server": {
                    "name": "server_private",
                    "description": "Private server with OAuth",
                    "visibility": "private",  # Must be inside server object due to default precedence
                    "oauth_enabled": True,
                    "oauth_config": {
                        "authorization_server": "https://idp.example.com",
                    },
                },
                "team_id": None,
            },
        )

        response = await client.get(f"/servers/{server_id}/.well-known/oauth-protected-resource")
        assert response.status_code == 404
        # Should not leak that the server exists (just "not found")
        assert "not found" in response.json()["detail"].lower()

    async def test_disabled_server_returns_404(self, client: AsyncClient):
        """Scenario 5: Disabled server (enabled=False) returns 404."""
        server_id = await self._create_server(
            client,
            {
                "server": {
                    "name": "server_to_disable",
                    "description": "Server that will be disabled",
                    "oauth_enabled": True,
                    "oauth_config": {
                        "authorization_server": "https://idp.example.com",
                    },
                },
                "team_id": None,
                "visibility": "public",
            },
        )

        # Disable the server
        await self._disable_server(client, server_id)

        response = await client.get(f"/servers/{server_id}/.well-known/oauth-protected-resource")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    async def test_nonexistent_server_returns_404(self, client: AsyncClient):
        """Scenario 6: Non-existent server ID returns 404."""
        nonexistent_id = "00000000000000000000000000000000"

        response = await client.get(f"/servers/{nonexistent_id}/.well-known/oauth-protected-resource")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    async def test_server_with_multiple_authorization_servers(self, client: AsyncClient):
        """Scenario 7: Server with multiple authorization_servers returns 200 + list of auth servers."""
        server_id = await self._create_server(
            client,
            {
                "server": {
                    "name": "server_multi_auth",
                    "description": "Server with multiple authorization servers",
                    "oauth_enabled": True,
                    "oauth_config": {
                        "authorization_servers": [
                            "https://primary-idp.example.com",
                            "https://secondary-idp.example.com",
                            "https://tertiary-idp.example.com",
                        ],
                        "scopes_supported": ["read", "write"],
                    },
                },
                "team_id": None,
                "visibility": "public",
            },
        )

        response = await client.get(f"/servers/{server_id}/.well-known/oauth-protected-resource")
        assert response.status_code == 200

        data = response.json()
        assert "authorization_servers" in data
        assert len(data["authorization_servers"]) == 3
        assert "https://primary-idp.example.com" in data["authorization_servers"]
        assert "https://secondary-idp.example.com" in data["authorization_servers"]
        assert "https://tertiary-idp.example.com" in data["authorization_servers"]

    async def test_endpoint_accessible_without_auth_headers(self, client: AsyncClient):
        """Scenario 8: Request WITHOUT auth headers (per RFC 9728, endpoint is public) returns 200."""
        server_id = await self._create_server(
            client,
            {
                "server": {
                    "name": "server_public_endpoint",
                    "description": "Server for testing public endpoint access",
                    "oauth_enabled": True,
                    "oauth_config": {
                        "authorization_server": "https://idp.example.com",
                    },
                },
                "team_id": None,
                "visibility": "public",
            },
        )

        # Make request WITHOUT auth headers
        response = await client.get(f"/servers/{server_id}/.well-known/oauth-protected-resource")
        assert response.status_code == 200

        # Verify the response is valid RFC 9728 metadata
        data = response.json()
        assert "resource" in data
        assert "authorization_servers" in data
        assert "bearer_methods_supported" in data


class TestVirtualServerWellKnownFiles:
    """Tests for well-known files (robots.txt, security.txt, etc.) on virtual servers."""

    async def _create_server(self, client: AsyncClient, payload: dict) -> str:
        """Helper to create a server and return its ID."""
        response = await client.post("/servers", json=payload, headers=TEST_AUTH_HEADER)
        assert response.status_code == 201, f"Failed to create server: {response.text}"
        return response.json()["id"]

    async def _disable_server(self, client: AsyncClient, server_id: str):
        """Helper to disable a server using the toggle endpoint."""
        response = await client.post(f"/servers/{server_id}/state?activate=false", headers=TEST_AUTH_HEADER)
        assert response.status_code == 200, f"Failed to disable server: {response.text}"

    async def test_robots_txt_on_public_server(self, client: AsyncClient):
        """robots.txt on a public server returns 200 with configured content."""
        server_id = await self._create_server(
            client,
            {
                "server": {
                    "name": "server_robots_test",
                    "description": "Server for robots.txt testing",
                },
                "team_id": None,
                "visibility": "public",
            },
        )

        response = await client.get(f"/servers/{server_id}/.well-known/robots.txt")
        assert response.status_code == 200
        assert "text/plain" in response.headers["content-type"]
        # Default robots.txt should contain User-agent directive
        assert "User-agent" in response.text or "user-agent" in response.text.lower()
        # Should have cache headers
        assert "public" in response.headers.get("cache-control", "")

    async def test_private_server_well_known_returns_404(self, client: AsyncClient):
        """Well-known files on private server returns 404."""
        server_id = await self._create_server(
            client,
            {
                "server": {
                    "name": "server_private_wellknown",
                    "description": "Private server for well-known testing",
                    "visibility": "private",
                },
                "team_id": None,
            },
        )

        response = await client.get(f"/servers/{server_id}/.well-known/robots.txt")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    async def test_disabled_server_well_known_returns_404(self, client: AsyncClient):
        """Well-known files on disabled server returns 404."""
        server_id = await self._create_server(
            client,
            {
                "server": {
                    "name": "server_disabled_wellknown",
                    "description": "Server to be disabled for well-known testing",
                },
                "team_id": None,
                "visibility": "public",
            },
        )

        # Disable the server
        await self._disable_server(client, server_id)

        response = await client.get(f"/servers/{server_id}/.well-known/robots.txt")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    async def test_nonexistent_server_well_known_returns_404(self, client: AsyncClient):
        """Well-known files on non-existent server returns 404."""
        nonexistent_id = "00000000000000000000000000000000"

        response = await client.get(f"/servers/{nonexistent_id}/.well-known/robots.txt")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    async def test_nonexistent_well_known_file_returns_404(self, client: AsyncClient):
        """Non-existent well-known file returns 404."""
        server_id = await self._create_server(
            client,
            {
                "server": {
                    "name": "server_nonexistent_file",
                    "description": "Server for testing non-existent well-known file",
                },
                "team_id": None,
                "visibility": "public",
            },
        )

        response = await client.get(f"/servers/{server_id}/.well-known/nonexistent-file.txt")
        assert response.status_code == 404

    async def test_well_known_accessible_without_auth(self, client: AsyncClient):
        """Well-known files are accessible without authentication."""
        server_id = await self._create_server(
            client,
            {
                "server": {
                    "name": "server_noauth_wellknown",
                    "description": "Server for testing public well-known access",
                },
                "team_id": None,
                "visibility": "public",
            },
        )

        # Request without auth headers
        response = await client.get(f"/servers/{server_id}/.well-known/robots.txt")
        assert response.status_code == 200
        assert "text/plain" in response.headers["content-type"]


class TestWellKnownDisabledScenarios:
    """Tests for well_known_enabled=false scenarios on server-scoped endpoints."""

    async def _create_server(self, client: AsyncClient, payload: dict) -> str:
        """Helper to create a server and return its ID."""
        response = await client.post("/servers", json=payload, headers=TEST_AUTH_HEADER)
        assert response.status_code == 201, f"Failed to create server: {response.text}"
        return response.json()["id"]

    async def test_oauth_endpoint_returns_404_when_well_known_disabled(self, client: AsyncClient):
        """OAuth endpoint returns 404 when well_known_enabled is false."""
        server_id = await self._create_server(
            client,
            {
                "server": {
                    "name": "server_oauth_wellknown_disabled",
                    "description": "Server with OAuth for well-known disabled test",
                    "oauth_enabled": True,
                    "oauth_config": {
                        "authorization_server": "https://idp.example.com",
                    },
                },
                "team_id": None,
                "visibility": "public",
            },
        )

        # Temporarily disable well_known_enabled
        original_value = settings.well_known_enabled
        settings.well_known_enabled = False
        try:
            response = await client.get(f"/servers/{server_id}/.well-known/oauth-protected-resource")
            assert response.status_code == 404
            # Should return generic "Not found" to avoid leaking information
            assert response.json()["detail"] == "Not found"
        finally:
            settings.well_known_enabled = original_value

    async def test_robots_txt_returns_404_when_well_known_disabled(self, client: AsyncClient):
        """robots.txt returns 404 when well_known_enabled is false."""
        server_id = await self._create_server(
            client,
            {
                "server": {
                    "name": "server_robots_wellknown_disabled",
                    "description": "Server for well-known disabled test",
                },
                "team_id": None,
                "visibility": "public",
            },
        )

        # Temporarily disable well_known_enabled
        original_value = settings.well_known_enabled
        settings.well_known_enabled = False
        try:
            response = await client.get(f"/servers/{server_id}/.well-known/robots.txt")
            assert response.status_code == 404
            # Should return generic "Not found" to avoid leaking information
            assert response.json()["detail"] == "Not found"
        finally:
            settings.well_known_enabled = original_value

    async def test_nonexistent_server_returns_same_error_when_well_known_disabled(self, client: AsyncClient):
        """Non-existent server returns same error as valid server when well_known_enabled is false."""
        nonexistent_id = "00000000000000000000000000000000"

        # Temporarily disable well_known_enabled
        original_value = settings.well_known_enabled
        settings.well_known_enabled = False
        try:
            response = await client.get(f"/servers/{nonexistent_id}/.well-known/robots.txt")
            assert response.status_code == 404
            # Both valid and invalid servers should return "Not found" - no information leakage
            assert response.json()["detail"] == "Not found"
        finally:
            settings.well_known_enabled = original_value
