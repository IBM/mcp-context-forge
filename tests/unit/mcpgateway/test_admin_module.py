# -*- coding: utf-8 -*-
"""Tests for mcpgateway.admin helpers and auth flows."""

# Standard
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

# Third-Party
from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# First-Party
from mcpgateway import admin


def _make_request(root_path: str = "/admin") -> MagicMock:
    request = MagicMock(spec=Request)
    request.scope = {"root_path": root_path}
    request.headers = {}
    request.client = SimpleNamespace(host="127.0.0.1")
    templates = MagicMock()
    templates.TemplateResponse.return_value = HTMLResponse("<html>ok</html>")
    request.app = SimpleNamespace(state=SimpleNamespace(templates=templates))
    request.cookies = {}
    return request


def test_team_id_helpers():
    team_id = uuid4()
    assert admin._normalize_team_id(team_id) == UUID(str(team_id)).hex
    assert admin._normalize_team_id(None) is None

    with pytest.raises(ValueError):
        admin._normalize_team_id("not-a-uuid")

    with pytest.raises(HTTPException):
        admin._validated_team_id_param("not-a-uuid")


def test_client_ip_and_user_agent():
    request = MagicMock()
    request.headers = {"X-Forwarded-For": "192.168.1.1, 10.0.0.1", "User-Agent": "TestAgent"}
    request.client = SimpleNamespace(host="10.0.0.2")
    assert admin.get_client_ip(request) == "192.168.1.1"
    assert admin.get_user_agent(request) == "TestAgent"

    request.headers = {"X-Real-IP": "10.0.0.5"}
    assert admin.get_client_ip(request) == "10.0.0.5"

    request.headers = {}
    request.client = None
    assert admin.get_client_ip(request) == "unknown"
    assert admin.get_user_agent(request) == "unknown"


@pytest.mark.asyncio
async def test_rate_limit_enforcement(monkeypatch):
    monkeypatch.setattr(admin.settings, "validation_max_requests_per_minute", 1)
    admin.rate_limit_storage.clear()

    decorator = admin.rate_limit(1)

    @decorator
    async def handler(request: Request | None = None):
        return "ok"

    request = MagicMock(spec=Request)
    request.client = SimpleNamespace(host="1.2.3.4")

    assert await handler(request=request) == "ok"
    with pytest.raises(HTTPException):
        await handler(request=request)


def test_user_identity_helpers():
    assert admin.get_user_email({"sub": "a@example.com"}) == "a@example.com"
    assert admin.get_user_email({"email": "b@example.com"}) == "b@example.com"
    assert admin.get_user_email("c@example.com") == "c@example.com"
    assert admin.get_user_email(None) == "unknown"

    user_obj = SimpleNamespace(email="d@example.com", id="user-1")
    assert admin.get_user_email(user_obj) == "d@example.com"
    assert admin.get_user_id(user_obj) == "user-1"
    assert admin.get_user_id({"id": "user-2"}) == "user-2"
    assert admin.get_user_id("user-3") == "user-3"


def test_serialize_datetime_and_password_strength(monkeypatch):
    dt = datetime(2025, 1, 15, 10, 30, 45, tzinfo=timezone.utc)
    assert admin.serialize_datetime(dt) == "2025-01-15T10:30:45+00:00"
    assert admin.serialize_datetime("2025-01-15T10:30:45") == "2025-01-15T10:30:45"

    monkeypatch.setattr(admin.settings, "password_policy_enabled", False)
    assert admin.validate_password_strength("short") == (True, "")

    monkeypatch.setattr(admin.settings, "password_policy_enabled", True)
    monkeypatch.setattr(admin.settings, "password_min_length", 8)
    monkeypatch.setattr(admin.settings, "password_require_uppercase", True)
    monkeypatch.setattr(admin.settings, "password_require_lowercase", True)
    monkeypatch.setattr(admin.settings, "password_require_numbers", True)
    monkeypatch.setattr(admin.settings, "password_require_special", True)

    ok, msg = admin.validate_password_strength("Abcdef1!")
    assert ok is True and msg == ""

    ok, msg = admin.validate_password_strength("abcdef1!")
    assert ok is False and "uppercase" in msg


@pytest.mark.asyncio
async def test_admin_login_page(monkeypatch):
    request = _make_request()
    monkeypatch.setattr(admin.settings, "email_auth_enabled", False)
    response = await admin.admin_login_page(request)
    assert isinstance(response, RedirectResponse)

    monkeypatch.setattr(admin.settings, "email_auth_enabled", True)
    response = await admin.admin_login_page(request)
    assert isinstance(response, HTMLResponse)


@pytest.mark.asyncio
async def test_admin_login_handler_paths(monkeypatch):
    request = _make_request(root_path="/root")
    mock_db = MagicMock()

    monkeypatch.setattr(admin.settings, "email_auth_enabled", True)
    monkeypatch.setattr(admin.settings, "password_change_enforcement_enabled", False)
    monkeypatch.setattr(admin.settings, "detect_default_password_on_login", False)

    request.form = AsyncMock(return_value={"email": "admin@example.com"})
    response = await admin.admin_login_handler(request, mock_db)
    assert isinstance(response, RedirectResponse)
    assert "missing_fields" in response.headers["location"]

    request.form = AsyncMock(return_value={"email": "admin@example.com", "password": "pw"})
    auth_service = MagicMock()
    auth_service.authenticate_user = AsyncMock(return_value=None)
    monkeypatch.setattr(admin, "EmailAuthService", lambda db: auth_service)
    response = await admin.admin_login_handler(request, mock_db)
    assert "invalid_credentials" in response.headers["location"]

    user = SimpleNamespace(email="admin@example.com", password_change_required=True, password_changed_at=None, password_hash="hash")
    auth_service.authenticate_user = AsyncMock(return_value=user)
    monkeypatch.setattr(admin.settings, "password_change_enforcement_enabled", True)
    monkeypatch.setattr(admin, "create_access_token", AsyncMock(return_value=("token", None)))
    set_cookie = MagicMock()
    monkeypatch.setattr(admin, "set_auth_cookie", set_cookie)
    response = await admin.admin_login_handler(request, mock_db)
    assert "change-password-required" in response.headers["location"]
    assert set_cookie.called

    user.password_change_required = False
    monkeypatch.setattr(admin.settings, "password_change_enforcement_enabled", False)
    response = await admin.admin_login_handler(request, mock_db)
    assert response.headers["location"].endswith("/root/admin")


