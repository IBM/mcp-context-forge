# -*- coding: utf-8 -*-
"""Tests for SSO router endpoints and helpers."""

# Standard
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import pytest
from fastapi import HTTPException
from fastapi.responses import RedirectResponse

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
    monkeypatch.setattr(sso_router.settings, "app_domain", "myapp.com")

    assert sso_router._validate_redirect_uri("/admin", None) is True
    assert sso_router._validate_redirect_uri("https://example.com:8443/cb", None) is True
    assert sso_router._validate_redirect_uri("https://myapp.com/cb", None) is True
    assert sso_router._validate_redirect_uri("https://evil.com/cb", None) is False


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
