# -*- coding: utf-8 -*-
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException, Request, status
from mcpgateway.middleware import rbac


@pytest.mark.asyncio
async def test_get_db_yields_and_closes():
    mock_session = MagicMock()
    with patch("mcpgateway.middleware.rbac.SessionLocal", return_value=mock_session):
        gen = rbac.get_db()
        db = next(gen)
        assert db == mock_session
        gen.close()
        mock_session.close.assert_called_once()


@pytest.mark.asyncio
async def test_get_permission_service_returns_instance():
    mock_db = MagicMock()
    with patch("mcpgateway.middleware.rbac.PermissionService", return_value="perm_service") as mock_perm:
        result = await rbac.get_permission_service(mock_db)
        assert result == "perm_service"
        mock_perm.assert_called_once_with(mock_db)


@pytest.mark.asyncio
async def test_get_current_user_with_permissions_cookie_token_success():
    mock_request = MagicMock(spec=Request)
    mock_request.cookies = {"jwt_token": "token123"}
    mock_request.headers = {"user-agent": "pytest"}
    mock_request.client = MagicMock()
    mock_request.client.host = "127.0.0.1"
    mock_request.state = MagicMock(auth_method="jwt", request_id="req123")

    mock_user = MagicMock(email="user@example.com", full_name="User", is_admin=True)
    with patch("mcpgateway.middleware.rbac.get_current_user", return_value=mock_user):
        result = await rbac.get_current_user_with_permissions(mock_request)
        assert result["email"] == "user@example.com"
        assert result["auth_method"] == "jwt"
        assert result["request_id"] == "req123"


@pytest.mark.asyncio
async def test_get_current_user_with_permissions_no_token_raises_401():
    mock_request = MagicMock(spec=Request)
    mock_request.cookies = {}
    mock_request.headers = {}
    mock_request.state = MagicMock()
    mock_request.client = None
    # Patch security dependency to mock HTTPAuthorizationCredentials behavior
    mock_credentials = MagicMock()
    mock_credentials.credentials = None
    with patch("mcpgateway.middleware.rbac.security", mock_credentials):
        with pytest.raises(HTTPException) as exc:
            await rbac.get_current_user_with_permissions(mock_request, credentials=mock_credentials)
        assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_get_current_user_with_permissions_auth_failure_redirect_html():
    mock_request = MagicMock(spec=Request)
    mock_request.cookies = {"jwt_token": "token123"}
    mock_request.headers = {"accept": "text/html"}
    mock_request.state = MagicMock()
    mock_request.client = MagicMock()
    mock_request.client.host = "127.0.0.1"
    with patch("mcpgateway.middleware.rbac.get_current_user", side_effect=Exception("fail")):
        with pytest.raises(HTTPException) as exc:
            await rbac.get_current_user_with_permissions(mock_request)
        assert exc.value.status_code == status.HTTP_302_FOUND


@pytest.mark.asyncio
async def test_require_permission_granted(monkeypatch):
    async def dummy_func(user=None):
        return "ok"

    mock_db = MagicMock()
    mock_user = {"email": "user@example.com", "db": mock_db}
    mock_perm_service = AsyncMock()
    mock_perm_service.check_permission.return_value = True
    monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

    decorated = rbac.require_permission("tools.read")(dummy_func)
    result = await decorated(user=mock_user)
    assert result == "ok"


@pytest.mark.asyncio
async def test_require_admin_permission_granted(monkeypatch):
    async def dummy_func(user=None):
        return "admin-ok"

    mock_db = MagicMock()
    mock_user = {"email": "user@example.com", "db": mock_db}
    mock_perm_service = AsyncMock()
    mock_perm_service.check_admin_permission.return_value = True
    monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

    decorated = rbac.require_admin_permission()(dummy_func)
    result = await decorated(user=mock_user)
    assert result == "admin-ok"


@pytest.mark.asyncio
async def test_require_any_permission_granted(monkeypatch):
    async def dummy_func(user=None):
        return "any-ok"

    mock_db = MagicMock()
    mock_user = {"email": "user@example.com", "db": mock_db}
    mock_perm_service = AsyncMock()
    mock_perm_service.check_permission.side_effect = [False, True]
    monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

    decorated = rbac.require_any_permission(["tools.read", "tools.execute"])(dummy_func)
    result = await decorated(user=mock_user)
    assert result == "any-ok"


@pytest.mark.asyncio
async def test_permission_checker_methods(monkeypatch):
    mock_db = MagicMock()
    mock_user = {"email": "user@example.com", "db": mock_db}
    mock_perm_service = AsyncMock()
    mock_perm_service.check_permission.return_value = True
    mock_perm_service.check_admin_permission.return_value = True
    monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

    checker = rbac.PermissionChecker(mock_user)
    assert await checker.has_permission("tools.read")
    assert await checker.has_admin_permission()
    assert await checker.has_any_permission(["tools.read", "tools.execute"])
    await checker.require_permission("tools.read")
