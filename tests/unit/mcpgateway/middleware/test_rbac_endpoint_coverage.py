# -*- coding: utf-8 -*-
# Copyright (c) 2025 ContextForge Contributors.
# SPDX-License-Identifier: Apache-2.0

"""RBAC Endpoint Coverage Tests.

Verifies that RBAC-protected endpoints enforce their declared permissions
at the decorator level. Uses the real require_permission decorator with
MockPermissionService.check_permission.return_value = False to verify 403.
"""

# Future
from __future__ import annotations

# Standard
from unittest.mock import AsyncMock, MagicMock

# Third-Party
from fastapi import HTTPException
import pytest

# ---------------------------------------------------------------------------
# Helper: invoke a decorated function and assert 403
# ---------------------------------------------------------------------------


def _make_user_ctx(email="test@test.local", is_admin=False, db=None):
    """Create a user context dict for testing."""
    return {
        "email": email,
        "full_name": "Test User",
        "is_admin": is_admin,
        "ip_address": "127.0.0.1",
        "user_agent": "test",
        "auth_method": "jwt",
        "db": db or MagicMock(),
        "token_use": "api",
    }


async def _assert_permission_denied(func, user_ctx=None, **extra_kwargs):
    """Assert that calling a decorated function raises 403 HTTPException.

    The conftest autouse fixture sets MockPermissionService.check_permission = False,
    so any decorated function should raise 403.
    """
    if user_ctx is None:
        user_ctx = _make_user_ctx()
    kwargs = {"user": user_ctx, "db": user_ctx.get("db", MagicMock())}
    kwargs.update(extra_kwargs)
    with pytest.raises(HTTPException) as exc_info:
        await func(**kwargs)
    assert exc_info.value.status_code == 403


async def _assert_permission_granted(func, user_ctx=None, mock_perm_service=None, **extra_kwargs):
    """Assert that calling a decorated function does NOT raise 403.

    Temporarily sets MockPermissionService.check_permission to True.
    """
    if user_ctx is None:
        user_ctx = _make_user_ctx()
    kwargs = {"user": user_ctx, "db": user_ctx.get("db", MagicMock())}
    kwargs.update(extra_kwargs)

    # Save and set
    if mock_perm_service:
        mock_perm_service.check_permission = AsyncMock(return_value=True)
        mock_perm_service.check_admin_permission = AsyncMock(return_value=True)

    try:
        await func(**kwargs)
    except HTTPException as e:
        if e.status_code == 403:
            pytest.fail(f"Expected permission granted but got 403: {e.detail}")
        # Other HTTP errors (404, 422, etc.) are fine — we only care about 403
    except Exception:
        # Non-HTTP errors are fine — we only care that 403 is NOT raised
        pass


# ---------------------------------------------------------------------------
# D6.1: Main endpoint permissions (main.py)
# ---------------------------------------------------------------------------


class TestMainEndpointPermissions:
    """Test that main.py endpoints enforce their declared permissions."""

    @pytest.mark.parametrize(
        "permission",
        [
            "servers.read",
            "servers.create",
            "servers.update",
            "servers.delete",
            "servers.use",
            "tools.read",
            "tools.create",
            "tools.update",
            "tools.delete",
            "tools.invoke",
            "resources.read",
            "resources.create",
            "resources.update",
            "resources.delete",
            "prompts.read",
            "prompts.create",
            "prompts.update",
            "prompts.delete",
            "gateways.read",
            "gateways.create",
            "gateways.update",
            "gateways.delete",
            "a2a.read",
            "a2a.create",
            "a2a.update",
            "a2a.delete",
            "a2a.invoke",
            "admin.system_config",
            "admin.metrics",
            "admin.export",
            "admin.import",
            "tags.read",
        ],
    )
    def test_permission_used_in_main(self, permission):
        """Verify the permission string is actually used in a @require_permission decorator in main.py."""
        # Standard
        import inspect

        # First-Party
        import mcpgateway.main as main_mod

        source = inspect.getsource(main_mod)
        assert (
            f'@require_permission("{permission}"' in source or f"@require_permission('{permission}'" in source
        ), f"Permission '{permission}' not found in any @require_permission decorator in main.py"

    @pytest.mark.asyncio
    async def test_require_permission_decorator_enforces_deny(self, mock_permission_service):
        """Test that a function decorated with require_permission actually denies access."""
        # First-Party
        from mcpgateway.middleware.rbac import require_permission

        mock_permission_service.check_permission = AsyncMock(return_value=False)

        @require_permission("tools.read")
        async def dummy_endpoint(user=None, db=None):
            return {"status": "ok"}

        await _assert_permission_denied(dummy_endpoint)

    @pytest.mark.asyncio
    async def test_require_permission_decorator_enforces_grant(self, mock_permission_service):
        """Test that a function decorated with require_permission grants access when permitted."""
        # First-Party
        from mcpgateway.middleware.rbac import require_permission

        mock_permission_service.check_permission = AsyncMock(return_value=True)

        @require_permission("tools.read")
        async def dummy_endpoint(user=None, db=None):
            return {"status": "ok"}

        await _assert_permission_granted(dummy_endpoint, mock_perm_service=mock_permission_service)


