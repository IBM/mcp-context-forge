# -*- coding: utf-8 -*-
# Copyright (c) 2025 ContextForge Contributors.
# SPDX-License-Identifier: Apache-2.0

"""Shared fixtures for mcpgateway unit tests."""

# Future
from __future__ import annotations

# Standard
import sys
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import pytest

# First-Party
# Save original RBAC decorator functions at conftest import time.
# Conftest files load before test modules, so these should be the real functions.
import mcpgateway.middleware.rbac as _rbac_mod
from mcpgateway.plugins.framework.settings import settings

_ORIG_REQUIRE_PERMISSION = _rbac_mod.require_permission
_ORIG_REQUIRE_ADMIN_PERMISSION = _rbac_mod.require_admin_permission
_ORIG_REQUIRE_ANY_PERMISSION = _rbac_mod.require_any_permission

# Use real gateway_rs.a2a_service if Rust extension is installed; otherwise inject a mock (TestRustA2AQueue fails).
if "gateway_rs" not in sys.modules:
    try:
        import gateway_rs.a2a_service  # noqa: F401
    except ImportError:
        _gw = MagicMock()
        _gw.a2a_service = MagicMock()
        _gw.a2a_service.invoke = AsyncMock(return_value=[])
        _gw.a2a_service.submit_queue = AsyncMock(
            return_value=[{"status_code": 200, "parsed": {"response": "Agent response", "status": "success"}}]
        )
        _gw.a2a_service.init_queue = MagicMock()

        def _build_a2a_metrics_batch(entries, end_time_ts):
            metrics = []
            success_ids = []
            for ent in entries:
                agent_id, interaction_type, status_code, body, duration_secs = ent[:5]
                success = status_code == 200
                err = None if success else (body or "Internal Server Error")
                metrics.append((agent_id, end_time_ts, duration_secs, success, interaction_type, err))
                if success:
                    success_ids.append(agent_id)
            return (metrics, success_ids)

        _gw.a2a_service.build_a2a_metrics_batch = _build_a2a_metrics_batch
        sys.modules["gateway_rs"] = _gw


class MockPermissionService:
    """Mock PermissionService that allows all permission checks by default."""

    # Class-level mock that can be patched by individual tests
    check_permission = AsyncMock(return_value=True)
    check_admin_permission = AsyncMock(return_value=True)

    def __init__(self, db=None):
        self.db = db


@pytest.fixture(autouse=True)
def mock_permission_service(monkeypatch):
    """Auto-mock PermissionService and restore real RBAC decorators.

    This fixture is auto-used for all tests in this directory.

    It also restores real RBAC decorator functions in case other tests
    patched them (e.g., via module-level monkeypatching) in the same worker
    process when running under xdist.

    Tests that need to verify permission denial behavior should:
    1. Set MockPermissionService.check_permission.return_value = False
    2. Or configure side_effect for more complex scenarios
    """
    # Restore real RBAC decorators (may have been replaced by noop in e2e test modules)
    monkeypatch.setattr(_rbac_mod, "require_permission", _ORIG_REQUIRE_PERMISSION)
    monkeypatch.setattr(_rbac_mod, "require_admin_permission", _ORIG_REQUIRE_ADMIN_PERMISSION)
    monkeypatch.setattr(_rbac_mod, "require_any_permission", _ORIG_REQUIRE_ANY_PERMISSION)

    # Reset the mock before each test to ensure clean state
    MockPermissionService.check_permission = AsyncMock(return_value=True)
    MockPermissionService.check_admin_permission = AsyncMock(return_value=True)
    monkeypatch.setattr("mcpgateway.middleware.rbac.PermissionService", MockPermissionService)
    return MockPermissionService


@pytest.fixture(autouse=True)
def clear_plugins_settings_cache():
    """Clear the settings LRU cache so env changes take effect per test."""
    settings.cache_clear()
    yield
    settings.cache_clear()
