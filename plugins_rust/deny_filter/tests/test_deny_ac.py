#!/usr/bin/env python3
"""
Pytest module for deny_ac.py Aho-Corasick deny list plugin.
Uses mixed case samples to detect deny words.
"""

import pytest
from mcpgateway.plugins.framework import PluginContext, PluginConfig
from mcpgateway.plugins.framework.hooks.prompts import PromptHookType
from mcpgateway.plugins.framework.hooks.prompts import PromptPrehookPayload
from mcpgateway.plugins.framework.models import GlobalContext

from deny_filter import DenyList
from plugins.deny_filter.deny_ac import DenyListAcPlugin


@pytest.fixture
def deny_list():
    """Create a DenyList with test words."""
    words = ["malware", "danger", "secret"]
    return DenyList(words)


@pytest.fixture
def plugin_context():
    """Create a plugin context for testing."""
    gctx = GlobalContext(request_id="deny-ac-test-batch")
    return PluginContext(global_context=gctx)


@pytest.fixture
def deny_ac_plugin():
    """Create a DenyListAcPlugin instance."""
    words = ["malware", "danger", "secret"]
    plugin_cfg = PluginConfig(
        name="deny_ac_test",
        kind=f"{DenyListAcPlugin.__module__}.{DenyListAcPlugin.__name__}",
        hooks=[PromptHookType.PROMPT_PRE_FETCH],
        priority=100,
        config={"words": words},
    )
    return DenyListAcPlugin(config=plugin_cfg)


def test_scan_str_with_violation(deny_list):
    """Test scan_str with mixed case deny words."""
    result = deny_list.scan_str("ok DANGER")
    assert result
    result = deny_list.scan_str("Malware detected")
    assert result
    result = deny_list.scan_str("        ok")
    assert not result


def test_scan_with_violation(deny_list):
    """Test scan method with mixed case deny words."""
    result = deny_list.scan({"path": "ok DANGER"})
    assert result
    result = deny_list.scan({"text": "SECRET key found"})
    assert result
    result = deny_list.scan({"asdf": "        ok"})
    assert not result


def test_automaton_case_insensitive(deny_ac_plugin):
    """Test that Aho-Corasick automaton matches case-insensitively."""
    assert deny_ac_plugin._contains_deny_word("ok DANGER")
    assert deny_ac_plugin._contains_deny_word("Malware detected")
    assert deny_ac_plugin._contains_deny_word("SECRET key")
    assert deny_ac_plugin._contains_deny_word("DaNgErOuS")
    assert deny_ac_plugin._contains_deny_word("mALWARE")
    assert not deny_ac_plugin._contains_deny_word("        ok")
    assert not deny_ac_plugin._contains_deny_word("safe content")


def test_mixed_case_patterns(deny_ac_plugin):
    """Test various mixed case patterns."""
    mixed_cases = [
        "MALWARE",
        "malware",
        "Malware",
        "mAlWaRe",
        "DANGER",
        "danger",
        "Danger",
        "dAnGeR",
        "SECRET",
        "secret",
        "Secret",
        "sEcReT",
    ]
    for text in mixed_cases:
        assert deny_ac_plugin._contains_deny_word(text), f"Failed to detect deny word in: {text}"


@pytest.mark.asyncio
async def test_plugin_prompt_pre_fetch_clean(deny_ac_plugin, plugin_context):
    """Test DenyListAcPlugin prompt_pre_fetch hook with clean input."""
    payload = PromptPrehookPayload(prompt_id="test", args={"text": "         ok"})
    result = await deny_ac_plugin.prompt_pre_fetch(payload, plugin_context)
    assert result.violation is None


@pytest.mark.asyncio
async def test_plugin_prompt_pre_fetch_violation(deny_ac_plugin, plugin_context):
    """Test DenyListAcPlugin prompt_pre_fetch hook with deny word violation."""
    payload = PromptPrehookPayload(prompt_id="test", args={"text": "DANGER zone"})
    result = await deny_ac_plugin.prompt_pre_fetch(payload, plugin_context)
    assert result.violation is not None


@pytest.mark.asyncio
async def test_plugin_prompt_pre_fetch_mixed_case(deny_ac_plugin, plugin_context):
    """Test DenyListAcPlugin prompt_pre_fetch hook with mixed case deny words."""
    test_cases = [
        {"text": "Malware found"},
        {"text": "SECRET information"},
        {"text": "This is DANGEROUS"},
        {"input": "mAlWaRe code"},
        {"query": "sEcReT data"},
    ]
    for args in test_cases:
        payload = PromptPrehookPayload(prompt_id="test", args=args)
        result = await deny_ac_plugin.prompt_pre_fetch(payload, plugin_context)
        assert result.violation is not None


@pytest.mark.asyncio
async def test_plugin_prompt_pre_fetch_multiple_args(deny_ac_plugin, plugin_context):
    """Test DenyListAcPlugin with multiple arguments, one containing deny word."""
    payload = PromptPrehookPayload(
        prompt_id="test",
        args={"title": "Safe title", "content": "DANGEROUS content", "description": "Normal text"},
    )
    result = await deny_ac_plugin.prompt_pre_fetch(payload, plugin_context)
    assert result.violation is not None


@pytest.mark.asyncio
async def test_plugin_shutdown(deny_ac_plugin):
    """Test DenyListAcPlugin shutdown method."""
    await deny_ac_plugin.shutdown()
