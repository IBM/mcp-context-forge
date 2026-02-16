# -*- coding: utf-8 -*-
"""Tests for mcpgateway.admin helpers and auth flows."""

# Standard
import base64
from datetime import datetime, timezone
import inspect
import json
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

# Third-Party
from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# First-Party
from mcpgateway import admin
from mcpgateway.services.permission_service import PermissionService
from mcpgateway.services.server_service import ServerNotFoundError
from mcpgateway.utils.passthrough_headers import PassthroughHeadersError


def _make_id_token(exp_offset: int = 3600) -> str:
    """Create a minimal unsigned JWT with the given expiry offset from now."""
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps({"exp": int(time.time()) + exp_offset}).encode()).rstrip(b"=").decode()
    return f"{header}.{payload}.sig"


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


def _response_text(response: HTMLResponse) -> str:
    return response.body.decode()


def _allow_permissions(monkeypatch):
    async def _ok(self, **kwargs):  # type: ignore[no-self-use]
        return True

    monkeypatch.setattr(PermissionService, "check_permission", _ok)


def _configure_admin_ui_test_dependencies(monkeypatch):
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
            return []

        async def get_member_counts_batch_cached(self, team_ids):
            return {}

        def get_user_roles_batch(self, email, team_ids):
            return {}

    async def list_tools(db, include_inactive=False, user_email=None, limit=0, team_id=None):
        return []

    async def list_servers(db, include_inactive=False, user_email=None, limit=0):
        return ([], None)

    async def list_resources(db, include_inactive=False, user_email=None, limit=0, team_id=None):
        return []

    async def list_prompts(db, include_inactive=False, user_email=None, limit=0, team_id=None):
        return []

    async def list_gateways(db, include_inactive=False, user_email=None, limit=0, team_id=None):
        return []

    async def list_roots():
        return []

    monkeypatch.setattr(admin, "TeamManagementService", FakeTeamService)
    monkeypatch.setattr(admin.tool_service, "list_tools", list_tools)
    monkeypatch.setattr(admin.server_service, "list_servers", list_servers)
    monkeypatch.setattr(admin.resource_service, "list_resources", list_resources)
    monkeypatch.setattr(admin.prompt_service, "list_prompts", list_prompts)
    monkeypatch.setattr(admin.gateway_service, "list_gateways", list_gateways)
    monkeypatch.setattr(admin.root_service, "list_roots", list_roots)


def _unwrap(func):
    target = func
    seen = set()
    while True:
        if hasattr(target, "__wrapped__"):
            target = target.__wrapped__
            continue
        closure = getattr(target, "__closure__", None)
        if not closure:
            return target
        inner = None
        for cell in closure:
            try:
                value = cell.cell_contents
            except ValueError:
                continue
            if inspect.isfunction(value) and value not in seen:
                inner = value
                break
        if inner is None:
            return target
        seen.add(target)
        target = inner


class _StubTeamService:
    def __init__(
        self,
        db: object,
        *,
        team: object | None = None,
        user_role: str | None = None,
        existing_requests: list | None = None,
        create_request: object | None = None,
        cancel_ok: bool = True,
        remove_member_ok: bool = True,
        owner_count: int | None = None,
        join_requests: list | None = None,
        approve_member: object | None = None,
        reject_ok: bool = True,
    ) -> None:
        self.db = db
        self.team = team
        self.user_role = user_role
        self.existing_requests = existing_requests or []
        self.create_request = create_request
        self.cancel_ok = cancel_ok
        self.remove_member_ok = remove_member_ok
        self.owner_count = owner_count
        self.join_requests = join_requests or []
        self.approve_member = approve_member
        self.reject_ok = reject_ok
        self.create_args = None
        self.cancel_args = None
        self.approve_args = None
        self.reject_args = None
        self.remove_member_args = None

    async def get_team_by_id(self, team_id: str):
        return self.team

    async def get_user_role_in_team(self, user_email: str, team_id: str):
        return self.user_role

    async def get_user_join_requests(self, user_email: str, team_id: str):
        return self.existing_requests

    async def create_join_request(self, *, team_id: str, user_email: str, message: str):
        self.create_args = (team_id, user_email, message)
        return self.create_request

    async def cancel_join_request(self, request_id: str, user_email: str):
        self.cancel_args = (request_id, user_email)
        return self.cancel_ok

    async def list_join_requests(self, team_id: str):
        return self.join_requests

    async def approve_join_request(self, request_id: str, approved_by: str):
        self.approve_args = (request_id, approved_by)
        return self.approve_member

    async def reject_join_request(self, request_id: str, rejected_by: str):
        self.reject_args = (request_id, rejected_by)
        return self.reject_ok

    def count_team_owners(self, team_id: str) -> int:
        return self.owner_count if self.owner_count is not None else 0

    async def remove_member_from_team(self, *, team_id: str, user_email: str, removed_by: str):
        self.remove_member_args = (team_id, user_email, removed_by)
        return self.remove_member_ok


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


@pytest.mark.parametrize(
    ("required_attr", "password", "expected_fragment"),
    [
        ("password_require_lowercase", "ABCDEFGH", "lowercase"),
        ("password_require_numbers", "Abcdefgh", "number"),
        ("password_require_special", "Abcdefg1", "special character"),
    ],
)
def test_validate_password_strength_requirement_failures(monkeypatch, required_attr, password, expected_fragment):
    monkeypatch.setattr(admin.settings, "password_policy_enabled", True)
    monkeypatch.setattr(admin.settings, "password_min_length", 1)
    monkeypatch.setattr(admin.settings, "password_require_uppercase", False)
    monkeypatch.setattr(admin.settings, "password_require_lowercase", False)
    monkeypatch.setattr(admin.settings, "password_require_numbers", False)
    monkeypatch.setattr(admin.settings, "password_require_special", False)
    monkeypatch.setattr(admin.settings, required_attr, True)

    ok, msg = admin.validate_password_strength(password)
    assert ok is False
    assert expected_fragment in msg.lower()


