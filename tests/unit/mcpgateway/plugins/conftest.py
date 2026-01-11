# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/conftest.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

Pytest fixtures for plugin framework tests.
"""

# Third-Party
import pytest

# First-Party
from mcpgateway.plugins.framework import PluginManager


@pytest.fixture(autouse=True)
def reset_plugin_manager_state():
    """Reset PluginManager Borg state before each test.

    This ensures each test starts with a fresh PluginManager instance,
    preventing state leakage between tests when using the Borg pattern.
    """
    PluginManager.reset()
    yield
