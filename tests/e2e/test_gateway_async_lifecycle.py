# -*- coding: utf-8 -*-
"""SQLite e2e coverage for async gateway lifecycle."""

# Standard
from datetime import datetime, timezone
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock

# Third-Party
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
import pytest
import pytest_asyncio
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import Base
from mcpgateway.main import app, get_db
from mcpgateway.schemas import ToolCreate
from tests.helpers.auth import make_auth_headers, make_legacy_test_jwt
from tests.utils.rbac_mocks import MockPermissionService, create_mock_email_user, create_mock_user_context


TEST_JWT_SECRET = "e2e-test-jwt-secret-key-with-minimum-32-bytes"  # pragma: allowlist secret

if hasattr(settings.jwt_secret_key, "get_secret_value") and callable(getattr(settings.jwt_secret_key, "get_secret_value", None)):
    settings.jwt_secret_key = SecretStr(TEST_JWT_SECRET)
else:
    settings.jwt_secret_key = TEST_JWT_SECRET

TEST_AUTH_HEADER = make_auth_headers(
    make_legacy_test_jwt(
        "testuser@example.com",
        teams=[],
        expires_in_minutes=60,
        secret=TEST_JWT_SECRET,
        algorithm=settings.jwt_algorithm,
        include_email_claim=True,
    )
)

TEST_ADMIN_AUTH_HEADER = make_auth_headers(
    make_legacy_test_jwt(
        "testuser@example.com",
        is_admin=True,
        teams=None,
        expires_in_minutes=60,
        secret=TEST_JWT_SECRET,
        algorithm=settings.jwt_algorithm,
        include_email_claim=True,
    )
)


def _response_value(payload: dict, snake_name: str):
    parts = snake_name.split("_")
    camel_name = parts[0] + "".join(part.capitalize() for part in parts[1:])
    return payload.get(camel_name, payload.get(snake_name))


def _make_tool(name: str, description: str) -> ToolCreate:
    return ToolCreate(
        name=name,
        description=description,
        integration_type="REST",
        request_type="POST",
        input_schema={"type": "object"},
    )


