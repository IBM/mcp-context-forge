# -*- coding: utf-8 -*-
"""Postgres-gated integration harness for async gateway lifecycle."""

# Standard
import os
import sys
from unittest.mock import AsyncMock, MagicMock

# Third-Party
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
import pytest
import pytest_asyncio
from sqlalchemy import create_engine
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

# First-Party
from mcpgateway.schemas import ToolCreate
from tests.helpers.auth import make_auth_headers, make_legacy_test_jwt
from tests.utils.rbac_mocks import MockPermissionService, create_mock_email_user, create_mock_user_context

pytestmark = [pytest.mark.integration, pytest.mark.postgresql]

TEST_JWT_SECRET = "integration-test-jwt-secret-key-with-minimum-32-bytes"  # pragma: allowlist secret


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


def _is_external_postgres_enabled() -> bool:
    db_env = os.getenv("DB", "").lower()
    database_url = os.getenv("DATABASE_URL", "").lower()
    postgres_url = os.getenv("MCPGATEWAY_TEST_POSTGRES_URL", "").lower()
    external_db_opt_in = os.getenv("MCPGATEWAY_TEST_ALLOW_EXTERNAL_DB", "").strip().lower() in {"1", "true", "yes", "on"}
    return external_db_opt_in and (db_env == "postgres" or "postgresql" in database_url or "postgresql" in postgres_url)


SKIP_IF_NOT_EXTERNAL_POSTGRES = pytest.mark.skipif(
    not _is_external_postgres_enabled(),
    reason="Postgres-gated: set MCPGATEWAY_TEST_ALLOW_EXTERNAL_DB=1 and DB=postgres (or DATABASE_URL=postgresql://...)",
)


