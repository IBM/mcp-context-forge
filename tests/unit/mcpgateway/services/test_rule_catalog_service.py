# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_rule_catalog_service.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for the rule catalog service and the DbRuleProvider overlay.
"""

# Standard
from typing import cast

from unittest.mock import AsyncMock

# Third-Party
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# First-Party
from mcpgateway.bootstrap_db import DEFAULT_ROLE_DEFINITIONS
from mcpgateway.db import Base, RbacRule
from mcpgateway.services.rule_catalog_service import (
    RuleCatalogError,
    RuleCatalogProtectedError,
    RuleCatalogService,
    capability_for_permission,
)
from mcpgateway.services.rule_provider import DbRuleProvider


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def catalog(db_session):
    return RuleCatalogService(db_session)


def test_capability_mapping():
    assert capability_for_permission("tools.read") == "tool"
    assert capability_for_permission("a2a:invoke") == "a2a_agent"
    assert capability_for_permission("teams.delete") == "route"
    assert capability_for_permission("metrics:read") == "route"


def test_seed_parity_with_builtin_matrix(catalog, db_session):
    seeded = catalog.reseed_defaults()
    expected = catalog.export_builtin_matrix()
    assert seeded == len(expected)
    names = {r.name for r in catalog.list_rules()}
    assert names == {spec["name"] for spec in expected}
    # Idempotent on the second run
    assert catalog.reseed_defaults() == 0


def test_seed_covers_every_builtin_permission(catalog):
    catalog.reseed_defaults()
    seeded_permissions = {(r.predicate, r.permission) for r in catalog.list_rules() if r.permission}
    for role in DEFAULT_ROLE_DEFINITIONS:
        for permission in cast(list[str], role["permissions"]):
            if permission == "*":
                continue
            assert (f"role.{role['name']}", permission) in seeded_permissions


def test_deny_rule_blocks_overlay(catalog, db_session):
    catalog.create_rule(name="no-tools-for-viewer", capability_type="tool", permission=None, predicate="role.viewer", effect="deny")
    decision = catalog.evaluate_overlay("tools.read", {"role": {"viewer": True}})
    assert decision is False
    assert db_session.query(RbacRule).filter_by(name="no-tools-for-viewer").one()


def test_allow_rule_grants_overlay(catalog):
    catalog.create_rule(name="auditor-reads-tools", capability_type="tool", permission="tools.read", predicate="role.auditor", effect="allow")
    assert catalog.evaluate_overlay("tools.read", {"role": {"auditor": True}}) is True
    assert catalog.evaluate_overlay("tools.update", {"role": {"auditor": True}}) is None


def test_entity_scoped_rule_matches_only_that_entity(catalog):
    catalog.create_rule(name="block-one-tool", capability_type="tool", capability_id="tool-42", predicate="authenticated", effect="deny")
    attrs = {"authenticated": True}
    assert catalog.evaluate_overlay("tools.execute", attrs, capability_id="tool-42") is False
    assert catalog.evaluate_overlay("tools.execute", attrs, capability_id="tool-43") is None
    assert catalog.evaluate_overlay("tools.execute", attrs) is None


def test_priority_orders_decisions(catalog):
    catalog.create_rule(name="low-priority-allow", capability_type="tool", predicate="authenticated", effect="allow", priority=500)
    catalog.create_rule(name="high-priority-deny", capability_type="tool", predicate="authenticated", effect="deny", priority=10)
    assert catalog.evaluate_overlay("tools.read", {"authenticated": True}) is False


def test_inactive_rule_ignored(catalog):
    rule = catalog.create_rule(name="disabled", capability_type="tool", predicate="authenticated", effect="deny")
    rule.is_active = False
    catalog._db.flush()
    assert catalog.evaluate_overlay("tools.read", {"authenticated": True}) is None


def test_predicate_validation_rejects_bad_input(catalog):
    with pytest.raises(RuleCatalogError, match="Invalid predicate"):
        catalog.create_rule(name="bad", capability_type="tool", predicate="role.hr; DROP TABLE", effect="deny")


def test_invalid_enum_fields_rejected(catalog):
    with pytest.raises(RuleCatalogError, match="capability_type"):
        catalog.create_rule(name="bad-cap", capability_type="widget", predicate="authenticated", effect="deny")
    with pytest.raises(RuleCatalogError, match="effect"):
        catalog.create_rule(name="bad-effect", capability_type="tool", predicate="authenticated", effect="block")


def test_system_rule_delete_protected(catalog):
    catalog.reseed_defaults()
    rule = catalog.list_rules()[0]
    with pytest.raises(RuleCatalogProtectedError):
        catalog.delete_rule(rule.id)


def test_duplicate_name_rejected(catalog):
    catalog.create_rule(name="dup", capability_type="tool", predicate="authenticated", effect="deny")
    with pytest.raises(RuleCatalogError, match="already exists"):
        catalog.create_rule(name="dup", capability_type="tool", predicate="authenticated", effect="deny")


@pytest.mark.asyncio
async def test_db_provider_overlay_denies_after_base_grant(db_session, monkeypatch):
    provider = DbRuleProvider(db_session)
    monkeypatch.setattr(type(provider).__mro__[1], "check_permission", AsyncMock(return_value=True))
    RuleCatalogService(db_session).create_rule(name="deny-all-tools", capability_type="tool", predicate="authenticated", effect="deny")
    granted = await provider.check_permission("user@example.com", "tools.read")
    assert granted is False


@pytest.mark.asyncio
async def test_db_provider_overlay_none_passthrough(db_session, monkeypatch):
    provider = DbRuleProvider(db_session)
    monkeypatch.setattr(type(provider).__mro__[1], "check_permission", AsyncMock(return_value=True))
    granted = await provider.check_permission("user@example.com", "teams.read")
    assert granted is True
