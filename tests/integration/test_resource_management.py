# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_resource_management.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Integration tests for resource management, exercised through the real HTTP
endpoints (auth, RBAC, routing, service layer) rather than mocked handler
internals.

Covers:
  - GET /resources/test/{resource_uri:path}  (legacy prefix)
  - GET /v1/resources/test/{resource_uri:path}  (canonical v1 prefix)
    Issue #5356 acceptance criteria requires both unit **and** integration tests.
  - POST /resources/ duplicate-name conflict handling (issue #4991): creating a
    resource with a name that already exists must return 409 with a meaningful
    conflict message, not an opaque IntegrityError.
"""

# Future
from __future__ import annotations

# Standard
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from _pytest.monkeypatch import MonkeyPatch
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.auth import get_current_user
from mcpgateway.db import Base
from mcpgateway.main import app
from mcpgateway.middleware.rbac import get_current_user_with_permissions, get_db as rbac_get_db, get_permission_service
from mcpgateway.utils.verify_credentials import require_auth

# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------


class _PermissionServiceAlwaysGrant:
    """Minimal permission-service stand-in that grants every check.

    `require_permission` instantiates `PermissionService(db)` directly inside
    its wrapper rather than resolving it via FastAPI DI, so the class itself
    must be patched -- overriding the `get_permission_service` dependency
    alone is not enough. Uses ``**kwargs`` so it stays compatible with the
    full ``PermissionService.check_permission`` signature (which includes
    ``token_teams``, ``allow_admin_bypass``, ``check_any_team``, etc.)
    without needing to mirror every parameter explicitly.
    """

    def __init__(self, *args, **kwargs):
        pass

    async def check_permission(self, *args, **kwargs) -> bool:
        return True

    async def check_admin_permission(self, *args, **kwargs) -> bool:
        return True


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _auth_client():
    """FastAPI TestClient backed by a real SQLite DB with auth fully mocked out.

    Yields a ``(client, auth_headers)`` tuple.  The auth overrides stay active
    for the lifetime of the module so that individual tests only need to patch
    the service layer.
    """
    mp = MonkeyPatch()

    fd, path = tempfile.mkstemp(suffix=".db")
    url = f"sqlite:///{path}"

    from mcpgateway.config import settings
    import mcpgateway.db as db_mod
    import mcpgateway.main as main_mod

    mp.setattr(settings, "database_url", url, raising=False)

    engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    mp.setattr(db_mod, "engine", engine, raising=False)
    mp.setattr(db_mod, "SessionLocal", TestSessionLocal, raising=False)
    mp.setattr(main_mod, "SessionLocal", TestSessionLocal, raising=False)
    mp.setattr(main_mod, "engine", engine, raising=False)

    db_mod.Base.metadata.create_all(bind=engine)

    mock_email_user = MagicMock()
    mock_email_user.email = "integration-test-user@example.com"
    mock_email_user.full_name = "Integration Test User"
    mock_email_user.is_admin = True
    mock_email_user.is_active = True

    async def _mock_user_with_permissions():
        db_session = TestSessionLocal()
        try:
            yield {
                "email": "integration-test-user@example.com",
                "full_name": "Integration Test User",
                "is_admin": True,
                "ip_address": "127.0.0.1",
                "user_agent": "test-client",
                "db": db_session,
            }
        finally:
            db_session.close()

    def _mock_get_permission_service(*args, **kwargs):
        return _PermissionServiceAlwaysGrant()

    def _override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    with patch("mcpgateway.middleware.rbac.PermissionService", _PermissionServiceAlwaysGrant):
        app.dependency_overrides[require_auth] = lambda: "integration-test-user"
        app.dependency_overrides[get_current_user] = lambda: mock_email_user
        app.dependency_overrides[get_current_user_with_permissions] = _mock_user_with_permissions
        app.dependency_overrides[get_permission_service] = _mock_get_permission_service
        app.dependency_overrides[rbac_get_db] = _override_get_db

        client = TestClient(app, raise_server_exceptions=False)
        auth_headers = {"Authorization": "Bearer integration.test.token"}  # pragma: allowlist secret
        yield client, auth_headers

        app.dependency_overrides.pop(require_auth, None)
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_current_user_with_permissions, None)
        app.dependency_overrides.pop(get_permission_service, None)
        app.dependency_overrides.pop(rbac_get_db, None)

    mp.undo()
    engine.dispose()
    os.close(fd)
    os.unlink(path)


@pytest.fixture
def test_app():
    """Wire the real app to an isolated (function-scoped) temp SQLite DB with
    auth/RBAC overridden. Separate from `_auth_client` above because the
    name-conflict tests below create real rows through the unmocked service
    layer and need per-test isolation rather than a module-shared DB.
    """
    mp = MonkeyPatch()

    fd, path = tempfile.mkstemp(suffix=".db")
    url = f"sqlite:///{path}"

    from mcpgateway.config import settings
    import mcpgateway.db as db_mod
    import mcpgateway.main as main_mod

    mp.setattr(settings, "database_url", url, raising=False)

    engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    mp.setattr(db_mod, "engine", engine, raising=False)
    mp.setattr(db_mod, "SessionLocal", TestingSessionLocal, raising=False)
    mp.setattr(main_mod, "SessionLocal", TestingSessionLocal, raising=False)
    mp.setattr(main_mod, "engine", engine, raising=False)

    Base.metadata.create_all(bind=engine)

    mock_user = MagicMock()
    mock_user.email = "test_user@example.com"
    mock_user.full_name = "Test User"
    mock_user.is_admin = True
    mock_user.is_active = True

    async def mock_user_with_permissions():
        db_session = TestingSessionLocal()
        try:
            yield {
                "email": "test_user@example.com",
                "full_name": "Test User",
                "is_admin": True,
                "ip_address": "127.0.0.1",
                "user_agent": "test-client",
                "db": db_session,
            }
        finally:
            db_session.close()

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    with patch("mcpgateway.middleware.rbac.PermissionService", _PermissionServiceAlwaysGrant):
        app.dependency_overrides[require_auth] = lambda: "test_user"
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_current_user_with_permissions] = mock_user_with_permissions
        app.dependency_overrides[get_permission_service] = _PermissionServiceAlwaysGrant
        app.dependency_overrides[rbac_get_db] = override_get_db

        yield app

        app.dependency_overrides.pop(require_auth, None)
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_current_user_with_permissions, None)
        app.dependency_overrides.pop(get_permission_service, None)
        app.dependency_overrides.pop(rbac_get_db, None)

    mp.undo()
    engine.dispose()
    os.close(fd)
    os.unlink(path)


@pytest.fixture
def client(test_app):
    return TestClient(test_app)


@pytest.fixture
def auth_headers() -> dict:
    return {"Authorization": "Bearer test.token.resource_management"}  # pragma: allowlist secret


# ---------------------------------------------------------------------------
# Integration test class: resource-by-URI endpoint (issue #5356)
# ---------------------------------------------------------------------------


class TestResourceByUriIntegration:
    """Integration tests for GET /[v1/]resources/test/{resource_uri:path}.

    These tests exercise the full ASGI middleware stack — authentication,
    RBAC middleware, routing, and the service call — rather than mocking
    individual handler internals as unit tests do.
    """

    # ------------------------------------------------------------------
    # Authenticated success paths
    # ------------------------------------------------------------------

    @patch("mcpgateway.main.resource_service.read_resource", new_callable=AsyncMock)
    def test_authenticated_success_returns_200_with_content(self, mock_read, _auth_client):
        """Authenticated GET /resources/test/{uri} returns 200 wrapping service output."""
        client, auth_headers = _auth_client
        mock_read.return_value = {"text": "hello from resource", "mime_type": "text/plain"}

        response = client.get("/resources/test/file:///tmp/hello.txt", headers=auth_headers)

        assert response.status_code == 200
        body = response.json()
        assert "content" in body
        assert body["content"]["text"] == "hello from resource"
        mock_read.assert_awaited_once()

    @patch("mcpgateway.main.resource_service.read_resource", new_callable=AsyncMock)
    def test_v1_prefix_authenticated_success_returns_200(self, mock_read, _auth_client):
        """Authenticated GET /v1/resources/test/{uri} routes to the same handler."""
        client, auth_headers = _auth_client
        mock_read.return_value = {"text": "versioned content"}

        response = client.get("/v1/resources/test/resource://example/demo", headers=auth_headers)

        assert response.status_code == 200
        body = response.json()
        assert body["content"]["text"] == "versioned content"

    @patch("mcpgateway.main.resource_service.read_resource", new_callable=AsyncMock)
    def test_resource_uri_with_nested_path_segments_preserved(self, mock_read, _auth_client):
        """Multi-segment URIs (resource://host/a/b/c) are passed verbatim to the service."""
        client, auth_headers = _auth_client
        mock_read.return_value = {"data": "nested"}

        client.get("/resources/test/resource://host/a/b/c", headers=auth_headers)

        call_kwargs = mock_read.call_args[1]
        assert call_kwargs["resource_uri"] == "resource://host/a/b/c"

    # ------------------------------------------------------------------
    # Error paths
    # ------------------------------------------------------------------

    @patch("mcpgateway.main.resource_service.read_resource", new_callable=AsyncMock)
    def test_resource_not_found_returns_404(self, mock_read, _auth_client):
        """Service raising ResourceNotFoundError → HTTP 404."""
        from mcpgateway.services.resource_service import ResourceNotFoundError

        client, auth_headers = _auth_client
        mock_read.side_effect = ResourceNotFoundError("resource://example/missing not found")

        response = client.get("/resources/test/resource://example/missing", headers=auth_headers)

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @patch("mcpgateway.main.resource_service.read_resource", new_callable=AsyncMock)
    def test_v1_prefix_resource_not_found_returns_404(self, mock_read, _auth_client):
        """Same 404 behaviour via the /v1 prefix."""
        from mcpgateway.services.resource_service import ResourceNotFoundError

        client, auth_headers = _auth_client
        mock_read.side_effect = ResourceNotFoundError("not found")

        response = client.get("/v1/resources/test/resource://example/gone", headers=auth_headers)

        assert response.status_code == 404

    # ------------------------------------------------------------------
    # Authentication / authorisation rejection
    # ------------------------------------------------------------------

    def test_unauthenticated_request_returns_401(self, app_with_temp_db):
        """GET /resources/test/{uri} without credentials must be rejected with 401.

        Overrides the auth dependency to raise 401 — the same way the app behaves
        when ``auth_required=True`` and no credentials are supplied — then verifies
        the full ASGI middleware stack propagates that rejection correctly.
        """
        from fastapi import HTTPException, status as http_status

        def _no_auth():
            raise HTTPException(status_code=http_status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

        app_with_temp_db.dependency_overrides[get_current_user_with_permissions] = _no_auth
        try:
            unauthenticated_client = TestClient(app_with_temp_db, raise_server_exceptions=False)
            response = unauthenticated_client.get("/resources/test/resource://example/demo")
            assert response.status_code == 401
        finally:
            app_with_temp_db.dependency_overrides.pop(get_current_user_with_permissions, None)

    def test_v1_unauthenticated_request_returns_401(self, app_with_temp_db):
        """GET /v1/resources/test/{uri} without credentials must also return 401."""
        from fastapi import HTTPException, status as http_status

        def _no_auth():
            raise HTTPException(status_code=http_status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

        app_with_temp_db.dependency_overrides[get_current_user_with_permissions] = _no_auth
        try:
            unauthenticated_client = TestClient(app_with_temp_db, raise_server_exceptions=False)
            response = unauthenticated_client.get("/v1/resources/test/resource://example/demo")
            assert response.status_code == 401
        finally:
            app_with_temp_db.dependency_overrides.pop(get_current_user_with_permissions, None)


# ---------------------------------------------------------------------------
# Integration test class: duplicate resource-name conflict (issue #4991)
# ---------------------------------------------------------------------------


class TestResourceNameConflict:
    """End-to-end coverage for issue #4991: duplicate resource name -> 409."""

    def test_duplicate_resource_name_returns_409_with_message(self, client, auth_headers):
        """Creating a resource, then creating another with the same name (public
        visibility) must return 409 with a message naming the conflicting resource,
        not a raw IntegrityError."""
        body = {
            "resource": {
                "uri": "test://resource-one",
                "name": "duplicate-name",
                "description": "first resource",
                "content": "hello",
                "mime_type": "text/plain",
            },
            "visibility": "public",
        }
        first = client.post("/resources/", json=body, headers=auth_headers)
        assert first.status_code == 200, first.text

        dup_body = {
            "resource": {
                "uri": "test://resource-two",
                "name": "duplicate-name",
                "description": "second resource, different URI",
                "content": "world",
                "mime_type": "text/plain",
            },
            "visibility": "public",
        }
        second = client.post("/resources/", json=dup_body, headers=auth_headers)

        assert second.status_code == 409, second.text
        detail = second.json()["detail"]
        assert "duplicate-name" in detail
        assert "already exists" in detail

    def test_different_names_do_not_conflict(self, client, auth_headers):
        """Sanity check: distinct names never trigger the conflict path."""
        for i in range(2):
            body = {
                "resource": {
                    "uri": f"test://resource-{i}",
                    "name": f"unique-name-{i}",
                    "description": "resource",
                    "content": "content",
                    "mime_type": "text/plain",
                },
                "visibility": "public",
            }
            resp = client.post("/resources/", json=body, headers=auth_headers)
            assert resp.status_code == 200, resp.text
