# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_rbac_rules_api.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for the /rbac/rules management API.
"""

# Standard
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import pytest

# Local
from tests.utils.rbac_mocks import patch_rbac_decorators, restore_rbac_decorators

_originals = patch_rbac_decorators()
# First-Party
from mcpgateway.routers import rbac as rbac_router  # noqa: E402
from mcpgateway.schemas import RbacRuleCreateRequest, RbacRuleUpdateRequest  # noqa: E402
from mcpgateway.services.rule_catalog_service import RuleCatalogError, RuleCatalogProtectedError  # noqa: E402

restore_rbac_decorators(_originals)


def _make_rule(rule_id: str = "rule-1", **overrides) -> SimpleNamespace:
    base = dict(
        id=rule_id,
        name="deny-viewer-tools",
        description="desc",
        capability_type="tool",
        capability_id=None,
        permission="tools.read",
        phase="pre_invocation",
        predicate="role.viewer",
        effect="deny",
        priority=100,
        is_active=True,
        is_system=False,
        created_by="admin@example.com",
        created_at=datetime.now(tz=timezone.utc),
        updated_at=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_list_rules(monkeypatch):
    service = MagicMock()
    service.list_rules.return_value = [_make_rule("rule-1"), _make_rule("rule-2")]
    monkeypatch.setattr(rbac_router, "RuleCatalogService", lambda db: service)
    result = await rbac_router.list_rules(capability_type="tool", capability_id=None, user={"email": "admin@example.com"}, db=MagicMock())
    assert [r.id for r in result] == ["rule-1", "rule-2"]


@pytest.mark.asyncio
async def test_create_rule_success(monkeypatch):
    service = MagicMock()
    service.create_rule.return_value = _make_rule("new-rule")
    monkeypatch.setattr(rbac_router, "RuleCatalogService", lambda db: service)
    request = RbacRuleCreateRequest(name="deny-viewer-tools", capability_type="tool", predicate="role.viewer", effect="deny")
    result = await rbac_router.create_rule(request, user={"email": "admin@example.com"}, db=MagicMock())
    assert result.id == "new-rule"


@pytest.mark.asyncio
async def test_create_rule_invalid_predicate_returns_422(monkeypatch):
    service = MagicMock()
    service.create_rule.side_effect = RuleCatalogError("Invalid predicate: bad")
    monkeypatch.setattr(rbac_router, "RuleCatalogService", lambda db: service)
    request = RbacRuleCreateRequest(name="bad", capability_type="tool", predicate="role.hr; DROP TABLE", effect="deny")
    with pytest.raises(rbac_router.HTTPException) as excinfo:
        await rbac_router.create_rule(request, user={"email": "admin@example.com"}, db=MagicMock())
    assert excinfo.value.status_code == 422


@pytest.mark.asyncio
async def test_update_rule_not_found_returns_404(monkeypatch):
    service = MagicMock()
    service.update_rule.side_effect = RuleCatalogError("Rule not found: x")
    monkeypatch.setattr(rbac_router, "RuleCatalogService", lambda db: service)
    request = RbacRuleUpdateRequest(priority=5)
    with pytest.raises(rbac_router.HTTPException) as excinfo:
        await rbac_router.update_rule("x", request, user={"email": "admin@example.com"}, db=MagicMock())
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_rule_system_row_returns_409(monkeypatch):
    service = MagicMock()
    service.delete_rule.side_effect = RuleCatalogProtectedError("System rules cannot be deleted: default-viewer-tools-read")
    monkeypatch.setattr(rbac_router, "RuleCatalogService", lambda db: service)
    with pytest.raises(rbac_router.HTTPException) as excinfo:
        await rbac_router.delete_rule("rule-1", user={"email": "admin@example.com"}, db=MagicMock())
    assert excinfo.value.status_code == 409


@pytest.mark.asyncio
async def test_delete_rule_success(monkeypatch):
    service = MagicMock()
    service.delete_rule.return_value = None
    monkeypatch.setattr(rbac_router, "RuleCatalogService", lambda db: service)
    result = await rbac_router.delete_rule("rule-1", user={"email": "admin@example.com"}, db=MagicMock())
    assert result is None


@pytest.mark.asyncio
async def test_entity_summary_sections(monkeypatch):
    service = MagicMock()
    scoped = _make_rule("s1", capability_id="tool-42")
    inherited = _make_rule("i1", capability_id=None)
    service.list_rules.side_effect = [[inherited], [scoped]]
    monkeypatch.setattr(rbac_router, "RuleCatalogService", lambda db: service)
    result = await rbac_router.get_entity_rules_summary(capability_type="tool", capability_id="tool-42", user={"email": "admin@example.com"}, db=MagicMock())
    assert [r.id for r in result.rules] == ["s1"]
    assert [r.id for r in result.inherited] == ["i1"]
    assert "viewer" in result.defaults


def test_rules_routes_require_manage_permission_for_mutations():
    """Mutations carry the rbac.rules.manage permission attribute."""
    mutation_paths = {(route.path, method) for route in rbac_router.router.routes for method in route.methods if route.path.startswith("/rbac/rules") and method in ("POST", "PATCH", "DELETE")}
    assert {("/rbac/rules", "POST"), ("/rbac/rules/{rule_id}", "PATCH"), ("/rbac/rules/{rule_id}", "DELETE")} <= mutation_paths


@pytest.mark.asyncio
async def test_reconcile_db_provider_reports_noop(monkeypatch):
    """The reconcile endpoint answers without mirroring on the db provider."""
    monkeypatch.setattr("mcpgateway.config.settings.rbac_rule_provider", "db", raising=False)
    result = await rbac_router.reconcile_rule_provider(user={"email": "admin@example.com"}, db=MagicMock())
    assert result == {"provider": "db", "applied": 0, "detail": "provider keeps no mirror to reconcile"}


@pytest.mark.asyncio
async def test_reconcile_openfga_forces_sync(monkeypatch):
    """The reconcile endpoint mirrors tuples and clears the decision cache."""
    monkeypatch.setattr("mcpgateway.config.settings.rbac_rule_provider", "openfga", raising=False)
    sync = MagicMock()
    sync.sync_now = AsyncMock(return_value=7)
    monkeypatch.setattr("mcpgateway.services.openfga_sync.OpenFgaSyncService", lambda db, client: sync)
    cleared = []
    monkeypatch.setattr("mcpgateway.services.openfga_provider.clear_decision_cache", lambda: cleared.append(True))
    result = await rbac_router.reconcile_rule_provider(user={"email": "david@demo.example.com"}, db=MagicMock())
    assert result == {"provider": "openfga", "applied": 7}
    sync.sync_now.assert_awaited_once()
    assert cleared == [True]