def test_admin_module_grpc_import_error_fallback(monkeypatch):
    import builtins
    import importlib.util
    from pathlib import Path

    real_import = builtins.__import__

    def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # type: ignore[no-redef]
        if name == "mcpgateway.services.grpc_service":
            raise ImportError("grpc not installed")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _guarded_import)

    admin_path = Path(admin.__file__)
    spec = importlib.util.spec_from_file_location("mcpgateway_admin_no_grpc", admin_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]

    assert module.GRPC_AVAILABLE is False
    assert module.GrpcServiceCreate is None
    assert issubclass(module.GrpcServiceNotFoundError, module.GrpcServiceError)


@pytest.mark.asyncio
async def test_global_passthrough_headers_endpoints(monkeypatch):
    _allow_permissions(monkeypatch)
    db = MagicMock()

    monkeypatch.setattr(admin.settings, "default_passthrough_headers", ["X-Default"])
    monkeypatch.setattr(admin.global_config_cache, "get_passthrough_headers", lambda *_args: ["X-Test"])

    get_func = _unwrap(admin.get_global_passthrough_headers)
    result = await get_func(db, _user={"email": "user@example.com"})
    assert result.passthrough_headers == ["X-Test"]

    invalidate_called = []
    monkeypatch.setattr(admin.global_config_cache, "invalidate", lambda: invalidate_called.append(True))

    config_update = admin.GlobalConfigUpdate(passthrough_headers=["X-New"])
    update_func = _unwrap(admin.update_global_passthrough_headers)
    db.query.return_value.first.return_value = None
    update_result = await update_func(MagicMock(), config_update, db, _user={"email": "user@example.com"})
    assert update_result.passthrough_headers == ["X-New"]
    assert invalidate_called

    stats = {"hits": 1}
    monkeypatch.setattr(admin.global_config_cache, "stats", lambda: stats)
    invalidate_func = _unwrap(admin.invalidate_passthrough_headers_cache)
    cache_result = await invalidate_func(_user={"email": "user@example.com"})
    assert cache_result["status"] == "invalidated"
    assert cache_result["cache_stats"] == stats


@pytest.mark.asyncio
async def test_update_global_passthrough_headers_errors(monkeypatch):
    _allow_permissions(monkeypatch)
    db = MagicMock()
    db.query.return_value.first.return_value = MagicMock()

    config_update = admin.GlobalConfigUpdate(passthrough_headers=["X-New"])
    update_func = _unwrap(admin.update_global_passthrough_headers)

    from sqlalchemy.exc import IntegrityError

    db.commit.side_effect = IntegrityError("stmt", {}, None)
    with pytest.raises(admin.HTTPException) as excinfo:
        await update_func(MagicMock(), config_update, db, _user={"email": "user@example.com"})
    assert excinfo.value.status_code == 409
    db.rollback.assert_called()

    # Pydantic ValidationError is a subclass of ValueError; ensure it's handled distinctly (422).
    from pydantic import ValidationError
    from pydantic_core import InitErrorDetails

    db.commit.side_effect = ValidationError.from_exception_data("test", [InitErrorDetails(type="missing", loc=("passthrough_headers",), input={})])
    with pytest.raises(admin.HTTPException) as excinfo:
        await update_func(MagicMock(), config_update, db, _user={"email": "user@example.com"})
    assert excinfo.value.status_code == 422
    db.rollback.assert_called()

    db.commit.side_effect = PassthroughHeadersError("boom")
    with pytest.raises(admin.HTTPException) as excinfo:
        await update_func(MagicMock(), config_update, db, _user={"email": "user@example.com"})
    assert excinfo.value.status_code == 500


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
async def test_admin_login_handler_default_password(monkeypatch):
    request = _make_request(root_path="/root")
    mock_db = MagicMock()
    mock_db.commit = MagicMock(side_effect=Exception("commit failed"))

    monkeypatch.setattr(admin.settings, "email_auth_enabled", True)
    monkeypatch.setattr(admin.settings, "password_change_enforcement_enabled", True)
    monkeypatch.setattr(admin.settings, "detect_default_password_on_login", True)
    monkeypatch.setattr(admin.settings, "require_password_change_for_default_password", True)

    request.form = AsyncMock(return_value={"email": "admin@example.com", "password": "pw"})

    user = SimpleNamespace(email="admin@example.com", password_change_required=False, password_changed_at=None, password_hash="hash")
    auth_service = MagicMock()
    auth_service.authenticate_user = AsyncMock(return_value=user)
    monkeypatch.setattr(admin, "EmailAuthService", lambda db: auth_service)

    password_service = MagicMock()
    password_service.verify_password_async = AsyncMock(return_value=True)
    monkeypatch.setattr(admin, "Argon2PasswordService", lambda: password_service)

    monkeypatch.setattr(admin, "create_access_token", AsyncMock(return_value=("token", None)))
    set_cookie = MagicMock()
    monkeypatch.setattr(admin, "set_auth_cookie", set_cookie)

    response = await admin.admin_login_handler(request, mock_db)
    assert "change-password-required" in response.headers["location"]
    assert set_cookie.called


@pytest.mark.asyncio
async def test_admin_logout_paths():
    post_request = _make_request(root_path="/root")
    post_request.method = "POST"
    response = await admin._admin_logout(post_request)
    assert isinstance(response, RedirectResponse)
    assert response.status_code == 303

    get_request = _make_request(root_path="/root")
    get_request.method = "GET"
    response = await admin._admin_logout(get_request)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_admin_logout_keycloak_redirect(monkeypatch):
    request = _make_request(root_path="/root")
    request.method = "POST"
    request.cookies = {"jwt_token": "jwt-token"}
    request.url = SimpleNamespace(scheme="http", netloc="localhost:4444")

    monkeypatch.setattr(admin, "verify_jwt_token_cached", AsyncMock(return_value={"auth_provider": "keycloak"}))
    monkeypatch.setattr(admin.settings, "sso_keycloak_enabled", True)
    monkeypatch.setattr(admin.settings, "sso_keycloak_base_url", "http://localhost:8080")
    monkeypatch.setattr(admin.settings, "sso_keycloak_public_base_url", "http://localhost:8080")
    monkeypatch.setattr(admin.settings, "sso_keycloak_realm", "mcp-gateway")
    monkeypatch.setattr(admin.settings, "sso_keycloak_client_id", "mcp-gateway-admin")

    response = await admin._admin_logout(request)

    assert isinstance(response, RedirectResponse)
    assert response.status_code == 303
    location = response.headers["location"]
    parsed = urlparse(location)
    params = parse_qs(parsed.query)
    assert parsed.path.endswith("/realms/mcp-gateway/protocol/openid-connect/logout")
    assert params["client_id"] == ["mcp-gateway-admin"]
    assert params["post_logout_redirect_uri"] == ["http://localhost:4444/root/admin/login"]
    assert "jwt_token=" in response.headers.get("set-cookie", "")


