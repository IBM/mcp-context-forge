# -*- coding: utf-8 -*-
"""

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Unit tests for utilities.
"""
from mcpgateway.plugins.framework.utils import pre_prompt_matches, matches, post_prompt_matches
from mcpgateway.plugins.framework.models import PluginCondition
from mcpgateway.plugins.framework.plugin_types import GlobalContext, PromptPosthookPayload, PromptPrehookPayload



def test_server_ids():
    condition1 = PluginCondition(server_ids={"1", "2"})
    context1 = GlobalContext(server_id="1", tenant_id="4", request_id="5")

    payload1 = PromptPrehookPayload(name="test_prompt", args={})

    assert matches(condition=condition1, context=context1)
    assert pre_prompt_matches(payload1, [condition1], context1)

    context2 = GlobalContext(server_id="3", tenant_id="6", request_id="1")
    assert not matches(condition=condition1, context=context2)
    assert not pre_prompt_matches(payload1, conditions=[condition1], context=context2)

    condition2 = PluginCondition(server_ids={"1"}, tenant_ids={"4"})

    context2 = GlobalContext(server_id="1", tenant_id="4", request_id="1")

    assert matches(condition2, context2)
    assert pre_prompt_matches(payload1, conditions=[condition2], context=context2)

    context3 = GlobalContext(server_id="1", tenant_id="5", request_id="1")

    assert not matches(condition2, context3)
    assert not pre_prompt_matches(payload1, conditions=[condition2], context=context3)

    condition4 = PluginCondition(user_patterns=["blah", "barker", "bobby"])
    context4 = GlobalContext(user="blah", request_id="1")

    assert matches(condition4, context4)
    assert pre_prompt_matches(payload1, conditions=[condition4], context=context4)

    context5 = GlobalContext(user="barney", request_id="1")
    assert not matches(condition4, context5)
    assert not pre_prompt_matches(payload1, conditions=[condition4], context=context5)

    condition5 = PluginCondition(server_ids={"1", "2"}, prompts={"test_prompt"})

    assert pre_prompt_matches(payload1, [condition5], context1)
    condition6 = PluginCondition(server_ids={"1", "2"}, prompts={"test_prompt2"})
    assert not pre_prompt_matches(payload1, [condition6], context1)
