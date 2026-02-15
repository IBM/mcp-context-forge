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
from mcpgateway.plugins.framework import (
    GlobalContext,
    PluginCondition,
    PromptPrehookPayload,
    PromptPosthookPayload,
    ToolPreInvokePayload,
    ToolPostInvokePayload,
)
from mcpgateway.plugins.framework.utils import import_module, matches, parse_class_name, payload_matches


def test_server_ids():
    """Test conditional matching with server IDs, tenant IDs, and user patterns."""
    condition1 = PluginCondition(server_ids={"1", "2"})
    context1 = GlobalContext(server_id="1", tenant_id="4", request_id="5")

    payload1 = PromptPrehookPayload(prompt_id="test_prompt", args={})

    assert matches(condition=condition1, context=context1)
    assert payload_matches(payload1, "prompt_pre_fetch", [condition1], context1)

    context2 = GlobalContext(server_id="3", tenant_id="6", request_id="1")
    assert not matches(condition=condition1, context=context2)
    assert not payload_matches(payload1, "prompt_pre_fetch", [condition1], context2)

    condition2 = PluginCondition(server_ids={"1"}, tenant_ids={"4"})

    context2 = GlobalContext(server_id="1", tenant_id="4", request_id="1")

    assert matches(condition2, context2)
    assert payload_matches(payload1, "prompt_pre_fetch", [condition2], context2)

    context3 = GlobalContext(server_id="1", tenant_id="5", request_id="1")

    assert not matches(condition2, context3)
    assert not payload_matches(payload1, "prompt_pre_fetch", [condition2], context3)

    condition4 = PluginCondition(user_patterns=["blah", "barker", "bobby"])
    context4 = GlobalContext(user="blah", request_id="1")

    assert matches(condition4, context4)
    assert payload_matches(payload1, "prompt_pre_fetch", [condition4], context4)

    context5 = GlobalContext(user="barney", request_id="1")
    assert not matches(condition4, context5)
    assert not payload_matches(payload1, "prompt_pre_fetch", [condition4], context5)

    condition5 = PluginCondition(server_ids={"1", "2"}, prompts={"test_prompt"})

    assert payload_matches(payload1, "prompt_pre_fetch", [condition5], context1)
    condition6 = PluginCondition(server_ids={"1", "2"}, prompts={"test_prompt2"})
    assert not payload_matches(payload1, "prompt_pre_fetch", [condition6], context1)


# ============================================================================
# Test import_module function
# ============================================================================


def test_import_module():
    """Test the import_module function."""
    # Test importing sys module
    imported_sys = import_module("sys")
    assert imported_sys is sys

    # Test importing os module
    os_mod = import_module("os")
    assert hasattr(os_mod, "path")

    # Test caching - calling again should return same object
    imported_sys2 = import_module("sys")
    assert imported_sys2 is imported_sys


# ============================================================================
# Test parse_class_name function
# ============================================================================


def test_parse_class_name():
    """Test the parse_class_name function with various inputs."""
    # Test fully qualified class name
    module, class_name = parse_class_name("module.submodule.ClassName")
    assert module == "module.submodule"
    assert class_name == "ClassName"

    # Test simple class name (no module)
    module, class_name = parse_class_name("SimpleClass")
    assert module == ""
    assert class_name == "SimpleClass"

    # Test package.Class format
    module, class_name = parse_class_name("package.Class")
    assert module == "package"
    assert class_name == "Class"

    # Test deeply nested class name
    module, class_name = parse_class_name("a.b.c.d.e.MyClass")
    assert module == "a.b.c.d.e"
    assert class_name == "MyClass"


# ============================================================================
# Test payload_matches for prompt hooks
# ============================================================================


def test_payload_matches_prompt_post_fetch():
    """Test payload_matches for prompt_post_fetch hook."""
    # Test basic matching
    payload = PromptPosthookPayload(prompt_id="greeting", result={"messages": []})
    condition = PluginCondition(prompts={"greeting"})
    context = GlobalContext(request_id="req1")

    assert payload_matches(payload, "prompt_post_fetch", [condition], context) is True

    # Test no match
    payload2 = PromptPosthookPayload(prompt_id="other", result={"messages": []})
    assert payload_matches(payload2, "prompt_post_fetch", [condition], context) is False

    # Test with server_id condition
    condition_with_server = PluginCondition(server_ids={"srv1"}, prompts={"greeting"})
    context_with_server = GlobalContext(request_id="req1", server_id="srv1")

    assert payload_matches(payload, "prompt_post_fetch", [condition_with_server], context_with_server) is True

    # Test with mismatched server_id
    context_wrong_server = GlobalContext(request_id="req1", server_id="srv2")
    assert payload_matches(payload, "prompt_post_fetch", [condition_with_server], context_wrong_server) is False


