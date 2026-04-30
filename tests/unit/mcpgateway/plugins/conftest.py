# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/conftest.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

Pytest fixtures for plugin framework tests.
"""

# Third-Party
import pytest

# First-Party
import mcpgateway.plugins.framework as fw
from mcpgateway.plugins.framework import PluginManager
from mcpgateway.plugins.framework.settings import settings
from tests.utils.plugin_redis_helper import install_dynamic_redis_provider


@pytest.fixture(autouse=True)
def _install_redis_provider():
    """Route the framework's Redis shim to the real ``get_redis_client`` for the duration of each test."""
    with install_dynamic_redis_provider():
        yield


@pytest.fixture(autouse=True)
def reset_plugin_manager_state():
    """Reset PluginManager Borg state, the shared-toggle cache, and the factory singleton before/after each test."""
    PluginManager.reset()
    fw.reset_plugin_manager_factory()
    fw._invalidate_shared_enabled_cache()
    fw._state.clear_local_mode_overrides()
    fw._reset_factory_init_degraded_for_tests()
    yield
    PluginManager.reset()
    fw.reset_plugin_manager_factory()
    fw._invalidate_shared_enabled_cache()
    fw._state.clear_local_mode_overrides()
    fw._reset_factory_init_degraded_for_tests()


@pytest.fixture(autouse=True)
def clear_plugins_settings_cache(reset_plugin_manager_state):
    """Clear the settings LRU cache so env changes take effect per test."""
    settings.cache_clear()
    yield
    settings.cache_clear()
