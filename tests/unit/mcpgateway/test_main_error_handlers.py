# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_main_error_handlers.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for error handling paths in main.py endpoints to improve coverage.
Targets uncovered exception handlers in gateway, A2A, tool, and resource routes.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy.exc import IntegrityError
import jwt
import pytest

# First-Party
from mcpgateway.config import settings
from mcpgateway.services.gateway_service import (
    GatewayConnectionError,
    GatewayDuplicateConflictError,
    GatewayNameConflictError,
    GatewayNotFoundError,
)

TEST_JWT_SECRET = "unit-test-jwt-secret-key-with-minimum-32-bytes"


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #


@pytest.fixture
def test_client(app_with_temp_db):
    """Return a TestClient with auth dependencies overridden."""
    # First-Party
    from mcpgateway.db import EmailUser
    from mcpgateway.middleware.rbac import get_current_user_with_permissions
    from mcpgateway.utils.verify_credentials import require_auth

    mock_user = EmailUser(
        email="test_user@example.com",
        full_name="Test User",
        is_admin=True,
        is_active=True,
        auth_provider="test",
    )

    app_with_temp_db.dependency_overrides[require_auth] = lambda: "test_user"

    # Use a strong JWT secret during tests to avoid short-key warnings.
    original_jwt_secret = settings.jwt_secret_key
    if hasattr(original_jwt_secret, "get_secret_value") and callable(getattr(original_jwt_secret, "get_secret_value", None)):
        settings.jwt_secret_key = SecretStr(TEST_JWT_SECRET)
    else:
        settings.jwt_secret_key = TEST_JWT_SECRET

    # First-Party
    from mcpgateway.auth import get_current_user

    app_with_temp_db.dependency_overrides[get_current_user] = lambda credentials=None, db=None: mock_user

    def mock_get_current_user_with_permissions(request=None, credentials=None, jwt_token=None):
        return {"email": "test_user@example.com", "full_name": "Test User", "is_admin": True, "ip_address": "127.0.0.1", "user_agent": "test", "db": None}

    app_with_temp_db.dependency_overrides[get_current_user_with_permissions] = mock_get_current_user_with_permissions

    # First-Party
    from mcpgateway.services.permission_service import PermissionService

    if not hasattr(PermissionService, "_original_check_permission"):
        PermissionService._original_check_permission = PermissionService.check_permission

    async def mock_check_permission(self, user_email: str, permission: str, resource_type=None, resource_id=None, team_id=None, ip_address=None, user_agent=None) -> bool:
        return True

    PermissionService.check_permission = mock_check_permission

    # Mock security logger
    mock_sec_logger = MagicMock()
    mock_sec_logger.log_authentication_attempt = MagicMock(return_value=None)
    mock_sec_logger.log_security_event = MagicMock(return_value=None)
    sec_patcher = patch("mcpgateway.middleware.auth_middleware.security_logger", mock_sec_logger)
    sec_patcher.start()

    client = TestClient(app_with_temp_db)
    yield client

    settings.jwt_secret_key = original_jwt_secret
    app_with_temp_db.dependency_overrides.pop(require_auth, None)
    app_with_temp_db.dependency_overrides.pop(get_current_user, None)
    app_with_temp_db.dependency_overrides.pop(get_current_user_with_permissions, None)
    sec_patcher.stop()
    if hasattr(PermissionService, "_original_check_permission"):
        PermissionService.check_permission = PermissionService._original_check_permission


@pytest.fixture
def mock_jwt_token():
    """Create a valid JWT token for testing."""
    payload = {"sub": "test_user@example.com", "email": "test_user@example.com", "iss": "mcpgateway", "aud": "mcpgateway-api"}
    secret = settings.jwt_secret_key
    if hasattr(secret, "get_secret_value") and callable(getattr(secret, "get_secret_value", None)):
        secret = secret.get_secret_value()
    algorithm = settings.jwt_algorithm
    return jwt.encode(payload, secret, algorithm=algorithm)


@pytest.fixture
def auth_headers(mock_jwt_token):
    """Default auth header."""
    return {"Authorization": f"Bearer {mock_jwt_token}"}


# --------------------------------------------------------------------------- #
# Gateway Error Handler Tests                                                  #
# --------------------------------------------------------------------------- #


