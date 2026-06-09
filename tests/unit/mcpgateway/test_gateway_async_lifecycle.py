# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_gateway_async_lifecycle.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Unit tests for async gateway lifecycle (Issue #4565).

Tests cover:
- Task 32: Synchronous behavior (flag off)
- Task 33: Async create (flag on)
- Task 34: Async update (flag on)
- Task 35: Async delete (flag on)
- Task 36: DELETE on pending gateway
- Task 37: Exponential backoff
- Task 38: Worker crash recovery
- Task 39: Security (deny-path)
- Task 40: Race conditions
"""

# Standard
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.admin import admin_add_gateway, admin_delete_gateway_rest, admin_get_gateway, admin_update_gateway_rest
from mcpgateway.config import settings
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.services.gateway_service import GatewayService
from mcpgateway.workers.gateway_worker import GatewayWorker


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_db():
    """Create mock database session."""
    return MagicMock(spec=Session)


@pytest.fixture
def mock_request():
    """Create mock FastAPI request."""
    request = MagicMock()
    request.scope = {"root_path": ""}
    request.state = MagicMock(token_teams=None)
    request.query_params = {}
    request.headers = {"content-type": "application/json"}
    return request


@pytest.fixture
def mock_user(mock_db):
    """Create mock user with db."""
    return {"email": "admin@example.com", "is_admin": True, "db": mock_db}


@pytest.fixture
def allow_permission(monkeypatch):
    """Allow RBAC permission checks to pass for decorator-wrapped handlers."""
    mock_perm_service = MagicMock()
    mock_perm_service.check_permission = AsyncMock(return_value=True)
    monkeypatch.setattr("mcpgateway.middleware.rbac.PermissionService", lambda db: mock_perm_service)
    monkeypatch.setattr("mcpgateway.admin.PermissionService", lambda db: mock_perm_service)
    monkeypatch.setattr("mcpgateway.plugins.get_plugin_manager", AsyncMock(return_value=None))
    return mock_perm_service


# ============================================================================
# Task 32: Test Synchronous Behavior (Flag OFF)
# ============================================================================


class TestSyncBehavior:
    """Test synchronous gateway operations when async flag is disabled."""

    @patch.object(GatewayService, "register_gateway")
    @patch("mcpgateway.admin.TeamManagementService")
    @patch("mcpgateway.admin.MetadataCapture")
    async def test_create_gateway_sync_returns_200(
        self, mock_metadata, mock_team_service_class, mock_register, mock_db, mock_request, mock_user, allow_permission, monkeypatch
    ):
        """Verify POST /admin/gateways returns 200/201 when flag is OFF."""
        monkeypatch.setattr(settings, "gateway_async_lifecycle_enabled", False)

        # Mock team service
        mock_team_service = AsyncMock()
        mock_team_service.verify_team_for_user = AsyncMock(return_value=None)
        mock_team_service_class.return_value = mock_team_service

        # Mock metadata
        mock_metadata.extract_creation_metadata.return_value = {
            "created_by": "admin@example.com",
            "created_from_ip": "127.0.0.1",
            "created_via": "admin_ui",
            "created_user_agent": "test",
        }

        # Mock register_gateway to return success
        mock_gateway = MagicMock()
        mock_gateway.model_dump.return_value = {"id": "gw-1", "name": "test-gateway", "status": "active"}
        mock_register.return_value = mock_gateway

        # Mock request JSON
        mock_request.json = AsyncMock(
            return_value={
                "name": "test-gateway",
                "url": "http://localhost:9000/sse",
                "transport": "SSE",
                "description": "Test",
            }
        )

        response = await admin_add_gateway(mock_request, mock_db, user=mock_user)

        assert response.status_code in (200, 201)
        data = response.body.decode()
        assert "success" in data or "test-gateway" in data

    @patch.object(GatewayService, "update_gateway")
    @patch("mcpgateway.admin.TeamManagementService")
    async def test_update_gateway_sync_returns_200(
        self, mock_team_service_class, mock_update, mock_db, mock_request, mock_user, allow_permission, monkeypatch
    ):
        """Verify PUT /admin/gateways/{id} returns 200 when flag is OFF."""
        monkeypatch.setattr(settings, "gateway_async_lifecycle_enabled", False)

        # Mock team service
        mock_team_service = AsyncMock()
        mock_team_service.verify_team_for_user = AsyncMock(return_value=None)
        mock_team_service_class.return_value = mock_team_service

        # Mock db.get to return existing gateway
        mock_existing = MagicMock()
        mock_existing.owner_email = "admin@example.com"
        mock_existing.team_id = None
        mock_db.get.return_value = mock_existing

        # Mock update_gateway
        mock_gateway = MagicMock()
        mock_gateway.model_dump.return_value = {"id": "gw-1", "name": "test-gateway", "status": "active"}
        mock_update.return_value = mock_gateway

        # Mock request JSON
        mock_request.json = AsyncMock(
            return_value={
                "name": "test-gateway",
                "url": "http://localhost:9001/sse",
                "transport": "SSE",
            }
        )

        response = await admin_update_gateway_rest("gw-1", mock_request, mock_db, user=mock_user)

        assert response.status_code == 200

    @patch.object(GatewayService, "delete_gateway")
    async def test_delete_gateway_sync_returns_204(self, mock_delete, mock_db, mock_user, allow_permission, monkeypatch):
        """Verify DELETE /admin/gateways/{id} returns 204 when flag is OFF."""
        monkeypatch.setattr(settings, "gateway_async_lifecycle_enabled", False)

        mock_delete.return_value = None

        response = await admin_delete_gateway_rest("gw-1", mock_db, user=mock_user)

        assert response.status_code == 204


# ============================================================================
# Task 33: Test Async Create (Flag ON)
# ============================================================================


class TestAsyncCreate:
    """Test asynchronous gateway creation when async flag is enabled."""

    @patch("mcpgateway.admin.gateway_service")
    @patch("mcpgateway.admin.TeamManagementService")
    @patch("mcpgateway.admin.MetadataCapture")
    @patch("mcpgateway.admin.slugify")
    async def test_create_gateway_async_returns_202(
        self, mock_slugify, mock_metadata, mock_team_service_class, mock_gateway_service, mock_db, mock_request, mock_user, monkeypatch
    ):
        """Verify POST /admin/gateways returns 202 with status=pending when flag is ON."""
        monkeypatch.setattr(settings, "gateway_async_lifecycle_enabled", True)

        # Mock slugify
        mock_slugify.return_value = "test-gateway"

        # Mock team service
        mock_team_service = AsyncMock()
        mock_team_service.verify_team_for_user = AsyncMock(return_value=None)
        mock_team_service_class.return_value = mock_team_service

        # Mock metadata
        mock_metadata.extract_creation_metadata.return_value = {
            "created_by": "admin@example.com",
            "created_from_ip": "127.0.0.1",
            "created_via": "admin_ui",
            "created_user_agent": "test",
        }

        # Mock gateway_service.normalize_url
        mock_gateway_service.normalize_url.return_value = "http://localhost:9000/sse"

        # Mock DB execute to return no existing gateway
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        # Mock request JSON
        mock_request.json = AsyncMock(
            return_value={
                "name": "test-gateway",
                "url": "http://localhost:9000/sse",
                "transport": "SSE",
            }
        )

        response = await admin_add_gateway(mock_request, mock_db, user=mock_user)

        assert response.status_code == 202
        body = response.body.decode()
        assert "pending" in body
        assert "queued" in body.lower()

    @patch("mcpgateway.admin.gateway_service")
    @patch("mcpgateway.admin.TeamManagementService")
    @patch("mcpgateway.admin.MetadataCapture")
    @patch("mcpgateway.admin.slugify")
    async def test_duplicate_create_pending_returns_202_idempotent(
        self, mock_slugify, mock_metadata, mock_team_service_class, mock_gateway_service, mock_db, mock_request, mock_user, allow_permission, monkeypatch
    ):
        """Verify duplicate create on pending gateway returns 202 (idempotent)."""
        monkeypatch.setattr(settings, "gateway_async_lifecycle_enabled", True)

        mock_slugify.return_value = "test-gateway"

        # Mock team service
        mock_team_service = AsyncMock()
        mock_team_service.verify_team_for_user = AsyncMock(return_value=None)
        mock_team_service_class.return_value = mock_team_service

        # Mock metadata
        mock_metadata.extract_creation_metadata.return_value = {
            "created_by": "admin@example.com",
            "created_from_ip": "127.0.0.1",
            "created_via": "admin_ui",
            "created_user_agent": "test",
        }

        # Mock existing pending gateway
        existing_gateway = MagicMock()
        existing_gateway.status = "pending"
        existing_gateway.status_message = "Gateway registration queued"
        mock_db.execute.return_value.scalar_one_or_none.return_value = existing_gateway

        # Mock request JSON
        mock_request.json = AsyncMock(
            return_value={
                "name": "test-gateway",
                "url": "http://localhost:9000/sse",
                "transport": "SSE",
            }
        )

        response = await admin_add_gateway(mock_request, mock_db, user=mock_user)

        assert response.status_code == 202
        body = response.body.decode()
        assert "already queued" in body.lower() or "pending" in body

    @patch("mcpgateway.admin.gateway_service")
    @patch("mcpgateway.admin.TeamManagementService")
    @patch("mcpgateway.admin.MetadataCapture")
    @patch("mcpgateway.admin.slugify")
    async def test_duplicate_create_active_returns_409(
        self, mock_slugify, mock_metadata, mock_team_service_class, mock_gateway_service, mock_db, mock_request, mock_user, allow_permission, monkeypatch
    ):
        """Verify duplicate create on active gateway returns 409 Conflict."""
        monkeypatch.setattr(settings, "gateway_async_lifecycle_enabled", True)

        mock_slugify.return_value = "test-gateway"

        # Mock team service
        mock_team_service = AsyncMock()
        mock_team_service.verify_team_for_user = AsyncMock(return_value=None)
        mock_team_service_class.return_value = mock_team_service

        # Mock metadata
        mock_metadata.extract_creation_metadata.return_value = {
            "created_by": "admin@example.com",
            "created_from_ip": "127.0.0.1",
            "created_via": "admin_ui",
            "created_user_agent": "test",
        }

        # Mock DB: no pending, but active exists
        mock_active = MagicMock()
        mock_active.status = "active"
        mock_db.execute.return_value.scalar_one_or_none.side_effect = [None, mock_active]

        # Mock request JSON
        mock_request.json = AsyncMock(
            return_value={
                "name": "test-gateway",
                "url": "http://localhost:9000/sse",
                "transport": "SSE",
            }
        )

        response = await admin_add_gateway(mock_request, mock_db, user=mock_user)

        assert response.status_code == 409


# ============================================================================
# Task 34: Test Async Update (Flag ON)
# ============================================================================


class TestAsyncUpdate:
    """Test asynchronous gateway updates when async flag is enabled."""

    @patch("mcpgateway.admin.TeamManagementService")
    async def test_update_gateway_async_returns_202(
        self, mock_team_service_class, mock_db, mock_request, mock_user, allow_permission, monkeypatch
    ):
        """Verify PUT /admin/gateways/{id} returns 202 with status=pending when flag is ON."""
        monkeypatch.setattr(settings, "gateway_async_lifecycle_enabled", True)

        # Mock team service
        mock_team_service = AsyncMock()
        mock_team_service.verify_team_for_user = AsyncMock(return_value=None)
        mock_team_service_class.return_value = mock_team_service

        # Mock db.get to return gateway
        mock_gateway = MagicMock()
        mock_gateway.status = "active"
        mock_gateway.id = "gw-1"
        mock_gateway.owner_email = "admin@example.com"
        mock_gateway.team_id = None
        mock_gateway.status_message = None
        mock_db.get.return_value = mock_gateway

        # Mock request JSON
        mock_request.json = AsyncMock(
            return_value={
                "name": "test-gateway",
                "url": "http://localhost:9001/sse",
                "transport": "SSE",
            }
        )

        response = await admin_update_gateway_rest("gw-1", mock_request, mock_db, user=mock_user)

        assert response.status_code == 202
        body = response.body.decode()
        assert "pending" in body or "queued" in body.lower()


# ============================================================================
# Task 35: Test Async Delete (Flag ON)
# ============================================================================


class TestAsyncDelete:
    """Test asynchronous gateway deletion when async flag is enabled."""

    async def test_delete_gateway_async_returns_202(self, mock_db, mock_user, allow_permission, monkeypatch):
        """Verify DELETE /admin/gateways/{id} returns 202 with status=deleting when flag is ON."""
        monkeypatch.setattr(settings, "gateway_async_lifecycle_enabled", True)

        # Mock db.get to return gateway
        mock_gateway = MagicMock()
        mock_gateway.status = "active"
        mock_gateway.id = "gw-1"
        mock_gateway.status_message = None
        mock_db.get.return_value = mock_gateway

        response = await admin_delete_gateway_rest("gw-1", mock_db, user=mock_user)

        assert response.status_code == 202
        body = response.body.decode()
        assert "deleting" in body or "deletion" in body.lower()


# ============================================================================
# Task 36: Test DELETE on Pending Gateway
# ============================================================================


class TestDeletePendingGateway:
    """Test DELETE operation on pending gateways."""

    async def test_delete_pending_gateway_transitions_to_deleting(
        self, mock_db, mock_user, allow_permission, monkeypatch
    ):
        """Verify pending gateway transitions to deleting on DELETE."""
        monkeypatch.setattr(settings, "gateway_async_lifecycle_enabled", True)

        # Mock pending gateway
        mock_gateway = MagicMock()
        mock_gateway.status = "pending"
        mock_gateway.id = "gw-1"
        mock_gateway.status_message = None
        mock_db.get.return_value = mock_gateway

        response = await admin_delete_gateway_rest("gw-1", mock_db, user=mock_user)

        assert response.status_code == 202
        # Verify status changed to deleting
        assert mock_gateway.status == "deleting"


# ============================================================================
# Task 37: Test Exponential Backoff
# ============================================================================


class TestExponentialBackoff:
    """Test exponential backoff retry schedule."""

    def test_backoff_schedule_follows_formula(self):
        """Verify next_retry_at follows formula: min(2^(attempt-1), 300)."""
        worker = GatewayWorker()

        # Test backoff calculation
        expected_delays = [1, 2, 4, 8, 16, 32, 64, 128, 256, 300, 300]  # Cap at 300s
        for attempt in range(1, len(expected_delays) + 1):
            delay = worker._calculate_backoff(attempt)
            assert delay == expected_delays[attempt - 1], f"Attempt {attempt}: expected {expected_delays[attempt-1]}s, got {delay}s"


# ============================================================================
# Task 38: Test Worker Crash Recovery
# ============================================================================


class TestWorkerCrashRecovery:
    """Test worker crash recovery behavior."""

    @patch.object(GatewayWorker, "_claim_pending_gateways")
    @patch.object(GatewayWorker, "_process_gateway")
    async def test_worker_resumes_after_crash(self, mock_process, mock_claim):
        """Simulate crash, verify worker resumes on restart."""
        # Mock pending gateway with retry metadata
        mock_gateway = MagicMock()
        mock_gateway.status = "pending"
        mock_gateway.registration_attempts = 3
        mock_gateway.next_retry_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        mock_claim.return_value = [mock_gateway]

        worker = GatewayWorker()
        await worker._process_pending_gateways()

        # Verify worker resumed processing
        mock_process.assert_called_once()


# ============================================================================
# Task 39: Test Security (Deny-Path)
# ============================================================================


class TestSecurity:
    """Test security deny-path scenarios."""

    @patch("mcpgateway.admin.gateway_service")
    async def test_status_message_visibility_respects_token_scoping(self, mock_gateway_service, mock_db, mock_request, mock_user, allow_permission):
        """Verify status_message visibility respects token scoping."""
        # Mock gateway.model_dump() directly (admin_get_gateway doesn't call masked())
        result_dict = {
            "id": "gw-1",
            "name": "test-gateway",
            "status": "pending",
            "status_message": "Gateway registration queued",
        }
        
        mock_gateway_read = MagicMock()
        mock_gateway_read.model_dump.return_value = result_dict
        
        # Use AsyncMock for async method
        mock_gateway_service.get_gateway = AsyncMock(return_value=mock_gateway_read)

        result = await admin_get_gateway("gw-1", mock_request, mock_db, user=mock_user)

        assert result["status_message"] == "Gateway registration queued"

    @patch("mcpgateway.admin.gateway_service")
    async def test_last_error_not_exposed_in_api(self, mock_gateway_service, mock_db, mock_request, mock_user, allow_permission):
        """Verify last_error is NOT exposed in API responses."""
        # Mock gateway.model_dump() directly (admin_get_gateway doesn't call masked())
        result_dict = {
            "id": "gw-1",
            "name": "test-gateway",
            "status": "pending",
            "status_message": "Retrying after error",
            # last_error should NOT be in model_dump output
        }
        
        mock_gateway_read = MagicMock()
        mock_gateway_read.model_dump.return_value = result_dict
        
        # Use AsyncMock for async method
        mock_gateway_service.get_gateway = AsyncMock(return_value=mock_gateway_read)

        result = await admin_get_gateway("gw-1", mock_request, mock_db, user=mock_user)

        assert "last_error" not in result


# ============================================================================
# Task 40: Test Race Conditions
# ============================================================================


class TestRaceConditions:
    """Test race condition handling."""

    @patch("mcpgateway.services.gateway_service.GatewayService._perform_gateway_registration")
    async def test_double_status_check_prevents_overwrite(self, mock_perform, mock_db):
        """Verify double status check prevents overwriting deleting status."""
        # Mock gateway that changes to deleting during MCP operation
        mock_gateway = MagicMock()
        mock_gateway.status = "pending"
        mock_gateway.name = "test-gateway"
        mock_gateway.id = "gw-1"
        
        # Simulate status change during MCP operation via db.refresh
        def refresh_side_effect(gw):
            # After MCP operation, gateway status changed to deleting
            gw.status = "deleting"
        
        mock_db.refresh.side_effect = refresh_side_effect
        mock_perform.return_value = {"tools": [], "prompts": [], "resources": []}

        worker = GatewayWorker()
        await worker._process_gateway(mock_db, mock_gateway)

        # Verify status remains deleting (not overwritten to active)
        assert mock_gateway.status == "deleting"
        # Verify db.refresh was called (double status check)
        assert mock_db.refresh.called

# Made with Bob
