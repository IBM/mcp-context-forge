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


# ============================================================================
# Tests for has_hooks_for optimization (Issue #1778)
# ============================================================================
# Note: These tests are skipped by default due to flakiness in parallel execution
# (pytest-xdist) caused by global state interference with the plugin manager singleton.
#
# To run these tests, temporarily comment out the @pytest.mark.skip decorator and run:
#   uv run pytest tests/unit/mcpgateway/middleware/test_rbac.py -v -k "has_hooks_for"
#
# The auth.py optimization tests (test_auth.py::TestAuthHooksOptimization) verify
# the same has_hooks_for pattern and run reliably in parallel execution.


@pytest.mark.skip(reason="Flaky in parallel execution due to plugin manager singleton; run individually")
@pytest.mark.asyncio
async def test_require_permission_skips_hooks_when_has_hooks_for_false(monkeypatch):
    """Test that hook invocation is skipped when has_hooks_for returns False.

    This test verifies the optimization added in issue #1778: when plugin manager
    exists but has_hooks_for returns False, the code should skip hook invocation
    and fall through directly to PermissionService.check_permission.
    """
    import importlib

    async def dummy_func(user=None):
        return "ok"

    mock_db = MagicMock()
    mock_user = {"email": "user@example.com", "db": mock_db}
    mock_perm_service = AsyncMock()
    mock_perm_service.check_permission.return_value = True
    monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

    # Create a mock plugin manager with has_hooks_for returning False
    mock_pm = MagicMock()
    mock_pm.has_hooks_for = MagicMock(return_value=False)
    mock_pm.invoke_hook = AsyncMock()  # Should NOT be called

    # Use importlib to ensure the module is loaded, then patch get_plugin_manager
    plugin_framework = importlib.import_module("mcpgateway.plugins.framework")
    original_get_pm = plugin_framework.get_plugin_manager
    try:
        plugin_framework.get_plugin_manager = lambda: mock_pm

        decorated = rbac.require_permission("tools.read")(dummy_func)
        result = await decorated(user=mock_user)

        assert result == "ok"
        # The key assertion: invoke_hook should NOT have been called
        # because has_hooks_for returned False
        mock_pm.invoke_hook.assert_not_called()
        # PermissionService.check_permission should have been called as fallback
        mock_perm_service.check_permission.assert_called_once()
    finally:
        plugin_framework.get_plugin_manager = original_get_pm


@pytest.mark.skip(reason="Flaky in parallel execution due to plugin manager singleton; run individually")
@pytest.mark.asyncio
async def test_require_permission_calls_hooks_when_has_hooks_for_true(monkeypatch):
    """Test that hook invocation occurs when has_hooks_for returns True.

    This test verifies that when plugins ARE registered for the permission hook,
    the invoke_hook method is called with the appropriate payload.
    """
    import importlib
    from mcpgateway.plugins.framework import PluginResult

    async def dummy_func(user=None):
        return "ok"

    mock_db = MagicMock()
    mock_user = {"email": "user@example.com", "db": mock_db}
    mock_perm_service = AsyncMock()
    mock_perm_service.check_permission.return_value = True
    monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

    # Create a mock plugin manager with has_hooks_for returning True
    # and invoke_hook returning a result that continues processing
    mock_plugin_result = PluginResult(modified_payload=None, continue_processing=True)
    mock_pm = MagicMock()
    mock_pm.has_hooks_for = MagicMock(return_value=True)
    mock_pm.invoke_hook = AsyncMock(return_value=(mock_plugin_result, None))

    # Use importlib to ensure the module is loaded, then patch get_plugin_manager
    plugin_framework = importlib.import_module("mcpgateway.plugins.framework")
    original_get_pm = plugin_framework.get_plugin_manager
    try:
        plugin_framework.get_plugin_manager = lambda: mock_pm

        decorated = rbac.require_permission("tools.read")(dummy_func)
        result = await decorated(user=mock_user)

        assert result == "ok"
        # The key assertion: invoke_hook SHOULD have been called
        mock_pm.invoke_hook.assert_called_once()
    finally:
        plugin_framework.get_plugin_manager = original_get_pm


# ============================================================================
# Tests for team_id fallback from user_context (Issue #2183)
# ============================================================================
# Note: These tests require mocking the plugin manager singleton, which is flaky
# in parallel execution (pytest-xdist). They are skipped by default but can be
# run individually with: pytest tests/unit/mcpgateway/middleware/test_rbac.py -k "team_id" -v