class TestGatewayCreateErrorHandlers:
    """Tests for error handling in gateway create endpoint."""

    def test_register_gateway_connection_error(self, test_client, auth_headers):
        """Test GatewayConnectionError handling in register_gateway."""
        with patch("mcpgateway.main.gateway_service.register_gateway", new_callable=AsyncMock) as mock_register:
            mock_register.side_effect = GatewayConnectionError("Connection failed")

            gateway_data = {
                "name": "test-gateway",
                "url": "http://localhost:9000",
                "description": "Test gateway",
            }
            response = test_client.post("/gateways/", json=gateway_data, headers=auth_headers)
            assert response.status_code == 502
            assert "Connection failed" in response.json()["message"]

    def test_register_gateway_value_error(self, test_client, auth_headers):
        """Test ValueError handling in register_gateway."""
        with patch("mcpgateway.main.gateway_service.register_gateway", new_callable=AsyncMock) as mock_register:
            mock_register.side_effect = ValueError("Invalid input")

            gateway_data = {
                "name": "test-gateway",
                "url": "http://localhost:9000",
                "description": "Test gateway",
            }
            response = test_client.post("/gateways/", json=gateway_data, headers=auth_headers)
            assert response.status_code == 400
            assert "Unable to process input" in response.json()["message"]

    def test_register_gateway_name_conflict_error(self, test_client, auth_headers):
        """Test GatewayNameConflictError handling in register_gateway."""
        with patch("mcpgateway.main.gateway_service.register_gateway", new_callable=AsyncMock) as mock_register:
            mock_register.side_effect = GatewayNameConflictError("Name already exists")

            gateway_data = {
                "name": "test-gateway",
                "url": "http://localhost:9000",
                "description": "Test gateway",
            }
            response = test_client.post("/gateways/", json=gateway_data, headers=auth_headers)
            assert response.status_code == 409
            assert "name already exists" in response.json()["message"]

    def test_register_gateway_duplicate_conflict_error(self, test_client, auth_headers):
        """Test GatewayDuplicateConflictError handling in register_gateway."""
        with patch("mcpgateway.main.gateway_service.register_gateway", new_callable=AsyncMock) as mock_register:
            # Create a mock DbGateway object
            mock_gateway = MagicMock()
            mock_gateway.url = "http://localhost:9000"
            mock_gateway.id = "existing-id"
            mock_gateway.enabled = True
            mock_gateway.visibility = "public"
            mock_gateway.team_id = None
            mock_gateway.name = "existing-gateway"
            mock_gateway.owner_email = "user@example.com"

            mock_register.side_effect = GatewayDuplicateConflictError(duplicate_gateway=mock_gateway)

            gateway_data = {
                "name": "test-gateway",
                "url": "http://localhost:9000",
                "description": "Test gateway",
            }
            response = test_client.post("/gateways/", json=gateway_data, headers=auth_headers)
            assert response.status_code == 409
            assert "already exists" in response.json()["message"]

    def test_register_gateway_runtime_error(self, test_client, auth_headers):
        """Test RuntimeError handling in register_gateway."""
        with patch("mcpgateway.main.gateway_service.register_gateway", new_callable=AsyncMock) as mock_register:
            mock_register.side_effect = RuntimeError("Unexpected runtime error")

            gateway_data = {
                "name": "test-gateway",
                "url": "http://localhost:9000",
                "description": "Test gateway",
            }
            response = test_client.post("/gateways/", json=gateway_data, headers=auth_headers)
            assert response.status_code == 500
            assert "Error during execution" in response.json()["message"]

    def test_register_gateway_integrity_error(self, test_client, auth_headers):
        """Test IntegrityError handling in register_gateway."""
        with patch("mcpgateway.main.gateway_service.register_gateway", new_callable=AsyncMock) as mock_register:
            # Create a realistic IntegrityError mock
            mock_error = IntegrityError("INSERT failed", {}, Exception("UNIQUE constraint failed"))
            mock_register.side_effect = mock_error

            gateway_data = {
                "name": "test-gateway",
                "url": "http://localhost:9000",
                "description": "Test gateway",
            }
            response = test_client.post("/gateways/", json=gateway_data, headers=auth_headers)
            assert response.status_code == 409

    def test_register_gateway_unexpected_error(self, test_client, auth_headers):
        """Test unexpected exception handling in register_gateway."""
        with patch("mcpgateway.main.gateway_service.register_gateway", new_callable=AsyncMock) as mock_register:
            mock_register.side_effect = Exception("Unknown error")

            gateway_data = {
                "name": "test-gateway",
                "url": "http://localhost:9000",
                "description": "Test gateway",
            }
            response = test_client.post("/gateways/", json=gateway_data, headers=auth_headers)
            assert response.status_code == 500
            assert "Unexpected error" in response.json()["message"]