@pytest_asyncio.fixture
async def lifecycle_client():
    # First-Party
    from mcpgateway.config import get_settings, settings
    import mcpgateway.db as db_mod

    database_url = os.getenv("MCPGATEWAY_TEST_POSTGRES_URL") or os.getenv("DATABASE_URL")
    if not database_url or "postgresql" not in database_url:
        pytest.skip("Postgres lifecycle test requires MCPGATEWAY_TEST_POSTGRES_URL or DATABASE_URL with postgresql://")

    os.environ["DB"] = "postgres"
    os.environ["DATABASE_URL"] = database_url
    os.environ["TEST_DATABASE_URL"] = database_url
    os.environ["MCPGATEWAY_ADMIN_API_ENABLED"] = "true"
    os.environ["MCPGATEWAY_UI_ENABLED"] = "true"
    get_settings.cache_clear()
    sys.modules.pop("mcpgateway.main", None)
    sys.modules.pop("mcpgateway.admin", None)

    import mcpgateway.main as main_mod
    from mcpgateway.admin import admin_router, set_logging_service, validate_section_permissions
    from mcpgateway.db import Base
    import mcpgateway.services.gateway_service as gateway_service_mod
    from mcpgateway.auth import get_current_user
    from mcpgateway.db import EmailUser
    from mcpgateway.middleware.auth_middleware import security_logger
    from mcpgateway.middleware.rbac import get_current_user_with_permissions, get_permission_service
    from mcpgateway.utils.create_jwt_token import get_jwt_token
    from mcpgateway.utils.verify_credentials import require_admin_auth, require_auth

    engine = create_engine(database_url)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    admin_routes = [r for r in main_mod.app.routes if getattr(r, "path", "").startswith("/admin/") and not getattr(r, "path", "").startswith("/admin/well-known")]
    if not admin_routes:
        set_logging_service(main_mod.logging_service)
        main_mod.app.include_router(admin_router)
        validate_section_permissions(admin_router)

    seed_db = SessionLocal()
    try:
        existing_user = seed_db.query(EmailUser).filter(EmailUser.email == "admin@example.com").one_or_none()
        if existing_user is None:
            seed_db.add(
                EmailUser(
                    email="admin@example.com",
                    password_hash="not-a-real-hash",
                    full_name="Integration Admin",
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
    original_jwt_secret = settings.jwt_secret_key
    original_auth_required = settings.auth_required
    original_require_jti = settings.require_jti
    original_require_user_in_db = settings.require_user_in_db
    original_async_enabled = settings.gateway_async_lifecycle_enabled
    original_poll_interval = settings.gateway_async_lifecycle_poll_interval

    mock_email_user = create_mock_email_user(email="admin@example.com", full_name="Integration Admin", is_admin=True, is_active=True)
    user_context_db = SessionLocal()
    user_context = create_mock_user_context(email="admin@example.com", full_name="Integration Admin", is_admin=True)
    user_context["db"] = user_context_db

    settings.database_url = database_url
    settings.jwt_secret_key = SecretStr(TEST_JWT_SECRET)
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

    test_auth_header = make_auth_headers(
        make_legacy_test_jwt(
            "admin@example.com",
            is_admin=True,
            teams=None,
            expires_in_minutes=60,
            secret=TEST_JWT_SECRET,
            algorithm=settings.jwt_algorithm,
            include_email_claim=True,
        )
    )

    class AllowAllPermissionService:
        def __init__(self, _db):
            pass

        async def check_permission(self, **_kwargs):
            return True

    import mcpgateway.middleware.rbac as rbac_mod

    original_rbac_permission_service = rbac_mod.PermissionService
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
        return "admin@example.com"

    async def mock_get_jwt():
        return make_legacy_test_jwt(
            "admin@example.com",
            is_admin=True,
            teams=None,
            expires_in_minutes=60,
            secret=TEST_JWT_SECRET,
            algorithm=settings.jwt_algorithm,
            include_email_claim=True,
        )

    def mock_permission_service(*_args, **_kwargs):
        return MockPermissionService(always_grant=True)

    main_mod.app.dependency_overrides[main_mod.get_db] = override_get_db
    main_mod.app.dependency_overrides[db_mod.get_db] = override_get_db
    main_mod.app.dependency_overrides[require_auth] = lambda: "integration-admin"
    main_mod.app.dependency_overrides[get_current_user] = lambda: mock_email_user
    main_mod.app.dependency_overrides[get_current_user_with_permissions] = mock_user_with_permissions
    main_mod.app.dependency_overrides[require_admin_auth] = mock_require_admin
    main_mod.app.dependency_overrides[get_jwt_token] = mock_get_jwt
    main_mod.app.dependency_overrides[get_permission_service] = mock_permission_service
    security_logger.log_authentication_attempt = MagicMock(return_value=None)
    security_logger.log_security_event = MagicMock(return_value=None)

    transport = ASGITransport(app=main_mod.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, main_mod.gateway_service, test_auth_header

    main_mod.app.dependency_overrides.clear()
    user_context_db.close()
    main_mod.SessionLocal = original_main_session_local
    main_mod.validate_token_user = original_validate_token_user
    gateway_service_mod.SessionLocal = original_gateway_session_local
    db_mod.SessionLocal = original_db_session_local
    rbac_mod.PermissionService = original_rbac_permission_service
    settings.database_url = original_db_url
    settings.jwt_secret_key = original_jwt_secret
    settings.auth_required = original_auth_required
    settings.require_jti = original_require_jti
    settings.require_user_in_db = original_require_user_in_db
    settings.gateway_async_lifecycle_enabled = original_async_enabled
    settings.gateway_async_lifecycle_poll_interval = original_poll_interval
    engine.dispose()


@pytest.mark.asyncio
@SKIP_IF_NOT_EXTERNAL_POSTGRES
async def test_postgres_gateway_async_lifecycle_fixture_gate(lifecycle_client):
    client, live_gateway_service, _test_auth_header = lifecycle_client

    assert client is not None
    assert live_gateway_service is not None
    response = await client.get("/health")
    assert response.status_code == 200


@pytest.mark.asyncio
@SKIP_IF_NOT_EXTERNAL_POSTGRES
async def test_postgres_async_gateway_lifecycle_happy_path(lifecycle_client):
    client, live_gateway_service, test_auth_header = lifecycle_client

    create_response = await client.post(
        "/gateways",
        json={"name": "pg-counter-three", "url": "http://example.com/mcp", "transport": "SSE"},
        headers=test_auth_header,
    )
    assert create_response.status_code == 202
    created = create_response.json()
    gateway_id = created["id"]
    assert created["status"] == "pending"
    assert _response_value(created, "registration_attempts") == 0
    assert _response_value(created, "next_retry_at") is None
    assert _response_value(created, "last_error") is None

    pending_response = await client.get("/admin/gateways/pg-counter-three", headers=test_auth_header)
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

    active_response = await client.get("/admin/gateways/pg-counter-three", headers=test_auth_header)
    assert active_response.status_code == 200
    active_gateway = active_response.json()
    assert active_gateway["status"] == "active"
    assert _response_value(active_gateway, "registration_attempts") == 0
    assert _response_value(active_gateway, "next_retry_at") is None
    assert _response_value(active_gateway, "last_error") is None
    assert active_gateway["reachable"] is True

    tools_response = await client.get("/tools", headers=test_auth_header)
    assert tools_response.status_code == 200
    initial_tool_names = {tool["name"] for tool in tools_response.json()}
    assert "pg-counter-three-echo-tool" in initial_tool_names

    update_response = await client.put(
        f"/gateways/{gateway_id}",
        json={"description": "updated postgres gateway description"},
        headers=test_auth_header,
    )
    assert update_response.status_code == 202
    updated_pending = update_response.json()
    assert updated_pending["status"] == "pending"

    live_gateway_service._initialize_gateway = AsyncMock(
        return_value=(
            {"tools": {"listChanged": True}},
            [_make_tool("updated_tool", "Updated Postgres tool")],
            [],
            [],
            [],
        )
    )
    await live_gateway_service._run_gateway_lifecycle_pass()

    updated_active_response = await client.get(f"/gateways/{gateway_id}", headers=test_auth_header)
    assert updated_active_response.status_code == 200
    assert updated_active_response.json()["status"] == "active"

    updated_tools_response = await client.get("/tools", headers=test_auth_header)
    assert updated_tools_response.status_code == 200
    updated_tool_names = {tool["name"] for tool in updated_tools_response.json()}
    assert "pg-counter-three-updated-tool" in updated_tool_names
    assert "pg-counter-three-echo-tool" not in updated_tool_names

    delete_response = await client.delete(f"/gateways/{gateway_id}", headers=test_auth_header)
    assert delete_response.status_code == 202
    deleting_gateway = delete_response.json()
    assert deleting_gateway["status"] == "deleting"

    await live_gateway_service._run_gateway_lifecycle_pass()

    deleted_response = await client.get("/admin/gateways/pg-counter-three", headers=test_auth_header)
    assert deleted_response.status_code == 404


@pytest.mark.asyncio
@SKIP_IF_NOT_EXTERNAL_POSTGRES
async def test_postgres_gateway_lifecycle_claims_prevent_duplicate_pickup(lifecycle_client):
    client, live_gateway_service, test_auth_header = lifecycle_client

    create_response = await client.post(
        "/gateways",
        json={"name": "pg-claim-one", "url": "http://example.com/mcp", "transport": "SSE"},
        headers=test_auth_header,
    )
    assert create_response.status_code == 202
    gateway_id = create_response.json()["id"]

    from mcpgateway.db import Gateway as DbGateway, SessionLocal

    first_claim = live_gateway_service._claim_due_gateway_lifecycle_ids({"pending"})
    second_service = type(live_gateway_service)()
    second_claim = second_service._claim_due_gateway_lifecycle_ids({"pending"})
    await second_service._http_client.aclose()

    assert first_claim == [gateway_id]
    assert second_claim == []

    with SessionLocal() as db:
        claimed_by = db.execute(select(DbGateway.lifecycle_claimed_by).where(DbGateway.id == gateway_id)).scalar_one()
    assert claimed_by == live_gateway_service._instance_id

    live_gateway_service._initialize_gateway = AsyncMock(
        return_value=(
            {"tools": {"listChanged": True}},
            [_make_tool("claim_tool", "Claim tool")],
            [],
            [],
            [],
        )
    )
    await live_gateway_service._process_gateway_lifecycle_batch(first_claim)

    with SessionLocal() as db:
        status, claimed_by = db.execute(select(DbGateway.status, DbGateway.lifecycle_claimed_by).where(DbGateway.id == gateway_id)).one()

    assert status == "active"
    assert claimed_by is None
