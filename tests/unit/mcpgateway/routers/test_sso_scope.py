# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_sso_scope.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Layer-1 scope enforcement for the SSO admin routes (issue #6134).
"""

# Standard
import importlib
import sys
from unittest.mock import MagicMock

# Third-Party
import pytest
from fastapi import HTTPException

# Pattern B — see "Test Isolation Patterns" above.
sys.modules.pop("mcpgateway.routers.sso", None)

# First-Party
sso = importlib.import_module("mcpgateway.routers.sso")
from tests.helpers.scope import admin_user_context, scoped_request  # noqa: E402

GUARDED = {
    "create_sso_provider": "admin.sso_providers:create",
    "list_all_sso_providers": "admin.sso_providers:read",
    "get_sso_provider": "admin.sso_providers:read",
    "update_sso_provider": "admin.sso_providers:update",
    "delete_sso_provider": "admin.sso_providers:delete",
    "list_pending_approvals": "admin.user_management",
    "handle_approval_request": "admin.user_management",
}

# Pre-authentication routes in the drift guard's EXEMPT bucket. Names verified
# against mcpgateway/routers/sso.py — list_sso_providers:142, initiate_sso_login:253,
# handle_sso_callback:338. Guarding any of these would break the login page.
EXEMPT = ("list_sso_providers", "initiate_sso_login", "handle_sso_callback")


@pytest.mark.asyncio
@pytest.mark.parametrize("token_teams", [["team-a"], []])
async def test_narrowed_and_public_only_are_denied(token_teams):
    """A narrowed admin token cannot enumerate SSO provider configuration."""
    with pytest.raises(HTTPException) as exc:
        await sso.list_all_sso_providers(
            db=MagicMock(),
            user=admin_user_context(token_teams),
            request=scoped_request(token_teams, path="/auth/sso/admin/providers"),
        )
    assert exc.value.status_code == 403


def test_all_sso_admin_routes_carry_both_guards():
    """Each admin endpoint keeps its own fine-grained permission, not a collapsed one."""
    for name, permission in GUARDED.items():
        endpoint = getattr(sso, name)
        assert getattr(endpoint, "__mcpgateway_scope_class__", None) == "global_only", f"{name} is missing the guard"
        assert getattr(endpoint, "_required_permission", None) == permission, f"{name} lost or changed its permission decorator"


def test_module_imports_with_real_decorators():
    """Guard against this file accidentally being imported under the RBAC mocks."""
    assert getattr(sso.list_all_sso_providers, "__mcpgateway_scope_class__", None) == "global_only"


def test_preauth_sso_routes_are_not_guarded():
    """Login-page and callback routes must stay reachable before authentication."""
    for name in EXEMPT:
        endpoint = getattr(sso, name)  # must exist; a missing name means this test is vacuous
        assert getattr(endpoint, "__mcpgateway_scope_class__", None) is None, f"{name} must remain unguarded"