@pytest.mark.asyncio
async def test_admin_logout_keycloak_provider_from_nested_user_payload(monkeypatch):
    request = _make_request(root_path="/root")
    request.method = "POST"
    request.cookies = {"jwt_token": "jwt-token"}
    request.url = SimpleNamespace(scheme="http", netloc="localhost:4444")

    monkeypatch.setattr(admin, "verify_jwt_token_cached", AsyncMock(return_value={"user": {"auth_provider": "keycloak"}}))
    monkeypatch.setattr(admin.settings, "sso_keycloak_enabled", True)
    monkeypatch.setattr(admin.settings, "sso_keycloak_base_url", "http://localhost:8080")
    monkeypatch.setattr(admin.settings, "sso_keycloak_public_base_url", "http://localhost:8080")
    monkeypatch.setattr(admin.settings, "sso_keycloak_realm", "mcp-gateway")
    monkeypatch.setattr(admin.settings, "sso_keycloak_client_id", "mcp-gateway-admin")

    response = await admin._admin_logout(request)

    assert isinstance(response, RedirectResponse)
    assert response.status_code == 303
    assert "/protocol/openid-connect/logout" in response.headers["location"]


@pytest.mark.asyncio
async def test_admin_logout_keycloak_redirect_includes_id_token_hint(monkeypatch):
    request = _make_request(root_path="/root")
    request.method = "POST"
    valid_id_token = _make_id_token(exp_offset=3600)
    request.cookies = {"jwt_token": "jwt-token", "sso_id_token_hint": valid_id_token}
    request.url = SimpleNamespace(scheme="http", netloc="localhost:4444")

    monkeypatch.setattr(admin, "verify_jwt_token_cached", AsyncMock(return_value={"auth_provider": "keycloak"}))
    monkeypatch.setattr(admin.settings, "sso_keycloak_enabled", True)
    monkeypatch.setattr(admin.settings, "sso_keycloak_base_url", "http://localhost:8080")
    monkeypatch.setattr(admin.settings, "sso_keycloak_public_base_url", "http://localhost:8080")
    monkeypatch.setattr(admin.settings, "sso_keycloak_realm", "mcp-gateway")
    monkeypatch.setattr(admin.settings, "sso_keycloak_client_id", "mcp-gateway-admin")

    response = await admin._admin_logout(request)

    assert isinstance(response, RedirectResponse)
    assert response.status_code == 303
    location = response.headers["location"]
    params = parse_qs(urlparse(location).query)
    assert params["id_token_hint"] == [valid_id_token]
    set_cookie_headers = [value.decode() for key, value in response.raw_headers if key.lower() == b"set-cookie"]
    assert any("sso_id_token_hint=" in header for header in set_cookie_headers)


@pytest.mark.asyncio
async def test_admin_logout_keycloak_omits_expired_id_token_hint(monkeypatch):
    request = _make_request(root_path="/root")
    request.method = "POST"
    expired_id_token = _make_id_token(exp_offset=-60)  # expired 60s ago
    request.cookies = {"jwt_token": "jwt-token", "sso_id_token_hint": expired_id_token}
    request.url = SimpleNamespace(scheme="http", netloc="localhost:4444")

    monkeypatch.setattr(admin, "verify_jwt_token_cached", AsyncMock(return_value={"auth_provider": "keycloak"}))
    monkeypatch.setattr(admin.settings, "sso_keycloak_enabled", True)
    monkeypatch.setattr(admin.settings, "sso_keycloak_base_url", "http://localhost:8080")
    monkeypatch.setattr(admin.settings, "sso_keycloak_public_base_url", "http://localhost:8080")
    monkeypatch.setattr(admin.settings, "sso_keycloak_realm", "mcp-gateway")
    monkeypatch.setattr(admin.settings, "sso_keycloak_client_id", "mcp-gateway-admin")

    response = await admin._admin_logout(request)

    assert isinstance(response, RedirectResponse)
    assert response.status_code == 303
    location = response.headers["location"]
    params = parse_qs(urlparse(location).query)
    assert "id_token_hint" not in params


@pytest.mark.asyncio
async def test_admin_logout_keycloak_without_absolute_login_url_falls_back(monkeypatch):
    request = _make_request(root_path="/root")
    request.method = "POST"
    request.cookies = {"jwt_token": "jwt-token"}
    request.url = SimpleNamespace(scheme="", netloc="")

    monkeypatch.setattr(admin, "verify_jwt_token_cached", AsyncMock(return_value={"auth_provider": "keycloak"}))
    monkeypatch.setattr(admin.settings, "sso_keycloak_enabled", True)
    monkeypatch.setattr(admin.settings, "sso_keycloak_base_url", "http://localhost:8080")
    monkeypatch.setattr(admin.settings, "sso_keycloak_public_base_url", None)
    monkeypatch.setattr(admin.settings, "sso_keycloak_realm", "mcp-gateway")
    monkeypatch.setattr(admin.settings, "sso_keycloak_client_id", "mcp-gateway-admin")
    monkeypatch.setattr(admin.settings, "app_domain", None)

    response = await admin._admin_logout(request)

    assert isinstance(response, RedirectResponse)
    assert response.status_code == 303
    assert response.headers["location"] == "/root/admin/login"


