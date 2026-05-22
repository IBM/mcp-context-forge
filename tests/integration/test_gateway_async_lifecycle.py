"""Integration tests for async gateway lifecycle (Issue #4565)."""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from mcpgateway.db import Gateway
from mcpgateway.main import app
from mcpgateway.services.gateway_worker import GatewayWorker


@pytest.fixture
def client(app_with_temp_db, main_app_with_admin_api):
    """Test client using app with admin API enabled and temp database."""
    from mcpgateway.admin import admin_router, set_logging_service, validate_section_permissions
    from mcpgateway.auth import get_current_user
    from mcpgateway.main import logging_service
    from mcpgateway.middleware.rbac import get_current_user_with_permissions

    # Check if admin routes are already mounted
    admin_routes = [r for r in app_with_temp_db.routes if getattr(r, "path", "").startswith("/admin/")
                    and not getattr(r, "path", "").startswith("/admin/well-known")]
    if not admin_routes:
        set_logging_service(logging_service)
        app_with_temp_db.include_router(admin_router)
        validate_section_permissions(admin_router)

    # Mock auth for tests - must match structure from get_current_user_with_permissions
    mock_user = {"email": "test@example.com", "sub": "test@example.com"}
    mock_user_context = {
        "email": "test@example.com",
        "full_name": "Test User",
        "is_admin": True,
        "teams": [],
        "token_teams": None,  # None = admin bypass (unrestricted scope)
        "ip_address": "127.0.0.1",
        "user_agent": "test-client",
        "db": None,
        "auth_method": "jwt",
        "request_id": None,
        "team_id": None,
        "plugin_context_table": None,
        "plugin_global_context": None,
    }

    app_with_temp_db.dependency_overrides[get_current_user] = lambda: mock_user
    app_with_temp_db.dependency_overrides[get_current_user_with_permissions] = lambda: mock_user_context

    return TestClient(app_with_temp_db)


@pytest.fixture
def session(app_with_temp_db):
    """Create a database session using the same engine as app_with_temp_db.

    The app_with_temp_db fixture patches SessionLocal, so we need to import
    it after the fixture has been set up to get the patched version.

    Note: We don't run migrations here because app_with_temp_db already creates
    tables from db.py models via Base.metadata.create_all(), which has the
    current schema. Running migrations would cause duplicate column errors.
    """
    # Import after app_with_temp_db has patched SessionLocal
    import mcpgateway.db as db_mod

    db = db_mod.SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def mock_mcp_init():
    """Mock MCP initialization - patch the actual method used by worker."""
    with patch("mcpgateway.services.gateway_service.GatewayService._initialize_gateway") as mock:
        mock.return_value = AsyncMock(return_value=({"tools": []}, [], [], []))
        yield mock


@pytest.fixture(autouse=True)
def disable_worker(app_with_temp_db):
    """Disable background worker in tests to avoid DB conflicts."""
    import mcpgateway.db as db_mod
    import mcpgateway.services.gateway_worker as gateway_worker_mod

    with (
        patch("mcpgateway.services.gateway_worker.GatewayWorker.run_forever", new_callable=AsyncMock),
        patch.object(gateway_worker_mod, "SessionLocal", db_mod.SessionLocal),
    ):
        yield


@pytest.fixture(autouse=True)
def mock_rbac_check():
    """Mock RBAC permission checks to always pass for these tests."""
    with patch("mcpgateway.services.permission_service.PermissionService.check_permission", return_value=True):
        yield