class TestGatewayUpdateErrorHandlers:
    """Tests for error handling in gateway update endpoint."""

    def test_update_gateway_permission_error(self, test_client, auth_headers):
        """Test PermissionError handling in update_gateway."""
        with patch("mcpgateway.main.gateway_service.update_gateway", new_callable=AsyncMock) as mock_update:
            mock_update.side_effect = PermissionError("Not authorized")

            gateway_data = {
                "name": "updated-gateway",
                "url": "http://localhost:9000",
                "description": "Updated gateway",
            }
            response = test_client.put("/gateways/test-id", json=gateway_data, headers=auth_headers)
            assert response.status_code == 403

    def test_update_gateway_not_found_error(self, test_client, auth_headers):
        """Test GatewayNotFoundError handling in update_gateway."""
        with patch("mcpgateway.main.gateway_service.update_gateway", new_callable=AsyncMock) as mock_update:
            mock_update.side_effect = GatewayNotFoundError("Gateway not found")

            gateway_data = {
                "name": "updated-gateway",
                "url": "http://localhost:9000",
                "description": "Updated gateway",
            }
            response = test_client.put("/gateways/nonexistent-id", json=gateway_data, headers=auth_headers)
            assert response.status_code == 404

    def test_update_gateway_connection_error(self, test_client, auth_headers):
        """Test GatewayConnectionError handling in update_gateway."""
        with patch("mcpgateway.main.gateway_service.update_gateway", new_callable=AsyncMock) as mock_update:
            mock_update.side_effect = GatewayConnectionError("Connection failed")

            gateway_data = {
                "name": "updated-gateway",
                "url": "http://localhost:9000",
                "description": "Updated gateway",
            }
            response = test_client.put("/gateways/test-id", json=gateway_data, headers=auth_headers)
            assert response.status_code == 502
            assert "Connection failed" in response.json()["message"]

    def test_update_gateway_value_error(self, test_client, auth_headers):
        """Test ValueError handling in update_gateway."""
        with patch("mcpgateway.main.gateway_service.update_gateway", new_callable=AsyncMock) as mock_update:
            mock_update.side_effect = ValueError("Invalid value")

            gateway_data = {
                "name": "updated-gateway",
                "url": "http://localhost:9000",
                "description": "Updated gateway",
            }
            response = test_client.put("/gateways/test-id", json=gateway_data, headers=auth_headers)
            assert response.status_code == 400

    def test_update_gateway_name_conflict_error(self, test_client, auth_headers):
        """Test GatewayNameConflictError handling in update_gateway."""
        with patch("mcpgateway.main.gateway_service.update_gateway", new_callable=AsyncMock) as mock_update:
            mock_update.side_effect = GatewayNameConflictError("Name conflict")

            gateway_data = {
                "name": "conflicting-name",
                "url": "http://localhost:9000",
                "description": "Updated gateway",
            }
            response = test_client.put("/gateways/test-id", json=gateway_data, headers=auth_headers)
            assert response.status_code == 409

    def test_update_gateway_duplicate_conflict_error(self, test_client, auth_headers):
        """Test GatewayDuplicateConflictError handling in update_gateway."""
        with patch("mcpgateway.main.gateway_service.update_gateway", new_callable=AsyncMock) as mock_update:
            # Create a mock DbGateway object
            mock_gateway = MagicMock()
            mock_gateway.url = "http://localhost:9000"
            mock_gateway.id = "existing-id"
            mock_gateway.enabled = True
            mock_gateway.visibility = "public"
            mock_gateway.team_id = None
            mock_gateway.name = "existing-gateway"
            mock_gateway.owner_email = "user@example.com"

            mock_update.side_effect = GatewayDuplicateConflictError(duplicate_gateway=mock_gateway)

            gateway_data = {
                "name": "updated-gateway",
                "url": "http://localhost:9000",
                "description": "Updated gateway",
            }
            response = test_client.put("/gateways/test-id", json=gateway_data, headers=auth_headers)
            assert response.status_code == 409

    def test_update_gateway_runtime_error(self, test_client, auth_headers):
        """Test RuntimeError handling in update_gateway."""
        with patch("mcpgateway.main.gateway_service.update_gateway", new_callable=AsyncMock) as mock_update:
            mock_update.side_effect = RuntimeError("Runtime error")

            gateway_data = {
                "name": "updated-gateway",
                "url": "http://localhost:9000",
                "description": "Updated gateway",
            }
            response = test_client.put("/gateways/test-id", json=gateway_data, headers=auth_headers)
            assert response.status_code == 500

    def test_update_gateway_integrity_error(self, test_client, auth_headers):
        """Test IntegrityError handling in update_gateway."""
        with patch("mcpgateway.main.gateway_service.update_gateway", new_callable=AsyncMock) as mock_update:
            mock_error = IntegrityError("UPDATE failed", {}, Exception("constraint violation"))
            mock_update.side_effect = mock_error

            gateway_data = {
                "name": "updated-gateway",
                "url": "http://localhost:9000",
                "description": "Updated gateway",
            }
            response = test_client.put("/gateways/test-id", json=gateway_data, headers=auth_headers)
            assert response.status_code == 409

    def test_update_gateway_unexpected_error(self, test_client, auth_headers):
        """Test unexpected exception handling in update_gateway."""
        with patch("mcpgateway.main.gateway_service.update_gateway", new_callable=AsyncMock) as mock_update:
            mock_update.side_effect = Exception("Unknown error")

            gateway_data = {
                "name": "updated-gateway",
                "url": "http://localhost:9000",
                "description": "Updated gateway",
            }
            response = test_client.put("/gateways/test-id", json=gateway_data, headers=auth_headers)
            assert response.status_code == 500