@pytest.mark.asyncio
async def test_admin_logout_verify_jwt_failure_defaults_to_keycloak_when_enabled(monkeypatch):
    request = _make_request(root_path="/root")
    request.method = "POST"
    request.cookies = {"jwt_token": "jwt-token"}
    request.url = SimpleNamespace(scheme="http", netloc="localhost:4444")

    monkeypatch.setattr(admin, "verify_jwt_token_cached", AsyncMock(side_effect=RuntimeError("token decode error")))
    monkeypatch.setattr(admin.settings, "sso_keycloak_enabled", True)
    monkeypatch.setattr(admin.settings, "sso_keycloak_base_url", "http://localhost:8080")
    monkeypatch.setattr(admin.settings, "sso_keycloak_public_base_url", "http://localhost:8080")
    monkeypatch.setattr(admin.settings, "sso_keycloak_realm", "mcp-gateway")

    response = await admin._admin_logout(request)

    assert isinstance(response, RedirectResponse)
    assert response.status_code == 303
    # With Keycloak SSO enabled, JWT failure defaults to keycloak logout redirect
    assert "realms/mcp-gateway/protocol/openid-connect/logout" in response.headers["location"]


@pytest.mark.asyncio
async def test_admin_logout_verify_jwt_failure_falls_back_to_local_when_keycloak_disabled(monkeypatch):
    request = _make_request(root_path="/root")
    request.method = "POST"
    request.cookies = {"jwt_token": "jwt-token"}
    request.url = SimpleNamespace(scheme="http", netloc="localhost:4444")

    monkeypatch.setattr(admin, "verify_jwt_token_cached", AsyncMock(side_effect=RuntimeError("token decode error")))
    monkeypatch.setattr(admin.settings, "sso_keycloak_enabled", False)

    response = await admin._admin_logout(request)

    assert isinstance(response, RedirectResponse)
    assert response.status_code == 303
    assert response.headers["location"] == "/root/admin/login"


@pytest.mark.asyncio
async def test_admin_logout_without_auth_provider_falls_back_to_local_redirect(monkeypatch):
    request = _make_request(root_path="/root")
    request.method = "POST"
    request.cookies = {"jwt_token": "jwt-token"}
    request.url = SimpleNamespace(scheme="http", netloc="localhost:4444")

    monkeypatch.setattr(admin, "verify_jwt_token_cached", AsyncMock(return_value={"user": {}}))
    monkeypatch.setattr(admin.settings, "sso_keycloak_enabled", True)
    monkeypatch.setattr(admin.settings, "sso_keycloak_base_url", "http://localhost:8080")
    monkeypatch.setattr(admin.settings, "sso_keycloak_public_base_url", "http://localhost:8080")
    monkeypatch.setattr(admin.settings, "sso_keycloak_realm", "mcp-gateway")

    response = await admin._admin_logout(request)

    assert isinstance(response, RedirectResponse)
    assert response.status_code == 303
    assert response.headers["location"] == "/root/admin/login"


@pytest.mark.asyncio
async def test_admin_logout_keycloak_uses_app_domain_fallback_for_login_url(monkeypatch):
    request = _make_request(root_path="/root")
    request.method = "POST"
    request.cookies = {"jwt_token": "jwt-token"}
    request.url = SimpleNamespace(scheme="", netloc="")

    monkeypatch.setattr(admin, "verify_jwt_token_cached", AsyncMock(return_value={"auth_provider": "keycloak"}))
    monkeypatch.setattr(admin.settings, "sso_keycloak_enabled", True)
    monkeypatch.setattr(admin.settings, "sso_keycloak_base_url", "http://localhost:8080")
    monkeypatch.setattr(admin.settings, "sso_keycloak_public_base_url", "http://localhost:8080")
    monkeypatch.setattr(admin.settings, "sso_keycloak_realm", "mcp-gateway")
    monkeypatch.setattr(admin.settings, "sso_keycloak_client_id", "mcp-gateway-admin")
    monkeypatch.setattr(admin.settings, "app_domain", "http://localhost:4444/")

    response = await admin._admin_logout(request)

    assert isinstance(response, RedirectResponse)
    assert response.status_code == 303
    location = response.headers["location"]
    params = parse_qs(urlparse(location).query)
    assert params["post_logout_redirect_uri"] == ["http://localhost:4444/root/admin/login"]


@pytest.mark.asyncio
async def test_admin_logout_keycloak_disabled_falls_back_to_local_redirect(monkeypatch):
    request = _make_request(root_path="/root")
    request.method = "POST"
    request.cookies = {"jwt_token": "jwt-token"}
    request.url = SimpleNamespace(scheme="http", netloc="localhost:4444")

    monkeypatch.setattr(admin, "verify_jwt_token_cached", AsyncMock(return_value={"auth_provider": "keycloak"}))
    monkeypatch.setattr(admin.settings, "sso_keycloak_enabled", False)
    monkeypatch.setattr(admin.settings, "sso_keycloak_base_url", "http://localhost:8080")

    response = await admin._admin_logout(request)

    assert isinstance(response, RedirectResponse)
    assert response.status_code == 303
    assert response.headers["location"] == "/root/admin/login"


@pytest.mark.asyncio
async def test_admin_logout_keycloak_missing_realm_falls_back_to_local_redirect(monkeypatch):
    request = _make_request(root_path="/root")
    request.method = "POST"
    request.cookies = {"jwt_token": "jwt-token"}
    request.url = SimpleNamespace(scheme="http", netloc="localhost:4444")

    monkeypatch.setattr(admin, "verify_jwt_token_cached", AsyncMock(return_value={"auth_provider": "keycloak"}))
    monkeypatch.setattr(admin.settings, "sso_keycloak_enabled", True)
    monkeypatch.setattr(admin.settings, "sso_keycloak_base_url", "http://localhost:8080")
    monkeypatch.setattr(admin.settings, "sso_keycloak_public_base_url", "http://localhost:8080")
    monkeypatch.setattr(admin.settings, "sso_keycloak_realm", "")

    response = await admin._admin_logout(request)

    assert isinstance(response, RedirectResponse)
    assert response.status_code == 303
    assert response.headers["location"] == "/root/admin/login"