# ---------------------------------------------------------------------------
# D6.2: Router endpoint permissions
# ---------------------------------------------------------------------------


class TestRouterEndpointPermissions:
    """Test that router endpoints declare the correct permissions."""

    @pytest.mark.parametrize(
        "router_module,permission",
        [
            ("mcpgateway.routers.teams", "teams.create"),
            ("mcpgateway.routers.teams", "teams.read"),
            ("mcpgateway.routers.teams", "teams.update"),
            ("mcpgateway.routers.teams", "teams.delete"),
            ("mcpgateway.routers.teams", "teams.manage_members"),
            ("mcpgateway.routers.tokens", "tokens.create"),
            ("mcpgateway.routers.tokens", "tokens.read"),
            ("mcpgateway.routers.tokens", "tokens.update"),
            ("mcpgateway.routers.tokens", "tokens.revoke"),
            ("mcpgateway.routers.email_auth", "admin.user_management"),
            ("mcpgateway.routers.sso", "admin.sso_providers:create"),
            ("mcpgateway.routers.sso", "admin.sso_providers:read"),
            ("mcpgateway.routers.sso", "admin.sso_providers:update"),
            ("mcpgateway.routers.sso", "admin.sso_providers:delete"),
            ("mcpgateway.routers.sso", "admin.user_management"),
            ("mcpgateway.routers.llm_config_router", "admin.system_config"),
            ("mcpgateway.routers.llm_admin_router", "admin.system_config"),
            ("mcpgateway.routers.observability", "admin.system_config"),
            ("mcpgateway.routers.log_search", "logs:read"),
            ("mcpgateway.routers.log_search", "security:read"),
            ("mcpgateway.routers.log_search", "audit:read"),
            ("mcpgateway.routers.log_search", "metrics:read"),
            ("mcpgateway.routers.toolops_router", "admin.system_config"),
            ("mcpgateway.routers.cancellation_router", "admin.system_config"),
        ],
    )
    def test_router_uses_permission(self, router_module, permission):
        """Verify the permission is used in a @require_permission decorator in the router."""
        # Standard
        import importlib
        import inspect

        mod = importlib.import_module(router_module)
        source = inspect.getsource(mod)
        assert f'@require_permission("{permission}"' in source or f"@require_permission('{permission}'" in source, f"Permission '{permission}' not found in @require_permission in {router_module}"

    def test_rbac_router_uses_require_admin_permission(self):
        """Verify RBAC router uses require_admin_permission for role CRUD."""
        # Standard
        import inspect

        # First-Party
        import mcpgateway.routers.rbac as rbac_router

        source = inspect.getsource(rbac_router)
        assert "@require_admin_permission()" in source, "RBAC router should use @require_admin_permission() for role CRUD"

    def test_rbac_router_uses_admin_user_management(self):
        """Verify RBAC router uses admin.user_management for user role assignment."""
        # Standard
        import inspect

        # First-Party
        import mcpgateway.routers.rbac as rbac_router

        source = inspect.getsource(rbac_router)
        assert '"admin.user_management"' in source, "RBAC router should use admin.user_management permission"

    def test_rbac_router_uses_security_audit(self):
        """Verify RBAC router uses admin.security_audit for audit log access."""
        # Standard
        import inspect

        # First-Party
        import mcpgateway.routers.rbac as rbac_router

        source = inspect.getsource(rbac_router)
        assert '"admin.security_audit"' in source, "RBAC router should use admin.security_audit permission"