@pytest_asyncio.fixture
async def lifecycle_client(main_app_with_admin_api):
    # First-Party
    import mcpgateway.db as db_mod
    import mcpgateway.main as main_mod
    import mcpgateway.services.gateway_service as gateway_service_mod
    from mcpgateway.auth import get_current_user
    from mcpgateway.middleware.auth_middleware import security_logger
    from mcpgateway.middleware.rbac import get_current_user_with_permissions, get_permission_service
    from mcpgateway.utils.create_jwt_token import get_jwt_token
    from mcpgateway.utils.verify_credentials import require_admin_auth, require_auth
    from mcpgateway.db import EmailUser

    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    seed_db = SessionLocal()
    try:
        seed_db.add(
            EmailUser(
                email="testuser@example.com",
                password_hash="not-a-real-hash",
                full_name="Test User",
                is_admin=True,
                is_active=True,
            )
        )
        seed_db.commit()
    finally:
        seed_db.close()

    original_main_session_local = main_mod.SessionLocal
    original_validate_token_user = main_mod.validate_token_user
    original_gateway_session_local = gateway_service_mod.SessionLocal
    original_db_session_local = db_mod.SessionLocal
    original_db_url = settings.database_url
    original_auth_required = settings.auth_required
    original_require_jti = settings.require_jti
    original_require_user_in_db = settings.require_user_in_db
    original_async_enabled = settings.gateway_async_lifecycle_enabled
    original_poll_interval = settings.gateway_async_lifecycle_poll_interval

    mock_email_user = create_mock_email_user(email="testuser@example.com", full_name="Test User", is_admin=True, is_active=True)
    user_context_db = SessionLocal()
    user_context = create_mock_user_context(email="testuser@example.com", full_name="Test User", is_admin=True)
    user_context["db"] = user_context_db
    user_context["permissions"] = ["*"]

    settings.database_url = f"sqlite:///{db_path}"
    settings.auth_required = True
    settings.require_jti = False
    settings.require_user_in_db = False
    settings.gateway_async_lifecycle_enabled = True
    settings.gateway_async_lifecycle_poll_interval = 0.01
    main_mod.SessionLocal = SessionLocal
    main_mod.validate_token_user = AsyncMock(return_value=mock_email_user)
    gateway_service_mod.SessionLocal = SessionLocal
    db_mod.SessionLocal = SessionLocal
    main_mod.gateway_service._event_service.publish_event = AsyncMock(return_value=None)

    class AllowAllPermissionService:
        def __init__(self, _db):
            pass

        async def check_permission(self, **_kwargs):
            return True

    import mcpgateway.middleware.rbac as rbac_mod

    original_permission_service = getattr(main_mod, "PermissionService", None)
    original_rbac_permission_service = rbac_mod.PermissionService
    if original_permission_service is not None:
        main_mod.PermissionService = AllowAllPermissionService
    rbac_mod.PermissionService = AllowAllPermissionService

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    async def mock_user_with_permissions():
        return user_context

    async def mock_require_admin():
        return "testuser@example.com"

    async def mock_get_jwt():
        return make_legacy_test_jwt(
            "testuser@example.com",
            teams=[],
            expires_in_minutes=60,
            secret=TEST_JWT_SECRET,
            algorithm=settings.jwt_algorithm,
            include_email_claim=True,
        )

    def mock_permission_service(*_args, **_kwargs):
        return MockPermissionService(always_grant=True)

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_auth] = lambda: "test_user"
    app.dependency_overrides[get_current_user] = lambda: mock_email_user
    app.dependency_overrides[get_current_user_with_permissions] = mock_user_with_permissions
    app.dependency_overrides[require_admin_auth] = mock_require_admin
    app.dependency_overrides[get_jwt_token] = mock_get_jwt
    app.dependency_overrides[get_permission_service] = mock_permission_service
    security_logger.log_authentication_attempt = MagicMock(return_value=None)
    security_logger.log_security_event = MagicMock(return_value=None)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, main_mod.gateway_service

    app.dependency_overrides.clear()
    user_context_db.close()
    main_mod.SessionLocal = original_main_session_local
    main_mod.validate_token_user = original_validate_token_user
    gateway_service_mod.SessionLocal = original_gateway_session_local
    db_mod.SessionLocal = original_db_session_local
    if original_permission_service is not None:
        main_mod.PermissionService = original_permission_service
    rbac_mod.PermissionService = original_rbac_permission_service
    settings.database_url = original_db_url
    settings.auth_required = original_auth_required
    settings.require_jti = original_require_jti
    settings.require_user_in_db = original_require_user_in_db
    settings.gateway_async_lifecycle_enabled = original_async_enabled
    settings.gateway_async_lifecycle_poll_interval = original_poll_interval
    engine.dispose()
    os.close(db_fd)
    os.unlink(db_path)