# --------------------------------------------------------------------------- #
# A2A Agent Error Handler Tests                                                #
# --------------------------------------------------------------------------- #


class TestA2AAgentErrorHandlers:
    """Tests for error handling in A2A agent endpoints."""

    def test_update_a2a_agent_permission_error(self, test_client, auth_headers):
        """Test PermissionError handling in update_a2a_agent."""
        with patch("mcpgateway.main.a2a_service") as mock_service:
            mock_service.update_agent = AsyncMock(side_effect=PermissionError("Not authorized"))

            agent_data = {
                "name": "test-agent",
                "description": "Test agent",
                "url": "http://localhost:9000",
            }
            response = test_client.put("/a2a/test-agent-id", json=agent_data, headers=auth_headers)
            assert response.status_code == 403

    def test_update_a2a_agent_not_found_error(self, test_client, auth_headers):
        """Test A2AAgentNotFoundError handling in update_a2a_agent."""
        # First-Party
        from mcpgateway.services.a2a_service import A2AAgentNotFoundError

        with patch("mcpgateway.main.a2a_service") as mock_service:
            mock_service.update_agent = AsyncMock(side_effect=A2AAgentNotFoundError("Agent not found"))

            agent_data = {
                "name": "test-agent",
                "description": "Test agent",
                "url": "http://localhost:9000",
            }
            response = test_client.put("/a2a/nonexistent-id", json=agent_data, headers=auth_headers)
            assert response.status_code == 404

    def test_update_a2a_agent_name_conflict_error(self, test_client, auth_headers):
        """Test A2AAgentNameConflictError handling in update_a2a_agent."""
        # First-Party
        from mcpgateway.services.a2a_service import A2AAgentNameConflictError

        with patch("mcpgateway.main.a2a_service") as mock_service:
            mock_service.update_agent = AsyncMock(side_effect=A2AAgentNameConflictError("Name conflict"))

            agent_data = {
                "name": "conflicting-name",
                "description": "Test agent",
                "url": "http://localhost:9000",
            }
            response = test_client.put("/a2a/test-id", json=agent_data, headers=auth_headers)
            assert response.status_code == 409

    def test_update_a2a_agent_general_error(self, test_client, auth_headers):
        """Test A2AAgentError handling in update_a2a_agent."""
        # First-Party
        from mcpgateway.services.a2a_service import A2AAgentError

        with patch("mcpgateway.main.a2a_service") as mock_service:
            mock_service.update_agent = AsyncMock(side_effect=A2AAgentError("General error"))

            agent_data = {
                "name": "test-agent",
                "description": "Test agent",
                "url": "http://localhost:9000",
            }
            response = test_client.put("/a2a/test-id", json=agent_data, headers=auth_headers)
            assert response.status_code == 400

    def test_update_a2a_agent_integrity_error(self, test_client, auth_headers):
        """Test IntegrityError handling in update_a2a_agent."""
        with patch("mcpgateway.main.a2a_service") as mock_service:
            mock_error = IntegrityError("UPDATE failed", {}, Exception("constraint violation"))
            mock_service.update_agent = AsyncMock(side_effect=mock_error)

            agent_data = {
                "name": "test-agent",
                "description": "Test agent",
                "url": "http://localhost:9000",
            }
            response = test_client.put("/a2a/test-id", json=agent_data, headers=auth_headers)
            assert response.status_code == 409

    def test_set_a2a_agent_state_permission_error(self, test_client, auth_headers):
        """Test PermissionError handling in set_a2a_agent_state."""
        with patch("mcpgateway.main.a2a_service") as mock_service:
            mock_service.set_agent_state = AsyncMock(side_effect=PermissionError("Not authorized"))

            response = test_client.post("/a2a/test-id/state?activate=true", headers=auth_headers)
            assert response.status_code == 403

    def test_set_a2a_agent_state_not_found_error(self, test_client, auth_headers):
        """Test A2AAgentNotFoundError handling in set_a2a_agent_state."""
        # First-Party
        from mcpgateway.services.a2a_service import A2AAgentNotFoundError

        with patch("mcpgateway.main.a2a_service") as mock_service:
            mock_service.set_agent_state = AsyncMock(side_effect=A2AAgentNotFoundError("Agent not found"))

            response = test_client.post("/a2a/nonexistent-id/state?activate=true", headers=auth_headers)
            assert response.status_code == 404

    def test_set_a2a_agent_state_general_error(self, test_client, auth_headers):
        """Test A2AAgentError handling in set_a2a_agent_state."""
        # First-Party
        from mcpgateway.services.a2a_service import A2AAgentError

        with patch("mcpgateway.main.a2a_service") as mock_service:
            mock_service.set_agent_state = AsyncMock(side_effect=A2AAgentError("General error"))

            response = test_client.post("/a2a/test-id/state?activate=false", headers=auth_headers)
            assert response.status_code == 400


