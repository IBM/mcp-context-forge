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
from datetime import datetime, timezone
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

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


@pytest.fixture
def _auth_client():
    """TestClient over the real app + a temp SQLite DB, with auth mocked to an admin.

    Function-scoped on purpose: the body holds a ``patch(PermissionService=...)``
    context and mutates ``app.dependency_overrides``. Module scope would keep that
    patch active for the whole file and leak the AlwaysGrant permission service
    into the later real-PermissionService tests in this module.

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


# ---------------------------------------------------------------------------
# Real-data RBAC / token-scoping regression
# ---------------------------------------------------------------------------
#
# Unlike the tests above (which stub admin_search_* and grant all permissions),
# these seed real rows and run the real handlers + real PermissionService so the
# security claim is proven end-to-end: a caller only sees entities their token
# scope permits. Layer 2 (tools.read) is a real but global pass-through so the
# thing under test is Layer 1 visibility/token scoping, not the permission gate.
#
# Note: identity is injected (not full JWT-middleware validation). PermissionService,
# admin_search_tools, and the DB rows are all real; a dedicated JWT-path test is a
# separate concern.

SEARCH_TERM = "zzzsearchable"


@pytest.fixture
def _real_data_env():
    """Real app + temp DB seeded with teams, a non-admin member, and scoped tools.

    Yields:
        tuple: ``(app, TestSessionLocal, ids)`` where ``ids`` maps logical names
        (public/teama/teamb tool ids, team_a/team_b ids, user_b email) to values.
    """
    mp = MonkeyPatch()

    fd, path = tempfile.mkstemp(suffix=".db")
    url = f"sqlite:///{path}"

    from mcpgateway.config import settings

    mp.setattr(settings, "database_url", url, raising=False)

    import mcpgateway.db as db_mod
    import mcpgateway.main as main_mod

    engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    mp.setattr(db_mod, "engine", engine, raising=False)
    mp.setattr(db_mod, "SessionLocal", TestSessionLocal, raising=False)
    mp.setattr(main_mod, "SessionLocal", TestSessionLocal, raising=False)
    mp.setattr(main_mod, "engine", engine, raising=False)

    db_mod.Base.metadata.create_all(bind=engine)

    from mcpgateway.db import EmailTeam, EmailTeamMember, EmailUser, Role, Server, Tool, UserRole

    now = datetime.now(timezone.utc)
    team_a = uuid.uuid4().hex
    team_b = uuid.uuid4().hex
    user_b = "user-b@example.com"
    owner = "owner@example.com"  # owns the tools so user_b access is never via ownership

    def _user(email):
        return EmailUser(id=uuid.uuid4().hex, email=email, password_hash="x", full_name=email, is_admin=False, is_active=True, auth_provider="local", email_verified_at=now)  # pragma: allowlist secret

    def _tool(name, visibility, team_id):
        return Tool(
            id=uuid.uuid4().hex,
            original_name=name,
            url=f"http://example.com/{name}",
            owner_email=owner,
            team_id=team_id,
            visibility=visibility,
            integration_type="REST",
            request_type="GET",
            input_schema={},
            output_schema={},
            enabled=True,
            deprecated=False,
            created_by=owner,
            tags=[],
        )

    db = TestSessionLocal()
    db.add_all([_user(user_b), _user(owner)])
    db.add_all(
        [
            EmailTeam(id=team_a, name="Team A", slug="team-a", created_by=owner, is_personal=False, visibility="public"),
            EmailTeam(id=team_b, name="Team B", slug="team-b", created_by=owner, is_personal=False, visibility="public"),
        ]
    )
    db.commit()

    # user_b is a real member of BOTH teams (so team-A is genuinely accessible),
    # and holds a real GLOBAL tools.read role (Layer 2 pass-through).
    role_id = uuid.uuid4().hex
    db.add_all(
        [
            EmailTeamMember(id=uuid.uuid4().hex, team_id=team_a, user_email=user_b, role="member", is_active=True),
            EmailTeamMember(id=uuid.uuid4().hex, team_id=team_b, user_email=user_b, role="member", is_active=True),
            Role(id=role_id, name="test-tools-reader", scope="global", permissions=["tools.read"], created_by=owner, is_active=True),
            UserRole(id=uuid.uuid4().hex, user_email=user_b, role_id=role_id, scope="global", scope_id=None, granted_by=owner, is_active=True),
        ]
    )

    t_public = _tool(f"{SEARCH_TERM}-public", "public", None)
    t_teama = _tool(f"{SEARCH_TERM}-teama", "team", team_a)
    t_teamb = _tool(f"{SEARCH_TERM}-teamb", "team", team_b)
    # A public server matching the search term: any caller WITH servers.read would
    # see it, so an empty servers result proves the servers.read denial (not no data).
    s_public = Server(id=uuid.uuid4().hex, name=f"{SEARCH_TERM}-server", visibility="public", enabled=True, owner_email=owner, tags=[])
    db.add_all([t_public, t_teama, t_teamb, s_public])
    db.commit()

    ids = {
        "public": t_public.id,
        "teama": t_teama.id,
        "teamb": t_teamb.id,
        "server_public": s_public.id,
        "team_a": team_a,
        "team_b": team_b,
        "user_b": user_b,
    }
    db.close()

    from mcpgateway.main import app

    yield app, TestSessionLocal, ids

    app.dependency_overrides.pop(get_current_user_with_permissions, None)
    mp.undo()
    engine.dispose()
    os.close(fd)
    os.unlink(path)


def _inject_identity(app, TestSessionLocal, email, token_teams=None):
    """Override the auth dependency to yield a non-admin context, optionally token-scoped.

    Args:
        app: The FastAPI app to override on.
        TestSessionLocal: Session factory bound to the temp DB.
        email (str): Caller email.
        token_teams: When provided, narrows the caller's visible team scope
            (list of team-id strings); when ``None``, the key is omitted so the
            caller's full DB team membership applies.
    """

    async def _ctx():
        session = TestSessionLocal()
        try:
            context = {"email": email, "is_admin": False, "ip_address": "127.0.0.1", "user_agent": "test-client", "db": session}
            if token_teams is not None:
                context["token_teams"] = token_teams
            yield context
        finally:
            session.close()

    app.dependency_overrides[get_current_user_with_permissions] = _ctx


class TestUnifiedSearchRealDataScoping:
    """Real-data tests proving /v1/search enforces token/team visibility scoping."""

    def test_token_scope_hides_other_teams_private_tool(self, _real_data_env):
        """A token scoped to team-B sees public + team-B tools, not team-A's private tool."""
        app, TestSessionLocal, ids = _real_data_env
        _inject_identity(app, TestSessionLocal, ids["user_b"], token_teams=[ids["team_b"]])

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(f"/v1/search?q={SEARCH_TERM}&entity_types=tools", headers={"Authorization": "Bearer x"})

        assert resp.status_code == 200
        returned = {tool["id"] for tool in resp.json()["results"]["tools"]}
        assert ids["public"] in returned  # public visible (positive)
        assert ids["teamb"] in returned  # own-team visible (positive: search did not collapse)
        assert ids["teama"] not in returned  # other-team private hidden (the deny)

    def test_without_token_narrowing_member_sees_both_teams(self, _real_data_env):
        """Contrast: same user, no token narrowing, sees team-A too (deny above was the token)."""
        app, TestSessionLocal, ids = _real_data_env
        _inject_identity(app, TestSessionLocal, ids["user_b"], token_teams=None)

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(f"/v1/search?q={SEARCH_TERM}&entity_types=tools", headers={"Authorization": "Bearer x"})

        assert resp.status_code == 200
        returned = {tool["id"] for tool in resp.json()["results"]["tools"]}
        assert ids["public"] in returned
        assert ids["teamb"] in returned
        assert ids["teama"] in returned  # visible now via real membership -> confirms the token caused the deny

    def test_non_admin_users_entity_dropped_without_collapsing_search(self, _real_data_env):
        """A non-admin requesting tools,users gets tools back and users silently dropped."""
        app, TestSessionLocal, ids = _real_data_env
        _inject_identity(app, TestSessionLocal, ids["user_b"], token_teams=[ids["team_b"]])

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(f"/v1/search?q={SEARCH_TERM}&entity_types=tools,users", headers={"Authorization": "Bearer x"})

        assert resp.status_code == 200
        body = resp.json()
        assert "users" not in body["entity_types"]  # restricted entity removed (no admin.user_management)
        assert ids["teamb"] in {tool["id"] for tool in body["results"]["tools"]}  # tools still returned (positive)

    def test_denied_entity_returns_empty_without_collapsing_search(self, _real_data_env):
        """A real servers.read denial is swallowed to empty; the allowed tools still return.

        user_b has tools.read but not servers.read, so admin_search_servers raises a
        genuine 403 that _safe_entity_search turns into empty results. The seeded public
        server matches the query, so empty servers proves the denial (not missing data).
        """
        app, TestSessionLocal, ids = _real_data_env
        _inject_identity(app, TestSessionLocal, ids["user_b"], token_teams=[ids["team_b"]])

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(f"/v1/search?q={SEARCH_TERM}&entity_types=servers,tools", headers={"Authorization": "Bearer x"})

        assert resp.status_code == 200  # a denied entity must not fail the whole request
        body = resp.json()
        assert body["results"]["servers"] == []  # servers.read denied -> 403 -> swallowed to empty
        assert body["results"]["tools"]  # allowed entity still returned (search did not collapse)
        assert ids["teamb"] in {tool["id"] for tool in body["results"]["tools"]}