@pytest.mark.asyncio
async def test_sqlite_async_gateway_lifecycle_happy_path(lifecycle_client):
    client, live_gateway_service = lifecycle_client

    create_response = await client.post(
        "/gateways",
        json={"name": "counter-three", "url": "http://example.com/mcp", "transport": "SSE"},
        headers=TEST_AUTH_HEADER,
    )
    assert create_response.status_code == 202
    created = create_response.json()
    gateway_id = created["id"]
    assert created["status"] == "pending"
    assert _response_value(created, "registration_attempts") == 0
    assert _response_value(created, "next_retry_at") is None
    assert _response_value(created, "last_error") is None

    pending_response = await client.get("/admin/gateways/counter-three", headers=TEST_ADMIN_AUTH_HEADER)
    assert pending_response.status_code == 200
    assert pending_response.json()["status"] == "pending"

    live_gateway_service._initialize_gateway = AsyncMock(
        return_value=(
            {"tools": {"listChanged": True}},
            [_make_tool("echo_tool", "Initial tool")],
            [],
            [],
            [],
        )
    )
    await live_gateway_service._run_gateway_lifecycle_pass()

    active_response = await client.get("/admin/gateways/counter-three", headers=TEST_ADMIN_AUTH_HEADER)
    assert active_response.status_code == 200
    active_gateway = active_response.json()
    assert active_gateway["status"] == "active"
    assert _response_value(active_gateway, "registration_attempts") == 0
    assert _response_value(active_gateway, "next_retry_at") is None
    assert _response_value(active_gateway, "last_error") is None
    assert active_gateway["reachable"] is True

    tools_response = await client.get("/tools", headers=TEST_AUTH_HEADER)
    assert tools_response.status_code == 200
    initial_tool_names = {tool["name"] for tool in tools_response.json()}
    assert "counter-three-echo-tool" in initial_tool_names

    update_response = await client.put(
        f"/gateways/{gateway_id}",
        json={"description": "updated gateway description"},
        headers=TEST_AUTH_HEADER,
    )
    assert update_response.status_code == 202
    updated_pending = update_response.json()
    assert updated_pending["status"] == "pending"

    live_gateway_service._initialize_gateway = AsyncMock(
        return_value=(
            {"tools": {"listChanged": True}},
            [_make_tool("updated_tool", "Updated tool")],
            [],
            [],
            [],
        )
    )
    await live_gateway_service._run_gateway_lifecycle_pass()

    updated_active_response = await client.get(f"/gateways/{gateway_id}", headers=TEST_AUTH_HEADER)
    assert updated_active_response.status_code == 200
    assert updated_active_response.json()["status"] == "active"

    updated_tools_response = await client.get("/tools", headers=TEST_AUTH_HEADER)
    assert updated_tools_response.status_code == 200
    updated_tool_names = {tool["name"] for tool in updated_tools_response.json()}
    assert "counter-three-updated-tool" in updated_tool_names
    assert "counter-three-echo-tool" not in updated_tool_names

    delete_response = await client.delete(f"/gateways/{gateway_id}", headers=TEST_AUTH_HEADER)
    assert delete_response.status_code == 202
    deleting_gateway = delete_response.json()
    assert deleting_gateway["status"] == "deleting"

    await live_gateway_service._run_gateway_lifecycle_pass()

    deleted_response = await client.get("/admin/gateways/counter-three", headers=TEST_ADMIN_AUTH_HEADER)
    assert deleted_response.status_code == 404


@pytest.mark.asyncio
async def test_sqlite_async_gateway_lifecycle_retry_and_delete_stop_flow(lifecycle_client):
    client, live_gateway_service = lifecycle_client

    create_response = await client.post(
        "/gateways",
        json={"name": "retry-gateway", "url": "http://example.com/retry", "transport": "SSE"},
        headers=TEST_AUTH_HEADER,
    )
    assert create_response.status_code == 202
    created = create_response.json()
    gateway_id = created["id"]

    live_gateway_service._initialize_gateway = AsyncMock(side_effect=RuntimeError("Connection refused: http://example.com/retry"))
    await live_gateway_service._run_gateway_lifecycle_pass()

    pending_response = await client.get("/admin/gateways/retry-gateway", headers=TEST_ADMIN_AUTH_HEADER)
    assert pending_response.status_code == 200
    pending_gateway = pending_response.json()
    assert pending_gateway["status"] == "pending"
    assert _response_value(pending_gateway, "registration_attempts") == 1
    assert _response_value(pending_gateway, "last_error") == "Connection refused: http://example.com/retry"
    next_retry_at = _response_value(pending_gateway, "next_retry_at")
    assert next_retry_at is not None
    parsed_next_retry = datetime.fromisoformat(next_retry_at.replace("Z", "+00:00"))
    if parsed_next_retry.tzinfo is None:
        parsed_next_retry = parsed_next_retry.replace(tzinfo=timezone.utc)
    updated_at = datetime.fromisoformat(pending_gateway["updatedAt"].replace("Z", "+00:00"))
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    assert parsed_next_retry > updated_at

    delete_response = await client.delete(f"/gateways/{gateway_id}", headers=TEST_AUTH_HEADER)
    assert delete_response.status_code == 202
    deleting_gateway = delete_response.json()
    assert deleting_gateway["status"] == "deleting"

    await live_gateway_service._run_gateway_lifecycle_pass()

    deleted_response = await client.get("/admin/gateways/retry-gateway", headers=TEST_ADMIN_AUTH_HEADER)
    assert deleted_response.status_code == 404
