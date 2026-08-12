# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_log_search_scope.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Layer-1 scope enforcement for the log search router (issue #6134).
"""

# Standard
import importlib
import sys
from unittest.mock import MagicMock

# Third-Party
import pytest
from fastapi import HTTPException

# Rebind fresh: another suite may have imported this module under RBAC mocks;
# pop and re-import so this file always binds freshly-applied, REAL decorators
# regardless of collection order.
sys.modules.pop("mcpgateway.routers.log_search", None)

# First-Party
log_search = importlib.import_module("mcpgateway.routers.log_search")
from tests.helpers.scope import admin_user_context, scoped_request  # noqa: E402

GUARDED = {
    "search_logs": "logs:read",
    "trace_correlation_id": "logs:read",
    "get_security_events": "security:read",
    "get_audit_trails": "audit:read",
    "get_performance_metrics": "metrics:read",
}


@pytest.mark.asyncio
@pytest.mark.parametrize("token_teams", [["team-a"], []])
async def test_narrowed_and_public_only_are_denied_on_search_logs(token_teams):
    """A narrowed admin token cannot search logs (POST body decorator works)."""
    with pytest.raises(HTTPException) as exc:
        await log_search.search_logs(
            body=log_search.LogSearchRequest(),
            user=admin_user_context(token_teams),
            db=MagicMock(),
            request=scoped_request(token_teams, path="/api/logs/search"),
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("token_teams", [["team-a"], []])
async def test_narrowed_and_public_only_are_denied_on_audit_trails(token_teams):
    """A narrowed admin token cannot read the platform-wide audit trail."""
    with pytest.raises(HTTPException) as exc:
        await log_search.get_audit_trails(
            user=admin_user_context(token_teams),
            db=MagicMock(),
            request=scoped_request(token_teams, path="/api/logs/audit-trails"),
        )
    assert exc.value.status_code == 403


def test_log_search_routes_keep_their_non_admin_permissions():
    """These routes use logs:/security:/audit:/metrics: grants, not admin.*; preserve them."""
    for name, permission in GUARDED.items():
        endpoint = getattr(log_search, name)
        assert getattr(endpoint, "__mcpgateway_scope_class__", None) == "global_only", f"{name} is missing the guard"
        assert getattr(endpoint, "_required_permission", None) == permission, f"{name} lost or changed its permission decorator"