@pytest.mark.skip(reason="Flaky in parallel execution due to plugin manager singleton; run individually")
@pytest.mark.asyncio
async def test_require_permission_uses_user_context_team_id_when_no_kwarg(monkeypatch):
    """Verify check_permission receives team_id from user_context when no team_id kwarg is passed.

    This tests the fix for issue #2183: when team_id is not in path/query parameters,
    the decorator should fall back to user_context.team_id from the JWT token.
    """
    import importlib

    async def dummy_func(user=None):
        return "ok"

    mock_db = MagicMock()
    mock_user = {"email": "user@example.com", "db": mock_db, "team_id": "team-123"}
    mock_perm_service = AsyncMock()
    mock_perm_service.check_permission.return_value = True
    monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

    plugin_framework = importlib.import_module("mcpgateway.plugins.framework")
    original_get_pm = plugin_framework.get_plugin_manager
    try:
        plugin_framework.get_plugin_manager = lambda: None
        decorated = rbac.require_permission("gateways.read")(dummy_func)
        result = await decorated(user=mock_user)
        assert result == "ok"
        mock_perm_service.check_permission.assert_called_once()
        assert mock_perm_service.check_permission.call_args.kwargs["team_id"] == "team-123"
    finally:
        plugin_framework.get_plugin_manager = original_get_pm


@pytest.mark.skip(reason="Flaky in parallel execution due to plugin manager singleton; run individually")
@pytest.mark.asyncio
async def test_require_permission_prefers_kwarg_team_id(monkeypatch):
    """Verify kwarg team_id takes precedence over user_context.team_id."""
    import importlib

    async def dummy_func(user=None, team_id=None):
        return "ok"

    mock_db = MagicMock()
    mock_user = {"email": "user@example.com", "db": mock_db, "team_id": "team-A"}
    mock_perm_service = AsyncMock()
    mock_perm_service.check_permission.return_value = True
    monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

    plugin_framework = importlib.import_module("mcpgateway.plugins.framework")
    original_get_pm = plugin_framework.get_plugin_manager
    try:
        plugin_framework.get_plugin_manager = lambda: None
        decorated = rbac.require_permission("gateways.read")(dummy_func)
        result = await decorated(user=mock_user, team_id="team-B")
        assert result == "ok"
        mock_perm_service.check_permission.assert_called_once()
        assert mock_perm_service.check_permission.call_args.kwargs["team_id"] == "team-B"
    finally:
        plugin_framework.get_plugin_manager = original_get_pm


@pytest.mark.skip(reason="Flaky in parallel execution due to plugin manager singleton; run individually")
@pytest.mark.asyncio
async def test_require_any_permission_uses_user_context_team_id_when_no_kwarg(monkeypatch):
    """Verify require_any_permission uses user_context.team_id when no team_id kwarg."""
    import importlib

    async def dummy_func(user=None):
        return "any-ok"

    mock_db = MagicMock()
    mock_user = {"email": "user@example.com", "db": mock_db, "team_id": "team-456"}
    mock_perm_service = AsyncMock()
    mock_perm_service.check_permission.return_value = True
    monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

    plugin_framework = importlib.import_module("mcpgateway.plugins.framework")
    original_get_pm = plugin_framework.get_plugin_manager
    try:
        plugin_framework.get_plugin_manager = lambda: None
        decorated = rbac.require_any_permission(["gateways.read", "gateways.list"])(dummy_func)
        result = await decorated(user=mock_user)
        assert result == "any-ok"
        assert mock_perm_service.check_permission.called
        assert mock_perm_service.check_permission.call_args.kwargs["team_id"] == "team-456"
    finally:
        plugin_framework.get_plugin_manager = original_get_pm


@pytest.mark.skip(reason="Flaky in parallel execution due to plugin manager singleton; run individually")
@pytest.mark.asyncio
async def test_require_any_permission_prefers_kwarg_team_id(monkeypatch):
    """Verify require_any_permission prefers kwarg team_id over user_context.team_id."""
    import importlib

    async def dummy_func(user=None, team_id=None):
        return "any-ok"

    mock_db = MagicMock()
    mock_user = {"email": "user@example.com", "db": mock_db, "team_id": "team-A"}
    mock_perm_service = AsyncMock()
    mock_perm_service.check_permission.return_value = True
    monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

    plugin_framework = importlib.import_module("mcpgateway.plugins.framework")
    original_get_pm = plugin_framework.get_plugin_manager
    try:
        plugin_framework.get_plugin_manager = lambda: None
        decorated = rbac.require_any_permission(["gateways.read"])(dummy_func)
        result = await decorated(user=mock_user, team_id="team-B")
        assert result == "any-ok"
        assert mock_perm_service.check_permission.call_args.kwargs["team_id"] == "team-B"
    finally:
        plugin_framework.get_plugin_manager = original_get_pm


