# -*- coding: utf-8 -*-
"""Tests for SSO router endpoints and helpers."""

# Standard
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import pytest
from fastapi import HTTPException
from fastapi.responses import RedirectResponse
from pydantic import HttpUrl

# First-Party
from mcpgateway.routers import sso as sso_router


@pytest.mark.asyncio
async def test_list_sso_providers_disabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sso_router.settings, "sso_enabled", False)

    with pytest.raises(HTTPException) as excinfo:
        await sso_router.list_sso_providers(db=MagicMock())

    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_list_sso_providers_success(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sso_router.settings, "sso_enabled", True)

    provider = SimpleNamespace(id="p1", name="Provider", display_name="Provider")

    class DummyService:
        def __init__(self, _db):
            pass

        def list_enabled_providers(self):
            return [provider]

    monkeypatch.setattr(sso_router, "SSOService", DummyService)

    result = await sso_router.list_sso_providers(db=MagicMock())

    assert result[0].id == "p1"


def test_validate_redirect_uri_allows_relative(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sso_router.settings, "allowed_origins", ["https://example.com:8443"])
    monkeypatch.setattr(sso_router.settings, "app_domain", HttpUrl("https://myapp.com"))

    assert sso_router._validate_redirect_uri("/admin", None) is True
    assert sso_router._validate_redirect_uri("https://example.com:8443/cb", None) is True
    assert sso_router._validate_redirect_uri("https://myapp.com/cb", None) is True
    assert sso_router._validate_redirect_uri("https://evil.com/cb", None) is False


def test_validate_redirect_uri_rejects_http_on_production_domain(monkeypatch: pytest.MonkeyPatch):
    """HTTP is rejected for non-localhost domains (open redirect protection)."""
    monkeypatch.setattr(sso_router.settings, "allowed_origins", [])
    monkeypatch.setattr(sso_router.settings, "app_domain", HttpUrl("https://myapp.com"))

    assert sso_router._validate_redirect_uri("http://myapp.com/cb", None) is False
    assert sso_router._validate_redirect_uri("https://myapp.com/cb", None) is True


def test_validate_redirect_uri_app_domain_matches_any_port(monkeypatch: pytest.MonkeyPatch):
    """app_domain is a domain-level match (hostname only); use allowed_origins for port-specific control."""
    monkeypatch.setattr(sso_router.settings, "allowed_origins", [])
    monkeypatch.setattr(sso_router.settings, "app_domain", HttpUrl("https://myapp.com"))

    assert sso_router._validate_redirect_uri("https://myapp.com/cb", None) is True
    assert sso_router._validate_redirect_uri("https://myapp.com:443/cb", None) is True
    assert sso_router._validate_redirect_uri("https://myapp.com:8443/cb", None) is True


def test_validate_redirect_uri_allowed_origin_without_scheme(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sso_router.settings, "allowed_origins", ["", "example.com"])
    monkeypatch.setattr(sso_router.settings, "app_domain", None)

    assert sso_router._validate_redirect_uri("https://example.com/cb", None) is True


def test_validate_redirect_uri_app_domain_localhost_http(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sso_router.settings, "allowed_origins", [])
    monkeypatch.setattr(sso_router.settings, "app_domain", HttpUrl("http://localhost:4444"))

    # HTTP allowed for localhost (any port) - development convenience
    assert sso_router._validate_redirect_uri("http://localhost:3000/cb", None) is True
    assert sso_router._validate_redirect_uri("http://localhost:8080/cb", None) is True
    assert sso_router._validate_redirect_uri("https://localhost/cb", None) is True


def test_normalize_origin_defaults():
    assert sso_router._normalize_origin("https", "example.com", 443) == "https://example.com"
    assert sso_router._normalize_origin("http", "example.com", None) == "http://example.com"
    assert sso_router._normalize_origin("http", "example.com", 8080) == "http://example.com:8080"


