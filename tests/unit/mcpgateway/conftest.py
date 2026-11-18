# -*- coding: utf-8 -*-
# Copyright (c) 2025 ContextForge Contributors.
# SPDX-License-Identifier: Apache-2.0

"""Location: ./tests/unit/mcpgateway/conftest.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Shared fixtures for mcpgateway unit tests.
"""

# Future
from __future__ import annotations

# Standard
import socket
import sys
from unittest.mock import AsyncMock

# Third-Party
import pytest

# First-Party
# Save original RBAC decorator functions at conftest import time.
# Conftest files load before test modules, so these should be the real functions.
import mcpgateway.middleware.rbac as _rbac_mod
from cpex.framework.settings import settings
from mcpgateway import config

_ORIG_REQUIRE_PERMISSION = _rbac_mod.require_permission
_ORIG_REQUIRE_ADMIN_PERMISSION = _rbac_mod.require_admin_permission
_ORIG_REQUIRE_ANY_PERMISSION = _rbac_mod.require_any_permission


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


@pytest.fixture(autouse=True)
def _reset_plugin_framework_redis_provider():
    """Clear the plugin framework's shared Redis provider between tests.

    ``main.py`` lifespan registers ``get_redis_client`` as the framework's
    Redis provider. Lifespan-exercising tests monkeypatch
    ``main_mod.get_redis_client`` to an ``AsyncMock`` so their lifespan run
    registers that mock as the provider — but ``set_shared_redis_provider``
    is module-level state that ``monkeypatch`` doesn't roll back, so the
    mock bleeds into subsequent tests. ``_read_shared_enabled`` then treats
    the mock's return value as a truthy-but-non-string Redis reply, which
    decodes to ``False`` and makes ``get_plugin_manager`` return ``None``.

    Resetting the provider to ``None`` before and after every test keeps
    that state out of the hot path; plugin-suite tests (which have their
    own conftest) re-install a real dynamic provider after this runs.
    """
    from mcpgateway.plugins._redis import set_shared_redis_provider  # pylint: disable=import-outside-toplevel

    set_shared_redis_provider(None)
    yield
    set_shared_redis_provider(None)


_SANDBOX_POOL_HOOKS = (
    "start_jq_pool",
    "start_validation_pool",
    "start_cel_pool",
    "shutdown_jq_pool",
    "shutdown_validation_pool",
    "shutdown_cel_pool",
)


@pytest.fixture(autouse=True)
def _skip_sandbox_pools_in_lifespan(request, monkeypatch):
    """Keep ``main.lifespan`` from forking sandbox worker pools.

    On Linux each lifespan entry forks a jq, a validation and a CEL pool. That
    costs seconds per entry and no lifespan test checks the pools. The sandbox
    pools build their executors lazily on first use, so skipping the start
    hooks is safe. Tests of the pools call ``jq_runner``, ``cel_runner`` and
    ``safe_jsonschema`` directly and do not go through ``main``.

    A test that needs the real pools carries the ``real_sandbox_pools`` marker.
    A renamed or removed hook raises ``AttributeError`` here, so CI cannot slow
    down without a failure.
    """
    if request.node.get_closest_marker("real_sandbox_pools"):
        return
    main_mod = sys.modules.get("mcpgateway.main")
    if main_mod is None:
        return
    for hook in _SANDBOX_POOL_HOOKS:
        monkeypatch.setattr(main_mod, hook, lambda: None, raising=True)


@pytest.fixture(autouse=True)
def reset_app_root_path(monkeypatch):
    """Reset app_root_path to empty string for all tests.

    This ensures tests are not affected by APP_ROOT_PATH environment variable.
    The resolve_root_path() function in mcpgateway.utils.paths falls back to
    settings.app_root_path when request.scope["root_path"] is empty. Without
    this fixture, tests would fail when APP_ROOT_PATH is set in the environment.

    Tests that specifically need to test root_path behavior should override this
    by setting the monkeypatch value explicitly in the test.
    """
    monkeypatch.setattr("mcpgateway.utils.paths.settings.app_root_path", "")


@pytest.fixture
def configure_gateway_test_allowlist(monkeypatch):
    """Configure gateway test endpoint allowlist for unit tests.

    This fixture is opt-in and should be used by tests that need to bypass
    gateway test endpoint security validation. It configures the gateway test
    endpoint to allow *.example.com and mocks DNS resolution to return public IPs.

    Usage: Add @pytest.mark.usefixtures("configure_gateway_test_allowlist")
    to test classes or functions that need this behavior.

    This is necessary because the security fix (ICA_ContextForgeICACF-14) now
    enforces an allowlist for the /admin/gateways/test endpoint.
    """
    # Configure allowlist to allow test domains
    monkeypatch.setattr(config.settings, "gateway_test_allow_registered_only", False)
    monkeypatch.setattr(config.settings, "gateway_test_allowed_hosts", ["example.com", "*.example.com", "google.com", "*.google.com"])

    # Mock DNS resolution to return public IP for all test domains
    # Scope to the validator module to avoid affecting other code
    def mock_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        """Mock getaddrinfo to return public IP (8.8.8.8) for all domains in tests."""
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', port or 443))]

    monkeypatch.setattr("mcpgateway.common.validators.socket.getaddrinfo", mock_getaddrinfo)