@pytest.mark.asyncio
async def test_admin_ui_with_team_filter_and_cookie(monkeypatch):
    request = _make_request(root_path="/root")
    request.cookies = {"jwt_token": "existing-jwt"}
    mock_db = MagicMock()
    mock_db.commit = MagicMock()
    user = {"email": "user@example.com", "is_admin": True, "db": mock_db}

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
    monkeypatch.setattr(admin, "verify_jwt_token_cached", AsyncMock(return_value={"user": {"auth_provider": "keycloak"}}))
    create_jwt = AsyncMock(return_value="jwt")
    monkeypatch.setattr(admin, "create_jwt_token", create_jwt)

    response = await admin.admin_ui(request, "team-1", True, mock_db, user=user)
    assert isinstance(response, HTMLResponse)
    assert "jwt_token" in response.headers.get("set-cookie", "")
    context = request.app.state.templates.TemplateResponse.call_args[0][2]
    assert context["selected_team_id"] == "team-1"
    assert len(context["tools"]) == 1
    refreshed_payload = create_jwt.await_args.args[0]
    assert refreshed_payload["auth_provider"] == "keycloak"
    assert refreshed_payload["user"]["auth_provider"] == "keycloak"


@pytest.mark.asyncio
async def test_admin_ui_refresh_uses_dict_user_auth_provider(monkeypatch):
    request = _make_request(root_path="/root")
    mock_db = MagicMock()
    mock_db.commit = MagicMock()
    user = {"email": "user@example.com", "is_admin": True, "auth_provider": "  keycloak  ", "db": mock_db}

    _configure_admin_ui_test_dependencies(monkeypatch)

    create_jwt = AsyncMock(return_value="jwt")
    monkeypatch.setattr(admin, "create_jwt_token", create_jwt)

    response = await admin.admin_ui(request, None, False, mock_db, user=user)

    assert isinstance(response, HTMLResponse)
    refreshed_payload = create_jwt.await_args.args[0]
    assert refreshed_payload["auth_provider"] == "keycloak"
    assert refreshed_payload["user"]["auth_provider"] == "keycloak"


@pytest.mark.asyncio
async def test_admin_ui_refresh_uses_object_user_full_name_and_provider(monkeypatch):
    request = _make_request(root_path="/root")
    mock_db = MagicMock()
    mock_db.commit = MagicMock()
    user = SimpleNamespace(email="user@example.com", full_name="Object User", auth_provider=" keycloak ", is_admin=True, db=mock_db)

    _configure_admin_ui_test_dependencies(monkeypatch)

    create_jwt = AsyncMock(return_value="jwt")
    monkeypatch.setattr(admin, "create_jwt_token", create_jwt)

    admin_ui_func = _unwrap(admin.admin_ui)
    response = await admin_ui_func(request, None, False, mock_db, user=user)

    assert isinstance(response, HTMLResponse)
    refreshed_payload = create_jwt.await_args.args[0]
    assert refreshed_payload["user"]["full_name"] == "Object User"
    assert refreshed_payload["auth_provider"] == "keycloak"


@pytest.mark.asyncio
async def test_admin_ui_refresh_falls_back_to_top_level_provider_from_existing_cookie(monkeypatch):
    request = _make_request(root_path="/root")
    request.cookies = {"jwt_token": "existing-jwt"}
    mock_db = MagicMock()
    mock_db.commit = MagicMock()
    user = {"email": "user@example.com", "is_admin": True, "db": mock_db}

    _configure_admin_ui_test_dependencies(monkeypatch)
    monkeypatch.setattr(admin, "verify_jwt_token_cached", AsyncMock(return_value={"auth_provider": " keycloak "}))
    create_jwt = AsyncMock(return_value="jwt")
    monkeypatch.setattr(admin, "create_jwt_token", create_jwt)

    response = await admin.admin_ui(request, None, False, mock_db, user=user)

    assert isinstance(response, HTMLResponse)
    refreshed_payload = create_jwt.await_args.args[0]
    assert refreshed_payload["auth_provider"] == "keycloak"


@pytest.mark.asyncio
async def test_admin_ui_refresh_provider_lookup_failure_keeps_local_provider(monkeypatch):
    request = _make_request(root_path="/root")
    request.cookies = {"jwt_token": "existing-jwt"}
    mock_db = MagicMock()
    mock_db.commit = MagicMock()
    user = {"email": "user@example.com", "is_admin": True, "db": mock_db}

    _configure_admin_ui_test_dependencies(monkeypatch)
    monkeypatch.setattr(admin, "verify_jwt_token_cached", AsyncMock(side_effect=RuntimeError("boom")))
    create_jwt = AsyncMock(return_value="jwt")
    monkeypatch.setattr(admin, "create_jwt_token", create_jwt)

    response = await admin.admin_ui(request, None, False, mock_db, user=user)

    assert isinstance(response, HTMLResponse)
    refreshed_payload = create_jwt.await_args.args[0]
    assert refreshed_payload["auth_provider"] == "local"
    assert refreshed_payload["user"]["auth_provider"] == "local"


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


@pytest.mark.asyncio
async def test_admin_create_join_request_team_not_found(monkeypatch):
    request = _make_request()
    mock_db = MagicMock()
    user = {"email": "user@example.com", "db": mock_db}
    monkeypatch.setattr(admin.settings, "email_auth_enabled", True)
    monkeypatch.setattr(admin, "TeamManagementService", lambda db: _StubTeamService(db, team=None))

    response = await admin.admin_create_join_request("team-1", request, mock_db, user=user)
    assert response.status_code == 404
    assert "Team not found" in _response_text(response)


@pytest.mark.asyncio
async def test_admin_create_join_request_pending(monkeypatch):
    request = _make_request()
    request.form = AsyncMock(return_value={"message": "hello"})
    mock_db = MagicMock()
    user = {"email": "user@example.com", "db": mock_db}
    monkeypatch.setattr(admin.settings, "email_auth_enabled", True)

    team = SimpleNamespace(id="team-1", visibility="public")
    pending = SimpleNamespace(id="req-1", status="pending")
    team_service = _StubTeamService(db=mock_db, team=team, existing_requests=[pending])
    monkeypatch.setattr(admin, "TeamManagementService", lambda db: team_service)

    response = await admin.admin_create_join_request("team-1", request, mock_db, user=user)
    assert response.status_code == 200
    body = _response_text(response)
    assert "pending request" in body
    assert "Cancel Request" in body