@pytest.mark.asyncio
async def test_admin_ui_with_team_filter_and_cookie(monkeypatch):
    request = _make_request(root_path="/root")
    mock_db = MagicMock()
    mock_db.commit = MagicMock()
    user = {"email": "user@example.com", "is_admin": True}

    monkeypatch.setattr(admin.settings, "email_auth_enabled", True)
    monkeypatch.setattr(admin.settings, "mcpgateway_a2a_enabled", False)
    monkeypatch.setattr(admin.settings, "mcpgateway_grpc_enabled", False)
    monkeypatch.setattr(admin.settings, "app_root_path", "/root")
    monkeypatch.setattr(admin.settings, "token_expiry", 60)
    monkeypatch.setattr(admin.settings, "secure_cookies", False)
    monkeypatch.setattr(admin.settings, "cookie_samesite", "lax")

    class FakeTeamService:
        def __init__(self, db):
            self.db = db

        async def get_user_teams(self, email):
            return [SimpleNamespace(id="team-1", name="Team One", type="organization", is_personal=False)]

        async def get_member_counts_batch_cached(self, team_ids):
            return {"team-1": 3}

        def get_user_roles_batch(self, email, team_ids):
            return {"team-1": "owner"}

    monkeypatch.setattr(admin, "TeamManagementService", FakeTeamService)

    class DummyModel:
        def __init__(self, **data):
            self._data = data

        def model_dump(self, by_alias: bool = False):
            return self._data

    async def list_tools(db, include_inactive=False, user_email=None, limit=0, team_id=None):
        return [DummyModel(team_id="team-1", url="http://tool", original_name="tool")]

    async def list_servers(db, include_inactive=False, user_email=None, limit=0):
        return ([DummyModel(team_id="team-1")], None)

    async def list_resources(db, include_inactive=False, user_email=None, limit=0, team_id=None):
        return [DummyModel(team_ids=["team-1"])]

    async def list_prompts(db, include_inactive=False, user_email=None, limit=0, team_id=None):
        return [DummyModel(team_id="team-1")]

    async def list_gateways(db, include_inactive=False, user_email=None, limit=0, team_id=None):
        return [DummyModel(team_id="team-1")]

    async def list_roots():
        return [DummyModel(id="root-1")]

    monkeypatch.setattr(admin.tool_service, "list_tools", list_tools)
    monkeypatch.setattr(admin.server_service, "list_servers", list_servers)
    monkeypatch.setattr(admin.resource_service, "list_resources", list_resources)
    monkeypatch.setattr(admin.prompt_service, "list_prompts", list_prompts)
    monkeypatch.setattr(admin.gateway_service, "list_gateways", list_gateways)
    monkeypatch.setattr(admin.root_service, "list_roots", list_roots)
    monkeypatch.setattr(admin, "create_jwt_token", AsyncMock(return_value="jwt"))

    response = await admin.admin_ui(request, "team-1", True, mock_db, user)
    assert isinstance(response, HTMLResponse)
    assert "jwt_token" in response.headers.get("set-cookie", "")
    context = request.app.state.templates.TemplateResponse.call_args[0][2]
    assert context["selected_team_id"] == "team-1"
    assert len(context["tools"]) == 1


@pytest.mark.asyncio
async def test_change_password_required_handler(monkeypatch):
    request = _make_request(root_path="/root")
    mock_db = MagicMock()
    monkeypatch.setattr(admin.settings, "email_auth_enabled", True)

    request.form = AsyncMock(return_value={"current_password": "old"})
    response = await admin.change_password_required_handler(request, mock_db)
    assert "missing_fields" in response.headers["location"]

    request.form = AsyncMock(return_value={"current_password": "old", "new_password": "new1", "confirm_password": "new2"})
    response = await admin.change_password_required_handler(request, mock_db)
    assert "mismatch" in response.headers["location"]

    request.form = AsyncMock(return_value={"current_password": "old", "new_password": "Newpass1!", "confirm_password": "Newpass1!"})
    request.cookies = {"jwt_token": "token"}
    request.headers = {"User-Agent": "TestAgent"}

    user = SimpleNamespace(email="user@example.com")
    monkeypatch.setattr(admin, "get_current_user", AsyncMock(return_value=user))

    auth_service = MagicMock()
    auth_service.change_password = AsyncMock(return_value=True)
    monkeypatch.setattr(admin, "EmailAuthService", lambda db: auth_service)
    monkeypatch.setattr(admin, "create_access_token", AsyncMock(return_value=("newtoken", None)))
    set_cookie = MagicMock()
    monkeypatch.setattr(admin, "set_auth_cookie", set_cookie)

    with patch("sqlalchemy.inspect", return_value=SimpleNamespace(transient=False, detached=False)):
        response = await admin.change_password_required_handler(request, mock_db)

    assert response.headers["location"].endswith("/root/admin")
    assert set_cookie.called
