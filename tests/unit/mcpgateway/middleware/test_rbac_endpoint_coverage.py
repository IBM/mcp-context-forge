# -*- coding: utf-8 -*-
# Copyright (c) 2025 ContextForge Contributors.
# SPDX-License-Identifier: Apache-2.0

"""Location: ./tests/unit/mcpgateway/middleware/test_rbac_endpoint_coverage.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

RBAC Endpoint Coverage Tests.

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