@pytest.mark.asyncio
async def test_admin_create_join_request_success(monkeypatch):
    request = _make_request()
    request.form = AsyncMock(return_value={"message": "please add me"})
    mock_db = MagicMock()
    user = {"email": "user@example.com", "db": mock_db}
    monkeypatch.setattr(admin.settings, "email_auth_enabled", True)

    team = SimpleNamespace(id="team-1", visibility="public")
    created = SimpleNamespace(id="req-2")
    team_service = _StubTeamService(db=mock_db, team=team, existing_requests=[], create_request=created)
    monkeypatch.setattr(admin, "TeamManagementService", lambda db: team_service)

    response = await admin.admin_create_join_request("team-1", request, mock_db, user=user)
    assert response.status_code == 201
    assert team_service.create_args == ("team-1", "user@example.com", "please add me")
    assert "Join request submitted successfully" in _response_text(response)


@pytest.mark.asyncio
async def test_admin_cancel_join_request_failure(monkeypatch):
    mock_db = MagicMock()
    user = {"email": "user@example.com"}
    monkeypatch.setattr(admin.settings, "email_auth_enabled", True)
    team_service = _StubTeamService(db=mock_db, cancel_ok=False)
    monkeypatch.setattr(admin, "TeamManagementService", lambda db: team_service)

    _allow_permissions(monkeypatch)
    response = await admin.admin_cancel_join_request("team-1", "req-1", db=mock_db, user=user)
    assert response.status_code == 400
    assert "Failed to cancel join request" in _response_text(response)


@pytest.mark.asyncio
async def test_admin_cancel_join_request_success(monkeypatch):
    mock_db = MagicMock()
    user = {"email": "user@example.com"}
    monkeypatch.setattr(admin.settings, "email_auth_enabled", True)
    team_service = _StubTeamService(db=mock_db, cancel_ok=True)
    monkeypatch.setattr(admin, "TeamManagementService", lambda db: team_service)

    _allow_permissions(monkeypatch)
    response = await admin.admin_cancel_join_request("team-1", "req-2", db=mock_db, user=user)
    assert response.status_code == 200
    assert "Request to Join" in _response_text(response)


@pytest.mark.asyncio
async def test_admin_list_join_requests_owner_no_pending(monkeypatch):
    request = _make_request()
    mock_db = MagicMock()
    user = {"email": "owner@example.com"}
    monkeypatch.setattr(admin.settings, "email_auth_enabled", True)

    team = SimpleNamespace(id="team-1", name="Alpha")
    team_service = _StubTeamService(db=mock_db, team=team, user_role="owner", join_requests=[])
    monkeypatch.setattr(admin, "TeamManagementService", lambda db: team_service)

    _allow_permissions(monkeypatch)
    response = await admin.admin_list_join_requests("team-1", request, db=mock_db, user=user)
    assert response.status_code == 200
    assert "No pending join requests" in _response_text(response)


@pytest.mark.asyncio
async def test_admin_list_join_requests_with_entries(monkeypatch):
    request = _make_request()
    mock_db = MagicMock()
    user = {"email": "owner@example.com"}
    monkeypatch.setattr(admin.settings, "email_auth_enabled", True)

    team = SimpleNamespace(id="team-1", name="Alpha")
    join_request = SimpleNamespace(
        id="req-9",
        user_email="member@example.com",
        message="hello",
        status="pending",
        requested_at=datetime(2025, 1, 10, 12, 0, 0),
    )
    team_service = _StubTeamService(db=mock_db, team=team, user_role="owner", join_requests=[join_request])
    monkeypatch.setattr(admin, "TeamManagementService", lambda db: team_service)

    _allow_permissions(monkeypatch)
    response = await admin.admin_list_join_requests("team-1", request, db=mock_db, user=user)
    assert response.status_code == 200
    body = _response_text(response)
    assert "member@example.com" in body
    assert "Message: hello" in body
    assert "PENDING" in body


@pytest.mark.asyncio
async def test_admin_approve_join_request_success(monkeypatch):
    mock_db = MagicMock()
    user = {"email": "owner@example.com"}
    monkeypatch.setattr(admin.settings, "email_auth_enabled", True)

    member = SimpleNamespace(user_email="new@example.com")
    team_service = _StubTeamService(db=mock_db, user_role="owner", approve_member=member)
    monkeypatch.setattr(admin, "TeamManagementService", lambda db: team_service)

    _allow_permissions(monkeypatch)
    response = await admin.admin_approve_join_request("team-1", "req-1", db=mock_db, user=user)
    assert response.status_code == 200
    assert "Join request approved" in _response_text(response)
    assert "HX-Trigger" in response.headers


@pytest.mark.asyncio
async def test_admin_reject_join_request_not_owner(monkeypatch):
    mock_db = MagicMock()
    user = {"email": "viewer@example.com"}
    monkeypatch.setattr(admin.settings, "email_auth_enabled", True)

    team_service = _StubTeamService(db=mock_db, user_role="member")
    monkeypatch.setattr(admin, "TeamManagementService", lambda db: team_service)

    _allow_permissions(monkeypatch)
    response = await admin.admin_reject_join_request("team-1", "req-1", db=mock_db, user=user)
    assert response.status_code == 403
    assert "Only team owners can reject join requests" in _response_text(response)


@pytest.mark.asyncio
async def test_admin_leave_team_personal(monkeypatch):
    request = _make_request()
    mock_db = MagicMock()
    user = {"email": "user@example.com"}
    monkeypatch.setattr(admin.settings, "email_auth_enabled", True)

    team = SimpleNamespace(id="team-1", is_personal=True)
    team_service = _StubTeamService(db=mock_db, team=team, user_role="member")
    monkeypatch.setattr(admin, "TeamManagementService", lambda db: team_service)

    _allow_permissions(monkeypatch)
    response = await admin.admin_leave_team("team-1", request, db=mock_db, user=user)
    assert response.status_code == 400
    assert "Cannot leave your personal team" in _response_text(response)


