# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/conftest.py
Copyright 2025
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


@pytest.fixture(autouse=True)
def reset_plugin_manager_state():
    """Reset PluginManager Borg state before and after each test.

    This ensures each test starts with a fresh PluginManager instance,
    preventing state leakage between tests when using the Borg pattern.
    Also resets the module-level singleton cached by get_plugin_manager().
    """
    PluginManager.reset()
    fw._plugin_manager = None
    yield
    PluginManager.reset()
    fw._plugin_manager = None


@pytest.fixture(autouse=True)
def clear_plugins_settings_cache(reset_plugin_manager_state):
    """Clear the settings LRU cache so env changes take effect per test."""
    settings.cache_clear()
    yield
    settings.cache_clear()
