# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_sso_user_provisioning.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Registration, request ordering, and security tests for SSO provisioning.
"""

# Standard
from datetime import datetime, timezone
from itertools import product
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

# Third-Party
from fastapi import APIRouter, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
import pytest
from starlette.types import ExceptionHandler

# First-Party
from mcpgateway import main
from mcpgateway.admin import admin_router
from mcpgateway.api import v1
from mcpgateway.config import settings
from mcpgateway.db import EmailUser
from mcpgateway.middleware import rbac
from mcpgateway.middleware.client_disconnect import ClientDisconnectMiddleware
from mcpgateway.middleware.token_scoping import token_scoping_middleware
from mcpgateway.middleware.token_usage_middleware import TokenUsageMiddleware
from mcpgateway.routers import sso_user_provisioning as provisioning
from mcpgateway.routers.email_auth import email_auth_router
from mcpgateway.services.email_auth_service import EmailValidationError, UserExistsError
from mcpgateway.services.permission_service import PermissionService
from mcpgateway.sso_provider_ids import SSOProviderValidationError

# Local
from tests.helpers.router_helpers import collect_routes

PATH = "/v1/admin/users/sso"
PAYLOAD = {"email": "new@example.com", "auth_provider": "azure-ad"}
FLAGS = list(product([False, True], repeat=3))


def _settings(flags: tuple[bool, bool, bool]) -> SimpleNamespace:
    """Build a settings object containing the three route-registration flags."""
    return SimpleNamespace(mcpgateway_admin_api_enabled=flags[0], sso_user_provisioning_api_enabled=flags[1], sso_enabled=flags[2])


def _routers() -> dict[str, Any]:
    """Provide empty inline routers required by the public assembly factory."""
    return {
        name: APIRouter()
        for name in (
            "protocol_router",
            "tool_router",
            "resource_router",
            "prompt_router",
            "gateway_router",
            "root_router",
            "server_router",
            "metrics_router",
            "tag_router",
            "export_import_router",
            "a2a_router",
        )
    }


@pytest.fixture
def harness(monkeypatch):
    """Build isolated apps with real provisioning registration and permission checks."""
    monkeypatch.setattr(v1, "_assemble_routers", lambda *_args, **_kwargs: None)
    service = MagicMock()
    user = MagicMock(spec=EmailUser)
    user.email = PAYLOAD["email"]
    user.full_name = None
    user.is_admin = False
    user.is_active = True
    user.auth_provider = "entra"
    user.created_at = datetime.now(timezone.utc)
    user.last_login = None
    user.password_change_required = False
    user.failed_login_attempts = 0
    user.locked_until = None
    user.is_account_locked.return_value = False
    user.is_email_verified.return_value = False
    service.create_sso_user = AsyncMock(return_value=user)
    monkeypatch.setattr(provisioning, "EmailAuthService", MagicMock(return_value=service))
    context = {"email": "admin@example.com", "sub": "different@example.com", "is_admin": True}
    authentication = MagicMock(return_value=context)
    db = MagicMock()

    async def current_user():
        """Record authentication dependency execution."""
        return authentication()

    def build(flags=(True, True, True), *, root_path="", admin_auth=False):
        """Assemble one startup snapshot without unrelated application routers."""
        config = _settings(flags)
        registered = all(flags)
        app = FastAPI(root_path=root_path)
        app.add_exception_handler(RequestValidationError, cast(ExceptionHandler, main.request_validation_exception_handler))
        app.include_router(v1.build_v1_router(config, **_routers()))
        app.dependency_overrides[rbac.get_current_user_with_permissions] = current_user
        app.dependency_overrides[rbac.get_db] = lambda: db
        if admin_auth:
            app.add_middleware(main.AdminAuthMiddleware)
        app.add_middleware(TokenUsageMiddleware)
        app.add_middleware(main.SSOUserProvisioningGateMiddleware, enabled=registered)
        return TestClient(app), app, config

    return SimpleNamespace(build=build, service=service, user=user, context=context, authentication=authentication, db=db)


@pytest.mark.parametrize("flags", FLAGS)
def test_three_flags_control_registration_and_disabled_post(harness, flags, monkeypatch):
    """Only all-enabled registers; disabled POSTs perform no authentication work."""
    verifier = AsyncMock(side_effect=AssertionError("token usage must not verify disabled POSTs"))
    monkeypatch.setattr("mcpgateway.middleware.token_usage_middleware.verify_jwt_token_cached", verifier)
    client, app, config = harness.build(flags, admin_auth=True)
    paths = {path for path, *_ in collect_routes(app)}
    assert (PATH in paths) == all(flags)
    # Mutating runtime flags must not change the registered routes or gate.
    config.mcpgateway_admin_api_enabled = not config.mcpgateway_admin_api_enabled
    config.sso_enabled = not config.sso_enabled
    config.sso_user_provisioning_api_enabled = not config.sso_user_provisioning_api_enabled
    assert {path for path, *_ in collect_routes(app)} == paths
    if all(flags):
        assert client.post(PATH, json=PAYLOAD).status_code != 404
    else:
        for body in (b"", b"{", b"[]", b'{"password":null}', b'{"auth_provider":"disabled"}'):
            for headers in ({}, {"Authorization": "Bearer invalid"}, {"Cookie": "jwt_token=invalid"}):
                response = client.post(PATH, content=body, headers=headers)
                assert response.status_code == 404
                assert response.json() == {"detail": "Not Found"}
        harness.authentication.assert_not_called()
        harness.service.create_sso_user.assert_not_awaited()
        verifier.assert_not_awaited()


@pytest.mark.parametrize("path", [PATH, PATH + "/", "/proxy" + PATH, "/proxy" + PATH + "/"])
def test_disabled_gate_normalizes_root_path(harness, path):
    """Both ASGI root-path representations hide disabled provisioning."""
    client, _, _ = harness.build((False, True, True), root_path="/proxy")
    assert client.post(path, content=b"{").json() == {"detail": "Not Found"}
    harness.authentication.assert_not_called()


@pytest.mark.parametrize("enabled", [False, True])
def test_gate_preserves_delete_and_unrelated_post(harness, enabled):
    """The gate leaves pre-existing methods and neighboring paths untouched."""
    client, app, _ = harness.build((enabled, True, True))

    @app.delete(PATH)
    def existing_delete():
        """Represent the existing dynamic Admin UI user-delete route."""
        return {"deleted": "sso"}

    @app.post(PATH + "-other")
    def unrelated_post():
        """Represent an unrelated protected path."""
        return {"unrelated": True}

    assert client.delete(PATH).json() == {"deleted": "sso"}
    assert client.post(PATH + "-other").json() == {"unrelated": True}


def test_no_legacy_provisioning_route(harness):
    """Versioned-only provisioning never enters legacy router assembly."""
    _, app, config = harness.build()
    app.include_router(v1.build_legacy_router(config, **_routers()))
    assert "/admin/users/sso" not in {path for path, *_ in collect_routes(app)}


def test_real_main_gate_precedes_auth_stack():
    """The real app places the gate outside token usage and all auth middleware."""
    classes: list[object] = [middleware.cls for middleware in main.app.user_middleware]
    gate_index = classes.index(main.SSOUserProvisioningGateMiddleware)
    for cls in (main.AdminAuthMiddleware, TokenUsageMiddleware):
        if cls in classes:
            assert gate_index < classes.index(cls)
    assert all("Auth" not in getattr(cls, "__name__", "") for cls in classes[:gate_index])
    if ClientDisconnectMiddleware in classes:
        assert classes.index(ClientDisconnectMiddleware) < gate_index


def test_success_uses_canonical_actor_and_response(harness):
    """Provisioning delegates to the service and returns public user fields."""
    client, _, _ = harness.build()
    response = client.post(PATH, json=PAYLOAD)
    assert response.status_code == 201
    assert response.json()["auth_provider"] == "entra"
    assert response.json()["email_verified"] is False
    assert response.json()["password_change_required"] is False
    assert "password_hash" not in response.json()
    harness.service.create_sso_user.assert_awaited_once_with(**PAYLOAD, full_name=None, is_admin=False, is_active=True, granted_by="admin@example.com")


@pytest.mark.parametrize("password", [None, "", "secret", False, 123])
def test_password_rejected_before_schema_validation(harness, password):
    """A password key takes precedence even when required fields are missing."""
    client, _, _ = harness.build()
    response = client.post(PATH, json={"password": password})
    assert response.status_code == 400
    assert response.json() == {"detail": "password not allowed for SSO users"}
    harness.service.create_sso_user.assert_not_awaited()


@pytest.mark.parametrize("body", [b"", b"{", b"null trailing"])
def test_malformed_json(harness, body):
    """Empty and malformed JSON follow the existing manual parser contract."""
    client, _, _ = harness.build()
    response = client.post(PATH, content=body, headers={"Content-Type": "application/json"})
    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid JSON in request body"}


@pytest.mark.parametrize(
    "body", [b"null", b"[]", b'"text"', b"42", b"true", b"{}", b'{"email":"bad","auth_provider":"entra"}', b'{"email":"new@example.com","auth_provider":"entra","owner_email":"attacker"}']
)
def test_schema_errors_match_fastapi_body_shape(harness, body):
    """Manual validation produces sanitized body-prefixed FastAPI errors."""
    client, _, _ = harness.build()
    response = client.post(PATH, content=body, headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    errors = response.json()["detail"]
    assert isinstance(errors, list) and errors
    assert all(error["loc"][0] == "body" and "input" not in error and "url" not in error for error in errors)
    harness.service.create_sso_user.assert_not_awaited()


@pytest.mark.parametrize("content_type", [None, "text/plain", "application/x-www-form-urlencoded"])
def test_unsupported_media_type(harness, content_type):
    """Bearer-style automation requires an explicit JSON content type."""
    client, _, _ = harness.build()
    headers = {"Authorization": "Bearer test"}
    if content_type:
        headers["Content-Type"] = content_type
    assert client.post(PATH, content=b"{}", headers=headers).status_code == 415
    harness.service.create_sso_user.assert_not_awaited()


def test_json_charset_accepted(harness):
    """JSON charset parameters do not interfere with media-type validation."""
    client, _, _ = harness.build()
    assert client.post(PATH, json=PAYLOAD, headers={"Content-Type": "application/json; charset=utf-8"}).status_code == 201


@pytest.mark.parametrize(
    "headers,token",
    [
        ({"Origin": "http://testserver"}, None),
        ({"Origin": "http://testserver", "X-CSRF-Token": "wrong"}, "correct"),
        ({"Origin": "https://evil.example", "X-CSRF-Token": "correct"}, "correct"),
        ({"Origin": "http://testserver", "Content-Type": "text/plain"}, None),
    ],
)
def test_cookie_csrf_denial_precedes_parsing(harness, headers, token):
    """Cookie requests require same-origin double-submit CSRF before parsing."""
    client, _, _ = harness.build()
    client.cookies.set("jwt_token", "session")
    if token:
        client.cookies.set("mcpgateway_csrf_token", token)
    response = client.post(PATH, content=b"{", headers=headers)
    assert response.status_code == 403
    assert "CSRF" in response.json()["detail"]
    harness.service.create_sso_user.assert_not_awaited()


def test_cookie_csrf_success(harness):
    """Valid cookie authentication and CSRF can provision users."""
    client, _, _ = harness.build()
    client.cookies.set("jwt_token", "session")
    client.cookies.set("mcpgateway_csrf_token", "csrf")
    assert client.post(PATH, json=PAYLOAD, headers={"Origin": "http://testserver", "X-CSRF-Token": "csrf"}).status_code == 201


@pytest.mark.parametrize(
    "error,code",
    [
        (SSOProviderValidationError("Provider disabled"), 400),
        (SSOProviderValidationError("Provider not configured"), 400),
        (EmailValidationError("Invalid email"), 400),
        (UserExistsError("User exists"), 409),
        (RuntimeError("internal failure"), 500),
    ],
)
def test_service_error_mapping(harness, error, code):
    """Known service errors map to client errors without leaking internals."""
    client, _, _ = harness.build()
    harness.service.create_sso_user.side_effect = error
    response = client.post(PATH, json=PAYLOAD)
    assert response.status_code == code
    if code == 500:
        assert response.json() == {"detail": "User creation failed"}


@pytest.mark.parametrize(
    "scopes,allowed",
    [
        (["tools.read"], False),
        (["admin.user_management"], True),
        (["admin.*"], True),
        (["*"], True),
        ([], True),
    ],
)
def test_token_scope_independent_of_admin_status(harness, scopes, allowed):
    """Admin identity cannot bypass restricted API-token permissions."""
    harness.context["token_scopes"] = scopes
    client, _, _ = harness.build()
    assert client.post(PATH, json=PAYLOAD).status_code == (201 if allowed else 403)
    if not allowed:
        harness.service.create_sso_user.assert_not_awaited()


def test_endpoint_rbac_denial_after_admin_middleware(harness, monkeypatch, mock_permission_service):
    """A caller with another admin permission still needs user management."""
    harness.context["is_admin"] = False
    identity = SimpleNamespace(email=harness.context["email"], is_admin=False)
    monkeypatch.setattr(main, "validate_token_user", AsyncMock(return_value=identity))
    monkeypatch.setattr(main, "settings", SimpleNamespace(auth_required=True))
    admin_permission = AsyncMock(return_value=True)
    monkeypatch.setattr(PermissionService, "has_admin_permission", admin_permission)
    mock_permission_service.check_permission.return_value = False
    client, _, _ = harness.build(admin_auth=True)
    response = client.post(PATH, content=b"{", headers={"Authorization": "Bearer test"})
    assert response.status_code == 403
    admin_permission.assert_awaited_once()
    assert mock_permission_service.check_permission.await_args.kwargs["permission"] == "admin.user_management"
    harness.service.create_sso_user.assert_not_awaited()


def test_unauthenticated_admin_middleware_denial(harness, monkeypatch):
    """Registered routes reject anonymous callers before body parsing."""
    monkeypatch.setattr(main, "settings", settings.model_copy(update={"auth_required": True}))
    client, _, _ = harness.build(admin_auth=True)
    assert client.post(PATH, content=b"{").status_code == 401
    harness.authentication.assert_not_called()


def test_existing_token_scope_map_covers_exact_path():
    """The existing admin-users mapping handles v1 and trailing-slash paths."""
    for path in (PATH, PATH + "/"):
        assert token_scoping_middleware._check_permission_restrictions(path, "POST", ["admin.user_management"])
        assert not token_scoping_middleware._check_permission_restrictions(path, "POST", ["admin.system_config"])


def test_openapi_request_schema(harness):
    """Manual body parsing still advertises a complete, resolvable request schema."""
    _, app, _ = harness.build()
    schema = app.openapi()
    body = schema["paths"][PATH]["post"]["requestBody"]
    assert body["required"] is True
    request_schema = body["content"]["application/json"]["schema"]
    assert request_schema["required"] == ["email", "auth_provider"]
    assert "password" not in request_schema["properties"]
    assert request_schema["additionalProperties"] is False
    assert "$defs" not in request_schema

    def check_references(node: Any) -> None:
        """Resolve every local schema reference against the complete OpenAPI document."""
        if isinstance(node, dict):
            if "$ref" in node:
                assert node["$ref"].startswith("#/")
                target = schema
                for segment in node["$ref"][2:].split("/"):
                    target = target[segment.replace("~1", "/").replace("~0", "~")]
            for value in node.values():
                check_references(value)
        elif isinstance(node, list):
            for value in node:
                check_references(value)

    check_references(schema)


@pytest.mark.parametrize("enabled", [False, True])
def test_existing_user_creation_routes_unchanged(harness, monkeypatch, enabled):
    """Existing JSON and UI creation still use local passwords under both flag states."""
    client, app, _ = harness.build((True, enabled, True))
    app.include_router(email_auth_router, prefix="/v1/auth/email")
    app.include_router(admin_router, prefix="/v1")
    legacy_service = MagicMock()
    legacy_service.create_user = AsyncMock(return_value=harness.user)
    legacy_service.is_last_active_admin = AsyncMock(return_value=False)
    legacy_service.delete_user = AsyncMock()
    monkeypatch.setattr("mcpgateway.routers.email_auth.EmailAuthService", MagicMock(return_value=legacy_service))
    monkeypatch.setattr("mcpgateway.admin.EmailAuthService", MagicMock(return_value=legacy_service))
    monkeypatch.setattr("mcpgateway.admin.validate_password_strength", lambda *_: (True, ""))
    password = "StrongLocal!Password9"  # pragma: allowlist secret
    response = client.post("/v1/auth/email/admin/users", json={"email": "local@example.com", "password": password})
    assert response.status_code == 201
    call = legacy_service.create_user.await_args
    assert call is not None
    assert call.kwargs["auth_provider"] == "local"
    response = client.post("/v1/admin/users", data={"email": "local-ui@example.com", "password": password})
    assert response.status_code == 201
    assert response.headers["HX-Trigger"] == "userCreated"
    call = legacy_service.create_user.await_args
    assert call is not None
    assert call.kwargs["password"] == password
    assert client.delete(PATH).status_code == 200
    legacy_service.delete_user.assert_awaited_once_with("sso")
    harness.service.create_sso_user.assert_not_awaited()