@pytest.mark.asyncio
async def test_admin_leave_team_last_owner(monkeypatch):
    request = _make_request()
    mock_db = MagicMock()
    user = {"email": "owner@example.com"}
    monkeypatch.setattr(admin.settings, "email_auth_enabled", True)

    team = SimpleNamespace(id="team-1", is_personal=False)
    team_service = _StubTeamService(db=mock_db, team=team, user_role="owner", owner_count=1)
    monkeypatch.setattr(admin, "TeamManagementService", lambda db: team_service)

    _allow_permissions(monkeypatch)
    response = await admin.admin_leave_team("team-1", request, db=mock_db, user=user)
    assert response.status_code == 400
    assert "Cannot leave team as the last owner" in _response_text(response)


@pytest.mark.asyncio
async def test_admin_leave_team_success(monkeypatch):
    request = _make_request()
    mock_db = MagicMock()
    user = {"email": "member@example.com"}
    monkeypatch.setattr(admin.settings, "email_auth_enabled", True)

    team = SimpleNamespace(id="team-1", is_personal=False)
    team_service = _StubTeamService(db=mock_db, team=team, user_role="member", remove_member_ok=True)
    monkeypatch.setattr(admin, "TeamManagementService", lambda db: team_service)

    _allow_permissions(monkeypatch)
    response = await admin.admin_leave_team("team-1", request, db=mock_db, user=user)
    assert response.status_code == 200
    assert "Successfully left the team" in _response_text(response)


@pytest.mark.asyncio
async def test_generate_unified_teams_view_renders_relationships():
    current_user = SimpleNamespace(email="owner@example.com")

    personal_team = SimpleNamespace(
        id="t-personal",
        name="Personal",
        description="private workspace",
        is_personal=True,
        visibility="private",
        created_by="owner@example.com",
    )
    owner_team = SimpleNamespace(
        id="t-owner",
        name="Owner Team",
        description="desc",
        is_personal=False,
        visibility="public",
        created_by="owner@example.com",
    )
    member_team = SimpleNamespace(
        id="t-member",
        name="Member Team",
        description="member",
        is_personal=False,
        visibility="private",
        created_by="owner@example.com",
    )
    public_pending = SimpleNamespace(
        id="t-public-pending",
        name="Public Pending",
        description="x" * 120,
        is_personal=False,
        visibility="public",
        created_by="owner@example.com",
    )
    public_open = SimpleNamespace(
        id="t-public-open",
        name="Public Open",
        description="Open team",
        is_personal=False,
        visibility="public",
        created_by="owner@example.com",
    )

    class _StubUnifiedTeamService:
        async def get_user_teams(self, _email):
            return [personal_team, owner_team, member_team]

        async def discover_public_teams(self, _email):
            return [public_pending, public_open]

        async def get_member_counts_batch_cached(self, team_ids):
            return {team_id: 3 for team_id in team_ids}

        def get_user_roles_batch(self, _email, team_ids):
            return {team_ids[0]: "owner", team_ids[1]: "owner", team_ids[2]: "member"}

        def get_pending_join_requests_batch(self, _email, team_ids):
            return {public_pending.id: SimpleNamespace(id="req-1")} if public_pending.id in team_ids else {}

    response = await admin._generate_unified_teams_view(_StubUnifiedTeamService(), current_user, "")
    html = response.body.decode()
    assert "PERSONAL" in html
    assert "OWNER" in html
    assert "MEMBER" in html
    assert "CAN JOIN" in html
    assert "Requested to Join" in html
    assert "Request to Join" in html
    assert "Cancel Request" in html
    assert "Personal workspace" in html
    assert "..." in html


@pytest.mark.asyncio
async def test_admin_get_all_team_ids_admin_and_user(monkeypatch):
    mock_db = MagicMock()

    class _StubTeamService:
        async def get_all_team_ids(self, **_kwargs):
            return ["team-1", "team-2"]

        async def get_user_teams(self, _email, include_personal=True):
            return [
                SimpleNamespace(id="team-3", name="Alpha", slug="alpha", is_active=True, visibility="public"),
                SimpleNamespace(id="team-4", name="Beta", slug="beta", is_active=False, visibility="private"),
            ]

    class _StubAuthService:
        def __init__(self, _db):
            self._user = None

        async def get_user_by_email(self, _email):
            return self._user

    auth_service = _StubAuthService(mock_db)
    team_service = _StubTeamService()

    monkeypatch.setattr(admin, "TeamManagementService", lambda db: team_service)
    monkeypatch.setattr(admin, "EmailAuthService", lambda db: auth_service)
    _allow_permissions(monkeypatch)

    auth_service._user = SimpleNamespace(is_admin=True)
    result = await admin.admin_get_all_team_ids(include_inactive=True, visibility=None, q=None, db=mock_db, user={"email": "admin@example.com"})
    assert result["team_ids"] == ["team-1", "team-2"]
    assert result["count"] == 2

    auth_service._user = SimpleNamespace(is_admin=False)
    result = await admin.admin_get_all_team_ids(include_inactive=False, visibility="public", q="alp", db=mock_db, user={"email": "user@example.com"})
    assert result["team_ids"] == ["team-3"]
    assert result["count"] == 1


@pytest.mark.asyncio
async def test_admin_get_all_team_ids_user_not_found(monkeypatch):
    mock_db = MagicMock()

    class _StubAuthService:
        async def get_user_by_email(self, _email):
            return None

    monkeypatch.setattr(admin, "EmailAuthService", lambda db: _StubAuthService())
    monkeypatch.setattr(admin, "TeamManagementService", lambda db: MagicMock())
    _allow_permissions(monkeypatch)

    result = await admin.admin_get_all_team_ids(db=mock_db, user={"email": "missing@example.com"})
    assert result == {"team_ids": [], "count": 0}


