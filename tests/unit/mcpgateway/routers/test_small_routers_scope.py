# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_small_routers_scope.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Layer-1 scope enforcement for the runtime admin, toolops, and RBAC
introspection routes (issue #6134).
"""

# Standard
import importlib
import sys
from unittest.mock import MagicMock

# Third-Party
import pytest
from fastapi import HTTPException

# Rebind fresh: test_rbac_router.py imports mcpgateway.routers.rbac under
# patch_rbac_decorators(), so this file must rebind all three modules to
# fresh, really-decorated copies regardless of collection order.
for _name in ("mcpgateway.routers.rbac", "mcpgateway.routers.runtime_admin_router", "mcpgateway.routers.toolops_router"):
    sys.modules.pop(_name, None)

# First-Party
rbac_router = importlib.import_module("mcpgateway.routers.rbac")
runtime_admin_router = importlib.import_module("mcpgateway.routers.runtime_admin_router")
toolops_router = importlib.import_module("mcpgateway.routers.toolops_router")
from tests.helpers.scope import admin_user_context, scoped_request  # noqa: E402

RUNTIME_GUARDED = ("get_mcp_mode", "patch_mcp_mode", "get_a2a_mode", "patch_a2a_mode")
TOOLOPS_GUARDED = ("generate_testcases_for_tool", "execute_tool_nl_testcases", "enrich_a_tool")
RBAC_IN_SCOPE = ("check_permission", "get_user_permissions")
# Migrated by #6132 under a different rule; this change must leave them alone.
RBAC_OUT_OF_SCOPE = ("list_roles", "get_role", "assign_role_to_user", "get_user_roles", "revoke_user_role")


@pytest.mark.asyncio
@pytest.mark.parametrize("token_teams", [["team-a"], []])
async def test_runtime_mode_read_is_denied_for_narrowed_token(token_teams):
    """Runtime mode is platform-wide state; a narrowed admin token cannot read it."""
    with pytest.raises(HTTPException) as exc:
        await runtime_admin_router.get_mcp_mode(
            user=admin_user_context(token_teams),
            request=scoped_request(token_teams, path="/admin/runtime/mcp-mode"),
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("token_teams", [["team-a"], []])
async def test_rbac_permission_introspection_is_denied_for_narrowed_token(token_teams):
    """Permission introspection reveals platform-wide grants."""
    with pytest.raises(HTTPException) as exc:
        await rbac_router.get_user_permissions(
            user_email="someone@example.com",
            user=admin_user_context(token_teams),
            db=MagicMock(),
            request=scoped_request(token_teams, path="/rbac/permissions/user/someone@example.com"),
        )
    assert exc.value.status_code == 403


def test_module_imports_with_real_decorators():
    """Guard against this file accidentally being imported under the RBAC mocks."""
    assert getattr(runtime_admin_router.get_mcp_mode, "__mcpgateway_scope_class__", None) == "global_only"
    assert getattr(rbac_router.check_permission, "__mcpgateway_scope_class__", None) == "global_only"


def test_runtime_and_toolops_routes_carry_both_guards():
    """All seven runtime and toolops endpoints gain the guard and keep their permission."""
    for module, names in ((runtime_admin_router, RUNTIME_GUARDED), (toolops_router, TOOLOPS_GUARDED)):
        for name in names:
            endpoint = getattr(module, name)
            assert getattr(endpoint, "__mcpgateway_scope_class__", None) == "global_only", f"{name} is missing the guard"
            assert getattr(endpoint, "_required_permission", None) == "admin.system_config", f"{name} lost its permission decorator"


def test_only_the_two_in_scope_rbac_routes_are_changed():
    """The five rbac.py routes migrated by #6132 must not gain this guard here."""
    for name in RBAC_IN_SCOPE:
        endpoint = getattr(rbac_router, name)
        assert getattr(endpoint, "__mcpgateway_scope_class__", None) == "global_only", f"{name} is missing the guard"
        assert getattr(endpoint, "_required_permission", None) == "admin.security_audit", f"{name} lost its permission decorator"
    for name in RBAC_OUT_OF_SCOPE:
        endpoint = getattr(rbac_router, name, None)
        if endpoint is None:
            continue
        assert getattr(endpoint, "__mcpgateway_scope_class__", None) != "global_only", f"{name} was wrongly guarded by this task"
