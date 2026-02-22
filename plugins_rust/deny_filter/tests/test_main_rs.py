#!/usr/bin/env python3
"""
Pytest conversion of main_rs.py samples.
"""

import pytest
from mcpgateway.plugins.framework import PluginContext, PluginConfig
from mcpgateway.plugins.framework.hooks.prompts import PromptHookType
from mcpgateway.plugins.framework.hooks.prompts import PromptPrehookPayload
from mcpgateway.plugins.framework.models import GlobalContext

from deny_filter import DenyList
from plugins.deny_filter.deny_rust import DenyListPluginRust


@pytest.fixture
def deny_list():
    """Create a DenyList with test words."""
    words = ["malware", "danger", "secret"]
    return DenyList(words)


@pytest.fixture
def plugin_context():
    """Create a plugin context for testing."""
    gctx = GlobalContext(request_id="deny-test-batch")
    return PluginContext(global_context=gctx)


@pytest.fixture
def deny_plugin():
    """Create a DenyListPluginRust instance."""
    words = ["malware", "danger", "secret"]
    plugin_cfg = PluginConfig(
        name="deny_test",
        kind=f"{DenyListPluginRust.__module__}.{DenyListPluginRust.__name__}",
        hooks=[PromptHookType.PROMPT_PRE_FETCH],
        priority=100,
        config={"words": words},
    )
    return DenyListPluginRust(config=plugin_cfg)


def test_scan_str_with_violation(deny_list):
    """Test scan_str"""
    result = deny_list.scan_str("ok danger")
    assert result
    result = deny_list.scan_str("        ok")
    assert not result


def test_scan_with_violation(deny_list):
    """Test scan method"""
    result = deny_list.scan({"path": "ok danger"})
    assert result
    result = deny_list.scan({"asdf": "        ok"})
    assert not result


@pytest.mark.asyncio
async def test_plugin_prompt_pre_fetch(deny_plugin, plugin_context):
    """Test DenyListPluginRust prompt_pre_fetch hook."""
    payload = PromptPrehookPayload(prompt_id="test", args={"text": "         ok"})
    result = await deny_plugin.prompt_pre_fetch(payload, plugin_context)
    assert result.violation is None
