# -*- coding: utf-8 -*-
# Standard
import asyncio
from contextlib import contextmanager
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi import HTTPException, Request, status
import pytest

# First-Party
from mcpgateway.middleware import rbac


@pytest.fixture(autouse=True)
def _restore_real_rbac_decorators():
    """Reload rbac module to restore real decorator functions from source code.

    e2e tests (test_main_apis.py, test_oauth_protected_resource.py) replace
    rbac.require_permission/require_admin_permission/require_any_permission
    with noop_decorator at module level without cleanup.  Under xdist, when
    these e2e modules land on the same worker, the decorators stay permanently
    patched as no-ops, causing 14 test failures here (DID NOT RAISE / 0 calls).

    importlib.reload() re-executes the module source, restoring real decorators.
    Non-decorator attributes are saved and restored to preserve object identity
    for FastAPI dependency_overrides in other test files on the same worker.
    """
    saved_ps = rbac.PermissionService
    saved_gcuwp = rbac.get_current_user_with_permissions
    saved_get_db = rbac.get_db
    saved_get_ps = rbac.get_permission_service

    importlib.reload(rbac)

    rbac.PermissionService = saved_ps
    rbac.get_current_user_with_permissions = saved_gcuwp
    rbac.get_db = saved_get_db
    rbac.get_permission_service = saved_get_ps
    yield
    rbac.get_current_user_with_permissions = saved_gcuwp
    rbac.get_db = saved_get_db
    rbac.get_permission_service = saved_get_ps


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
    mock_request.headers = {"user-agent": "pytest", "accept": "text/html"}  # Mark as browser request
    mock_request.client = MagicMock()
    mock_request.client.host = "127.0.0.1"
    mock_request.state = MagicMock(auth_method="jwt", request_id="req123", token_teams=["team-1"])

    mock_user = MagicMock(email="user@example.com", full_name="User", is_admin=True)
    with patch("mcpgateway.middleware.rbac.get_current_user", return_value=mock_user):
        result = await rbac.get_current_user_with_permissions(mock_request, credentials=None, jwt_token="token123")
        assert result["email"] == "user@example.com"
        assert result["auth_method"] == "jwt"
        assert result["request_id"] == "req123"
        assert result["token_teams"] == ["team-1"]


@pytest.mark.asyncio
async def test_get_current_user_with_permissions_cookie_rejected_for_api_request():
    """Cookie-only authentication must return 401 for non-browser (API) requests."""
    mock_request = MagicMock(spec=Request)
    mock_request.cookies = {"jwt_token": "token123"}
    mock_request.headers = {"user-agent": "python-requests/2.31", "accept": "application/json"}
    mock_request.client = MagicMock()
    mock_request.client.host = "127.0.0.1"
    mock_request.state = MagicMock(auth_method="jwt", request_id="req123")

    with pytest.raises(HTTPException) as exc:
        await rbac.get_current_user_with_permissions(mock_request, credentials=None, jwt_token=None)
    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Cookie authentication not allowed" in exc.value.detail


@pytest.mark.asyncio
async def test_cookie_auth_allowed_with_admin_referer():
    """/admin referer marks the request as a browser/UI request; cookie auth must be accepted."""
    mock_request = MagicMock(spec=Request)
    mock_request.cookies = {"jwt_token": "token123"}
    mock_request.headers = {"accept": "application/json", "referer": "http://localhost:4444/admin#gateways"}
    mock_request.client = MagicMock()
    mock_request.client.host = "127.0.0.1"
    mock_request.state = MagicMock(auth_method="jwt", request_id="req-admin", token_teams=["team-1"])

    mock_user = MagicMock(email="user@example.com", full_name="User", is_admin=False)
    with patch("mcpgateway.middleware.rbac.get_current_user", return_value=mock_user):
        result = await rbac.get_current_user_with_permissions(mock_request, credentials=None, jwt_token="token123")
    assert result["email"] == "user@example.com"


@pytest.mark.asyncio
async def test_cookie_auth_allowed_with_accept_text_html():
    """Accept: text/html header (e.g. OAuth callback fetch) must be treated as a browser request."""
    mock_request = MagicMock(spec=Request)
    mock_request.cookies = {"jwt_token": "token123"}
    mock_request.headers = {"accept": "text/html", "referer": "http://localhost:4444/oauth/callback"}
    mock_request.client = MagicMock()
    mock_request.client.host = "127.0.0.1"
    mock_request.state = MagicMock(auth_method="jwt", request_id="req-oauth", token_teams=["team-1"])

    mock_user = MagicMock(email="user@example.com", full_name="User", is_admin=False)
    with patch("mcpgateway.middleware.rbac.get_current_user", return_value=mock_user):
        result = await rbac.get_current_user_with_permissions(mock_request, credentials=None, jwt_token="token123")
    assert result["email"] == "user@example.com"


@pytest.mark.asyncio
async def test_cookie_auth_rejected_with_cross_origin_oauth_referer():
    """Cross-origin /oauth/ referer without browser headers must NOT grant cookie auth."""
    mock_request = MagicMock(spec=Request)
    mock_request.cookies = {"jwt_token": "token123"}
    mock_request.headers = {"accept": "application/json", "referer": "https://attacker.example/oauth/callback"}
    mock_request.client = MagicMock()
    mock_request.client.host = "127.0.0.1"
    mock_request.state = MagicMock(auth_method="jwt", request_id="req-xorigin")

    with pytest.raises(HTTPException) as exc:
        await rbac.get_current_user_with_permissions(mock_request, credentials=None, jwt_token=None)
    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Cookie authentication not allowed" in exc.value.detail


@pytest.mark.asyncio
async def test_cookie_auth_rejected_with_unrelated_referer():
    """An unrelated referer (e.g. /api/tools) must NOT grant cookie auth — still a 401."""
    mock_request = MagicMock(spec=Request)
    mock_request.cookies = {"jwt_token": "token123"}
    mock_request.headers = {"accept": "application/json", "referer": "http://localhost:4444/api/tools"}
    mock_request.client = MagicMock()
    mock_request.client.host = "127.0.0.1"
    mock_request.state = MagicMock(auth_method="jwt", request_id="req-api")

    with pytest.raises(HTTPException) as exc:
        await rbac.get_current_user_with_permissions(mock_request, credentials=None, jwt_token=None)
    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Cookie authentication not allowed" in exc.value.detail


@pytest.mark.asyncio
async def test_get_current_user_with_permissions_no_token_raises_401():
    mock_request = MagicMock(spec=Request)
    mock_request.cookies = {}
    mock_request.headers = {}
    mock_request.state = MagicMock()
    mock_request.client = None
    # Create proper HTTPAuthorizationCredentials mock
    mock_credentials = MagicMock()
    mock_credentials.credentials = None
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
            await rbac.get_current_user_with_permissions(mock_request, credentials=None, jwt_token="token123")
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
    # Standard
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
    # Standard
    import importlib

    # First-Party
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
    # Standard
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
    # Standard
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
    # Standard
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
    # Standard
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
    # Standard
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
    # Standard
    import importlib

    # First-Party
    from mcpgateway.plugins.framework import HttpAuthCheckPermissionPayload, PluginResult

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
    # Standard
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


# ============================================================================
# Coverage improvement tests
# Lines: 61, 63-70, 151-152, 205-216, 416-457, 476-486, 564-566,
#        671-686, 746-756, 769-770, 797, 799-811, 825
# ============================================================================


def _make_fresh_db(mock_db):
    """Create a mock fresh_db_session context manager."""

    @contextmanager
    def _fresh():
        yield mock_db

    return _fresh


# --- get_db() exception handling (lines 61, 63-70) ---


@pytest.mark.asyncio
async def test_get_db_commit_on_success():
    """get_db() calls commit() after successful generator completion (line 61)."""
    mock_session = MagicMock()
    with patch("mcpgateway.middleware.rbac.SessionLocal", return_value=mock_session):
        gen = rbac.get_db()
        next(gen)
        try:
            next(gen)
        except StopIteration:
            pass
        mock_session.commit.assert_called_once()
        mock_session.close.assert_called_once()


@pytest.mark.asyncio
async def test_get_db_rollback_on_exception():
    """get_db() rolls back and re-raises on exception (lines 63-64)."""
    mock_session = MagicMock()
    with patch("mcpgateway.middleware.rbac.SessionLocal", return_value=mock_session):
        gen = rbac.get_db()
        next(gen)
        with pytest.raises(ValueError, match="boom"):
            gen.throw(ValueError("boom"))
        mock_session.rollback.assert_called_once()
        mock_session.close.assert_called_once()


