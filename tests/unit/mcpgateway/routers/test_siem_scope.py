# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_siem_scope.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Layer-1 scope enforcement for the SIEM admin router (issue #6134).

This suite deliberately does NOT patch the RBAC decorators — it exercises the
real guard.
"""

# Standard
import importlib
import sys
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
from fastapi import HTTPException

# Rebind fresh: another suite may have imported this module under the RBAC mocks;
# pop and re-import so this file always binds freshly-applied, REAL decorators
# regardless of collection order.
sys.modules.pop("mcpgateway.routers.siem", None)

# First-Party
siem = importlib.import_module("mcpgateway.routers.siem")
from tests.helpers.scope import admin_user_context, scoped_request  # noqa: E402


@pytest.fixture(name="stub_service")
def _stub_service(monkeypatch):
    """Replace the SIEM export service with a stub."""
    service = MagicMock()
    service.get_health = AsyncMock(return_value={"status": "healthy"})
    monkeypatch.setattr(siem, "get_siem_export_service", lambda: service)
    return service


def test_module_imports_with_real_decorators():
    """Guard against this file accidentally being imported under the RBAC mocks."""
    assert getattr(siem.get_siem_health, "__mcpgateway_scope_class__", None) == "global_only"


@pytest.mark.asyncio
async def test_unrestricted_admin_is_allowed(stub_service):
    """token_teams=None is the unrestricted scope and must pass."""
    with patch("mcpgateway.middleware.rbac._global_scope_denied", AsyncMock(return_value=False)):
        result = await siem.get_siem_health(
            _user=admin_user_context(None),
            request=scoped_request(None, path="/admin/siem/health"),
        )
    assert result == {"status": "healthy"}


@pytest.mark.asyncio
@pytest.mark.parametrize("token_teams", [["team-a"], []])
async def test_narrowed_and_public_only_are_denied(stub_service, token_teams):
    """A narrowed or public-only admin token is rejected before the handler runs."""
    with pytest.raises(HTTPException) as exc:
        await siem.get_siem_health(
            _user=admin_user_context(token_teams),
            request=scoped_request(token_teams, path="/admin/siem/health"),
        )
    assert exc.value.status_code == 403
    stub_service.get_health.assert_not_awaited()


@pytest.mark.asyncio
async def test_all_five_siem_routes_carry_the_guard():
    """Every SIEM endpoint is guarded, not just the one exercised above."""
    for name in ("get_siem_health", "get_siem_destinations", "add_siem_destination", "replace_siem_destinations", "test_siem_destination"):
        endpoint = getattr(siem, name)
        assert getattr(endpoint, "__mcpgateway_scope_class__", None) == "global_only", f"{name} is missing the guard"
        assert getattr(endpoint, "_required_permission", None) == "admin.security_audit", f"{name} lost its permission decorator"