# --------------------------------------------------------------------------- #
# Tool Service Error Handler Tests                                             #
# --------------------------------------------------------------------------- #


class TestToolServiceErrorHandlers:
    """Tests for error handling in tool endpoints."""

    def test_update_tool_permission_error(self, test_client, auth_headers):
        """Test PermissionError handling in update_tool."""
        with patch("mcpgateway.main.tool_service.update_tool", new_callable=AsyncMock) as mock_update:
            mock_update.side_effect = PermissionError("Not authorized")

            tool_data = {
                "name": "updated-tool",
                "description": "Updated tool",
            }
            response = test_client.put("/tools/test-id", json=tool_data, headers=auth_headers)
            assert response.status_code == 403

    def test_delete_tool_permission_error(self, test_client, auth_headers):
        """Test PermissionError handling in delete_tool."""
        with patch("mcpgateway.main.tool_service.delete_tool", new_callable=AsyncMock) as mock_delete:
            mock_delete.side_effect = PermissionError("Not authorized")

            response = test_client.delete("/tools/test-id", headers=auth_headers)
            assert response.status_code == 403


# --------------------------------------------------------------------------- #
# Resource Service Error Handler Tests                                         #
# --------------------------------------------------------------------------- #


class TestResourceServiceErrorHandlers:
    """Tests for error handling in resource endpoints."""

    def test_update_resource_permission_error(self, test_client, auth_headers):
        """Test PermissionError handling in update_resource."""
        with patch("mcpgateway.main.resource_service.update_resource", new_callable=AsyncMock) as mock_update:
            mock_update.side_effect = PermissionError("Not authorized")

            resource_data = {
                "name": "updated-resource",
                "description": "Updated resource",
            }
            response = test_client.put("/resources/test-id", json=resource_data, headers=auth_headers)
            assert response.status_code == 403


# --------------------------------------------------------------------------- #
# Prompt Service Error Handler Tests                                           #
# --------------------------------------------------------------------------- #


class TestPromptServiceErrorHandlers:
    """Tests for error handling in prompt endpoints."""

    def test_update_prompt_permission_error(self, test_client, auth_headers):
        """Test PermissionError handling in update_prompt."""
        with patch("mcpgateway.main.prompt_service.update_prompt", new_callable=AsyncMock) as mock_update:
            mock_update.side_effect = PermissionError("Not authorized")

            prompt_data = {
                "name": "updated-prompt",
                "description": "Updated prompt",
            }
            response = test_client.put("/prompts/test-id", json=prompt_data, headers=auth_headers)
            assert response.status_code == 403


# --------------------------------------------------------------------------- #
# Server Service Error Handler Tests                                           #
# --------------------------------------------------------------------------- #


class TestServerServiceErrorHandlers:
    """Tests for error handling in server endpoints."""

    def test_update_server_permission_error(self, test_client, auth_headers):
        """Test PermissionError handling in update_server."""
        with patch("mcpgateway.main.server_service.update_server", new_callable=AsyncMock) as mock_update:
            mock_update.side_effect = PermissionError("Not authorized")

            server_data = {
                "name": "updated-server",
                "description": "Updated server",
            }
            response = test_client.put("/servers/test-id", json=server_data, headers=auth_headers)
            assert response.status_code == 403