@pytest.mark.asyncio
async def test_get_db_invalidate_when_rollback_fails():
    """get_db() calls invalidate() when rollback fails (lines 65-67)."""
    mock_session = MagicMock()
    mock_session.rollback.side_effect = Exception("rollback fail")
    with patch("mcpgateway.middleware.rbac.SessionLocal", return_value=mock_session):
        gen = rbac.get_db()
        next(gen)
        with pytest.raises(ValueError, match="boom"):
            gen.throw(ValueError("boom"))
        mock_session.invalidate.assert_called_once()
        mock_session.close.assert_called_once()


@pytest.mark.asyncio
async def test_get_db_invalidate_fails_silently():
    """get_db() swallows invalidate() failure and still re-raises (lines 68-69)."""
    mock_session = MagicMock()
    mock_session.rollback.side_effect = Exception("rollback fail")
    mock_session.invalidate.side_effect = Exception("invalidate fail")
    with patch("mcpgateway.middleware.rbac.SessionLocal", return_value=mock_session):
        gen = rbac.get_db()
        next(gen)
        with pytest.raises(ValueError, match="boom"):
            gen.throw(ValueError("boom"))
        mock_session.invalidate.assert_called_once()
        mock_session.close.assert_called_once()


# --- Proxy user DB lookup exception (lines 151-152) ---


@pytest.mark.asyncio
async def test_proxy_user_db_lookup_exception_continues():
    """Proxy user DB lookup failure continues with is_admin=False (lines 151-152)."""
    mock_request = MagicMock(spec=Request)
    mock_request.headers = {"x-forwarded-user": "user@test.com", "user-agent": "test"}
    mock_request.client = MagicMock(host="127.0.0.1")
    mock_request.state = SimpleNamespace(
        plugin_context_table=None,
        plugin_global_context=None,
        request_id="req1",
        team_id=None,
    )

    mock_settings = MagicMock()
    mock_settings.mcp_client_auth_enabled = False
    mock_settings.trust_proxy_auth = True
    mock_settings.proxy_user_header = "x-forwarded-user"
    mock_settings.platform_admin_email = "admin@platform.com"

    with patch("mcpgateway.middleware.rbac.settings", mock_settings), patch("mcpgateway.middleware.rbac.fresh_db_session", side_effect=Exception("DB error")):
        result = await rbac.get_current_user_with_permissions(mock_request, credentials=None, jwt_token=None)

    assert result["email"] == "user@test.com"
    assert result["is_admin"] is False
    assert result["auth_method"] == "proxy"
    assert result["full_name"] == "user@test.com"


# --- No proxy auth + auth_required (lines 205-216) ---


@pytest.mark.asyncio
async def test_no_proxy_no_trust_auth_required_html_redirect():
    """mcp_client_auth disabled, no proxy trust, auth_required -> 302 for HTML (lines 205-212)."""
    mock_request = MagicMock(spec=Request)
    mock_request.headers = {"accept": "text/html", "user-agent": "browser"}
    mock_request.state = SimpleNamespace(plugin_context_table=None, plugin_global_context=None)

    mock_settings = MagicMock()
    mock_settings.mcp_client_auth_enabled = False
    mock_settings.trust_proxy_auth = False
    mock_settings.auth_required = True
    mock_settings.app_root_path = ""

    with patch("mcpgateway.middleware.rbac.settings", mock_settings):
        with pytest.raises(HTTPException) as exc:
            await rbac.get_current_user_with_permissions(mock_request, credentials=None, jwt_token=None)
    assert exc.value.status_code == status.HTTP_302_FOUND


@pytest.mark.asyncio
async def test_no_proxy_no_trust_auth_required_api_401():
    """mcp_client_auth disabled, no proxy trust, auth_required -> 401 for API (lines 213-216)."""
    mock_request = MagicMock(spec=Request)
    mock_request.headers = {"accept": "application/json", "user-agent": "api-client"}
    mock_request.state = SimpleNamespace(plugin_context_table=None, plugin_global_context=None)

    mock_settings = MagicMock()
    mock_settings.mcp_client_auth_enabled = False
    mock_settings.trust_proxy_auth = False
    mock_settings.auth_required = True

    with patch("mcpgateway.middleware.rbac.settings", mock_settings):
        with pytest.raises(HTTPException) as exc:
            await rbac.get_current_user_with_permissions(mock_request, credentials=None, jwt_token=None)
    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert "no auth method configured" in exc.value.detail


# --- Plugin hook grant/deny (lines 416-457) ---


@pytest.mark.asyncio
async def test_require_permission_plugin_hook_grants(monkeypatch):
    """Plugin hook grants permission, skipping RBAC (lines 416-452)."""

    async def dummy_func(user=None):
        return "plugin-granted"

    mock_user = {
        "email": "user@test.com",
        "db": MagicMock(),
        "plugin_context_table": None,
        "plugin_global_context": None,
        "request_id": "r1",
    }

    mock_result = MagicMock()
    mock_result.modified_payload.granted = True
    mock_result.modified_payload.reason = "Allowed by test"

    mock_pm = MagicMock()
    mock_pm.has_hooks_for.return_value = True
    mock_pm.invoke_hook = AsyncMock(return_value=(mock_result, None))

    with patch("mcpgateway.plugins.framework.get_plugin_manager", return_value=mock_pm):
        decorated = rbac.require_permission("tools.read")(dummy_func)
        result = await decorated(user=mock_user)

    assert result == "plugin-granted"
    mock_pm.invoke_hook.assert_called_once()


@pytest.mark.asyncio
async def test_require_permission_plugin_hook_denies(monkeypatch):
    """Plugin hook denies permission, raises 403 (lines 453-457)."""

    async def dummy_func(user=None):
        return "should-not-reach"

    # Use a truthy plugin_global_context to cover line 422 (reuse existing context)
    mock_global_ctx = MagicMock()
    mock_user = {
        "email": "user@test.com",
        "db": MagicMock(),
        "plugin_context_table": None,
        "plugin_global_context": mock_global_ctx,
        "request_id": "r1",
    }

    mock_result = MagicMock()
    mock_result.modified_payload.granted = False
    mock_result.modified_payload.reason = "Denied by test"

    mock_pm = MagicMock()
    mock_pm.has_hooks_for.return_value = True
    mock_pm.invoke_hook = AsyncMock(return_value=(mock_result, None))

    with patch("mcpgateway.plugins.framework.get_plugin_manager", return_value=mock_pm):
        decorated = rbac.require_permission("tools.read")(dummy_func)
        with pytest.raises(HTTPException) as exc:
            await decorated(user=mock_user)

    assert exc.value.status_code == status.HTTP_403_FORBIDDEN


# --- Decorator fresh_db_session paths ---


@pytest.mark.asyncio
async def test_require_permission_fresh_db_session(monkeypatch):
    """require_permission uses fresh_db_session when no db available (lines 476-486)."""

    async def dummy_func(user=None):
        return "fresh-ok"

    mock_user = {"email": "user@test.com"}  # No 'db' key
    mock_perm_service = AsyncMock()
    mock_perm_service.check_permission.return_value = True
    monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

    mock_db = MagicMock()
    with patch("mcpgateway.middleware.rbac.fresh_db_session", _make_fresh_db(mock_db)):
        decorated = rbac.require_permission("tools.read")(dummy_func)
        result = await decorated(user=mock_user)

    assert result == "fresh-ok"
    mock_perm_service.check_permission.assert_called_once()


@pytest.mark.asyncio
async def test_require_admin_permission_fresh_db_session(monkeypatch):
    """require_admin_permission uses fresh_db_session when no db (lines 564-566)."""

    async def dummy_func(user=None):
        return "admin-fresh-ok"

    mock_user = {"email": "admin@test.com"}  # No 'db' key
    mock_perm_service = AsyncMock()
    mock_perm_service.check_admin_permission.return_value = True
    monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

    mock_db = MagicMock()
    with patch("mcpgateway.middleware.rbac.fresh_db_session", _make_fresh_db(mock_db)):
        decorated = rbac.require_admin_permission()(dummy_func)
        result = await decorated(user=mock_user)

    assert result == "admin-fresh-ok"
    mock_perm_service.check_admin_permission.assert_called_once()


@pytest.mark.asyncio
async def test_require_any_permission_fresh_db_session(monkeypatch):
    """require_any_permission uses fresh_db_session when no db (lines 671-686)."""

    async def dummy_func(user=None):
        return "any-fresh-ok"

    mock_user = {"email": "user@test.com"}  # No 'db' key
    mock_perm_service = AsyncMock()
    mock_perm_service.check_permission.side_effect = [False, True]
    monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

    mock_db = MagicMock()
    with patch("mcpgateway.middleware.rbac.fresh_db_session", _make_fresh_db(mock_db)):
        decorated = rbac.require_any_permission(["tools.read", "tools.execute"])(dummy_func)
        result = await decorated(user=mock_user)

    assert result == "any-fresh-ok"


