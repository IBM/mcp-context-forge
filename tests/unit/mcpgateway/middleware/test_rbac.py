# -*- coding: utf-8 -*-
import pytest
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException, Request, status
from mcpgateway.middleware import rbac


@pytest.mark.asyncio
async def test_get_permission_service_uses_fresh_session():
    """Test that get_permission_service creates a service with a fresh database session."""
    mock_session = MagicMock()
    mock_perm_service = MagicMock()

    @contextmanager
    def mock_fresh_db_session():
        yield mock_session

    with patch("mcpgateway.middleware.rbac.fresh_db_session", mock_fresh_db_session):
        with patch("mcpgateway.middleware.rbac.PermissionService", return_value=mock_perm_service) as mock_perm:
            result = await rbac.get_permission_service()
            assert result == mock_perm_service
            mock_perm.assert_called_once_with(mock_session)


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


# ============================================================================
# Tests for RBAC with fresh_db_session (Session Isolation)
# ============================================================================


class TestRBACFreshSessions:
    """Test RBAC permission decorators use fresh database sessions correctly.

    These tests verify that:
    1. Each RBAC check uses a fresh, isolated database session
    2. Sessions are properly committed on success
    3. Sessions are properly rolled back on exception
    4. Sessions are properly closed after use
    5. Multiple concurrent RBAC checks have isolated sessions
    """

    @pytest.mark.asyncio
    async def test_require_permission_uses_fresh_session(self, monkeypatch):
        """Test that require_permission creates a fresh database session for each call."""
        import importlib

        async def dummy_func(user=None):
            return "ok"

        mock_user = {"email": "user@example.com"}
        mock_perm_service = AsyncMock()
        mock_perm_service.check_permission.return_value = True

        # Track session creation and closure
        sessions_created = []
        sessions_closed = []

        class MockSession:
            def __init__(self):
                self.id = len(sessions_created)
                sessions_created.append(self)
                self._committed = False
                self._rolled_back = False

            def commit(self):
                self._committed = True

            def rollback(self):
                self._rolled_back = True

            def invalidate(self):
                pass

            def close(self):
                sessions_closed.append(self)

        @contextmanager
        def mock_fresh_db_session():
            session = MockSession()
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        monkeypatch.setattr("mcpgateway.middleware.rbac.fresh_db_session", mock_fresh_db_session)
        monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

        # Patch plugin manager to None to skip plugin hooks
        plugin_framework = importlib.import_module("mcpgateway.plugins.framework")
        original_get_pm = plugin_framework.get_plugin_manager
        try:
            plugin_framework.get_plugin_manager = lambda: None

            decorated = rbac.require_permission("tools.read")(dummy_func)
            result = await decorated(user=mock_user)

            assert result == "ok"
            assert len(sessions_created) == 1, "Should create exactly one session"
            assert len(sessions_closed) == 1, "Should close the session"
            assert sessions_created[0]._committed, "Session should be committed on success"
        finally:
            plugin_framework.get_plugin_manager = original_get_pm

    @pytest.mark.asyncio
    async def test_require_admin_permission_uses_fresh_session(self, monkeypatch):
        """Test that require_admin_permission creates a fresh database session."""

        async def dummy_func(user=None):
            return "admin-ok"

        mock_user = {"email": "admin@example.com"}
        mock_perm_service = AsyncMock()
        mock_perm_service.check_admin_permission.return_value = True

        # Track session lifecycle
        session_lifecycle = {"created": False, "committed": False, "closed": False}

        class MockSession:
            def __init__(self):
                session_lifecycle["created"] = True

            def commit(self):
                session_lifecycle["committed"] = True

            def rollback(self):
                pass

            def invalidate(self):
                pass

            def close(self):
                session_lifecycle["closed"] = True

        @contextmanager
        def mock_fresh_db_session():
            session = MockSession()
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        monkeypatch.setattr("mcpgateway.middleware.rbac.fresh_db_session", mock_fresh_db_session)
        monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

        decorated = rbac.require_admin_permission()(dummy_func)
        result = await decorated(user=mock_user)

        assert result == "admin-ok"
        assert session_lifecycle["created"], "Fresh session should be created"
        assert session_lifecycle["committed"], "Session should be committed"
        assert session_lifecycle["closed"], "Session should be closed"

    @pytest.mark.asyncio
    async def test_require_any_permission_uses_fresh_session(self, monkeypatch):
        """Test that require_any_permission creates a fresh database session."""
        import importlib

        async def dummy_func(user=None):
            return "any-ok"

        mock_user = {"email": "user@example.com"}
        mock_perm_service = AsyncMock()
        # First permission check fails, second succeeds
        mock_perm_service.check_permission.side_effect = [False, True]

        session_count = {"created": 0, "closed": 0}

        class MockSession:
            def __init__(self):
                session_count["created"] += 1

            def commit(self):
                pass

            def rollback(self):
                pass

            def invalidate(self):
                pass

            def close(self):
                session_count["closed"] += 1

        @contextmanager
        def mock_fresh_db_session():
            session = MockSession()
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        monkeypatch.setattr("mcpgateway.middleware.rbac.fresh_db_session", mock_fresh_db_session)
        monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

        # Patch plugin manager to None
        plugin_framework = importlib.import_module("mcpgateway.plugins.framework")
        original_get_pm = plugin_framework.get_plugin_manager
        try:
            plugin_framework.get_plugin_manager = lambda: None

            decorated = rbac.require_any_permission(["tools.read", "tools.execute"])(dummy_func)
            result = await decorated(user=mock_user)

            assert result == "any-ok"
            # Should create one session for the require_any_permission check
            assert session_count["created"] == 1, "Should use one fresh session"
            assert session_count["closed"] == 1, "Session should be closed"
        finally:
            plugin_framework.get_plugin_manager = original_get_pm

    @pytest.mark.asyncio
    async def test_fresh_session_rollback_on_permission_denied(self, monkeypatch):
        """Test that session is properly handled when permission is denied."""
        import importlib

        async def dummy_func(user=None):
            return "ok"

        mock_user = {"email": "user@example.com"}
        mock_perm_service = AsyncMock()
        mock_perm_service.check_permission.return_value = False  # Permission denied

        session_state = {"committed": False, "closed": False}

        class MockSession:
            def commit(self):
                session_state["committed"] = True

            def rollback(self):
                pass

            def invalidate(self):
                pass

            def close(self):
                session_state["closed"] = True

        @contextmanager
        def mock_fresh_db_session():
            session = MockSession()
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        monkeypatch.setattr("mcpgateway.middleware.rbac.fresh_db_session", mock_fresh_db_session)
        monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

        # Patch plugin manager to None
        plugin_framework = importlib.import_module("mcpgateway.plugins.framework")
        original_get_pm = plugin_framework.get_plugin_manager
        try:
            plugin_framework.get_plugin_manager = lambda: None

            decorated = rbac.require_permission("tools.read")(dummy_func)

            with pytest.raises(HTTPException) as exc_info:
                await decorated(user=mock_user)

            assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
            # Session should still be committed (read operations are complete)
            # and definitely closed
            assert session_state["closed"], "Session must be closed even on permission denied"
        finally:
            plugin_framework.get_plugin_manager = original_get_pm

    @pytest.mark.asyncio
    async def test_permission_checker_uses_fresh_session_for_each_check(self, monkeypatch):
        """Test that PermissionChecker creates fresh sessions for each permission check."""
        mock_perm_service = AsyncMock()
        mock_perm_service.check_permission.return_value = True
        mock_perm_service.check_admin_permission.return_value = True

        session_ids = []

        class MockSession:
            def __init__(self):
                self.id = len(session_ids)
                session_ids.append(self.id)

            def commit(self):
                pass

            def rollback(self):
                pass

            def invalidate(self):
                pass

            def close(self):
                pass

        @contextmanager
        def mock_fresh_db_session():
            session = MockSession()
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        monkeypatch.setattr("mcpgateway.middleware.rbac.fresh_db_session", mock_fresh_db_session)
        monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

        user_context = {"email": "user@example.com", "ip_address": "127.0.0.1", "user_agent": "test"}
        checker = rbac.PermissionChecker(user_context)

        # Each method should use a fresh session
        await checker.has_permission("tools.read")
        await checker.has_admin_permission()
        await checker.has_any_permission(["tools.read", "tools.execute"])

        # has_any_permission calls has_permission for each permission
        # So we expect: 1 (has_permission) + 1 (has_admin_permission) + 1 (first perm in has_any) = 3 minimum
        # The exact count depends on whether has_any_permission short-circuits
        assert len(session_ids) >= 3, f"Expected at least 3 fresh sessions, got {len(session_ids)}"
        # All session IDs should be unique (fresh sessions)
        assert len(session_ids) == len(set(session_ids)), "All sessions should be unique"

    @pytest.mark.asyncio
    async def test_multiple_concurrent_rbac_checks_isolated_sessions(self, monkeypatch):
        """Test that concurrent RBAC checks use isolated sessions."""
        import asyncio
        import importlib

        async def dummy_func(user=None, delay=0):
            if delay:
                await asyncio.sleep(delay)
            return f"ok-{user['email']}"

        mock_perm_service = AsyncMock()
        mock_perm_service.check_permission.return_value = True

        active_sessions = []
        session_order = []

        class MockSession:
            def __init__(self):
                self.id = len(session_order)
                session_order.append(("created", self.id))
                active_sessions.append(self.id)

            def commit(self):
                session_order.append(("committed", self.id))

            def rollback(self):
                pass

            def invalidate(self):
                pass

            def close(self):
                session_order.append(("closed", self.id))
                if self.id in active_sessions:
                    active_sessions.remove(self.id)

        @contextmanager
        def mock_fresh_db_session():
            session = MockSession()
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        monkeypatch.setattr("mcpgateway.middleware.rbac.fresh_db_session", mock_fresh_db_session)
        monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

        # Patch plugin manager to None
        plugin_framework = importlib.import_module("mcpgateway.plugins.framework")
        original_get_pm = plugin_framework.get_plugin_manager
        try:
            plugin_framework.get_plugin_manager = lambda: None

            decorated = rbac.require_permission("tools.read")(dummy_func)

            users = [
                {"email": "user1@example.com"},
                {"email": "user2@example.com"},
                {"email": "user3@example.com"},
            ]

            # Run concurrent permission checks
            results = await asyncio.gather(*[decorated(user=user) for user in users])

            assert len(results) == 3
            # Each user should have gotten their own session
            created_count = sum(1 for op, _ in session_order if op == "created")
            closed_count = sum(1 for op, _ in session_order if op == "closed")

            assert created_count == 3, f"Expected 3 sessions created, got {created_count}"
            assert closed_count == 3, f"Expected 3 sessions closed, got {closed_count}"
            assert len(active_sessions) == 0, "All sessions should be closed"
        finally:
            plugin_framework.get_plugin_manager = original_get_pm

    @pytest.mark.asyncio
    async def test_fresh_session_exception_handling(self, monkeypatch):
        """Test that fresh_db_session properly handles exceptions during permission check."""
        import importlib

        async def dummy_func(user=None):
            return "ok"

        mock_user = {"email": "user@example.com"}
        mock_perm_service = AsyncMock()
        mock_perm_service.check_permission.side_effect = Exception("DB Error")

        session_state = {"rolled_back": False, "closed": False}

        class MockSession:
            def commit(self):
                pass

            def rollback(self):
                session_state["rolled_back"] = True

            def invalidate(self):
                pass

            def close(self):
                session_state["closed"] = True

        @contextmanager
        def mock_fresh_db_session():
            session = MockSession()
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        monkeypatch.setattr("mcpgateway.middleware.rbac.fresh_db_session", mock_fresh_db_session)
        monkeypatch.setattr(rbac, "PermissionService", lambda db: mock_perm_service)

        # Patch plugin manager to None
        plugin_framework = importlib.import_module("mcpgateway.plugins.framework")
        original_get_pm = plugin_framework.get_plugin_manager
        try:
            plugin_framework.get_plugin_manager = lambda: None

            decorated = rbac.require_permission("tools.read")(dummy_func)

            # The exception from permission_service should propagate
            # but session should still be properly cleaned up
            with pytest.raises(Exception, match="DB Error"):
                await decorated(user=mock_user)

            assert session_state["rolled_back"], "Session should be rolled back on exception"
            assert session_state["closed"], "Session should be closed on exception"
        finally:
            plugin_framework.get_plugin_manager = original_get_pm