@pytest.mark.asyncio
async def test_initiate_sso_login_invalid_redirect(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sso_router.settings, "sso_enabled", True)
    monkeypatch.setattr(sso_router, "_validate_redirect_uri", lambda *_args, **_kwargs: False)

    with pytest.raises(HTTPException) as excinfo:
        await sso_router.initiate_sso_login("provider", MagicMock(), redirect_uri="https://evil.com", db=MagicMock())

    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_initiate_sso_login_disabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sso_router.settings, "sso_enabled", False)

    with pytest.raises(HTTPException) as excinfo:
        await sso_router.initiate_sso_login("provider", MagicMock(), redirect_uri="/cb", db=MagicMock())

    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_initiate_sso_login_provider_not_found(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sso_router.settings, "sso_enabled", True)
    monkeypatch.setattr(sso_router, "_validate_redirect_uri", lambda *_args, **_kwargs: True)

    class DummyService:
        def __init__(self, _db):
            pass

        def get_authorization_url(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(sso_router, "SSOService", DummyService)

    with pytest.raises(HTTPException) as excinfo:
        await sso_router.initiate_sso_login("provider", MagicMock(), redirect_uri="/cb", scopes=None, db=MagicMock())

    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_initiate_sso_login_success(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sso_router.settings, "sso_enabled", True)
    monkeypatch.setattr(sso_router, "_validate_redirect_uri", lambda *_args, **_kwargs: True)

    class DummyService:
        def __init__(self, _db):
            pass

        def get_authorization_url(self, *_args, **_kwargs):
            return "https://auth.example.com?state=abc"

    monkeypatch.setattr(sso_router, "SSOService", DummyService)

    result = await sso_router.initiate_sso_login("provider", MagicMock(), redirect_uri="/cb", scopes=None, db=MagicMock())

    assert result.state == "abc"


@pytest.mark.asyncio
async def test_initiate_sso_login_state_missing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sso_router.settings, "sso_enabled", True)
    monkeypatch.setattr(sso_router, "_validate_redirect_uri", lambda *_args, **_kwargs: True)

    class DummyService:
        def __init__(self, _db):
            pass

        def get_authorization_url(self, *_args, **_kwargs):
            return "https://auth.example.com"

    monkeypatch.setattr(sso_router, "SSOService", DummyService)

    result = await sso_router.initiate_sso_login("provider", MagicMock(), redirect_uri="/cb", scopes=None, db=MagicMock())

    assert result.state == ""