# --- PermissionChecker fresh_db_session paths ---


@pytest.mark.asyncio
async def test_permission_checker_has_permission_fresh_db(monkeypatch):
    """PermissionChecker.has_permission uses fresh_db_session (lines 746-756)."""
    mock_user = {"email": "user@test.com"}  # No 'db' key
    mock_perm_service = AsyncMock()
    mock_perm_service.check_permission.return_value = True
    monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

    mock_db = MagicMock()
    with patch("mcpgateway.middleware.rbac.fresh_db_session", _make_fresh_db(mock_db)):
        checker = rbac.PermissionChecker(mock_user)
        result = await checker.has_permission("tools.read")

    assert result is True


@pytest.mark.asyncio
async def test_permission_checker_has_admin_permission_fresh_db(monkeypatch):
    """PermissionChecker.has_admin_permission uses fresh_db_session (lines 769-770)."""
    mock_user = {"email": "admin@test.com"}  # No 'db' key
    mock_perm_service = AsyncMock()
    mock_perm_service.check_admin_permission.return_value = True
    monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

    mock_db = MagicMock()
    with patch("mcpgateway.middleware.rbac.fresh_db_session", _make_fresh_db(mock_db)):
        checker = rbac.PermissionChecker(mock_user)
        result = await checker.has_admin_permission()

    assert result is True


@pytest.mark.asyncio
async def test_permission_checker_has_any_permission_fresh_db(monkeypatch):
    """PermissionChecker.has_any_permission uses fresh_db_session (lines 799-811)."""
    mock_user = {"email": "user@test.com"}  # No 'db' key
    mock_perm_service = AsyncMock()
    mock_perm_service.check_permission.side_effect = [False, True]
    monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

    mock_db = MagicMock()
    with patch("mcpgateway.middleware.rbac.fresh_db_session", _make_fresh_db(mock_db)):
        checker = rbac.PermissionChecker(mock_user)
        result = await checker.has_any_permission(["tools.read", "tools.execute"])

    assert result is True


@pytest.mark.asyncio
async def test_permission_checker_has_any_permission_none_granted(monkeypatch):
    """PermissionChecker.has_any_permission returns False when none match (line 797)."""
    mock_db = MagicMock()
    mock_user = {"email": "user@test.com", "db": mock_db}
    mock_perm_service = AsyncMock()
    mock_perm_service.check_permission.return_value = False
    monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

    checker = rbac.PermissionChecker(mock_user)
    result = await checker.has_any_permission(["tools.read", "tools.execute"])

    assert result is False


@pytest.mark.asyncio
async def test_permission_checker_has_any_permission_fresh_db_none_granted(monkeypatch):
    """PermissionChecker.has_any_permission returns False with fresh_db (line 811)."""
    mock_user = {"email": "user@test.com"}  # No 'db' key
    mock_perm_service = AsyncMock()
    mock_perm_service.check_permission.return_value = False
    monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

    mock_db = MagicMock()
    with patch("mcpgateway.middleware.rbac.fresh_db_session", _make_fresh_db(mock_db)):
        checker = rbac.PermissionChecker(mock_user)
        result = await checker.has_any_permission(["tools.read", "tools.execute"])

    assert result is False


@pytest.mark.asyncio
async def test_permission_checker_require_permission_denied(monkeypatch):
    """PermissionChecker.require_permission raises 403 when denied (line 825)."""
    mock_db = MagicMock()
    mock_user = {"email": "user@test.com", "db": mock_db}
    mock_perm_service = AsyncMock()
    mock_perm_service.check_permission.return_value = False
    monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

    checker = rbac.PermissionChecker(mock_user)
    with pytest.raises(HTTPException) as exc:
        await checker.require_permission("tools.delete")
    assert exc.value.status_code == status.HTTP_403_FORBIDDEN


# --- Additional get_current_user_with_permissions paths ---


@pytest.mark.asyncio
async def test_proxy_user_is_platform_admin():
    """Proxy user matching platform_admin_email gets is_admin=True (lines 134-135)."""
    mock_request = MagicMock(spec=Request)
    mock_request.headers = {"x-forwarded-user": "admin@platform.com", "user-agent": "test"}
    mock_request.client = MagicMock(host="127.0.0.1")
    mock_request.state = SimpleNamespace(plugin_context_table=None, plugin_global_context=None, request_id="req1", team_id=None)

    mock_settings = MagicMock()
    mock_settings.mcp_client_auth_enabled = False
    mock_settings.trust_proxy_auth = True
    mock_settings.proxy_user_header = "x-forwarded-user"
    mock_settings.platform_admin_email = "admin@platform.com"

    with patch("mcpgateway.middleware.rbac.settings", mock_settings):
        result = await rbac.get_current_user_with_permissions(mock_request, credentials=None, jwt_token=None)

    assert result["email"] == "admin@platform.com"
    assert result["is_admin"] is True
    assert result["full_name"] == "Platform Admin"


@pytest.mark.asyncio
async def test_proxy_user_db_lookup_succeeds():
    """Proxy user DB lookup returns user with is_admin and full_name (lines 147-150)."""
    mock_request = MagicMock(spec=Request)
    mock_request.headers = {"x-forwarded-user": "user@test.com", "user-agent": "test"}
    mock_request.client = MagicMock(host="127.0.0.1")
    mock_request.state = SimpleNamespace(plugin_context_table=None, plugin_global_context=None, request_id="req1", team_id=None)

    mock_settings = MagicMock()
    mock_settings.mcp_client_auth_enabled = False
    mock_settings.trust_proxy_auth = True
    mock_settings.proxy_user_header = "x-forwarded-user"
    mock_settings.platform_admin_email = "admin@platform.com"

    mock_db_user = MagicMock(is_admin=True, full_name="Test User")
    mock_db = MagicMock()
    mock_db.execute.return_value.scalar_one_or_none.return_value = mock_db_user

    with patch("mcpgateway.middleware.rbac.settings", mock_settings), patch("mcpgateway.middleware.rbac.fresh_db_session", _make_fresh_db(mock_db)):
        result = await rbac.get_current_user_with_permissions(mock_request, credentials=None, jwt_token=None)

    assert result["email"] == "user@test.com"
    assert result["is_admin"] is True
    assert result["full_name"] == "Test User"


@pytest.mark.asyncio
async def test_trust_proxy_no_header_auth_required_html():
    """Trust proxy auth, no proxy header, auth_required, HTML → 302 (lines 171-179)."""
    mock_request = MagicMock(spec=Request)
    mock_request.headers = {"accept": "text/html", "user-agent": "browser"}
    mock_request.state = SimpleNamespace(plugin_context_table=None, plugin_global_context=None)

    mock_settings = MagicMock()
    mock_settings.mcp_client_auth_enabled = False
    mock_settings.trust_proxy_auth = True
    mock_settings.proxy_user_header = "x-forwarded-user"
    mock_settings.auth_required = True
    mock_settings.app_root_path = ""

    with patch("mcpgateway.middleware.rbac.settings", mock_settings):
        with pytest.raises(HTTPException) as exc:
            await rbac.get_current_user_with_permissions(mock_request, credentials=None, jwt_token=None)
    assert exc.value.status_code == status.HTTP_302_FOUND


@pytest.mark.asyncio
async def test_trust_proxy_no_header_auth_required_api():
    """Trust proxy auth, no proxy header, auth_required, API → 401 (lines 180-183)."""
    mock_request = MagicMock(spec=Request)
    mock_request.headers = {"accept": "application/json", "user-agent": "api"}
    mock_request.state = SimpleNamespace(plugin_context_table=None, plugin_global_context=None)

    mock_settings = MagicMock()
    mock_settings.mcp_client_auth_enabled = False
    mock_settings.trust_proxy_auth = True
    mock_settings.proxy_user_header = "x-forwarded-user"
    mock_settings.auth_required = True

    with patch("mcpgateway.middleware.rbac.settings", mock_settings):
        with pytest.raises(HTTPException) as exc:
            await rbac.get_current_user_with_permissions(mock_request, credentials=None, jwt_token=None)
    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_trust_proxy_no_header_anonymous():
    """Trust proxy auth, no proxy header, auth_required=False → anonymous (lines 187-199)."""
    mock_request = MagicMock(spec=Request)
    mock_request.headers = {"user-agent": "test"}
    mock_request.client = MagicMock(host="127.0.0.1")
    mock_request.state = SimpleNamespace(plugin_context_table=None, plugin_global_context=None, request_id="req1", team_id=None)

    mock_settings = MagicMock()
    mock_settings.mcp_client_auth_enabled = False
    mock_settings.trust_proxy_auth = True
    mock_settings.proxy_user_header = "x-forwarded-user"
    mock_settings.auth_required = False

    with patch("mcpgateway.middleware.rbac.settings", mock_settings):
        result = await rbac.get_current_user_with_permissions(mock_request, credentials=None, jwt_token=None)

    assert result["email"] == "anonymous"
    assert result["auth_method"] == "anonymous"