def test_payload_matches_prompt_multiple_conditions():
    """Test payload_matches for prompts with multiple conditions (OR logic)."""
    # Create the payload
    payload = PromptPosthookPayload(prompt_id="greeting", result={"messages": []})

    # First condition fails, second condition succeeds
    condition1 = PluginCondition(server_ids={"srv1"}, prompts={"greeting"})
    condition2 = PluginCondition(server_ids={"srv2"}, prompts={"greeting"})
    context = GlobalContext(request_id="req1", server_id="srv2")

    assert payload_matches(payload, "prompt_post_fetch", [condition1, condition2], context) is True

    # Both conditions fail
    context_no_match = GlobalContext(request_id="req1", server_id="srv3")
    assert payload_matches(payload, "prompt_post_fetch", [condition1, condition2], context_no_match) is False

    # Test reset logic between conditions
    condition3 = PluginCondition(server_ids={"srv3"}, prompts={"other"})
    condition4 = PluginCondition(prompts={"greeting"})
    assert payload_matches(payload, "prompt_post_fetch", [condition3, condition4], context_no_match) is True


# ============================================================================
# Test payload_matches for tool hooks
# ============================================================================


def test_payload_matches_tool_pre_invoke():
    """Test payload_matches for tool_pre_invoke hook."""
    # Test basic matching
    payload = ToolPreInvokePayload(name="calculator", args={"operation": "add"})
    condition = PluginCondition(tools={"calculator"})
    context = GlobalContext(request_id="req1")

    assert payload_matches(payload, "tool_pre_invoke", [condition], context) is True

    # Test no match
    payload2 = ToolPreInvokePayload(name="other_tool", args={})
    assert payload_matches(payload2, "tool_pre_invoke", [condition], context) is False

    # Test with server_id condition
    condition_with_server = PluginCondition(server_ids={"srv1"}, tools={"calculator"})
    context_with_server = GlobalContext(request_id="req1", server_id="srv1")

    assert payload_matches(payload, "tool_pre_invoke", [condition_with_server], context_with_server) is True

    # Test with mismatched server_id
    context_wrong_server = GlobalContext(request_id="req1", server_id="srv2")
    assert payload_matches(payload, "tool_pre_invoke", [condition_with_server], context_wrong_server) is False


def test_payload_matches_tool_pre_invoke_multiple_conditions():
    """Test payload_matches for tool_pre_invoke with multiple conditions (OR logic)."""
    payload = ToolPreInvokePayload(name="calculator", args={"operation": "add"})

    # First condition fails, second condition succeeds
    condition1 = PluginCondition(server_ids={"srv1"}, tools={"calculator"})
    condition2 = PluginCondition(server_ids={"srv2"}, tools={"calculator"})
    context = GlobalContext(request_id="req1", server_id="srv2")

    assert payload_matches(payload, "tool_pre_invoke", [condition1, condition2], context) is True

    # Both conditions fail
    context_no_match = GlobalContext(request_id="req1", server_id="srv3")
    assert payload_matches(payload, "tool_pre_invoke", [condition1, condition2], context_no_match) is False

    # Test reset logic between conditions
    condition3 = PluginCondition(server_ids={"srv3"}, tools={"other"})
    condition4 = PluginCondition(tools={"calculator"})
    assert payload_matches(payload, "tool_pre_invoke", [condition3, condition4], context_no_match) is True


# ============================================================================
# Test payload_matches for tool_post_invoke
# ============================================================================


def test_payload_matches_tool_post_invoke():
    """Test payload_matches for tool_post_invoke hook."""
    # Test basic matching
    payload = ToolPostInvokePayload(name="calculator", result={"value": 42})
    condition = PluginCondition(tools={"calculator"})
    context = GlobalContext(request_id="req1")

    assert payload_matches(payload, "tool_post_invoke", [condition], context) is True

    # Test no match
    payload2 = ToolPostInvokePayload(name="other_tool", result={})
    assert payload_matches(payload2, "tool_post_invoke", [condition], context) is False

    # Test with server_id condition
    condition_with_server = PluginCondition(server_ids={"srv1"}, tools={"calculator"})
    context_with_server = GlobalContext(request_id="req1", server_id="srv1")

    assert payload_matches(payload, "tool_post_invoke", [condition_with_server], context_with_server) is True

    # Test with mismatched server_id
    context_wrong_server = GlobalContext(request_id="req1", server_id="srv2")
    assert payload_matches(payload, "tool_post_invoke", [condition_with_server], context_wrong_server) is False


def test_payload_matches_tool_post_invoke_multiple_conditions():
    """Test payload_matches for tool_post_invoke with multiple conditions (OR logic)."""
    payload = ToolPostInvokePayload(name="calculator", result={"value": 42})

    # First condition fails, second condition succeeds
    condition1 = PluginCondition(server_ids={"srv1"}, tools={"calculator"})
    condition2 = PluginCondition(server_ids={"srv2"}, tools={"calculator"})
    context = GlobalContext(request_id="req1", server_id="srv2")

    assert payload_matches(payload, "tool_post_invoke", [condition1, condition2], context) is True

    # Both conditions fail
    context_no_match = GlobalContext(request_id="req1", server_id="srv3")
    assert payload_matches(payload, "tool_post_invoke", [condition1, condition2], context_no_match) is False

    # Test reset logic between conditions
    condition3 = PluginCondition(server_ids={"srv3"}, tools={"other"})
    condition4 = PluginCondition(tools={"calculator"})
    assert payload_matches(payload, "tool_post_invoke", [condition3, condition4], context_no_match) is True


