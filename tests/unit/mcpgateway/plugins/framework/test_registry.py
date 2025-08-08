# -*- coding: utf-8 -*-
"""

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Unit tests for plugin registry.
"""
import pytest

from mcpgateway.plugins.framework.loader.config import ConfigLoader
from mcpgateway.plugins.framework.loader.plugin import PluginLoader
from mcpgateway.plugins.framework.registry import PluginInstanceRegistry

@pytest.mark.asyncio
async def test_registry_register():
    """Load a plugin with the plugin loader."""
    config = ConfigLoader.load_config(config="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_single_plugin.yaml")
    loader = PluginLoader()
    plugin = await loader.load_and_instantiate_plugin(config.plugins[0])
    registry = PluginInstanceRegistry()
    registry.register(plugin)

    all_plugins = registry.get_all_plugins()
    assert len(all_plugins) == 1
    assert registry.get_plugin("ReplaceBadWordsPlugin")
    assert registry.get_plugin("SomeNonExistentPlugin") is None

    registry.unregister("ReplaceBadWordsPlugin")
    assert registry.plugin_count == 0

    registry.unregister("SomePluginThatDoesntExist")

    all_plugins = registry.get_all_plugins()
    assert len(all_plugins) == 0