@pytest.mark.asyncio
async def test_no_proxy_no_trust_anonymous():
    """No proxy trust, auth_required=False → anonymous (lines 218-230)."""
    mock_request = MagicMock(spec=Request)
    mock_request.headers = {"user-agent": "test"}
    mock_request.client = MagicMock(host="127.0.0.1")
    mock_request.state = SimpleNamespace(plugin_context_table=None, plugin_global_context=None, request_id="req1", team_id=None)

    mock_settings = MagicMock()
    mock_settings.mcp_client_auth_enabled = False
    mock_settings.trust_proxy_auth = False
    mock_settings.auth_required = False

    with patch("mcpgateway.middleware.rbac.settings", mock_settings):
        result = await rbac.get_current_user_with_permissions(mock_request, credentials=None, jwt_token=None)

    assert result["email"] == "anonymous"
    assert result["auth_method"] == "anonymous"


@pytest.mark.asyncio
async def test_bearer_token_from_credentials():
    """Bearer token from Authorization header (line 239)."""
    mock_request = MagicMock(spec=Request)
    mock_request.cookies = {}
    mock_request.headers = {"accept": "application/json", "user-agent": "api"}
    mock_request.client = MagicMock(host="127.0.0.1")
    mock_request.state = SimpleNamespace(
        auth_method="jwt",
        request_id="req1",
        team_id=None,
        plugin_context_table=None,
        plugin_global_context=None,
    )

    mock_credentials = MagicMock()
    mock_credentials.credentials = "valid-token"

    mock_user = MagicMock(email="api@test.com", full_name="API User", is_admin=False)
    with patch("mcpgateway.middleware.rbac.get_current_user", return_value=mock_user):
        result = await rbac.get_current_user_with_permissions(mock_request, credentials=mock_credentials, jwt_token=None)

    assert result["email"] == "api@test.com"


@pytest.mark.asyncio
async def test_no_token_browser_redirect():
    """No token for browser request → 302 redirect (lines 272-273)."""
    mock_request = MagicMock(spec=Request)
    mock_request.cookies = {}
    mock_request.headers = {"accept": "text/html", "user-agent": "browser"}
    mock_request.state = MagicMock()
    mock_request.client = MagicMock(host="127.0.0.1")

    mock_credentials = MagicMock()
    mock_credentials.credentials = None

    with pytest.raises(HTTPException) as exc:
        await rbac.get_current_user_with_permissions(mock_request, credentials=mock_credentials, jwt_token=None)
    assert exc.value.status_code == status.HTTP_302_FOUND


@pytest.mark.asyncio
async def test_no_token_auth_disabled_platform_admin():
    """No token, auth disabled → platform admin (lines 276-287)."""
    mock_request = MagicMock(spec=Request)
    mock_request.cookies = {}
    mock_request.headers = {"accept": "application/json", "user-agent": "api"}
    mock_request.client = MagicMock(host="127.0.0.1")
    mock_request.state = SimpleNamespace(request_id="req1", team_id=None)

    mock_credentials = MagicMock()
    mock_credentials.credentials = None

    mock_settings = MagicMock()
    mock_settings.mcp_client_auth_enabled = True
    mock_settings.auth_required = False
    mock_settings.platform_admin_email = "admin@platform.com"

    with patch("mcpgateway.middleware.rbac.settings", mock_settings):
        result = await rbac.get_current_user_with_permissions(mock_request, credentials=mock_credentials, jwt_token=None)

    assert result["email"] == "admin@platform.com"
    assert result["is_admin"] is True
    assert result["auth_method"] == "disabled"


@pytest.mark.asyncio
async def test_auth_failure_non_browser_401():
    """Auth failure for non-browser request → 401 (line 334)."""
    mock_request = MagicMock(spec=Request)
    mock_request.cookies = {}
    mock_request.headers = {"accept": "application/json", "user-agent": "api"}
    mock_request.client = MagicMock(host="127.0.0.1")
    mock_request.state = MagicMock()

    mock_credentials = MagicMock()
    mock_credentials.credentials = "bad-token"

    with patch("mcpgateway.middleware.rbac.get_current_user", side_effect=Exception("Invalid token")):
        with pytest.raises(HTTPException) as exc:
            await rbac.get_current_user_with_permissions(mock_request, credentials=mock_credentials, jwt_token=None)
    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED


# --- Decorator denied paths ---


@pytest.mark.asyncio
async def test_require_permission_denied(monkeypatch):
    """require_permission raises 403 when check_permission returns False (lines 489-490)."""

    async def dummy_func(user=None):
        return "should-not-reach"

    mock_db = MagicMock()
    mock_user = {"email": "user@test.com", "db": mock_db}
    mock_perm_service = AsyncMock()
    mock_perm_service.check_permission.return_value = False
    monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

    decorated = rbac.require_permission("tools.delete")(dummy_func)
    with pytest.raises(HTTPException) as exc:
        await decorated(user=mock_user)
    assert exc.value.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_require_admin_permission_denied(monkeypatch):
    """require_admin_permission raises 403 when denied (lines 569-570)."""

    async def dummy_func(user=None):
        return "should-not-reach"

    mock_db = MagicMock()
    mock_user = {"email": "user@test.com", "db": mock_db}
    mock_perm_service = AsyncMock()
    mock_perm_service.check_admin_permission.return_value = False
    monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

    decorated = rbac.require_admin_permission()(dummy_func)
    with pytest.raises(HTTPException) as exc:
        await decorated(user=mock_user)
    assert exc.value.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_require_any_permission_denied(monkeypatch):
    """require_any_permission raises 403 when all denied (lines 689-690)."""

    async def dummy_func(user=None):
        return "should-not-reach"

    mock_db = MagicMock()
    mock_user = {"email": "user@test.com", "db": mock_db}
    mock_perm_service = AsyncMock()
    mock_perm_service.check_permission.return_value = False
    monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

    decorated = rbac.require_any_permission(["tools.read", "tools.execute"])(dummy_func)
    with pytest.raises(HTTPException) as exc:
        await decorated(user=mock_user)
    assert exc.value.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_require_permission_no_user_context():
    """require_permission raises 401 when no valid user context (line 398)."""

    async def dummy_func(user=None):
        return "should-not-reach"

    decorated = rbac.require_permission("tools.read")(dummy_func)
    with pytest.raises(HTTPException) as exc:
        await decorated(user=None)
    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_require_admin_permission_no_user_context():
    """require_admin_permission raises 401 when no valid user context (line 554)."""

    async def dummy_func(user=None):
        return "should-not-reach"

    decorated = rbac.require_admin_permission()(dummy_func)
    with pytest.raises(HTTPException) as exc:
        await decorated(user=None)
    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_require_any_permission_no_user_context():
    """require_any_permission raises 401 when no valid user context (line 640)."""

    async def dummy_func(user=None):
        return "should-not-reach"

    decorated = rbac.require_any_permission(["tools.read"])(dummy_func)
    with pytest.raises(HTTPException) as exc:
        await decorated(user=None)
    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_no_token_auth_required_api_401():
    """No token, auth required, non-browser → 401 (line 289)."""
    mock_request = MagicMock(spec=Request)
    mock_request.cookies = {}
    mock_request.headers = {"accept": "application/json", "user-agent": "api"}
    mock_request.state = MagicMock()
    mock_request.client = MagicMock(host="127.0.0.1")

    mock_credentials = MagicMock()
    mock_credentials.credentials = None

    with pytest.raises(HTTPException) as exc:
        await rbac.get_current_user_with_permissions(mock_request, credentials=mock_credentials, jwt_token=None)
    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Authorization token required" in exc.value.detail