@pytest.mark.asyncio
async def test_admin_search_teams_admin_and_user(monkeypatch):
    mock_db = MagicMock()

    class _StubTeamService:
        async def list_teams(self, **_kwargs):
            return {
                "data": [
                    SimpleNamespace(id="t-1", name="Alpha", slug="alpha", description="desc", visibility="public", is_active=True),
                ]
            }

        async def get_user_teams(self, _email, include_personal=True):
            return [
                SimpleNamespace(id="t-2", name="Beta", slug="beta", description="desc", visibility="public", is_active=True),
                SimpleNamespace(id="t-3", name="Gamma", slug="gamma", description="desc", visibility="private", is_active=False),
            ]

    class _StubAuthService:
        def __init__(self, _db):
            self._user = None

        async def get_user_by_email(self, _email):
            return self._user

    auth_service = _StubAuthService(mock_db)
    team_service = _StubTeamService()

    monkeypatch.setattr(admin, "TeamManagementService", lambda db: team_service)
    monkeypatch.setattr(admin, "EmailAuthService", lambda db: auth_service)
    _allow_permissions(monkeypatch)

    auth_service._user = SimpleNamespace(is_admin=True)
    result = await admin.admin_search_teams(q="alp", include_inactive=False, limit=10, visibility=None, db=mock_db, user={"email": "admin@example.com"})
    assert result == [
        {"id": "t-1", "name": "Alpha", "slug": "alpha", "description": "desc", "visibility": "public", "is_active": True}
    ]

    auth_service._user = SimpleNamespace(is_admin=False)
    result = await admin.admin_search_teams(q="be", include_inactive=False, limit=10, visibility="public", db=mock_db, user={"email": "user@example.com"})
    assert result == [
        {"id": "t-2", "name": "Beta", "slug": "beta", "description": "desc", "visibility": "public", "is_active": True}
    ]


@pytest.mark.asyncio
async def test_admin_search_teams_user_not_found(monkeypatch):
    mock_db = MagicMock()

    class _StubAuthService:
        async def get_user_by_email(self, _email):
            return None

    monkeypatch.setattr(admin, "EmailAuthService", lambda db: _StubAuthService())
    monkeypatch.setattr(admin, "TeamManagementService", lambda db: MagicMock())
    _allow_permissions(monkeypatch)

    result = await admin.admin_search_teams(db=mock_db, user={"email": "missing@example.com"})
    assert result == []


@pytest.mark.asyncio
async def test_get_user_team_ids_returns_cached_ids_without_service_lookup(monkeypatch):
    class _NoCallTeamService:
        def __init__(self, _db):
            raise AssertionError("TeamManagementService should not be constructed when cache is present")

    monkeypatch.setattr(admin, "TeamManagementService", _NoCallTeamService)
    cached_team_ids = ["team-1", "team-2"]

    result = await admin._get_user_team_ids(user={"email": "user@example.com", "_cached_team_ids": cached_team_ids}, db=MagicMock())

    assert result == cached_team_ids


@pytest.mark.asyncio
async def test_admin_list_servers_returns_paginated(monkeypatch):
    mock_db = MagicMock()

    mock_server = MagicMock()
    mock_server.model_dump.return_value = {"id": "server-1"}

    pagination = MagicMock()
    pagination.model_dump.return_value = {"page": 1, "per_page": 10}

    links = MagicMock()
    links.model_dump.return_value = {"self": "/admin/servers?page=1&per_page=10"}

    async def _fake_list_servers(**_kwargs):
        return {"data": [mock_server], "pagination": pagination, "links": links}

    monkeypatch.setattr(admin.server_service, "list_servers", _fake_list_servers)

    result = await admin.admin_list_servers(page=1, per_page=10, include_inactive=False, db=mock_db, user={"email": "user@example.com"})
    assert result["data"] == [{"id": "server-1"}]
    assert result["pagination"] == {"page": 1, "per_page": 10}
    assert result["links"] == {"self": "/admin/servers?page=1&per_page=10"}
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_admin_get_server_success(monkeypatch):
    mock_db = MagicMock()
    mock_server = MagicMock()
    mock_server.model_dump.return_value = {"id": "server-1"}

    async def _fake_get_server(_db, _server_id):
        return mock_server

    monkeypatch.setattr(admin.server_service, "get_server", _fake_get_server)

    result = await admin.admin_get_server("server-1", db=mock_db, user={"email": "user@example.com"})
    assert result == {"id": "server-1"}


@pytest.mark.asyncio
async def test_admin_get_server_not_found(monkeypatch):
    mock_db = MagicMock()

    async def _fake_get_server(_db, _server_id):
        raise ServerNotFoundError("missing")

    monkeypatch.setattr(admin.server_service, "get_server", _fake_get_server)

    with pytest.raises(HTTPException) as exc:
        await admin.admin_get_server("missing", db=mock_db, user={"email": "user@example.com"})

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_admin_servers_partial_html_render_variants(monkeypatch):
    mock_db = MagicMock()
    request = _make_request()

    class _StubTeamService:
        def __init__(self, _db):
            self._db = _db

        async def get_user_teams(self, _email):
            return [SimpleNamespace(id="team-1")]

    async def _fake_paginate_query(**_kwargs):
        pagination = MagicMock()
        pagination.model_dump.return_value = {"page": 1}
        links = MagicMock()
        links.model_dump.return_value = {"self": "/admin/servers/partial?page=1"}
        return {"data": [MagicMock()], "pagination": pagination, "links": links}

    monkeypatch.setattr(admin, "TeamManagementService", lambda db: _StubTeamService(db))
    monkeypatch.setattr(admin, "paginate_query", _fake_paginate_query)
    monkeypatch.setattr(admin.server_service, "convert_server_to_read", lambda _s, include_metrics=False: {"id": "server-1"})

    response = await admin.admin_servers_partial_html(
        request,
        page=1,
        per_page=10,
        include_inactive=False,
        render="controls",
        team_id="team-1",
        db=mock_db,
        user={"email": "user@example.com"},
    )
    assert isinstance(response, HTMLResponse)
    assert request.app.state.templates.TemplateResponse.call_args[0][1] == "pagination_controls.html"

    response = await admin.admin_servers_partial_html(
        request,
        page=1,
        per_page=10,
        include_inactive=False,
        render="selector",
        team_id="team-1",
        db=mock_db,
        user={"email": "user@example.com"},
    )
    assert isinstance(response, HTMLResponse)
    assert request.app.state.templates.TemplateResponse.call_args[0][1] == "servers_selector_items.html"

    response = await admin.admin_servers_partial_html(
        request,
        page=1,
        per_page=10,
        include_inactive=False,
        render=None,
        team_id="team-1",
        db=mock_db,
        user={"email": "user@example.com"},
    )
    assert isinstance(response, HTMLResponse)
    assert request.app.state.templates.TemplateResponse.call_args[0][1] == "servers_partial.html"
