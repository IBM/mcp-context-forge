"""Integration tests for canonical_url OAuth flow.

Tests the E2E flow: create server with canonical_url → well-known metadata
resolution → WWW-Authenticate header with canonical metadata URL.
"""

# Third-Party
from fastapi.testclient import TestClient
import pytest


@pytest.fixture
def test_app():
    import os
    import tempfile
    from unittest.mock import MagicMock, patch

    from _pytest.monkeypatch import MonkeyPatch
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    mp = MonkeyPatch()

    fd, path = tempfile.mkstemp(suffix=".db")
    url = f"sqlite:///{path}"

    from mcpgateway.config import settings

    mp.setattr(settings, "database_url", url, raising=False)
    mp.setattr(settings, "app_domain", "https://gw.example.com", raising=False)
    mp.setattr(settings, "auth_required", False, raising=False)

    import mcpgateway.db as db_mod
    from mcpgateway.main import app as main_app
    import mcpgateway.main as main_mod
    from mcpgateway.utils.verify_credentials import require_auth

    engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    mp.setattr(db_mod, "engine", engine, raising=False)
    mp.setattr(db_mod, "SessionLocal", TestingSessionLocal, raising=False)
    mp.setattr(main_mod, "SessionLocal", TestingSessionLocal, raising=False)
    mp.setattr(main_mod, "engine", engine, raising=False)

    from mcpgateway.db import Base

    Base.metadata.create_all(bind=engine)

    # Seed a gateway record for tests
    gw_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    gw_db = TestingSessionLocal()
    try:
        from mcpgateway.db import Gateway
        gw = Gateway(
            id=gw_id, name="test-gw", slug="test-gw", url="https://gw.example.com",
            capabilities={}, enabled=True,
        )
        gw_db.add(gw)
        gw_db.commit()
    finally:
        gw_db.close()

    from mcpgateway.auth import get_current_user
    from mcpgateway.middleware.rbac import get_current_user_with_permissions
    from mcpgateway.middleware.rbac import get_db as rbac_get_db
    from mcpgateway.middleware.rbac import get_permission_service

    mock_email_user = MagicMock()
    mock_email_user.email = "admin@example.com"
    mock_email_user.full_name = "Admin"
    mock_email_user.is_admin = True
    mock_email_user.is_active = True

    async def mock_user_with_permissions():
        db_session = TestingSessionLocal()
        try:
            yield {
                "email": "admin@example.com",
                "full_name": "Admin",
                "is_admin": True,
                "ip_address": "127.0.0.1",
                "user_agent": "test-client",
                "db": db_session,
            }
        finally:
            db_session.close()

    def mock_get_permission_service(*args, **kwargs):
        from tests.utils.rbac_mocks import MockPermissionService
        return MockPermissionService(always_grant=True)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    from tests.utils.rbac_mocks import MockPermissionService

    with patch("mcpgateway.middleware.rbac.PermissionService", MockPermissionService):
        with patch("mcpgateway.routers.well_known.get_base_url_with_protocol", return_value="https://gw.example.com"):
            main_app.dependency_overrides[require_auth] = lambda: "admin"
            main_app.dependency_overrides[get_current_user] = lambda: mock_email_user
            main_app.dependency_overrides[get_current_user_with_permissions] = mock_user_with_permissions
            main_app.dependency_overrides[get_permission_service] = mock_get_permission_service
            main_app.dependency_overrides[rbac_get_db] = override_get_db

            yield main_app, TestingSessionLocal, gw_id

            main_app.dependency_overrides.pop(require_auth, None)
            main_app.dependency_overrides.pop(get_current_user, None)
            main_app.dependency_overrides.pop(get_current_user_with_permissions, None)
            main_app.dependency_overrides.pop(get_permission_service, None)
            main_app.dependency_overrides.pop(rbac_get_db, None)

    mp.undo()
    engine.dispose()
    os.close(fd)
    os.unlink(path)


@pytest.fixture
def client(test_app):
    app_instance, _, _ = test_app
    return TestClient(app_instance)


@pytest.fixture
def auth_headers():
    return {}


@pytest.fixture
def server_with_canonical(client, auth_headers, test_app):
    _, TestingSessionLocal, gw_id = test_app

    canonical_path = "/my-canon-srv/mcp"
    server_data = {
        "server": {
            "name": "canon-srv",
            "gateway_id": gw_id,
            "oauth_enabled": True,
            "oauth_config": {
                "authorization_server": "https://auth.example.com",
            },
            "canonical_url": f"https://gw.example.com{canonical_path}",
        },
        "team_id": None,
        "visibility": "public",
    }
    response = client.post("/servers/", json=server_data, headers=auth_headers)
    assert response.status_code == 201, f"Server creation failed: {response.text}"
    return response.json(), canonical_path


class TestCanonicalUrlOAuthFlow:
    """End-to-end tests for canonical_url OAuth flow."""

    def test_create_server_with_canonical(self, server_with_canonical):
        server, _ = server_with_canonical
        assert server["canonicalUrl"] == "https://gw.example.com/my-canon-srv/mcp"

    def test_well_known_uuid_path_returns_canonical_resource(self, client, server_with_canonical):
        server, _ = server_with_canonical
        server_id = server["id"]
        response = client.get(f"/.well-known/oauth-protected-resource/servers/{server_id}/mcp")
        assert response.status_code == 200
        data = response.json()
        assert data["resource"] == "https://gw.example.com/my-canon-srv/mcp"

    def test_well_known_canonical_path_returns_metadata(self, client, server_with_canonical):
        server, canonical_path = server_with_canonical
        response = client.get(f"/.well-known/oauth-protected-resource{canonical_path}")
        assert response.status_code == 200
        data = response.json()
        assert "resource" in data
        assert "authorization_servers" in data

    def test_well_known_canonical_path_404_for_unknown(self, client):
        response = client.get("/.well-known/oauth-protected-resource/nonexistent/path/mcp")
        assert response.status_code == 404

    def test_well_known_uuid_path_returns_uuid_when_no_canonical(self, client, auth_headers, test_app):
        _, TestingSessionLocal, gw_id = test_app

        server_data = {
            "server": {
                "name": "plain-srv",
                "gateway_id": gw_id,
                "oauth_enabled": True,
                "oauth_config": {
                    "authorization_server": "https://auth.example.com",
                },
            },
            "team_id": None,
            "visibility": "public",
        }
        response = client.post("/servers/", json=server_data, headers=auth_headers)
        server = response.json()
        server_id = server["id"]

        response = client.get(f"/.well-known/oauth-protected-resource/servers/{server_id}/mcp")
        assert response.status_code == 200
        data = response.json()
        assert server_id in data["resource"]