@pytest.mark.asyncio
async def test_proxy_user_db_lookup_not_found():
    """Proxy user DB lookup returns None, keeps defaults (branch 148->155)."""
    mock_request = MagicMock(spec=Request)
    mock_request.headers = {"x-forwarded-user": "unknown@test.com", "user-agent": "test"}
    mock_request.client = MagicMock(host="127.0.0.1")
    mock_request.state = SimpleNamespace(plugin_context_table=None, plugin_global_context=None, request_id="req1", team_id=None)

    mock_settings = MagicMock()
    mock_settings.mcp_client_auth_enabled = False
    mock_settings.trust_proxy_auth = True
    mock_settings.proxy_user_header = "x-forwarded-user"
    mock_settings.platform_admin_email = "admin@platform.com"

    mock_db = MagicMock()
    mock_db.execute.return_value.scalar_one_or_none.return_value = None

    with patch("mcpgateway.middleware.rbac.settings", mock_settings), patch("mcpgateway.middleware.rbac.fresh_db_session", _make_fresh_db(mock_db)):
        result = await rbac.get_current_user_with_permissions(mock_request, credentials=None, jwt_token=None)

    assert result["email"] == "unknown@test.com"
    assert result["is_admin"] is False
    assert result["full_name"] == "unknown@test.com"


@pytest.mark.asyncio
async def test_cookies_without_jwt_token():
    """Cookies exist but no jwt_token/access_token → manual_token is None (branch 245->250)."""
    mock_request = MagicMock(spec=Request)
    mock_request.cookies = {"session_id": "abc123"}  # No jwt_token or access_token
    mock_request.headers = {"accept": "application/json", "user-agent": "api"}
    mock_request.state = MagicMock()
    mock_request.client = MagicMock(host="127.0.0.1")

    mock_credentials = MagicMock()
    mock_credentials.credentials = None

    with pytest.raises(HTTPException) as exc:
        await rbac.get_current_user_with_permissions(mock_request, credentials=mock_credentials, jwt_token=None)
    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_require_permission_plugin_no_decision(monkeypatch):
    """Plugin hook returns no modified_payload, falls through to RBAC (branch 449->461)."""

    async def dummy_func(user=None):
        return "rbac-fallthrough"

    mock_user = {
        "email": "user@test.com",
        "db": MagicMock(),
        "plugin_context_table": None,
        "plugin_global_context": None,
        "request_id": "r1",
    }

    mock_perm_service = AsyncMock()
    mock_perm_service.check_permission.return_value = True
    monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

    mock_result = MagicMock()
    mock_result.modified_payload = None  # No decision made

    mock_pm = MagicMock()
    mock_pm.has_hooks_for.return_value = True
    mock_pm.invoke_hook = AsyncMock(return_value=(mock_result, None))

    with patch("mcpgateway.plugins.framework.get_plugin_manager", return_value=mock_pm):
        decorated = rbac.require_permission("tools.read")(dummy_func)
        result = await decorated(user=mock_user)

    assert result == "rbac-fallthrough"
    mock_perm_service.check_permission.assert_called_once()


@pytest.mark.asyncio
async def test_require_permission_team_id_from_kwargs(monkeypatch):
    """require_permission uses team_id from kwargs (branch 404->410)."""

    async def dummy_func(user=None, team_id=None):
        return "ok"

    mock_db = MagicMock()
    mock_user = {"email": "user@test.com", "db": mock_db}
    mock_perm_service = AsyncMock()
    mock_perm_service.check_permission.return_value = True
    monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

    decorated = rbac.require_permission("tools.read")(dummy_func)
    result = await decorated(user=mock_user, team_id="team-123")
    assert result == "ok"
    assert mock_perm_service.check_permission.call_args.kwargs["team_id"] == "team-123"


@pytest.mark.asyncio
async def test_require_any_permission_team_id_from_kwargs(monkeypatch):
    """require_any_permission uses team_id from kwargs (branch 646->651)."""

    async def dummy_func(user=None, team_id=None):
        return "ok"

    mock_db = MagicMock()
    mock_user = {"email": "user@test.com", "db": mock_db}
    mock_perm_service = AsyncMock()
    mock_perm_service.check_permission.return_value = True
    monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

    decorated = rbac.require_any_permission(["tools.read", "tools.execute"])(dummy_func)
    result = await decorated(user=mock_user, team_id="team-456")
    assert result == "ok"
    assert mock_perm_service.check_permission.call_args.kwargs["team_id"] == "team-456"


@pytest.mark.asyncio
async def test_require_any_permission_fresh_db_session_all_denied(monkeypatch):
    """require_any_permission with fresh_db_session, all denied (branch 675->688)."""

    async def dummy_func(user=None):
        return "should-not-reach"

    mock_user = {"email": "user@test.com"}  # No 'db' key
    mock_perm_service = AsyncMock()
    mock_perm_service.check_permission.return_value = False
    monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

    mock_db = MagicMock()
    with patch("mcpgateway.middleware.rbac.fresh_db_session", _make_fresh_db(mock_db)):
        decorated = rbac.require_any_permission(["tools.read", "tools.execute"])(dummy_func)
        with pytest.raises(HTTPException) as exc:
            await decorated(user=mock_user)
    assert exc.value.status_code == status.HTTP_403_FORBIDDEN


# ============================================================================
# Tests for team derivation helpers and _is_mutate_permission
# ============================================================================


class TestDeriveTeamFromResource:
    """Tests for _derive_team_from_resource helper."""

    def test_resource_found_returns_team_id(self):
        """When resource exists with team_id, return it."""
        mock_db = MagicMock()
        mock_resource = MagicMock()
        mock_resource.team_id = "team-abc"
        mock_db.get.return_value = mock_resource

        with patch("mcpgateway.middleware.rbac._get_resource_param_to_model") as mock_mapping:
            mock_model = MagicMock()
            mock_mapping.return_value = {"tool_id": mock_model}
            result = rbac._derive_team_from_resource({"tool_id": "t-1"}, mock_db)

        assert result == "team-abc"
        mock_db.get.assert_called_once_with(mock_model, "t-1")

    def test_resource_not_found_returns_none(self):
        """When resource not found in DB, return None for 404 handling."""
        mock_db = MagicMock()
        mock_db.get.return_value = None

        with patch("mcpgateway.middleware.rbac._get_resource_param_to_model") as mock_mapping:
            mock_model = MagicMock()
            mock_mapping.return_value = {"tool_id": mock_model}
            result = rbac._derive_team_from_resource({"tool_id": "t-missing"}, mock_db)

        assert result is None

    def test_no_resource_param_returns_none(self):
        """When no resource ID param in kwargs, return None."""
        mock_db = MagicMock()

        with patch("mcpgateway.middleware.rbac._get_resource_param_to_model") as mock_mapping:
            mock_mapping.return_value = {"tool_id": MagicMock()}
            result = rbac._derive_team_from_resource({"other_param": "val"}, mock_db)

        assert result is None

    def test_db_exception_returns_none(self):
        """When DB lookup raises, return None gracefully."""
        mock_db = MagicMock()
        mock_db.get.side_effect = Exception("DB error")

        with patch("mcpgateway.middleware.rbac._get_resource_param_to_model") as mock_mapping:
            mock_model = MagicMock()
            mock_mapping.return_value = {"tool_id": mock_model}
            result = rbac._derive_team_from_resource({"tool_id": "t-1"}, mock_db)

        assert result is None

    def test_resource_no_team_id_attr(self):
        """When resource has no team_id attribute, getattr returns None."""
        mock_db = MagicMock()
        mock_resource = MagicMock(spec=[])  # No attributes
        mock_db.get.return_value = mock_resource

        with patch("mcpgateway.middleware.rbac._get_resource_param_to_model") as mock_mapping:
            mock_model = MagicMock()
            mock_mapping.return_value = {"tool_id": mock_model}
            result = rbac._derive_team_from_resource({"tool_id": "t-1"}, mock_db)

        assert result is None


