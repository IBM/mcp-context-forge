# -*- coding: utf-8 -*-
"""Shared fixtures for service-layer tests."""

import pytest
from cpex.framework import PluginManager

import mcpgateway.plugins as plugin_framework


def _reset_plugin_state() -> None:
    """Clear process-wide plugin state shared across service tests."""
    PluginManager.reset()
    plugin_framework.reset_plugin_manager_factory()
    plugin_framework._invalidate_shared_enabled_cache()
    plugin_framework._state.clear_local_mode_overrides()
    plugin_framework._reset_factory_init_degraded_for_tests()


@pytest.fixture(autouse=True)
def reset_plugin_manager_state():
    """Keep plugin manager configuration isolated between service tests."""
    _reset_plugin_state()
    yield
    _reset_plugin_state()
