# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/loader/test_plugin_loader.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Unit tests for config and plugin loaders.
"""

# Standard
from unittest.mock import MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.common.models import Message, PromptResult, Role, TextContent
from mcpgateway.plugins.framework.loader.config import ConfigLoader
from mcpgateway.plugins.framework.loader.plugin import PluginLoader
from mcpgateway.plugins.framework import GlobalContext, PluginContext, PluginMode, PromptPosthookPayload, PromptPrehookPayload
from plugins.regex_filter.search_replace import SearchReplaceConfig, SearchReplacePlugin

def test_config_loader_load():
    """pytest for testing the config loader."""
    config = ConfigLoader.load_config(config="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_single_plugin.yaml")
    assert config
    assert len(config.plugins) == 1
    assert config.plugins[0].name == "ReplaceBadWordsPlugin"
    assert config.plugins[0].kind == "plugins.regex_filter.search_replace.SearchReplacePlugin"
    assert config.plugins[0].description == "A plugin for finding and replacing words."
    assert config.plugins[0].version == "0.1"
    assert config.plugins[0].author == "MCP Context Forge Team"
    assert config.plugins[0].hooks[0] == "prompt_pre_fetch"
    assert config.plugins[0].hooks[1] == "prompt_post_fetch"
    assert config.plugins[0].config
    srconfig = SearchReplaceConfig.model_validate(config.plugins[0].config)
    assert len(srconfig.words) == 2
    assert srconfig.words[0].search == "crap"
    assert srconfig.words[0].replace == "crud"


@pytest.mark.asyncio
async def test_plugin_loader_load():
    """Load a plugin with the plugin loader."""
    config = ConfigLoader.load_config(config="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_single_plugin.yaml")
    loader = PluginLoader()
    plugin = await loader.load_and_instantiate_plugin(config.plugins[0])
    assert isinstance(plugin, SearchReplacePlugin)
    assert plugin.name == "ReplaceBadWordsPlugin"
    assert plugin.mode == PluginMode.ENFORCE
    assert plugin.priority == 150
    assert "test_prompt" in plugin.conditions[0].prompts
    assert plugin.hooks[0] == "prompt_pre_fetch"
    assert plugin.hooks[1] == "prompt_post_fetch"

    context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))
    prompt = PromptPrehookPayload(prompt_id="test_prompt", args={"user": "What a crapshow!"})
    result = await plugin.prompt_pre_fetch(prompt, context=context)
    assert len(result.modified_payload.args) == 1
    assert result.modified_payload.args["user"] == "What a yikesshow!"

    message = Message(content=TextContent(type="text", text="What the crud?"), role=Role.USER)
    prompt_result = PromptResult(messages=[message])

    payload_result = PromptPosthookPayload(prompt_id="test_prompt", result=prompt_result)

    result = await plugin.prompt_post_fetch(payload_result, context)
    assert len(result.modified_payload.result.messages) == 1
    assert result.modified_payload.result.messages[0].content.text == "What the yikes?"

    await loader.shutdown()


@pytest.mark.asyncio
async def test_plugin_loader_invalid_plugin_load():
    """Load an invalid plugin with the plugin loader."""
    config = ConfigLoader.load_config(config="./tests/unit/mcpgateway/plugins/fixtures/configs/invalid_single_plugin.yaml", use_jinja=False)
    loader = PluginLoader()
    with pytest.raises(ModuleNotFoundError):
        await loader.load_and_instantiate_plugin(config.plugins[0])


@pytest.mark.asyncio
async def test_plugin_loader_duplicate_registration():
    """Test that duplicate plugin type registration is handled correctly."""
    config = ConfigLoader.load_config(config="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_single_plugin.yaml")
    loader = PluginLoader()

    # Load the same plugin twice to test the "if kind not in self._plugin_types" path (line 72)
    plugin1 = await loader.load_and_instantiate_plugin(config.plugins[0])
    plugin2 = await loader.load_and_instantiate_plugin(config.plugins[0])

    # Both should be instances of the same type
    assert type(plugin1) == type(plugin2)
    assert isinstance(plugin1, SearchReplacePlugin)
    assert isinstance(plugin2, SearchReplacePlugin)

    # Verify the plugin type was only registered once
    assert len(loader._plugin_types) == 1
    assert config.plugins[0].kind in loader._plugin_types

    await loader.shutdown()


@pytest.mark.asyncio
async def test_plugin_loader_get_plugin_type_error():
    """Test error handling in __get_plugin_type method."""
    # First-Party
    from mcpgateway.plugins.framework.models import PluginConfig

    loader = PluginLoader()

    # Create a config with an invalid plugin kind that will cause an import error
    invalid_config = PluginConfig(
        name="InvalidPlugin",
        description="Test invalid plugin",
        author="Test Author",
        version="1.0",
        tags=["test"],
        kind="nonexistent.module.InvalidPlugin",
        hooks=["prompt_pre_fetch"],
        config={}
    )

    # This should raise an exception during plugin type registration
    with pytest.raises(Exception):  # Could be ModuleNotFoundError or other import-related error
        await loader.load_and_instantiate_plugin(invalid_config)

    await loader.shutdown()


@pytest.mark.asyncio
async def test_plugin_loader_none_plugin_type():
    """Test handling when plugin type resolves to None."""
    # First-Party
    from mcpgateway.plugins.framework.models import PluginConfig

    loader = PluginLoader()

    # Mock the _plugin_types to return None for a specific kind
    test_config = PluginConfig(
        name="TestPlugin",
        description="Test plugin",
        author="Test Author",
        version="1.0",
        tags=["test"],
        kind="test.plugin.TestPlugin",
        hooks=["prompt_pre_fetch"],
        config={}
    )

    # Manually set plugin type to None to test line 90 (return None)
    with patch.object(loader, '_PluginLoader__get_plugin_type') as mock_get_type:
        mock_get_type.return_value = None
        loader._plugin_types[test_config.kind] = None

        result = await loader.load_and_instantiate_plugin(test_config)
        assert result is None  # Should return None when plugin_type is None

    await loader.shutdown()


@pytest.mark.asyncio
async def test_plugin_loader_shutdown_with_empty_types():
    """Test shutdown when _plugin_types is empty."""
    loader = PluginLoader()

    # Start with empty plugin types
    assert len(loader._plugin_types) == 0

    # Shutdown should handle empty dict gracefully (line 94: if self._plugin_types)
    await loader.shutdown()

    # Should still be empty
    assert len(loader._plugin_types) == 0


@pytest.mark.asyncio
async def test_plugin_loader_shutdown_with_existing_types():
    """Test shutdown clears existing plugin types."""
    config = ConfigLoader.load_config(config="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_single_plugin.yaml")
    loader = PluginLoader()

    # Load a plugin to populate _plugin_types
    plugin = await loader.load_and_instantiate_plugin(config.plugins[0])
    assert plugin is not None
    assert len(loader._plugin_types) == 1

    # Shutdown should clear the dict
    await loader.shutdown()
    assert len(loader._plugin_types) == 0


@pytest.mark.asyncio
async def test_plugin_loader_registration_branch_coverage():
    """Test plugin registration path coverage."""
    # First-Party
    from mcpgateway.plugins.framework.models import PluginConfig

    loader = PluginLoader()

    # Create a valid config
    config = PluginConfig(
        name="TestPlugin",
        description="Test plugin for registration",
        author="Test Author",
        version="1.0",
        tags=["test"],
        kind="plugins.regex_filter.search_replace.SearchReplacePlugin",
        hooks=["prompt_pre_fetch"],
        config={"words": [{"search": "test", "replace": "example"}]}
    )

    # First load - should register the plugin type (lines 85-87)
    assert config.kind not in loader._plugin_types  # Verify it's not registered yet
    plugin1 = await loader.load_and_instantiate_plugin(config)
    assert plugin1 is not None
    assert config.kind in loader._plugin_types  # Now it should be registered

    # Second load - should skip registration (line 72 condition is false)
    plugin2 = await loader.load_and_instantiate_plugin(config)
    assert plugin2 is not None
    assert len(loader._plugin_types) == 1  # Still only one type registered

    await loader.shutdown()