@pytest.mark.skip(reason="Flaky in parallel execution due to plugin manager singleton; run individually")
@pytest.mark.asyncio
async def test_decorators_handle_none_user_context_team_id(monkeypatch):
    """Verify decorators work when user_context.team_id is None."""
    import importlib

    async def dummy_func(user=None):
        return "ok"

    mock_db = MagicMock()
    mock_user = {"email": "user@example.com", "db": mock_db}
    mock_perm_service = AsyncMock()
    mock_perm_service.check_permission.return_value = True
    monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

    plugin_framework = importlib.import_module("mcpgateway.plugins.framework")
    original_get_pm = plugin_framework.get_plugin_manager
    try:
        plugin_framework.get_plugin_manager = lambda: None
        decorated_perm = rbac.require_permission("gateways.read")(dummy_func)
        result = await decorated_perm(user=mock_user)
        assert result == "ok"
        assert mock_perm_service.check_permission.call_args.kwargs["team_id"] is None
    finally:
        plugin_framework.get_plugin_manager = original_get_pm


@pytest.mark.skip(reason="Flaky in parallel execution due to plugin manager singleton; run individually")
@pytest.mark.asyncio
async def test_plugin_permission_hook_receives_token_team_id(monkeypatch):
    """Test that plugin permission hook receives correct team_id from user_context.

    Scenario:
    - Plugin registered for HTTP_AUTH_CHECK_PERMISSION hook
    - User has team_id in token (via user_context)
    - User calls endpoint without team_id param
    Expected: Plugin's HttpAuthCheckPermissionPayload.team_id equals token's team_id
    """
    import importlib
    from mcpgateway.plugins.framework import PluginResult, HttpAuthCheckPermissionPayload

    async def dummy_func(user=None):
        return "ok"

    mock_db = MagicMock()
    # User context with team_id from JWT token
    mock_user = {"email": "user@example.com", "db": mock_db, "team_id": "team-from-token"}
    mock_perm_service = AsyncMock()
    mock_perm_service.check_permission.return_value = True
    monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

    # Create a mock plugin manager that captures the payload
    captured_payload = None

    async def capture_invoke_hook(hook_type, payload, global_context, local_contexts=None):
        nonlocal captured_payload
        captured_payload = payload
        # Return result that continues processing (doesn't make decision)
        return (PluginResult(modified_payload=None, continue_processing=True), None)

    mock_pm = MagicMock()
    mock_pm.has_hooks_for = MagicMock(return_value=True)
    mock_pm.invoke_hook = AsyncMock(side_effect=capture_invoke_hook)

    plugin_framework = importlib.import_module("mcpgateway.plugins.framework")
    original_get_pm = plugin_framework.get_plugin_manager
    try:
        plugin_framework.get_plugin_manager = lambda: mock_pm

        decorated = rbac.require_permission("gateways.read")(dummy_func)
        result = await decorated(user=mock_user)

        assert result == "ok"
        # Key assertion: the plugin hook should have received the team_id from user_context
        assert captured_payload is not None
        assert isinstance(captured_payload, HttpAuthCheckPermissionPayload)
        assert captured_payload.team_id == "team-from-token"
    finally:
        plugin_framework.get_plugin_manager = original_get_pm


@pytest.mark.skip(reason="Flaky in parallel execution due to plugin manager singleton; run individually")
@pytest.mark.asyncio
async def test_require_permission_fallback_when_plugin_manager_none(monkeypatch):
    """Test that RBAC falls back to PermissionService when plugin manager is None.

    This verifies the optimization handles the case where get_plugin_manager()
    returns None (plugins disabled).
    """
    import importlib

    async def dummy_func(user=None):
        return "ok"

    mock_db = MagicMock()
    mock_user = {"email": "user@example.com", "db": mock_db}
    mock_perm_service = AsyncMock()
    mock_perm_service.check_permission.return_value = True
    monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

    # Use importlib to ensure the module is loaded, then patch get_plugin_manager
    plugin_framework = importlib.import_module("mcpgateway.plugins.framework")
    original_get_pm = plugin_framework.get_plugin_manager
    try:
        plugin_framework.get_plugin_manager = lambda: None

        decorated = rbac.require_permission("tools.read")(dummy_func)
        result = await decorated(user=mock_user)

        assert result == "ok"
        # PermissionService.check_permission should have been called as fallback
        mock_perm_service.check_permission.assert_called_once()
    finally:
        plugin_framework.get_plugin_manager = original_get_pm