# ---------------------------------------------------------------------------
# D6.3: Decorator deny behavior tests
# ---------------------------------------------------------------------------


class TestDecoratorDenyBehavior:
    """Test that each decorator type properly denies access."""

    @pytest.mark.asyncio
    async def test_require_permission_denies_without_user(self):
        """require_permission should raise 401 when no user context provided."""
        # First-Party
        from mcpgateway.middleware.rbac import require_permission

        @require_permission("tools.read")
        async def endpoint():
            return "ok"

        with pytest.raises(HTTPException) as exc_info:
            await endpoint()
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_require_permission_denies_with_invalid_user(self):
        """require_permission should raise 401 when user context is invalid (no email)."""
        # First-Party
        from mcpgateway.middleware.rbac import require_permission

        @require_permission("tools.read")
        async def endpoint(user=None):
            return "ok"

        with pytest.raises(HTTPException) as exc_info:
            await endpoint(user={"name": "no-email"})
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_require_admin_permission_denies_without_user(self):
        """require_admin_permission should raise 401 when no user context."""
        # First-Party
        from mcpgateway.middleware.rbac import require_admin_permission

        @require_admin_permission()
        async def endpoint():
            return "ok"

        with pytest.raises(HTTPException) as exc_info:
            await endpoint()
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_require_admin_permission_denies_non_admin(self, mock_permission_service):
        """require_admin_permission should raise 403 for non-admin user."""
        # First-Party
        from mcpgateway.middleware.rbac import require_admin_permission

        mock_permission_service.check_admin_permission = AsyncMock(return_value=False)

        @require_admin_permission()
        async def endpoint(user=None, db=None):
            return "ok"

        with pytest.raises(HTTPException) as exc_info:
            await endpoint(user=_make_user_ctx(), db=MagicMock())
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_require_any_permission_denies_without_user(self):
        """require_any_permission should raise 401 when no user context."""
        # First-Party
        from mcpgateway.middleware.rbac import require_any_permission

        @require_any_permission(["tools.read", "tools.create"])
        async def endpoint():
            return "ok"

        with pytest.raises(HTTPException) as exc_info:
            await endpoint()
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_require_any_permission_denies_no_match(self, mock_permission_service):
        """require_any_permission should raise 403 when user has none of the permissions."""
        # First-Party
        from mcpgateway.middleware.rbac import require_any_permission

        mock_permission_service.check_permission = AsyncMock(return_value=False)

        @require_any_permission(["tools.read", "tools.create"])
        async def endpoint(user=None, db=None):
            return "ok"

        with pytest.raises(HTTPException) as exc_info:
            await endpoint(user=_make_user_ctx(), db=MagicMock())
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# D6.4: Admin bypass parameter coverage
# ---------------------------------------------------------------------------


class TestAdminBypassParameterCoverage:
    """Verify admin.py uses allow_admin_bypass=False on all endpoints."""

    def test_admin_module_uses_bypass_false(self):
        """admin.py should consistently use allow_admin_bypass=False."""
        # Standard
        import inspect

        # First-Party
        import mcpgateway.admin as admin_mod

        source = inspect.getsource(admin_mod)

        # Count bypass=True and bypass=False
        bypass_false = source.count("allow_admin_bypass=False")
        bypass_true = source.count("allow_admin_bypass=True")

        # admin.py should NOT have any bypass=True (all should be False)
        assert bypass_true == 0, f"admin.py has {bypass_true} endpoints with allow_admin_bypass=True (should be 0)"
        # admin.py should have many bypass=False
        assert bypass_false > 50, f"admin.py has only {bypass_false} endpoints with allow_admin_bypass=False (expected >50)"

    def test_main_api_uses_default_bypass(self):
        """main.py API endpoints should use default bypass (True) or explicitly set it."""
        # Standard
        import inspect

        # First-Party
        import mcpgateway.main as main_mod

        source = inspect.getsource(main_mod)
        # main.py uses default bypass=True (no explicit parameter in most cases)
        require_perm_count = source.count("@require_permission(")
        assert require_perm_count > 30, f"main.py has only {require_perm_count} @require_permission decorators (expected >30)"