# ============================================================================
# Test payload_matches for prompt_pre_fetch with multiple conditions
# ============================================================================


def test_payload_matches_prompt_pre_fetch_multiple_conditions():
    """Test payload_matches for prompt_pre_fetch with multiple conditions to cover OR logic paths."""
    payload = PromptPrehookPayload(prompt_id="greeting", args={})

    # First condition fails, second condition succeeds
    condition1 = PluginCondition(server_ids={"srv1"}, prompts={"greeting"})
    condition2 = PluginCondition(server_ids={"srv2"}, prompts={"greeting"})
    context = GlobalContext(request_id="req1", server_id="srv2")

    assert payload_matches(payload, "prompt_pre_fetch", [condition1, condition2], context) is True

    # Both conditions fail
    context_no_match = GlobalContext(request_id="req1", server_id="srv3")
    assert payload_matches(payload, "prompt_pre_fetch", [condition1, condition2], context_no_match) is False

    # Test reset logic between conditions (OR logic)
    condition3 = PluginCondition(server_ids={"srv3"}, prompts={"other"})
    condition4 = PluginCondition(prompts={"greeting"})
    assert payload_matches(payload, "prompt_pre_fetch", [condition3, condition4], context_no_match) is True


# ============================================================================
# Test matches function edge cases
# ============================================================================


# ============================================================================
# Test StructuredData and coerce_nested
# ============================================================================


def test_structured_data_attribute_access():
    """Test StructuredData provides attribute access on extra fields."""
    from mcpgateway.plugins.framework.utils import StructuredData

    sd = StructuredData(name="test", value=42)
    assert sd.name == "test"
    assert sd.value == 42


def test_structured_data_model_dump():
    """Test StructuredData round-trips through model_dump."""
    from mcpgateway.plugins.framework.utils import StructuredData

    sd = StructuredData(role="user", content="hello")
    dumped = sd.model_dump()
    assert dumped == {"role": "user", "content": "hello"}


def test_coerce_nested_dict():
    """Test coerce_nested converts a dict to StructuredData."""
    from mcpgateway.plugins.framework.utils import StructuredData, coerce_nested

    result = coerce_nested({"name": "test"})
    assert isinstance(result, StructuredData)
    assert result.name == "test"


def test_coerce_nested_deeply_nested():
    """Test coerce_nested handles deeply nested dicts."""
    from mcpgateway.plugins.framework.utils import coerce_nested

    data = {
        "messages": [
            {"role": "user", "content": {"type": "text", "text": "hi"}},
        ],
    }
    result = coerce_nested(data)
    assert result.messages[0].content.text == "hi"
    assert result.messages[0].role == "user"


def test_coerce_nested_list():
    """Test coerce_nested handles lists."""
    from mcpgateway.plugins.framework.utils import StructuredData, coerce_nested

    result = coerce_nested([{"a": 1}, {"b": 2}])
    assert isinstance(result, list)
    assert len(result) == 2
    assert isinstance(result[0], StructuredData)
    assert result[0].a == 1


def test_coerce_nested_scalar():
    """Test coerce_nested passes through scalars unchanged."""
    from mcpgateway.plugins.framework.utils import coerce_nested

    assert coerce_nested(42) == 42
    assert coerce_nested("hello") == "hello"
    assert coerce_nested(None) is None


def test_coerce_nested_pydantic_model():
    """Test coerce_nested returns Pydantic models as-is."""
    from pydantic import BaseModel

    from mcpgateway.plugins.framework.utils import coerce_nested

    class MyModel(BaseModel):
        x: int = 1

    model = MyModel()
    assert coerce_nested(model) is model


# ============================================================================
# Test ORJSONResponse
# ============================================================================


def test_orjson_response_media_type():
    """Test ORJSONResponse has correct media type."""
    from mcpgateway.plugins.framework.utils import ORJSONResponse

    assert ORJSONResponse.media_type == "application/json"


def test_orjson_response_render():
    """Test ORJSONResponse renders JSON bytes."""
    from mcpgateway.plugins.framework.utils import ORJSONResponse

    response = ORJSONResponse(content={"status": "ok", "count": 42})
    assert response.body is not None
    import orjson

    parsed = orjson.loads(response.body)
    assert parsed == {"status": "ok", "count": 42}


def test_orjson_response_render_non_str_keys():
    """Test ORJSONResponse handles non-string keys."""
    from mcpgateway.plugins.framework.utils import ORJSONResponse

    response = ORJSONResponse(content={1: "one", 2: "two"})
    import orjson

    parsed = orjson.loads(response.body)
    assert parsed == {"1": "one", "2": "two"}


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
    complex_condition = PluginCondition(server_ids={"srv1", "srv2"}, tenant_ids={"tenant1"}, user_patterns=["admin"])
    assert matches(complex_condition, context) is True

    # Test complex condition with one mismatch
    context_wrong_tenant = GlobalContext(request_id="req1", server_id="srv1", tenant_id="tenant2", user="admin_user")
    assert matches(complex_condition, context_wrong_tenant) is False
