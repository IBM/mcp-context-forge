# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/test_errors.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for errors module.
"""

import pytest
from mcpgateway.plugins.framework.errors import convert_exception_to_error, PluginError


@pytest.mark.asyncio
async def test_convert_exception_to_error():
    error_model = convert_exception_to_error(ValueError("This is some error."), "SomePluginName")
    assert error_model.message == "ValueError('This is some error.')"
    assert error_model.plugin_name == "SomePluginName"

    plugin_error = PluginError(error_model)

    assert plugin_error.error.message == "ValueError('This is some error.')"
    assert plugin_error.error.plugin_name == "SomePluginName"
