# -*- coding: utf-8 -*-
"""Test cases for OPA plugin

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Shriti Priya

This module contains test cases for running opa plugin.
"""


# Third-Party
import pytest

# First-Party
from opapluginfilter.plugin import OPAPluginFilter
from mcpgateway.plugins.framework import (
    PluginConfig,
    PluginContext,
    ToolPreInvokePayload,
    GlobalContext
)
from mcpgateway.plugins.framework.models import AppliedTo, ToolTemplate

from tests.server.opa_server import run_mock_opa


@pytest.mark.asyncio
# Test for when opaplugin is not applied to a tool
async def test_benign_opapluginfilter():
    """Test plugin prompt prefetch hook."""
    config = PluginConfig(
        name="test",
        kind="opapluginfilter.OPAPluginFilter",
        hooks=["tool_pre_invoke"],
        config={"opa_base_url": "http://127.0.0.1:8181/v1/data/"}
    )
    mock_server = run_mock_opa()


    plugin = OPAPluginFilter(config)

    # Test your plugin logic
    payload = ToolPreInvokePayload(name="fast-time-git-status", args={"repo_path": "/path/IBM"})
    context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))
    result = await plugin.tool_pre_invoke(payload, context)
    mock_server.shutdown()
    assert result.continue_processing


@pytest.mark.asyncio
# Test for when opaplugin is not applied to a tool
async def test_malign_opapluginfilter():
    """Test plugin prompt prefetch hook."""
    config = PluginConfig(
        name="test",
        kind="opapluginfilter.OPAPluginFilter",
        hooks=["tool_pre_invoke"],
        config={"opa_base_url": "http://127.0.0.1:8181/v1/data/"}
    )
    mock_server = run_mock_opa()
    plugin = OPAPluginFilter(config)

    # Test your plugin logic
    payload = ToolPreInvokePayload(name="fast-time-git-status", args={"repo_path": "/path/IM"})
    context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))
    result = await plugin.tool_pre_invoke(payload, context)
    mock_server.shutdown()
    assert not result.continue_processing and result.violation.code == "deny"

@pytest.mark.asyncio
# Test for opa plugin not applied to any of the tools
async def test_applied_to_opaplugin():
    """Test plugin prompt prefetch hook."""
    config = PluginConfig(
        name="test",
        kind="opapluginfilter.OPAPluginFilter",
        hooks=["tool_pre_invoke"],
        config={"opa_base_url": "http://127.0.0.1:8181/v1/data/"}
    )
    mock_server = run_mock_opa()
    plugin = OPAPluginFilter(config)

    # Test your plugin logic
    payload = ToolPreInvokePayload(name="fast-time-git-status", args={"repo_path": "/path/IM"})
    context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))
    result = await plugin.tool_pre_invoke(payload, context)
    mock_server.shutdown()
    assert result.continue_processing
