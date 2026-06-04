"""E2E tests for async gateway lifecycle (Issue #4565).

Simplified E2E tests using direct worker invocation instead of background polling.
"""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

from mcpgateway.db import Gateway
from mcpgateway.services.gateway_worker import GatewayWorker


@pytest.fixture
async def client(app_with_temp_db, main_app_with_admin_api):
    """Async test client."""
    from mcpgateway.admin import admin_router, set_logging_service, validate_section_permissions
    from mcpgateway.auth import get_current_user
    from mcpgateway.main import logging_service
    from mcpgateway.middleware.rbac import get_current_user_with_permissions

    # Mount admin routes
    admin_routes = [r for r in app_with_temp_db.routes if getattr(r, "path", "").startswith("/admin/")
                    and not getattr(r, "path", "").startswith("/admin/well-known")]
    if not admin_routes:
        set_logging_service(logging_service)
        app_with_temp_db.include_router(admin_router)
        validate_section_permissions(admin_router)

    # Mock auth
    mock_user = {"email": "test@example.com", "sub": "test@example.com"}
    mock_user_context = {
        "email": "test@example.com",
        "full_name": "Test User",
        "is_admin": True,
        "teams": [],
        "token_teams": None,
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

    transport = ASGITransport(app=app_with_temp_db)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def session(app_with_temp_db):
    """Database session."""
    import mcpgateway.db as db_mod

    db = db_mod.SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def mock_mcp_init_success():
    """Mock successful MCP init."""
    async def mock_init(*args, **kwargs):
        return ({"tools": []}, [], [], [], [])  # Added 5th element (validation_errors)

    with patch("mcpgateway.services.gateway_worker.GatewayService._initialize_gateway", new=mock_init) as mock:
        yield mock


@pytest.fixture
def mock_mcp_init_fail_then_succeed():
    """Mock MCP init: fail twice, succeed third time."""
    call_count = 0

    async def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise ConnectionError("Connection refused")
        return ({"tools": []}, [], [], [], [])  # Added 5th element (validation_errors)

    with patch("mcpgateway.services.gateway_worker.GatewayService._initialize_gateway", new=side_effect) as mock:
        yield mock


@pytest.fixture(autouse=True)
def disable_background_worker(app_with_temp_db):
    """Disable background worker - use direct calls instead."""
    import mcpgateway.db as db_mod
    import mcpgateway.services.gateway_worker as gateway_worker_mod

    with (
        patch("mcpgateway.services.gateway_worker.GatewayWorker.run_forever", new_callable=AsyncMock),
        patch.object(gateway_worker_mod, "SessionLocal", db_mod.SessionLocal),
    ):
        yield


@pytest.fixture(autouse=True)
def mock_rbac_check():
    """Mock RBAC checks."""
    with patch("mcpgateway.services.permission_service.PermissionService.check_permission", return_value=True):
        yield


class TestGatewayAsyncE2E:
    """E2E tests for async gateway lifecycle."""

    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_create_poll_active_lifecycle(self, client, session, mock_mcp_init_success):
        """E2E: Create → poll → active."""
        # Create
        response = await client.post(
            "/gateways",
            json={"name": "e2e-lifecycle", "url": "http://localhost:9000/mcp"},
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 202
        data = response.json()
        gateway_id = data["id"]
        assert data["status"] == "pending"

        # Verify DB
        gateway = session.query(Gateway).filter(Gateway.id == gateway_id).first()
        assert gateway.status == "pending"

        # Simulate worker processing
        worker = GatewayWorker()
        await worker.retry_gateway_init(gateway, session)

        # Poll status
        response = await client.get(
            f"/gateways/{gateway_id}",
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "active"
        assert data["registrationAttempts"] >= 1

    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_retry_with_backoff(self, client, session, mock_mcp_init_fail_then_succeed):
        """E2E: Retry with exponential backoff."""
        # Create
        response = await client.post(
            "/gateways",
            json={"name": "e2e-retry", "url": "http://localhost:9001/mcp"},
            headers={"Authorization": "Bearer test-token"},
        )

        gateway_id = response.json()["id"]
        gateway = session.query(Gateway).filter(Gateway.id == gateway_id).first()

        # Simulate 3 retry attempts
        worker = GatewayWorker()
        for i in range(3):
            session.refresh(gateway)
            await worker.retry_gateway_init(gateway, session)
            await asyncio.sleep(0.1)

        # Verify success after retries
        session.refresh(gateway)
        assert gateway.status == "active"
        # Initial creation + 3 manual worker calls = 4 total attempts
        assert gateway.registration_attempts == 4

    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_delete_stops_retry(self, client, session, mock_mcp_init_fail_then_succeed):
        """E2E: DELETE stops retry loop."""
        # Create
        response = await client.post(
            "/gateways",
            json={"name": "e2e-delete", "url": "http://localhost:9002/mcp"},
            headers={"Authorization": "Bearer test-token"},
        )

        gateway_id = response.json()["id"]
        gateway = session.query(Gateway).filter(Gateway.id == gateway_id).first()

        # First retry attempt (fails)
        worker = GatewayWorker()
        await worker.retry_gateway_init(gateway, session)
        session.refresh(gateway)
        assert gateway.status == "pending"
        assert gateway.registration_attempts == 1

        # Delete
        response = await client.delete(
            f"/gateways/{gateway_id}",
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 202
        session.refresh(gateway)
        assert gateway.status == "deleting"

        # Worker cleanup removes gateway
        await worker.retry_gateway_init(gateway, session)

        # Verify removed
        remaining = session.query(Gateway).filter(Gateway.id == gateway_id).first()
        assert remaining is None

    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_update_resets_and_retries(self, client, session, mock_mcp_init_success):
        """E2E: Update resets to pending and retries."""
        # Create and activate
        response = await client.post(
            "/gateways",
            json={"name": "e2e-update", "url": "http://localhost:9003/mcp"},
            headers={"Authorization": "Bearer test-token"},
        )

        gateway_id = response.json()["id"]
        gateway = session.query(Gateway).filter(Gateway.id == gateway_id).first()

        # Activate
        worker = GatewayWorker()
        await worker.retry_gateway_init(gateway, session)
        session.refresh(gateway)
        assert gateway.status == "active"

        # Update
        response = await client.put(
            f"/gateways/{gateway_id}",
            json={"url": "http://localhost:9004/mcp"},
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "pending"
        assert data["registration_attempts"] == 0

        # Retry after update
        session.refresh(gateway)
        await worker.retry_gateway_init(gateway, session)
        session.refresh(gateway)
        assert gateway.status == "active"
