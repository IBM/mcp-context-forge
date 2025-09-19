# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/test_utils.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Unit tests for utilities.
"""
# Standard
import sys

# First-Party
from mcpgateway.plugins.framework.models import GlobalContext, PluginCondition, PromptPosthookPayload, PromptPrehookPayload, ToolPostInvokePayload, ToolPreInvokePayload
from mcpgateway.plugins.framework.utils import import_module, matches, parse_class_name, post_prompt_matches, post_tool_matches, pre_prompt_matches, pre_tool_matches


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


# ============================================================================
# Test import_module function
# ============================================================================

def test_import_module():
    """Test the import_module function."""
    # Test importing sys module
    imported_sys = import_module('sys')
    assert imported_sys is sys

    # Test importing os module
    os_mod = import_module('os')
    assert hasattr(os_mod, 'path')

    # Test caching - calling again should return same object
    imported_sys2 = import_module('sys')
    assert imported_sys2 is imported_sys


# ============================================================================
# Test parse_class_name function
# ============================================================================

def test_parse_class_name():
    """Test the parse_class_name function with various inputs."""
    # Test fully qualified class name
    module, class_name = parse_class_name('module.submodule.ClassName')
    assert module == 'module.submodule'
    assert class_name == 'ClassName'

    # Test simple class name (no module)
    module, class_name = parse_class_name('SimpleClass')
    assert module == ''
    assert class_name == 'SimpleClass'

    # Test package.Class format
    module, class_name = parse_class_name('package.Class')
    assert module == 'package'
    assert class_name == 'Class'

    # Test deeply nested class name
    module, class_name = parse_class_name('a.b.c.d.e.MyClass')
    assert module == 'a.b.c.d.e'
    assert class_name == 'MyClass'


# ============================================================================
# Test post_prompt_matches function
# ============================================================================

def test_post_prompt_matches():
    """Test the post_prompt_matches function."""
    # Import required models
    # First-Party
    from mcpgateway.models import Message, PromptResult, TextContent

    # Test basic matching
    msg = Message(role="assistant", content=TextContent(type="text", text="Hello"))
    result = PromptResult(messages=[msg])
    payload = PromptPosthookPayload(name="greeting", result=result)
    condition = PluginCondition(prompts={"greeting"})
    context = GlobalContext(request_id="req1")

    assert post_prompt_matches(payload, [condition], context) is True

    # Test no match
    payload2 = PromptPosthookPayload(name="other", result=result)
    assert post_prompt_matches(payload2, [condition], context) is False

    # Test with server_id condition
    condition_with_server = PluginCondition(server_ids={"srv1"}, prompts={"greeting"})
    context_with_server = GlobalContext(request_id="req1", server_id="srv1")

    assert post_prompt_matches(payload, [condition_with_server], context_with_server) is True

    # Test with mismatched server_id
    context_wrong_server = GlobalContext(request_id="req1", server_id="srv2")
    assert post_prompt_matches(payload, [condition_with_server], context_wrong_server) is False


def test_post_prompt_matches_multiple_conditions():
    """Test post_prompt_matches with multiple conditions (OR logic)."""
    # First-Party
    from mcpgateway.models import Message, PromptResult, TextContent

    # Create the payload
    msg = Message(role="assistant", content=TextContent(type="text", text="Hello"))
    result = PromptResult(messages=[msg])
    payload = PromptPosthookPayload(name="greeting", result=result)

    # First condition fails, second condition succeeds
    condition1 = PluginCondition(server_ids={"srv1"}, prompts={"greeting"})
    condition2 = PluginCondition(server_ids={"srv2"}, prompts={"greeting"})
    context = GlobalContext(request_id="req1", server_id="srv2")

    assert post_prompt_matches(payload, [condition1, condition2], context) is True

    # Both conditions fail
    context_no_match = GlobalContext(request_id="req1", server_id="srv3")
    assert post_prompt_matches(payload, [condition1, condition2], context_no_match) is False

    # Test reset logic between conditions
    condition3 = PluginCondition(server_ids={"srv3"}, prompts={"other"})
    condition4 = PluginCondition(prompts={"greeting"})
    assert post_prompt_matches(payload, [condition3, condition4], context_no_match) is True


# ============================================================================
# Test pre_tool_matches function
# ============================================================================

def test_pre_tool_matches():
    """Test the pre_tool_matches function."""
    # Test basic matching
    payload = ToolPreInvokePayload(name="calculator", args={"operation": "add"})
    condition = PluginCondition(tools={"calculator"})
    context = GlobalContext(request_id="req1")

    assert pre_tool_matches(payload, [condition], context) is True

    # Test no match
    payload2 = ToolPreInvokePayload(name="other_tool", args={})
    assert pre_tool_matches(payload2, [condition], context) is False

    # Test with server_id condition
    condition_with_server = PluginCondition(server_ids={"srv1"}, tools={"calculator"})
    context_with_server = GlobalContext(request_id="req1", server_id="srv1")

    assert pre_tool_matches(payload, [condition_with_server], context_with_server) is True

    # Test with mismatched server_id
    context_wrong_server = GlobalContext(request_id="req1", server_id="srv2")
    assert pre_tool_matches(payload, [condition_with_server], context_wrong_server) is False


def test_pre_tool_matches_multiple_conditions():
    """Test pre_tool_matches with multiple conditions (OR logic)."""
    payload = ToolPreInvokePayload(name="calculator", args={"operation": "add"})

    # First condition fails, second condition succeeds
    condition1 = PluginCondition(server_ids={"srv1"}, tools={"calculator"})
    condition2 = PluginCondition(server_ids={"srv2"}, tools={"calculator"})
    context = GlobalContext(request_id="req1", server_id="srv2")

    assert pre_tool_matches(payload, [condition1, condition2], context) is True

    # Both conditions fail
    context_no_match = GlobalContext(request_id="req1", server_id="srv3")
    assert pre_tool_matches(payload, [condition1, condition2], context_no_match) is False

    # Test reset logic between conditions
    condition3 = PluginCondition(server_ids={"srv3"}, tools={"other"})
    condition4 = PluginCondition(tools={"calculator"})
    assert pre_tool_matches(payload, [condition3, condition4], context_no_match) is True


# ============================================================================
# Test post_tool_matches function
# ============================================================================

def test_post_tool_matches():
    """Test the post_tool_matches function."""
    # Test basic matching
    payload = ToolPostInvokePayload(name="calculator", result={"value": 42})
    condition = PluginCondition(tools={"calculator"})
    context = GlobalContext(request_id="req1")

    assert post_tool_matches(payload, [condition], context) is True

    # Test no match
    payload2 = ToolPostInvokePayload(name="other_tool", result={})
    assert post_tool_matches(payload2, [condition], context) is False

    # Test with server_id condition
    condition_with_server = PluginCondition(server_ids={"srv1"}, tools={"calculator"})
    context_with_server = GlobalContext(request_id="req1", server_id="srv1")

    assert post_tool_matches(payload, [condition_with_server], context_with_server) is True

    # Test with mismatched server_id
    context_wrong_server = GlobalContext(request_id="req1", server_id="srv2")
    assert post_tool_matches(payload, [condition_with_server], context_wrong_server) is False


def test_post_tool_matches_multiple_conditions():
    """Test post_tool_matches with multiple conditions (OR logic)."""
    payload = ToolPostInvokePayload(name="calculator", result={"value": 42})

    # First condition fails, second condition succeeds
    condition1 = PluginCondition(server_ids={"srv1"}, tools={"calculator"})
    condition2 = PluginCondition(server_ids={"srv2"}, tools={"calculator"})
    context = GlobalContext(request_id="req1", server_id="srv2")

    assert post_tool_matches(payload, [condition1, condition2], context) is True

    # Both conditions fail
    context_no_match = GlobalContext(request_id="req1", server_id="srv3")
    assert post_tool_matches(payload, [condition1, condition2], context_no_match) is False

    # Test reset logic between conditions
    condition3 = PluginCondition(server_ids={"srv3"}, tools={"other"})
    condition4 = PluginCondition(tools={"calculator"})
    assert post_tool_matches(payload, [condition3, condition4], context_no_match) is True


# ============================================================================
# Test enhanced pre_prompt_matches scenarios
# ============================================================================

def test_pre_prompt_matches_multiple_conditions():
    """Test pre_prompt_matches with multiple conditions to cover OR logic paths."""
    payload = PromptPrehookPayload(name="greeting", args={})

    # First condition fails, second condition succeeds
    condition1 = PluginCondition(server_ids={"srv1"}, prompts={"greeting"})
    condition2 = PluginCondition(server_ids={"srv2"}, prompts={"greeting"})
    context = GlobalContext(request_id="req1", server_id="srv2")

    assert pre_prompt_matches(payload, [condition1, condition2], context) is True

    # Both conditions fail
    context_no_match = GlobalContext(request_id="req1", server_id="srv3")
    assert pre_prompt_matches(payload, [condition1, condition2], context_no_match) is False

    # Test reset logic between conditions (line 140)
    condition3 = PluginCondition(server_ids={"srv3"}, prompts={"other"})
    condition4 = PluginCondition(prompts={"greeting"})
    assert pre_prompt_matches(payload, [condition3, condition4], context_no_match) is True


# ============================================================================
# Test matches function edge cases
# ============================================================================

def test_matches_edge_cases():
    """Test the matches function with edge cases."""
    context = GlobalContext(request_id="req1", server_id="srv1", tenant_id="tenant1", user="admin_user")

    # Test empty conditions (should match everything)
    empty_condition = PluginCondition()
    assert matches(empty_condition, context) is True

    # Test user pattern matching
    condition_user = PluginCondition(user_patterns=["admin", "root"])
    assert matches(condition_user, context) is True

    # Test user pattern no match
    condition_user_no_match = PluginCondition(user_patterns=["guest", "visitor"])
    assert matches(condition_user_no_match, context) is False

    # Test context without user
    context_no_user = GlobalContext(request_id="req1", server_id="srv1")
    condition_user_required = PluginCondition(user_patterns=["admin"])
    assert matches(condition_user_required, context_no_user) is True  # No user means condition is ignored

    # Test all conditions together
    complex_condition = PluginCondition(
        server_ids={"srv1", "srv2"},
        tenant_ids={"tenant1"},
        user_patterns=["admin"]
    )
    assert matches(complex_condition, context) is True

    # Test complex condition with one mismatch
    context_wrong_tenant = GlobalContext(
        request_id="req1", server_id="srv1", tenant_id="tenant2", user="admin_user"
    )
    assert matches(complex_condition, context_wrong_tenant) is False