class TestRBACSessionIsolation:
    """Test that RBAC operations maintain proper session isolation.

    These tests verify that database changes in one session don't leak
    into another, ensuring proper transaction boundaries.
    """

    @pytest.mark.asyncio
    async def test_permission_check_does_not_leak_db_state(self, monkeypatch):
        """Test that permission checks don't leave stale database state."""
        import importlib

        async def dummy_func(user=None):
            return "ok"

        mock_user = {"email": "user@example.com"}

        # Track that each call gets a fresh PermissionService instance
        permission_service_instances = []

        class MockPermissionService:
            def __init__(self, db):
                self.db = db
                self.instance_id = len(permission_service_instances)
                permission_service_instances.append(self)

            async def check_permission(self, **kwargs):
                return True

        @contextmanager
        def mock_fresh_db_session():
            session = MagicMock()
            session.id = len(permission_service_instances)
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        monkeypatch.setattr("mcpgateway.middleware.rbac.fresh_db_session", mock_fresh_db_session)
        monkeypatch.setattr(rbac, "PermissionService", MockPermissionService)

        # Patch plugin manager to None
        plugin_framework = importlib.import_module("mcpgateway.plugins.framework")
        original_get_pm = plugin_framework.get_plugin_manager
        try:
            plugin_framework.get_plugin_manager = lambda: None

            decorated = rbac.require_permission("tools.read")(dummy_func)

            # Call multiple times
            await decorated(user=mock_user)
            await decorated(user=mock_user)
            await decorated(user=mock_user)

            # Each call should create a new PermissionService with a fresh session
            assert len(permission_service_instances) == 3
            # Each instance should have a different db session
            db_ids = [ps.db.id for ps in permission_service_instances]
            assert len(set(db_ids)) == 3, "Each PermissionService should have unique db session"
        finally:
            plugin_framework.get_plugin_manager = original_get_pm

    @pytest.mark.asyncio
    async def test_get_permission_service_uses_fresh_session(self):
        """Test that get_permission_service creates service with fresh session."""
        with patch("mcpgateway.middleware.rbac.fresh_db_session") as mock_fresh:
            mock_session = MagicMock()
            mock_fresh.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_fresh.return_value.__exit__ = MagicMock(return_value=False)

            with patch("mcpgateway.middleware.rbac.PermissionService") as mock_ps:
                mock_ps.return_value = "test_service"

                result = await rbac.get_permission_service()

                assert result == "test_service"
                mock_fresh.assert_called_once()
                mock_ps.assert_called_once_with(mock_session)