class TestDeriveTeamFromPayload:
    """Tests for _derive_team_from_payload helper."""

    @pytest.mark.asyncio
    async def test_pydantic_payload_with_team_id(self):
        """Extract team_id from Pydantic payload object."""
        payload = SimpleNamespace(team_id="team-from-payload")
        result = await rbac._derive_team_from_payload({"tool": payload})
        assert result == "team-from-payload"

    @pytest.mark.asyncio
    async def test_pydantic_payload_team_id_none(self):
        """Return None when payload team_id is None."""
        payload = SimpleNamespace(team_id=None)
        result = await rbac._derive_team_from_payload({"tool": payload})
        assert result is None

    @pytest.mark.asyncio
    async def test_no_matching_payload(self):
        """Return None when no recognized payload param."""
        result = await rbac._derive_team_from_payload({"unrelated": "data"})
        assert result is None

    @pytest.mark.asyncio
    async def test_form_data_team_id(self):
        """Extract team_id from form data in request."""
        mock_form = AsyncMock(return_value={"team_id": "team-from-form"})
        mock_request = MagicMock(spec=Request)
        mock_request.headers = {"content-type": "application/x-www-form-urlencoded"}
        mock_request.form = mock_form

        result = await rbac._derive_team_from_payload({"request": mock_request})
        assert result == "team-from-form"

    @pytest.mark.asyncio
    async def test_form_data_no_team_id(self):
        """Return None when form data has no team_id."""
        mock_form = AsyncMock(return_value={})
        mock_request = MagicMock(spec=Request)
        mock_request.headers = {"content-type": "application/x-www-form-urlencoded"}
        mock_request.form = mock_form

        result = await rbac._derive_team_from_payload({"request": mock_request})
        assert result is None

    @pytest.mark.asyncio
    async def test_form_parse_exception(self):
        """Return None when form parsing fails."""
        mock_request = MagicMock(spec=Request)
        mock_request.headers = {"content-type": "multipart/form-data"}
        mock_request.form = AsyncMock(side_effect=Exception("parse error"))

        result = await rbac._derive_team_from_payload({"request": mock_request})
        assert result is None

    @pytest.mark.asyncio
    async def test_non_form_content_type(self):
        """Skip form parsing for non-form content types."""
        mock_request = MagicMock(spec=Request)
        mock_request.headers = {"content-type": "application/json"}

        result = await rbac._derive_team_from_payload({"request": mock_request})
        assert result is None

    @pytest.mark.asyncio
    async def test_pydantic_request_param_not_confused_with_fastapi_request(self):
        """Ensure a Pydantic model named 'request' is not treated as a FastAPI Request."""
        mock_pydantic_model = MagicMock()  # No spec=Request, simulates a Pydantic body param
        mock_pydantic_model.headers = None  # Pydantic models might have arbitrary attrs

        result = await rbac._derive_team_from_payload({"request": mock_pydantic_model})
        assert result is None


class TestIsMutatePermission:
    """Tests for _is_mutate_permission helper."""

    def test_dot_separated_create(self):
        assert rbac._is_mutate_permission("tools.create") is True

    def test_dot_separated_read(self):
        assert rbac._is_mutate_permission("tools.read") is False

    def test_colon_separated_create(self):
        assert rbac._is_mutate_permission("admin.sso_providers:create") is True

    def test_colon_separated_read(self):
        assert rbac._is_mutate_permission("admin.sso_providers:read") is False

    def test_single_word(self):
        assert rbac._is_mutate_permission("create") is False

    def test_dot_execute(self):
        assert rbac._is_mutate_permission("tools.execute") is True

    def test_dot_delete(self):
        assert rbac._is_mutate_permission("resources.delete") is True

    def test_dot_toggle(self):
        assert rbac._is_mutate_permission("tools.toggle") is True

    def test_colon_manage(self):
        assert rbac._is_mutate_permission("admin.teams:manage") is True

    def test_colon_invoke(self):
        assert rbac._is_mutate_permission("tools.a2a:invoke") is True


class TestMultiTeamSessionTokenDerivation:
    """Tests for multi-team session token team derivation in require_permission."""

    @pytest.mark.asyncio
    async def test_session_token_derive_from_resource(self, monkeypatch):
        """Session token derives team_id from resource via _derive_team_from_resource."""

        async def dummy_func(user=None, db=None):
            return "ok"

        mock_db = MagicMock()
        mock_user = {"email": "user@test.com", "db": mock_db, "token_use": "session"}
        mock_perm_service = AsyncMock()
        mock_perm_service.check_permission.return_value = True
        monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

        with patch("mcpgateway.middleware.rbac._derive_team_from_resource", return_value="team-derived"), patch("mcpgateway.plugins.framework.get_plugin_manager", return_value=None):
            decorated = rbac.require_permission("tools.read")(dummy_func)
            result = await decorated(user=mock_user, db=mock_db)

        assert result == "ok"
        assert mock_perm_service.check_permission.call_args.kwargs["team_id"] == "team-derived"

    @pytest.mark.asyncio
    async def test_session_token_derive_from_payload(self, monkeypatch):
        """Session token falls back to _derive_team_from_payload when resource returns None."""

        async def dummy_func(user=None, db=None, tool=None):
            return "ok"

        mock_db = MagicMock()
        payload = SimpleNamespace(team_id="team-payload")
        mock_user = {"email": "user@test.com", "db": mock_db, "token_use": "session"}
        mock_perm_service = AsyncMock()
        mock_perm_service.check_permission.return_value = True
        monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

        with patch("mcpgateway.middleware.rbac._derive_team_from_resource", return_value=None), patch("mcpgateway.plugins.framework.get_plugin_manager", return_value=None):
            decorated = rbac.require_permission("tools.create")(dummy_func)
            result = await decorated(user=mock_user, db=mock_db, tool=payload)

        assert result == "ok"
        assert mock_perm_service.check_permission.call_args.kwargs["team_id"] == "team-payload"

    @pytest.mark.asyncio
    async def test_session_token_read_check_any_team(self, monkeypatch):
        """Session token with no team context uses check_any_team for read ops."""

        async def dummy_func(user=None, db=None):
            return "ok"

        mock_db = MagicMock()
        mock_user = {"email": "user@test.com", "db": mock_db, "token_use": "session"}
        mock_perm_service = AsyncMock()
        mock_perm_service.check_permission.return_value = True
        monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

        with (
            patch("mcpgateway.middleware.rbac._derive_team_from_resource", return_value=None),
            patch("mcpgateway.middleware.rbac._derive_team_from_payload", new_callable=AsyncMock, return_value=None),
            patch("mcpgateway.plugins.framework.get_plugin_manager", return_value=None),
        ):
            decorated = rbac.require_permission("tools.read")(dummy_func)
            result = await decorated(user=mock_user, db=mock_db)

        assert result == "ok"
        assert mock_perm_service.check_permission.call_args.kwargs["check_any_team"] is True

    @pytest.mark.asyncio
    async def test_session_token_mutate_no_team_check_any_team(self, monkeypatch):
        """Session token with mutate permission and no team context uses check_any_team.

        This is the fix for #2883/#2891: mutate operations without team context should
        check permission across all teams (same as read ops), separating authorization
        from resource scoping.
        """

        async def dummy_func(user=None, db=None):
            return "ok"

        mock_db = MagicMock()
        mock_user = {"email": "user@test.com", "db": mock_db, "token_use": "session"}
        mock_perm_service = AsyncMock()
        mock_perm_service.check_permission.return_value = True
        monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

        with (
            patch("mcpgateway.middleware.rbac._derive_team_from_resource", return_value=None),
            patch("mcpgateway.middleware.rbac._derive_team_from_payload", new_callable=AsyncMock, return_value=None),
            patch("mcpgateway.plugins.framework.get_plugin_manager", return_value=None),
        ):
            decorated = rbac.require_permission("tools.create")(dummy_func)
            result = await decorated(user=mock_user, db=mock_db)

        assert result == "ok"
        assert mock_perm_service.check_permission.call_args.kwargs["check_any_team"] is True

    @pytest.mark.asyncio
    async def test_session_token_delete_no_team_check_any_team(self, monkeypatch):
        """Session token with delete permission and no team context uses check_any_team.

        Regression test for #2891: platform admin blocked on gateway delete because
        delete forms don't include team_id and public gateways have team_id=NULL.
        """

        async def dummy_func(user=None, db=None):
            return "ok"

        mock_db = MagicMock()
        mock_user = {"email": "admin@test.com", "db": mock_db, "token_use": "session"}
        mock_perm_service = AsyncMock()
        mock_perm_service.check_permission.return_value = True
        monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

        with (
            patch("mcpgateway.middleware.rbac._derive_team_from_resource", return_value=None),
            patch("mcpgateway.middleware.rbac._derive_team_from_payload", new_callable=AsyncMock, return_value=None),
            patch("mcpgateway.plugins.framework.get_plugin_manager", return_value=None),
        ):
            decorated = rbac.require_permission("gateways.delete")(dummy_func)
            result = await decorated(user=mock_user, db=mock_db)

        assert result == "ok"
        assert mock_perm_service.check_permission.call_args.kwargs["check_any_team"] is True

    @pytest.mark.asyncio
    async def test_session_token_mutate_with_derived_team_does_not_check_any_team(self, monkeypatch):
        """When team_id IS derived for a mutate op, check_any_team should be False."""

        async def dummy_func(user=None, db=None):
            return "ok"

        mock_db = MagicMock()
        mock_user = {"email": "user@test.com", "db": mock_db, "token_use": "session"}
        mock_perm_service = AsyncMock()
        mock_perm_service.check_permission.return_value = True
        monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

        with patch("mcpgateway.middleware.rbac._derive_team_from_resource", return_value="team-abc"), patch("mcpgateway.plugins.framework.get_plugin_manager", return_value=None):
            decorated = rbac.require_permission("gateways.create")(dummy_func)
            result = await decorated(user=mock_user, db=mock_db)

        assert result == "ok"
        assert mock_perm_service.check_permission.call_args.kwargs["team_id"] == "team-abc"
        assert mock_perm_service.check_permission.call_args.kwargs["check_any_team"] is False

    @pytest.mark.asyncio
    async def test_session_token_no_db_skips_derivation_and_uses_fresh_db(self, monkeypatch):
        """Session token with no DB available should skip derivation and use fresh DB session."""

        async def dummy_func(user=None):
            return "ok"

        mock_user = {"email": "user@test.com", "token_use": "session"}
        mock_perm_service = AsyncMock()
        mock_perm_service.check_permission.return_value = True
        monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

        @contextmanager
        def fake_fresh_db_session():
            yield MagicMock()

        monkeypatch.setattr(rbac, "fresh_db_session", fake_fresh_db_session)

        with patch("mcpgateway.plugins.framework.get_plugin_manager", return_value=None):
            decorated = rbac.require_permission("tools.read")(dummy_func)
            result = await decorated(user=mock_user)

        assert result == "ok"
        assert mock_perm_service.check_permission.call_args.kwargs["check_any_team"] is True


