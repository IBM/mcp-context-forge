# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_rbac_scope.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Layer-1 scope behavior in the RBAC role handler bodies.

Imported WITHOUT patch_rbac_decorators so handler-body logic runs for real.
Decorator behaviour itself is covered by
tests/unit/mcpgateway/middleware/test_global_scope_helpers.py, and the fact that
specific routes carry the guard is covered by
tests/unit/mcpgateway/test_global_record_scope.py.
"""

# Standard
from datetime import datetime, timezone
import importlib
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# Third-Party
from fastapi import HTTPException
import pytest

# `test_rbac_router.py` (and any other suite using patch_rbac_decorators) imports
# this same module while `mcpgateway.middleware.rbac.require_global_admin_permission`
# is monkeypatched to a no-op. Because Python caches modules in sys.modules, if that
# import happens first in the test session (e.g. collected alphabetically ahead of
# this file), `create_role`/`update_role`/`delete_role` end up permanently decorated
# with the mock — restoring the patched attribute afterwards can't retroactively
# re-decorate functions already bound at import time. Drop any cached entry and
# re-import so this file always exercises freshly-applied, real decorators,
# regardless of collection order. This intentionally does NOT reuse
# `importlib.reload`, which would mutate the *same* module object other test
# files (e.g. test_rbac_router.py) already hold a reference to and corrupt their
# mocked state; popping + re-importing rebinds `sys.modules` to a brand new
# module object instead, leaving any existing references untouched.
sys.modules.pop("mcpgateway.routers.rbac", None)

# First-Party
rbac_router = importlib.import_module("mcpgateway.routers.rbac")
from tests.helpers.scope import admin_user_context, scoped_request  # noqa: E402


def test_module_imports_with_real_decorators():
    """Guard against this file accidentally being imported under the mocks."""
    assert rbac_router.create_role.__mcpgateway_scope_class__ == "global_only"
    assert rbac_router.update_role.__mcpgateway_scope_class__ == "global_only"
    assert rbac_router.delete_role.__mcpgateway_scope_class__ == "global_only"


_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _jwt_scoped_request(token_teams, path):
    """Build a ``scoped_request`` that also carries a verified JWT payload.

    ``list_roles``/``get_role`` call ``get_scoped_resource_access_context``
    (unlike the decorator-gated handlers, which read ``request.state.token_teams``
    directly via ``get_token_teams_from_request``). Without a verified JWT payload
    cached on ``request.state``, ``get_scoped_resource_access_context`` treats the
    caller as a non-JWT dev-mode/basic-auth admin and grants unconditional bypass
    (see ``_has_verified_jwt_payload`` / the fallback-admin branch in
    ``mcpgateway.auth_context.get_scoped_resource_access_context``) regardless of
    ``token_teams`` — that carve-out is intentional for dev-mode callers but wrong
    for simulating a real narrowed admin session token here. Setting
    ``_jwt_verified_payload`` makes this fixture exercise the same verified-token
    code path a real narrowed admin session hits in production.

    Args:
        token_teams: ``None`` for unrestricted, ``[]`` for public-only, or a list of team IDs.
        path: Route path passed through to ``scoped_request``.

    Returns:
        MagicMock: Request stub with a verified JWT payload in addition to ``scoped_request``'s state.
    """
    request = scoped_request(token_teams, path=path)
    request.state._jwt_verified_payload = ("token", {"is_admin": True, "teams": token_teams})
    return request


def _role_row(role_id, name, scope):
    """Build a row satisfying every RoleResponse field."""
    return SimpleNamespace(
        id=role_id,
        name=name,
        description="d",
        scope=scope,
        permissions=[],
        effective_permissions=[],
        inherits_from=None,
        created_by="admin@example.com",
        is_system_role=False,
        is_active=True,
        created_at=_NOW,
        updated_at=_NOW,
    )


@pytest.mark.asyncio
async def test_list_roles_hides_global_roles_from_narrowed_admin(monkeypatch):
    """Narrowed admins see non-global roles only — a 403 here would break the UI role picker."""
    rows = [_role_row("1", "platform_admin", "global"), _role_row("2", "team_admin", "team")]
    monkeypatch.setattr("mcpgateway.services.role_service.RoleService.list_roles", AsyncMock(return_value=rows))

    result = await rbac_router.list_roles(
        request=_jwt_scoped_request(["team-a"], path="/rbac/roles"),
        user=admin_user_context(["team-a"]),
        db=MagicMock(),
    )

    assert {r.scope for r in result} == {"team"}


@pytest.mark.asyncio
async def test_list_roles_shows_everything_to_unrestricted_admin(monkeypatch):
    rows = [_role_row("1", "platform_admin", "global"), _role_row("2", "team_admin", "team")]
    monkeypatch.setattr("mcpgateway.services.role_service.RoleService.list_roles", AsyncMock(return_value=rows))

    result = await rbac_router.list_roles(
        request=_jwt_scoped_request(None, path="/rbac/roles"),
        user=admin_user_context(None),
        db=MagicMock(),
    )

    assert len(result) == 2


@pytest.mark.asyncio
async def test_get_global_role_returns_404_for_narrowed_admin(monkeypatch):
    """404, not 403 — do not confirm the existence of a role the caller may not enumerate."""
    monkeypatch.setattr(
        "mcpgateway.services.role_service.RoleService.get_role_by_id",
        AsyncMock(return_value=_role_row("1", "platform_admin", "global")),
    )

    with pytest.raises(HTTPException) as exc:
        await rbac_router.get_role(
            request=_jwt_scoped_request(["team-a"], path="/rbac/roles/1"),
            role_id="1",
            user=admin_user_context(["team-a"]),
            db=MagicMock(),
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Role not found"