@pytest.mark.asyncio
async def test_handle_sso_callback_failure_redirect(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sso_router.settings, "sso_enabled", True)

    class DummyService:
        def __init__(self, _db):
            pass

        async def handle_oauth_callback(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(sso_router, "SSOService", DummyService)

    request = MagicMock()
    request.scope = {"root_path": ""}

    response = await sso_router.handle_sso_callback("provider", "code", "state", request=request, response=MagicMock(), db=MagicMock())

    assert isinstance(response, RedirectResponse)
    assert response.status_code == 302
    assert "/admin/login?error=sso_failed" in response.headers.get("location", "")


@pytest.mark.asyncio
async def test_handle_sso_callback_disabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sso_router.settings, "sso_enabled", False)

    with pytest.raises(HTTPException) as excinfo:
        await sso_router.handle_sso_callback("provider", "code", "state", request=MagicMock(), response=MagicMock(), db=MagicMock())

    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_handle_sso_callback_user_creation_failed(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sso_router.settings, "sso_enabled", True)

    class DummyService:
        def __init__(self, _db):
            pass

        async def handle_oauth_callback(self, *_args, **_kwargs):
            return {"email": "user@example.com"}

        async def authenticate_or_create_user(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(sso_router, "SSOService", DummyService)

    request = MagicMock()
    request.scope = {"root_path": ""}

    response = await sso_router.handle_sso_callback("provider", "code", "state", request=request, response=MagicMock(), db=MagicMock())

    assert isinstance(response, RedirectResponse)
    assert response.status_code == 302
    assert "/admin/login?error=user_creation_failed" in response.headers.get("location", "")


@pytest.mark.asyncio
async def test_handle_sso_callback_success_sets_cookie(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sso_router.settings, "sso_enabled", True)

    class DummyService:
        def __init__(self, _db):
            pass

        async def handle_oauth_callback(self, *_args, **_kwargs):
            return {"email": "user@example.com"}

        async def authenticate_or_create_user(self, *_args, **_kwargs):
            return "token"

    monkeypatch.setattr(sso_router, "SSOService", DummyService)

    import mcpgateway.utils.security_cookies as cookie_module

    set_cookie = MagicMock()
    monkeypatch.setattr(cookie_module, "set_auth_cookie", set_cookie)

    request = MagicMock()
    request.scope = {"root_path": ""}

    response = await sso_router.handle_sso_callback("provider", "code", "state", request=request, response=MagicMock(), db=MagicMock())

    assert isinstance(response, RedirectResponse)
    assert response.status_code == 302
    assert response.headers.get("location", "").endswith("/admin")
    assert set_cookie.called


@pytest.mark.asyncio
async def test_create_sso_provider_conflict(monkeypatch: pytest.MonkeyPatch):
    class DummyService:
        def __init__(self, _db):
            pass

        def get_provider(self, _provider_id):
            return SimpleNamespace(id="existing")

    monkeypatch.setattr(sso_router, "SSOService", DummyService)

    payload = sso_router.SSOProviderCreateRequest(
        id="provider",
        name="Provider",
        display_name="Provider",
        provider_type="oidc",
        client_id="cid",
        client_secret="secret",
        authorization_url="https://auth",
        token_url="https://token",
        userinfo_url="https://userinfo",
    )

    with pytest.raises(HTTPException) as excinfo:
        await sso_router.create_sso_provider(payload, db=MagicMock(), user={"email": "admin@example.com"})

    assert excinfo.value.status_code == 409


@pytest.mark.asyncio
async def test_create_sso_provider_success(monkeypatch: pytest.MonkeyPatch):
    created = SimpleNamespace(
        id="provider",
        name="Provider",
        display_name="Provider",
        provider_type="oidc",
        is_enabled=True,
        created_at="now",
    )

    class DummyService:
        def __init__(self, _db):
            pass

        def get_provider(self, _provider_id):
            return None

        async def create_provider(self, _data):
            return created

    monkeypatch.setattr(sso_router, "SSOService", DummyService)

    payload = sso_router.SSOProviderCreateRequest(
        id="provider",
        name="Provider",
        display_name="Provider",
        provider_type="oidc",
        client_id="cid",
        client_secret="secret",
        authorization_url="https://auth",
        token_url="https://token",
        userinfo_url="https://userinfo",
    )

    result = await sso_router.create_sso_provider(payload, db=MagicMock(), user={"email": "admin@example.com"})

    assert result["id"] == "provider"
    assert result["is_enabled"] is True


@pytest.mark.asyncio
async def test_list_all_sso_providers(monkeypatch: pytest.MonkeyPatch):
    provider = SimpleNamespace(
        id="provider",
        name="Provider",
        display_name="Provider",
        provider_type="oidc",
        is_enabled=True,
        trusted_domains=["example.com"],
        auto_create_users=True,
        created_at="created",
        updated_at="updated",
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = [provider]
    db = MagicMock()
    db.execute.return_value = result

    response = await sso_router.list_all_sso_providers(db=db, user={"email": "admin@example.com"})

    assert response[0]["id"] == "provider"


@pytest.mark.asyncio
async def test_get_sso_provider_not_found(monkeypatch: pytest.MonkeyPatch):
    class DummyService:
        def __init__(self, _db):
            pass

        def get_provider(self, _provider_id):
            return None

    monkeypatch.setattr(sso_router, "SSOService", DummyService)

    with pytest.raises(HTTPException) as excinfo:
        await sso_router.get_sso_provider("missing", db=MagicMock(), user={"email": "admin@example.com"})

    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_get_sso_provider_success(monkeypatch: pytest.MonkeyPatch):
    provider = SimpleNamespace(
        id="provider",
        name="Provider",
        display_name="Provider",
        provider_type="oidc",
        client_id="cid",
        authorization_url="https://auth",
        token_url="https://token",
        userinfo_url="https://userinfo",
        issuer="https://issuer",
        scope="openid",
        trusted_domains=["example.com"],
        auto_create_users=True,
        team_mapping={},
        is_enabled=True,
        created_at="created",
        updated_at="updated",
    )

    class DummyService:
        def __init__(self, _db):
            pass

        def get_provider(self, _provider_id):
            return provider

    monkeypatch.setattr(sso_router, "SSOService", DummyService)

    result = await sso_router.get_sso_provider("provider", db=MagicMock(), user={"email": "admin@example.com"})

    assert result["authorization_url"] == "https://auth"


@pytest.mark.asyncio
async def test_update_sso_provider_no_data(monkeypatch: pytest.MonkeyPatch):
    payload = sso_router.SSOProviderUpdateRequest()

    with pytest.raises(HTTPException) as excinfo:
        await sso_router.update_sso_provider("provider", payload, db=MagicMock(), user={"email": "admin@example.com"})

    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_update_sso_provider_not_found(monkeypatch: pytest.MonkeyPatch):
    class DummyService:
        def __init__(self, _db):
            pass

        async def update_provider(self, _provider_id, _data):
            return None

    monkeypatch.setattr(sso_router, "SSOService", DummyService)

    payload = sso_router.SSOProviderUpdateRequest(name="Updated")

    with pytest.raises(HTTPException) as excinfo:
        await sso_router.update_sso_provider("provider", payload, db=MagicMock(), user={"email": "admin@example.com"})

    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_update_sso_provider_success(monkeypatch: pytest.MonkeyPatch):
    provider = SimpleNamespace(
        id="provider",
        name="Provider",
        display_name="Provider",
        provider_type="oidc",
        is_enabled=True,
        updated_at="updated",
    )

    class DummyService:
        def __init__(self, _db):
            pass

        async def update_provider(self, _provider_id, _data):
            return provider

    monkeypatch.setattr(sso_router, "SSOService", DummyService)

    payload = sso_router.SSOProviderUpdateRequest(name="Updated")
    result = await sso_router.update_sso_provider("provider", payload, db=MagicMock(), user={"email": "admin@example.com"})

    assert result["updated_at"] == "updated"


@pytest.mark.asyncio
async def test_delete_sso_provider_not_found(monkeypatch: pytest.MonkeyPatch):
    class DummyService:
        def __init__(self, _db):
            pass

        def delete_provider(self, _provider_id):
            return False

    monkeypatch.setattr(sso_router, "SSOService", DummyService)

    with pytest.raises(HTTPException) as excinfo:
        await sso_router.delete_sso_provider("provider", db=MagicMock(), user={"email": "admin@example.com"})

    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_sso_provider_success(monkeypatch: pytest.MonkeyPatch):
    class DummyService:
        def __init__(self, _db):
            pass

        def delete_provider(self, _provider_id):
            return True

    monkeypatch.setattr(sso_router, "SSOService", DummyService)

    result = await sso_router.delete_sso_provider("provider", db=MagicMock(), user={"email": "admin@example.com"})
    assert "deleted successfully" in result["message"]


@pytest.mark.asyncio
async def test_list_pending_approvals(monkeypatch: pytest.MonkeyPatch):
    now = datetime.now(timezone.utc)
    approval = SimpleNamespace(
        id="approval",
        email="user@example.com",
        full_name="User",
        auth_provider="provider",
        requested_at=now,
        expires_at=now + timedelta(days=1),
        status="pending",
        sso_metadata={"role": "user"},
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = [approval]
    db = MagicMock()
    db.execute.return_value = result

    response = await sso_router.list_pending_approvals(db=db, user={"email": "admin@example.com"})

    assert response[0].id == "approval"


@pytest.mark.asyncio
async def test_handle_approval_request_not_found(monkeypatch: pytest.MonkeyPatch):
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result

    with pytest.raises(HTTPException) as excinfo:
        await sso_router.handle_approval_request("missing", sso_router.ApprovalActionRequest(action="approve"), db=db, user={"email": "admin@example.com"})

    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_handle_approval_request_already_processed(monkeypatch: pytest.MonkeyPatch):
    approval = MagicMock()
    approval.status = "approved"

    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = approval
    db.execute.return_value = result

    with pytest.raises(HTTPException) as excinfo:
        await sso_router.handle_approval_request("approval", sso_router.ApprovalActionRequest(action="approve"), db=db, user={"email": "admin@example.com"})

    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_handle_approval_request_expired(monkeypatch: pytest.MonkeyPatch):
    approval = MagicMock()
    approval.status = "pending"
    approval.is_expired.return_value = True

    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = approval
    db.execute.return_value = result

    with pytest.raises(HTTPException) as excinfo:
        await sso_router.handle_approval_request("approval", sso_router.ApprovalActionRequest(action="approve"), db=db, user={"email": "admin@example.com"})

    assert excinfo.value.status_code == 400
    assert approval.status == "expired"
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_handle_approval_request_approve(monkeypatch: pytest.MonkeyPatch):
    approval = MagicMock()
    approval.status = "pending"
    approval.is_expired.return_value = False
    approval.email = "user@example.com"

    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = approval
    db.execute.return_value = result

    result_msg = await sso_router.handle_approval_request(
        "approval",
        sso_router.ApprovalActionRequest(action="approve", notes="ok"),
        db=db,
        user={"email": "admin@example.com"},
    )

    approval.approve.assert_called_once_with("admin@example.com", "ok")
    db.commit.assert_called_once()
    assert "approved successfully" in result_msg["message"]


@pytest.mark.asyncio
async def test_handle_approval_request_reject_missing_reason(monkeypatch: pytest.MonkeyPatch):
    approval = MagicMock()
    approval.status = "pending"
    approval.is_expired.return_value = False

    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = approval
    db.execute.return_value = result

    with pytest.raises(HTTPException) as excinfo:
        await sso_router.handle_approval_request(
            "approval",
            sso_router.ApprovalActionRequest(action="reject"),
            db=db,
            user={"email": "admin@example.com"},
        )

    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_handle_approval_request_reject_success(monkeypatch: pytest.MonkeyPatch):
    approval = MagicMock()
    approval.status = "pending"
    approval.is_expired.return_value = False
    approval.email = "user@example.com"

    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = approval
    db.execute.return_value = result

    result_msg = await sso_router.handle_approval_request(
        "approval",
        sso_router.ApprovalActionRequest(action="reject", reason="nope", notes="later"),
        db=db,
        user={"email": "admin@example.com"},
    )

    approval.reject.assert_called_once_with("admin@example.com", "nope", "later")
    db.commit.assert_called_once()
    assert "rejected" in result_msg["message"]


@pytest.mark.asyncio
async def test_handle_approval_request_invalid_action(monkeypatch: pytest.MonkeyPatch):
    approval = MagicMock()
    approval.status = "pending"
    approval.is_expired.return_value = False

    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = approval
    db.execute.return_value = result

    with pytest.raises(HTTPException) as excinfo:
        await sso_router.handle_approval_request(
            "approval",
            sso_router.ApprovalActionRequest(action="noop"),
            db=db,
            user={"email": "admin@example.com"},
        )

    assert excinfo.value.status_code == 400