class TestMultiTeamSessionTokenDerivationAnyPermission:
    """Tests for multi-team session token team derivation in require_any_permission."""

    @pytest.mark.asyncio
    async def test_session_token_any_permission_check_any_team(self, monkeypatch):
        async def dummy_func(user=None, db=None):
            return "any-ok"

        mock_db = MagicMock()
        mock_user = {"email": "user@test.com", "db": mock_db, "token_use": "session"}
        mock_perm_service = AsyncMock()
        mock_perm_service.check_permission.return_value = True
        monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

        with (
            patch("mcpgateway.middleware.rbac._derive_team_from_resource", return_value=None),
            patch("mcpgateway.middleware.rbac._derive_team_from_payload", new_callable=AsyncMock, return_value=None),
            patch("mcpgateway.plugins.framework.get_plugin_manager", return_value=None),
        ):
            decorated = rbac.require_any_permission(["tools.read", "tools.execute"])(dummy_func)
            result = await decorated(user=mock_user, db=mock_db)

        assert result == "any-ok"
        assert mock_perm_service.check_permission.call_args.kwargs["check_any_team"] is True

    @pytest.mark.asyncio
    async def test_session_token_any_permission_no_db_session_skips_derivation(self, monkeypatch):
        """When db session is unavailable, derivation is skipped and fresh DB is used."""

        async def dummy_func(user=None):
            return "any-ok"

        mock_user = {"email": "user@test.com", "token_use": "session"}
        mock_perm_service = AsyncMock()
        mock_perm_service.check_permission.return_value = True
        monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

        @contextmanager
        def fake_fresh_db_session():
            yield MagicMock()

        monkeypatch.setattr(rbac, "fresh_db_session", fake_fresh_db_session)

        with patch("mcpgateway.plugins.framework.get_plugin_manager", return_value=None):
            decorated = rbac.require_any_permission(["tools.read", "tools.execute"])(dummy_func)
            result = await decorated(user=mock_user)

        assert result == "any-ok"
        assert mock_perm_service.check_permission.call_args.kwargs["check_any_team"] is True

    @pytest.mark.asyncio
    async def test_session_token_any_permission_with_derived_team_skips_payload(self, monkeypatch):
        """When team_id is derived, payload derivation and check_any_team logic are skipped."""

        async def dummy_func(user=None, db=None, tool_id=None):
            return "any-ok"

        mock_db = MagicMock()
        mock_user = {"email": "user@test.com", "db": mock_db, "token_use": "session"}
        mock_perm_service = AsyncMock()
        mock_perm_service.check_permission.return_value = True
        monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

        with (
            patch("mcpgateway.middleware.rbac._derive_team_from_resource", return_value="team-derived"),
            patch("mcpgateway.middleware.rbac._derive_team_from_payload", new_callable=AsyncMock, return_value=None),
            patch("mcpgateway.plugins.framework.get_plugin_manager", return_value=None),
        ):
            decorated = rbac.require_any_permission(["tools.execute"])(dummy_func)
            result = await decorated(user=mock_user, db=mock_db, tool_id="tool-1")

        assert result == "any-ok"
        assert mock_perm_service.check_permission.call_args.kwargs["team_id"] == "team-derived"
        assert mock_perm_service.check_permission.call_args.kwargs["check_any_team"] is False

    @pytest.mark.asyncio
    async def test_session_token_any_permission_all_mutating_no_team_check_any_team(self, monkeypatch):
        """All-mutating permissions with no team context should enable check_any_team.

        Fix for #2883/#2891: mutate operations without team context should check
        permission across all teams, same as read operations.
        """

        async def dummy_func(user=None, db=None):
            return "any-ok"

        mock_db = MagicMock()
        mock_user = {"email": "user@test.com", "db": mock_db, "token_use": "session"}
        mock_perm_service = AsyncMock()
        mock_perm_service.check_permission.return_value = True
        monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

        with (
            patch("mcpgateway.middleware.rbac._derive_team_from_resource", return_value=None),
            patch("mcpgateway.middleware.rbac._derive_team_from_payload", new_callable=AsyncMock, return_value=None),
            patch("mcpgateway.plugins.framework.get_plugin_manager", return_value=None),
        ):
            decorated = rbac.require_any_permission(["tools.execute", "tools.create"])(dummy_func)
            result = await decorated(user=mock_user, db=mock_db)

        assert result == "any-ok"
        assert mock_perm_service.check_permission.call_args.kwargs["check_any_team"] is True


class TestNonSessionTokenTeamDerivation:
    """Tests for non-session token behavior (e.g. API tokens, CLI tokens).

    Non-session tokens skip the derivation block entirely (gated by token_use == "session").
    This is safe because:
    - Single-team API tokens get team_id set by auth.py before RBAC runs
    - Zero-team API tokens (teams=[]) have no team-scoped roles to find
    - CLI tokens are typically admin bypass (teams=None, is_admin=True)
    """

    @pytest.mark.asyncio
    async def test_api_token_with_team_id_uses_it(self, monkeypatch):
        """API token with team_id in user_context uses it directly (set by auth.py)."""

        async def dummy_func(user=None, db=None):
            return "ok"

        mock_db = MagicMock()
        mock_user = {"email": "user@test.com", "db": mock_db, "token_use": "api", "team_id": "team-from-auth"}
        mock_perm_service = AsyncMock()
        mock_perm_service.check_permission.return_value = True
        monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

        with patch("mcpgateway.plugins.framework.get_plugin_manager", return_value=None):
            decorated = rbac.require_permission("gateways.create")(dummy_func)
            result = await decorated(user=mock_user, db=mock_db)

        assert result == "ok"
        assert mock_perm_service.check_permission.call_args.kwargs["team_id"] == "team-from-auth"
        assert mock_perm_service.check_permission.call_args.kwargs["check_any_team"] is False

    @pytest.mark.asyncio
    async def test_api_token_no_team_id_skips_derivation(self, monkeypatch):
        """API token with no team_id skips derivation block (check_any_team stays False).

        This documents existing behavior: non-session tokens rely on auth.py to set
        team_id. Multi-team non-session tokens don't exist in practice.
        """

        async def dummy_func(user=None, db=None):
            return "ok"

        mock_db = MagicMock()
        mock_user = {"email": "user@test.com", "db": mock_db, "token_use": "api"}
        mock_perm_service = AsyncMock()
        mock_perm_service.check_permission.return_value = True
        monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

        with patch("mcpgateway.plugins.framework.get_plugin_manager", return_value=None):
            decorated = rbac.require_permission("gateways.create")(dummy_func)
            result = await decorated(user=mock_user, db=mock_db)

        assert result == "ok"
        assert mock_perm_service.check_permission.call_args.kwargs["team_id"] is None
        assert mock_perm_service.check_permission.call_args.kwargs["check_any_team"] is False

    @pytest.mark.asyncio
    async def test_cli_token_no_token_use_skips_derivation(self, monkeypatch):
        """CLI-generated token (no token_use claim) skips derivation block."""

        async def dummy_func(user=None, db=None):
            return "ok"

        mock_db = MagicMock()
        mock_user = {"email": "admin@test.com", "db": mock_db}
        mock_perm_service = AsyncMock()
        mock_perm_service.check_permission.return_value = True
        monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

        with patch("mcpgateway.plugins.framework.get_plugin_manager", return_value=None):
            decorated = rbac.require_permission("gateways.delete")(dummy_func)
            result = await decorated(user=mock_user, db=mock_db)

        assert result == "ok"
        assert mock_perm_service.check_permission.call_args.kwargs["team_id"] is None
        assert mock_perm_service.check_permission.call_args.kwargs["check_any_team"] is False

    @pytest.mark.asyncio
    async def test_api_token_with_team_id_for_any_permission(self, monkeypatch):
        """API token with team_id uses it in require_any_permission."""

        async def dummy_func(user=None, db=None):
            return "any-ok"

        mock_db = MagicMock()
        mock_user = {"email": "user@test.com", "db": mock_db, "token_use": "api", "team_id": "team-api"}
        mock_perm_service = AsyncMock()
        mock_perm_service.check_permission.return_value = True
        monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

        with patch("mcpgateway.plugins.framework.get_plugin_manager", return_value=None):
            decorated = rbac.require_any_permission(["tools.create", "tools.execute"])(dummy_func)
            result = await decorated(user=mock_user, db=mock_db)

        assert result == "any-ok"
        assert mock_perm_service.check_permission.call_args.kwargs["team_id"] == "team-api"
        assert mock_perm_service.check_permission.call_args.kwargs["check_any_team"] is False