class TestGatewayAsyncLifecycle:
    """Integration tests for async gateway lifecycle."""

    @pytest.mark.asyncio
    async def test_create_gateway_returns_202(self, client, session, mock_mcp_init):
        """POST /gateways returns 202 with pending status."""
        response = client.post(
            "/gateways",
            json={"name": "test-gateway-202", "url": "http://localhost:9000/mcp"},
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "pending"
        assert data["registration_attempts"] == 0
        assert data["name"] == "test-gateway-202"

        # Verify DB state
        gateway = session.query(Gateway).filter(Gateway.name == "test-gateway-202").first()
        assert gateway is not None
        assert gateway.status == "pending"

    @pytest.mark.asyncio
    async def test_retry_with_same_name_returns_existing(self, client, session, mock_mcp_init):
        """Retry with same name returns existing gateway (409 conflict for now)."""
        # First request
        response1 = client.post(
            "/gateways",
            json={"name": "test-retry-unique", "url": "http://localhost:9001/mcp"},
            headers={"Authorization": "Bearer test-token"},
        )
        assert response1.status_code == 202
        gateway_id = response1.json()["id"]

        # Retry with same name - currently returns 409 (duplicate detection)
        # TODO: Implement idempotent retry logic to return existing pending gateway
        response2 = client.post(
            "/gateways",
            json={"name": "test-retry-unique", "url": "http://localhost:9001/mcp"},
            headers={"Authorization": "Bearer test-token"},
        )

        # For now, expect 409 conflict (duplicate detection working)
        assert response2.status_code == 409

    @pytest.mark.asyncio
    async def test_worker_retries_until_success(self, session, mock_mcp_init):
        """Worker retries failed init with exponential backoff."""
        # Create pending gateway
        gateway = Gateway(
            name="test-worker-retry",
            url="http://localhost:9000/mcp",
            status="pending",
            registration_attempts=0,
            capabilities={},
        )
        session.add(gateway)
        session.commit()

        # Mock: fail 2 times, then succeed
        call_count = 0

        async def mock_init_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise ConnectionError("Connection refused")
            return {"tools": []}, [], [], []

        mock_mcp_init.side_effect = mock_init_side_effect

        # Run worker directly against only this gateway to avoid cross-test interference
        worker = GatewayWorker()
        for _ in range(5):
            session.refresh(gateway)
            await worker.retry_gateway_init(gateway, session)
            await asyncio.sleep(0.1)
            session.refresh(gateway)
            if gateway.status == "active":
                break

        # Verify success after retries
        session.refresh(gateway)
        assert gateway.status == "active"
        assert gateway.registration_attempts >= 3  # At least 2 failures + 1 success

    @pytest.mark.asyncio
    async def test_delete_gateway_returns_202(self, client, session):
        """DELETE /gateways/{id} returns 202."""
        # Create gateway with owner
        gateway = Gateway(
            name="test-delete-202",
            url="http://localhost:9000/mcp",
            status="active",
            capabilities={},
            owner_email="test@example.com",
        )
        session.add(gateway)
        session.commit()

        # Delete
        response = client.delete(
            f"/gateways/{gateway.id}",
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 202
        assert "deletion accepted" in response.json()["message"].lower()

        # Verify status=deleting
        session.refresh(gateway)
        assert gateway.status == "deleting"

    @pytest.mark.asyncio
    async def test_update_gateway_returns_202(self, client, session):
        """PUT /gateways/{id} returns 202 and resets to pending."""
        # Create active gateway with owner
        gateway = Gateway(
            name="test-update-202",
            url="http://localhost:9000/mcp",
            status="active",
            registration_attempts=5,
            capabilities={},
            owner_email="test@example.com",
        )
        session.add(gateway)
        session.commit()

        # Update
        response = client.put(
            f"/gateways/{gateway.id}",
            json={"url": "http://localhost:9001/mcp"},
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "pending"
        assert data["registration_attempts"] == 0  # Reset

    @pytest.mark.asyncio
    async def test_get_gateway_includes_status_fields(self, client, session):
        """GET /gateways/{id} includes status fields."""
        # Create gateway with retry metadata
        gateway = Gateway(
            name="test-get-status",
            url="http://localhost:9000/mcp",
            status="pending",
            registration_attempts=3,
            next_retry_at=datetime.now() + timedelta(seconds=16),
            last_error="Connection timeout",
            capabilities={},
        )
        session.add(gateway)
        session.commit()

        # Get gateway
        response = client.get(
            f"/gateways/{gateway.id}",
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "pending"
        assert data["registrationAttempts"] == 3
        assert data["nextRetryAt"] is not None
        assert data["lastError"] == "Connection timeout"

    @pytest.mark.asyncio
    async def test_worker_stops_on_deleting_status(self, session, mock_mcp_init):
        """Worker exits retry loop when status=deleting."""
        # Create pending gateway
        gateway = Gateway(
            name="test-worker-delete",
            url="http://localhost:9000/mcp",
            status="pending",
            registration_attempts=2,
            capabilities={},
        )
        session.add(gateway)
        session.commit()

        # Set to deleting
        gateway.status = "deleting"
        session.commit()

        # Run worker directly against this gateway
        worker = GatewayWorker()
        await worker.retry_gateway_init(gateway, session)

        # Verify no retry attempt (mock not called)
        mock_mcp_init.assert_not_called()

        # Gateway should be removed by cleanup
        remaining = session.query(Gateway).filter(Gateway.id == gateway.id).first()
        assert remaining is None
