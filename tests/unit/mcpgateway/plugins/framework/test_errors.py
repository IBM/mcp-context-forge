# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/test_errors.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for errors module.
"""

# Third-Party
import pytest
import re
from mcpgateway.plugins.framework.errors import convert_exception_to_error
from mcpgateway.plugins.framework import (
    GlobalContext,
    PluginError,
    PluginMode,
    PluginManager,
    PromptHookType,
    PromptPrehookPayload
)


@pytest.mark.asyncio
async def test_convert_exception_to_error():
    error_model = convert_exception_to_error(ValueError("This is some error."), "SomePluginName")
    assert error_model.message == "ValueError('This is some error.')"
    assert error_model.plugin_name == "SomePluginName"

    plugin_error = PluginError(error_model)

    assert plugin_error.error.message == "ValueError('This is some error.')"
    assert plugin_error.error.plugin_name == "SomePluginName"


@pytest.mark.asyncio
async def test_error_plugin():
    plugin_manager = PluginManager(config="tests/unit/mcpgateway/plugins/fixtures/configs/error_plugin.yaml")
    await plugin_manager.initialize()
    payload = PromptPrehookPayload(prompt_id="test_prompt", args={"arg0": "This is a crap argument"})
    global_context = GlobalContext(request_id="1")
    escaped_regex = re.escape("ValueError('Sadly! Prompt prefetch is broken!')")
    with pytest.raises(PluginError, match=escaped_regex):
        await plugin_manager.invoke_hook(PromptHookType.PROMPT_PRE_FETCH, payload, global_context)

    await plugin_manager.shutdown()


async def test_error_plugin_raise_error_false():
    plugin_manager = PluginManager(config="tests/unit/mcpgateway/plugins/fixtures/configs/error_plugin_raise_error_false.yaml")
    await plugin_manager.initialize()
    payload = PromptPrehookPayload(prompt_id="test_prompt", args={"arg0": "This is a crap argument"})
    global_context = GlobalContext(request_id="1")
    with pytest.raises(PluginError):
        result, _ = await plugin_manager.invoke_hook(PromptHookType.PROMPT_PRE_FETCH, payload, global_context)
    # assert result.continue_processing
    # assert not result.modified_payload

    await plugin_manager.shutdown()
    plugin_manager.config.plugins[0].mode = PluginMode.ENFORCE_IGNORE_ERROR
    await plugin_manager.initialize()
    result, _ = await plugin_manager.invoke_hook(PromptHookType.PROMPT_PRE_FETCH, payload, global_context)
    assert result.continue_processing
    assert not result.modified_payload
    await plugin_manager.shutdown()
