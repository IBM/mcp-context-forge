# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_rule_provider.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

RuleProvider seam tests: factory dispatch and db-provider contract.
"""

# Standard
from unittest.mock import Mock

# Third-Party
import pytest

# First-Party
from mcpgateway.config import settings
from mcpgateway.middleware import rbac
from mcpgateway.services.permission_service import PermissionService
from mcpgateway.services.rule_provider import DbRuleProvider, RuleProvider, get_rule_provider


def test_factory_returns_db_provider_by_default():
    provider = get_rule_provider(Mock())
    assert isinstance(provider, DbRuleProvider)
    assert isinstance(provider, PermissionService)
    assert isinstance(provider, RuleProvider)


def test_factory_passes_audit_flag_through(monkeypatch):
    monkeypatch.setattr(settings, "rbac_rule_provider", "db")
    provider = get_rule_provider(Mock(), audit_enabled=False)
    assert isinstance(provider, DbRuleProvider)
    assert provider.audit_enabled is False


def test_factory_dispatches_openfga(monkeypatch):
    monkeypatch.setattr(settings, "rbac_rule_provider", "openfga")
    monkeypatch.setattr(settings, "rbac_rule_provider_shadow", False)
    from mcpgateway.services.openfga_provider import OpenFgaRuleProvider

    provider = get_rule_provider(Mock())
    assert isinstance(provider, OpenFgaRuleProvider)


def test_factory_shadow_wraps_db(monkeypatch):
    monkeypatch.setattr(settings, "rbac_rule_provider", "db")
    monkeypatch.setattr(settings, "rbac_rule_provider_shadow", True)
    from mcpgateway.services.rule_provider import ShadowRuleProvider

    provider = get_rule_provider(Mock())
    assert isinstance(provider, ShadowRuleProvider)


def test_invalidate_user_clears_provider_cache():
    provider = DbRuleProvider(Mock())
    provider.clear_user_cache = Mock()
    provider.invalidate_user("user@example.com")
    provider.clear_user_cache.assert_called_once_with("user@example.com")


def test_rbac_module_alias_stays_patchable(monkeypatch):
    """The rbac.PermissionService name must remain an interception point."""
    assert callable(rbac.PermissionService)

    class _Fake:
        def __init__(self, *_args, **_kwargs):
            pass

    monkeypatch.setattr(rbac, "PermissionService", _Fake)
    assert isinstance(rbac.PermissionService(Mock()), _Fake)
