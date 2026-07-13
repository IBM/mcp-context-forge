# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_search_endpoint.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Integration tests for the versioned unified search endpoint.

Exercises the full ASGI stack (routing, auth middleware, RBAC, orchestration)
against the real ``mcpgateway.main.app`` for:
  GET /search      (legacy unversioned alias)
  GET /v1/search   (canonical versioned path)

Complements the handler-level unit tests in
``tests/unit/mcpgateway/routers/test_search_router.py``. The per-entity
``admin_search_*`` DB queries are the only thing stubbed; the router,
middleware, and ``perform_unified_search`` orchestration all run for real.

Mirrors the pattern established for the public resource-by-URI endpoint in
``tests/integration/test_resource_management.py`` (PR #5455).
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
from mcpgateway.middleware.rbac import get_current_user_with_permissions, get_db as rbac_get_db, get_permission_service
from mcpgateway.utils.verify_credentials import require_auth


class _PermissionServiceAlwaysGrant:
    """Permission-service stand-in that grants every check.

    Uses ``**kwargs`` so it stays compatible with the full
    ``PermissionService.check_permission`` signature without mirroring it.
    """

    def __init__(self, *args, **kwargs):
        """Accept and ignore any constructor arguments."""

    async def check_permission(self, *args, **kwargs) -> bool:
        """Grant every permission check.

        Returns:
            bool: Always ``True``.
        """
        return True

    async def check_admin_permission(self, *args, **kwargs) -> bool:
        """Grant every admin permission check.

        Returns:
            bool: Always ``True``.
        """
        return True


@pytest.fixture(scope="module")
def _auth_client():
    """TestClient over the real app + a temp SQLite DB, with auth mocked to an admin.

    Yields:
        tuple: ``(client, auth_headers)`` for authenticated requests.
    """
    mp = MonkeyPatch()

    fd, path = tempfile.mkstemp(suffix=".db")
    url = f"sqlite:///{path}"

    # First-Party
    from mcpgateway.config import settings

    mp.setattr(settings, "database_url", url, raising=False)

    # First-Party
    import mcpgateway.db as db_mod
    import mcpgateway.main as main_mod

    engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    mp.setattr(db_mod, "engine", engine, raising=False)
    mp.setattr(db_mod, "SessionLocal", TestSessionLocal, raising=False)
    mp.setattr(main_mod, "SessionLocal", TestSessionLocal, raising=False)
    mp.setattr(main_mod, "engine", engine, raising=False)

    db_mod.Base.metadata.create_all(bind=engine)

    mock_email_user = MagicMock()
    mock_email_user.email = "integration-test-user@example.com"
    mock_email_user.is_admin = True
    mock_email_user.is_active = True

    async def _mock_user_with_permissions():
        db_session = TestSessionLocal()
        try:
            yield {
                "email": "integration-test-user@example.com",
                "is_admin": True,
                "ip_address": "127.0.0.1",
                "user_agent": "test-client",
                "db": db_session,
            }
        finally:
            db_session.close()

    def _override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    from mcpgateway.main import app

    with patch("mcpgateway.middleware.rbac.PermissionService", _PermissionServiceAlwaysGrant):
        app.dependency_overrides[require_auth] = lambda: "integration-test-user"
        app.dependency_overrides[get_current_user] = lambda: mock_email_user
        app.dependency_overrides[get_current_user_with_permissions] = _mock_user_with_permissions
        app.dependency_overrides[get_permission_service] = lambda *a, **k: _PermissionServiceAlwaysGrant()
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


class TestUnifiedSearchIntegration:
    """Full-stack tests for GET /[v1/]search."""

    # ------------------------------------------------------------------
    # Authenticated success paths
    # ------------------------------------------------------------------

    @patch("mcpgateway.admin.admin_search_servers", new_callable=AsyncMock)
    @patch("mcpgateway.admin.admin_search_tools", new_callable=AsyncMock)
    def test_v1_search_authenticated_returns_200_grouped(self, mock_tools, mock_servers, _auth_client):
        """GET /v1/search returns 200 with the grouped + flattened contract."""
        client, auth_headers = _auth_client
        mock_tools.return_value = {"tools": [{"id": "tool-1", "name": "Alpha"}], "count": 1}
        mock_servers.return_value = {"servers": [{"id": "srv-1", "name": "Beta"}], "count": 1}

        response = client.get("/v1/search?q=a&entity_types=tools,servers", headers=auth_headers)

        assert response.status_code == 200
        body = response.json()
        assert body["entity_types"] == ["tools", "servers"]
        assert body["results"]["tools"][0]["id"] == "tool-1"
        assert body["results"]["servers"][0]["id"] == "srv-1"
        assert body["count"] == 2
        assert {item["entity_type"] for item in body["items"]} == {"tools", "servers"}

    @patch("mcpgateway.admin.admin_search_tools", new_callable=AsyncMock)
    def test_legacy_search_prefix_returns_200(self, mock_tools, _auth_client):
        """The legacy unversioned /search alias routes to the same handler."""
        client, auth_headers = _auth_client
        mock_tools.return_value = {"tools": [{"id": "tool-9", "name": "Gamma"}], "count": 1}

        response = client.get("/search?q=g&entity_types=tools", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["results"]["tools"][0]["id"] == "tool-9"

    @patch("mcpgateway.admin.admin_search_tools", new_callable=AsyncMock)
    def test_limit_per_type_forwarded_through_real_orchestration(self, mock_tools, _auth_client):
        """limit_per_type reaches the per-entity search via the real orchestration."""
        client, auth_headers = _auth_client
        mock_tools.return_value = {"tools": [], "count": 0}

        response = client.get("/v1/search?q=a&entity_types=tools&limit=8&limit_per_type=3", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["limit_per_type"] == 3
        assert mock_tools.await_args.kwargs["limit"] == 3

    # ------------------------------------------------------------------
    # Authentication rejection (full middleware stack)
    # ------------------------------------------------------------------

    def test_v1_search_unauthenticated_returns_401(self, app_with_temp_db):
        """GET /v1/search without credentials is rejected with 401."""
        from fastapi import HTTPException, status as http_status

        def _no_auth():
            raise HTTPException(status_code=http_status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

        app_with_temp_db.dependency_overrides[get_current_user_with_permissions] = _no_auth
        try:
            client = TestClient(app_with_temp_db, raise_server_exceptions=False)
            assert client.get("/v1/search?q=a").status_code == 401
        finally:
            app_with_temp_db.dependency_overrides.pop(get_current_user_with_permissions, None)

    def test_legacy_search_unauthenticated_returns_401(self, app_with_temp_db):
        """GET /search (legacy) without credentials is also rejected with 401."""
        from fastapi import HTTPException, status as http_status

        def _no_auth():
            raise HTTPException(status_code=http_status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

        app_with_temp_db.dependency_overrides[get_current_user_with_permissions] = _no_auth
        try:
            client = TestClient(app_with_temp_db, raise_server_exceptions=False)
            assert client.get("/search?q=a").status_code == 401
        finally:
            app_with_temp_db.dependency_overrides.pop(get_current_user_with_permissions, None)
