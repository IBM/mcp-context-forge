# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/conftest.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Shared fixtures for plugin framework tests.
"""

# Third-Party
import pytest

# First-Party
import mcpgateway.plugins.framework as fw
from mcpgateway.plugins.framework.manager import PluginManager


@pytest.fixture(autouse=True)
def reset_plugin_manager_state():
    """Ensure PluginManager shared state is reset between tests."""
    PluginManager.reset()
    fw._plugin_manager = None
    yield
    PluginManager.reset()
    fw._plugin_manager = None