class TestMutatePermissionDenial:
    """Tests that permission denial still works correctly after the check_any_team fix."""

    @pytest.mark.asyncio
    async def test_session_mutate_denied_raises_403(self, monkeypatch):
        """Session token mutate with check_any_team=True still gets 403 when permission is denied."""

        async def dummy_func(user=None, db=None):
            return "ok"

        mock_db = MagicMock()
        mock_user = {"email": "viewer@test.com", "db": mock_db, "token_use": "session"}
        mock_perm_service = AsyncMock()
        mock_perm_service.check_permission.return_value = False
        monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

        with (
            patch("mcpgateway.middleware.rbac._derive_team_from_resource", return_value=None),
            patch("mcpgateway.middleware.rbac._derive_team_from_payload", new_callable=AsyncMock, return_value=None),
            patch("mcpgateway.plugins.framework.get_plugin_manager", return_value=None),
        ):
            decorated = rbac.require_permission("gateways.create")(dummy_func)
            with pytest.raises(HTTPException) as exc:
                await decorated(user=mock_user, db=mock_db)

        assert exc.value.status_code == 403
        # Verify check_any_team was True (the fix is in effect) but permission was still denied
        assert mock_perm_service.check_permission.call_args.kwargs["check_any_team"] is True

    @pytest.mark.asyncio
    async def test_session_delete_denied_raises_403(self, monkeypatch):
        """Session token delete with check_any_team=True still gets 403 when permission is denied."""

        async def dummy_func(user=None, db=None):
            return "ok"

        mock_db = MagicMock()
        mock_user = {"email": "viewer@test.com", "db": mock_db, "token_use": "session"}
        mock_perm_service = AsyncMock()
        mock_perm_service.check_permission.return_value = False
        monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

        with (
            patch("mcpgateway.middleware.rbac._derive_team_from_resource", return_value=None),
            patch("mcpgateway.middleware.rbac._derive_team_from_payload", new_callable=AsyncMock, return_value=None),
            patch("mcpgateway.plugins.framework.get_plugin_manager", return_value=None),
        ):
            decorated = rbac.require_permission("gateways.delete")(dummy_func)
            with pytest.raises(HTTPException) as exc:
                await decorated(user=mock_user, db=mock_db)

        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_any_permission_all_mutate_denied_raises_403(self, monkeypatch):
        """require_any_permission with all-mutate perms, check_any_team=True, still denies correctly."""

        async def dummy_func(user=None, db=None):
            return "ok"

        mock_db = MagicMock()
        mock_user = {"email": "viewer@test.com", "db": mock_db, "token_use": "session"}
        mock_perm_service = AsyncMock()
        mock_perm_service.check_permission.return_value = False
        monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

        with (
            patch("mcpgateway.middleware.rbac._derive_team_from_resource", return_value=None),
            patch("mcpgateway.middleware.rbac._derive_team_from_payload", new_callable=AsyncMock, return_value=None),
            patch("mcpgateway.plugins.framework.get_plugin_manager", return_value=None),
        ):
            decorated = rbac.require_any_permission(["tools.create", "tools.execute"])(dummy_func)
            with pytest.raises(HTTPException) as exc:
                await decorated(user=mock_user, db=mock_db)

        assert exc.value.status_code == 403


class TestMutateCheckAnyTeamPermissionVariants:
    """Tests that various mutate permission types all get check_any_team=True."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "permission",
        [
            "gateways.create",
            "gateways.delete",
            "servers.create",
            "servers.delete",
            "tools.execute",
            "tools.toggle",
            "resources.delete",
            "admin.teams:manage",
        ],
    )
    async def test_all_mutate_permissions_use_check_any_team(self, monkeypatch, permission):
        """All mutate permission types use check_any_team when no team context."""

        async def dummy_func(user=None, db=None):
            return "ok"

        mock_db = MagicMock()
        mock_user = {"email": "user@test.com", "db": mock_db, "token_use": "session"}
        mock_perm_service = AsyncMock()
        mock_perm_service.check_permission.return_value = True
        monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

        with (
            patch("mcpgateway.middleware.rbac._derive_team_from_resource", return_value=None),
            patch("mcpgateway.middleware.rbac._derive_team_from_payload", new_callable=AsyncMock, return_value=None),
            patch("mcpgateway.plugins.framework.get_plugin_manager", return_value=None),
        ):
            decorated = rbac.require_permission(permission)(dummy_func)
            await decorated(user=mock_user, db=mock_db)

        assert mock_perm_service.check_permission.call_args.kwargs["check_any_team"] is True

    @pytest.mark.asyncio
    async def test_any_permission_mixed_read_mutate_no_team(self, monkeypatch):
        """require_any_permission with mixed read+mutate, no team → check_any_team=True."""

        async def dummy_func(user=None, db=None):
            return "ok"

        mock_db = MagicMock()
        mock_user = {"email": "user@test.com", "db": mock_db, "token_use": "session"}
        mock_perm_service = AsyncMock()
        mock_perm_service.check_permission.return_value = True
        monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

        with (
            patch("mcpgateway.middleware.rbac._derive_team_from_resource", return_value=None),
            patch("mcpgateway.middleware.rbac._derive_team_from_payload", new_callable=AsyncMock, return_value=None),
            patch("mcpgateway.plugins.framework.get_plugin_manager", return_value=None),
        ):
            decorated = rbac.require_any_permission(["tools.read", "tools.create"])(dummy_func)
            await decorated(user=mock_user, db=mock_db)

        assert mock_perm_service.check_permission.call_args.kwargs["check_any_team"] is True

    @pytest.mark.asyncio
    async def test_any_permission_mutate_with_payload_derived_team(self, monkeypatch):
        """require_any_permission with mutate + team derived from payload → scoped check."""

        async def dummy_func(user=None, db=None, tool=None):
            return "ok"

        mock_db = MagicMock()
        payload = SimpleNamespace(team_id="team-from-payload")
        mock_user = {"email": "user@test.com", "db": mock_db, "token_use": "session"}
        mock_perm_service = AsyncMock()
        mock_perm_service.check_permission.return_value = True
        monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

        with patch("mcpgateway.middleware.rbac._derive_team_from_resource", return_value=None), patch("mcpgateway.plugins.framework.get_plugin_manager", return_value=None):
            decorated = rbac.require_any_permission(["tools.create", "tools.execute"])(dummy_func)
            await decorated(user=mock_user, db=mock_db, tool=payload)

        assert mock_perm_service.check_permission.call_args.kwargs["team_id"] == "team-from-payload"
        assert mock_perm_service.check_permission.call_args.kwargs["check_any_team"] is False


def test_get_resource_param_to_model_builds_mapping():
    """_get_resource_param_to_model should import models and build the mapping."""
    rbac._get_resource_param_to_model.cache_clear()
    mapping = rbac._get_resource_param_to_model()
    assert mapping["tool_id"].__name__ == "Tool"
    assert mapping["server_id"].__name__ == "Server"
