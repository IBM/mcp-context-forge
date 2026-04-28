# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/test_utils_and_logic.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for hybrid AND/OR condition evaluation logic.

This test module validates the breaking change from OR-based to AND/OR-based
condition evaluation in the plugin framework (Issue #3930).
"""

# Third-Party
import pytest

# First-Party
from mcpgateway.plugins.framework import (
    GlobalContext,
    PluginCondition,
    PromptPrehookPayload,
    ToolPreInvokePayload,
    ToolPostInvokePayload,
    ResourcePreFetchPayload,
)
from mcpgateway.plugins.framework.utils import matches, payload_matches

# ============================================================================
# Test Single Condition Object - AND Logic Within Object
# ============================================================================


def test_single_condition_all_fields_match():
    """Test that all fields in a single condition object must match (AND logic)."""
    # Setup: condition with tenant_ids, tools, and server_ids
    condition = PluginCondition(tenant_ids={"healthcare"}, tools={"patient_reader"}, server_ids={"prod-server"})

    payload = ToolPreInvokePayload(name="patient_reader", args={})
    context = GlobalContext(request_id="req1", tenant_id="healthcare", server_id="prod-server")

    # All fields match → should execute
    assert payload_matches(payload, "tool_pre_invoke", [condition], context) is True


def test_single_condition_one_field_mismatch():
    """Test that if one field doesn't match, the condition fails (AND logic)."""
    # Setup: condition with tenant_ids, tools, and server_ids
    condition = PluginCondition(tenant_ids={"healthcare"}, tools={"patient_reader"}, server_ids={"prod-server"})

    payload = ToolPreInvokePayload(name="patient_reader", args={})

    # Test 1: Wrong tenant (other fields match)
    context_wrong_tenant = GlobalContext(request_id="req1", tenant_id="finance", server_id="prod-server")  # Wrong tenant
    assert payload_matches(payload, "tool_pre_invoke", [condition], context_wrong_tenant) is False

    # Test 2: Wrong server (other fields match)
    context_wrong_server = GlobalContext(request_id="req1", tenant_id="healthcare", server_id="dev-server")  # Wrong server
    assert payload_matches(payload, "tool_pre_invoke", [condition], context_wrong_server) is False

    # Test 3: Wrong tool (other fields match)
    payload_wrong_tool = ToolPreInvokePayload(name="other_tool", args={})
    context_correct = GlobalContext(request_id="req1", tenant_id="healthcare", server_id="prod-server")
    assert payload_matches(payload_wrong_tool, "tool_pre_invoke", [condition], context_correct) is False


def test_single_condition_multiple_fields_all_match():
    """Test multiple fields in one condition - all must match."""
    condition = PluginCondition(tenant_ids={"healthcare", "finance"}, tools={"tool1", "tool2"}, user_patterns=["admin"])

    payload = ToolPreInvokePayload(name="tool1", args={})
    context = GlobalContext(request_id="req1", tenant_id="healthcare", user="admin_alice")

    # All fields match → should execute
    assert payload_matches(payload, "tool_pre_invoke", [condition], context) is True


def test_single_condition_multiple_fields_one_mismatch():
    """Test multiple fields in one condition - one mismatch fails the condition."""
    condition = PluginCondition(tenant_ids={"healthcare", "finance"}, tools={"tool1", "tool2"}, user_patterns=["admin"])

    payload = ToolPreInvokePayload(name="tool1", args={})
    context = GlobalContext(request_id="req1", tenant_id="healthcare", user="regular_user")  # User pattern doesn't match

    # User pattern doesn't match → should NOT execute
    assert payload_matches(payload, "tool_pre_invoke", [condition], context) is False


# ============================================================================
# Test Multiple Condition Objects - OR Logic Across Objects
# ============================================================================


def test_multiple_conditions_first_matches():
    """Test that if the first condition object matches, plugin executes (OR logic)."""
    condition1 = PluginCondition(tenant_ids={"healthcare"}, tools={"patient_reader"})
    condition2 = PluginCondition(server_ids={"prod"}, user_patterns=["admin"])

    payload = ToolPreInvokePayload(name="patient_reader", args={})
    context = GlobalContext(request_id="req1", tenant_id="healthcare")

    # First condition fully matches → should execute
    assert payload_matches(payload, "tool_pre_invoke", [condition1, condition2], context) is True


def test_multiple_conditions_second_matches():
    """Test that if the second condition object matches, plugin executes (OR logic)."""
    condition1 = PluginCondition(tenant_ids={"healthcare"}, tools={"patient_reader"})
    condition2 = PluginCondition(server_ids={"prod"}, user_patterns=["admin"])

    payload = ToolPreInvokePayload(name="other_tool", args={})
    context = GlobalContext(request_id="req1", server_id="prod", user="admin_alice")

    # First condition fails, second condition fully matches → should execute
    assert payload_matches(payload, "tool_pre_invoke", [condition1, condition2], context) is True


def test_multiple_conditions_none_match():
    """Test that if no condition objects match, plugin doesn't execute."""
    condition1 = PluginCondition(tenant_ids={"healthcare"}, tools={"patient_reader"})
    condition2 = PluginCondition(server_ids={"prod"}, user_patterns=["admin"])

    payload = ToolPreInvokePayload(name="other_tool", args={})
    context = GlobalContext(request_id="req1", tenant_id="finance", server_id="dev")  # Doesn't match condition1  # Doesn't match condition2

    # No condition objects match → should NOT execute
    assert payload_matches(payload, "tool_pre_invoke", [condition1, condition2], context) is False


def test_multiple_conditions_partial_matches_fail():
    """Test that partial matches in condition objects don't trigger execution."""
    condition1 = PluginCondition(tenant_ids={"healthcare"}, tools={"patient_reader"})
    condition2 = PluginCondition(server_ids={"prod"}, user_patterns=["admin"])

    # Context matches tenant from condition1 and server from condition2
    # but neither condition object fully matches
    payload = ToolPreInvokePayload(name="other_tool", args={})
    context = GlobalContext(
        request_id="req1",
        tenant_id="healthcare",  # Matches condition1 tenant
        server_id="prod",  # Matches condition2 server
        user=None,  # Explicitly set user to None - condition2 requires user pattern
    )

    # Condition1: tenant matches but tool doesn't → fails
    # Condition2: server matches but user is None (pattern required) → fails
    # Neither condition object fully matches → should NOT execute
    assert payload_matches(payload, "tool_pre_invoke", [condition1, condition2], context) is False


# ============================================================================
# Test Edge Cases
# ============================================================================


def test_empty_conditions_list_matches_all():
    """Test that empty conditions list matches all requests."""
    payload = ToolPreInvokePayload(name="any_tool", args={})
    context = GlobalContext(request_id="req1")

    # Empty conditions → should match all
    assert payload_matches(payload, "tool_pre_invoke", [], context) is True


def test_condition_with_no_fields_matches_all():
    """Test that a condition object with no fields matches all requests."""
    condition = PluginCondition()  # No fields set

    payload = ToolPreInvokePayload(name="any_tool", args={})
    context = GlobalContext(request_id="req1")

    # Condition with no fields → should match all
    assert payload_matches(payload, "tool_pre_invoke", [condition], context) is True


def test_null_values_in_context():
    """Test handling of None/null values in context."""
    condition = PluginCondition(tenant_ids={"healthcare"}, tools={"patient_reader"})

    payload = ToolPreInvokePayload(name="patient_reader", args={})
    context = GlobalContext(request_id="req1", tenant_id=None, server_id=None)  # Null tenant

    # Tenant is None, doesn't match condition → should NOT execute
    assert payload_matches(payload, "tool_pre_invoke", [condition], context) is False


def test_empty_sets_in_condition():
    """Test handling of empty sets in condition fields."""
    condition = PluginCondition(tenant_ids=set(), tools={"patient_reader"})  # Empty set

    payload = ToolPreInvokePayload(name="patient_reader", args={})
    context = GlobalContext(request_id="req1", tenant_id="healthcare")

    # Empty tenant_ids set is treated as "no constraint" → should match
    assert payload_matches(payload, "tool_pre_invoke", [condition], context) is True


# ============================================================================
# Test Breaking Change Validation
# ============================================================================


def test_breaking_change_old_or_behavior_no_longer_works():
    """Test that old OR behavior (any field match) no longer works."""
    # Old behavior: This would have matched because tenant OR tool matched
    # New behavior: This should NOT match because not all fields match
    condition = PluginCondition(tenant_ids={"healthcare"}, tools={"patient_reader"})

    # Only tenant matches, tool doesn't
    payload = ToolPreInvokePayload(name="other_tool", args={})
    context = GlobalContext(request_id="req1", tenant_id="healthcare")

    # Old OR logic would have matched (tenant matches)
    # New AND logic should NOT match (tool doesn't match)
    assert payload_matches(payload, "tool_pre_invoke", [condition], context) is False


def test_breaking_change_new_and_behavior_works():
    """Test that new AND behavior works correctly."""
    condition = PluginCondition(tenant_ids={"healthcare"}, tools={"patient_reader"})

    payload = ToolPreInvokePayload(name="patient_reader", args={})
    context = GlobalContext(request_id="req1", tenant_id="healthcare")

    # New AND logic: both tenant AND tool must match
    assert payload_matches(payload, "tool_pre_invoke", [condition], context) is True


def test_migration_pattern_separate_conditions_for_or():
    """Test migration pattern: separate condition objects for OR logic."""
    # Migration pattern: To get OR behavior, use separate condition objects
    condition1 = PluginCondition(tenant_ids={"healthcare"})
    condition2 = PluginCondition(tools={"patient_reader"})

    # Test 1: Only tenant matches
    payload1 = ToolPreInvokePayload(name="other_tool", args={})
    context1 = GlobalContext(request_id="req1", tenant_id="healthcare")
    assert payload_matches(payload1, "tool_pre_invoke", [condition1, condition2], context1) is True

    # Test 2: Only tool matches
    payload2 = ToolPreInvokePayload(name="patient_reader", args={})
    context2 = GlobalContext(request_id="req1", tenant_id="finance")
    assert payload_matches(payload2, "tool_pre_invoke", [condition1, condition2], context2) is True

    # Test 3: Both match
    payload3 = ToolPreInvokePayload(name="patient_reader", args={})
    context3 = GlobalContext(request_id="req1", tenant_id="healthcare")
    assert payload_matches(payload3, "tool_pre_invoke", [condition1, condition2], context3) is True


# ============================================================================
# Test Hook Type Coverage
# ============================================================================


def test_tool_pre_invoke_hook():
    """Test AND/OR logic for tool_pre_invoke hook."""
    condition = PluginCondition(tenant_ids={"healthcare"}, tools={"patient_reader"})

    payload = ToolPreInvokePayload(name="patient_reader", args={})
    context = GlobalContext(request_id="req1", tenant_id="healthcare")

    assert payload_matches(payload, "tool_pre_invoke", [condition], context) is True


def test_tool_post_invoke_hook():
    """Test AND/OR logic for tool_post_invoke hook."""
    condition = PluginCondition(tenant_ids={"healthcare"}, tools={"patient_reader"})

    payload = ToolPostInvokePayload(name="patient_reader", result={"data": "test"})
    context = GlobalContext(request_id="req1", tenant_id="healthcare")

    assert payload_matches(payload, "tool_post_invoke", [condition], context) is True


def test_prompt_pre_fetch_hook():
    """Test AND/OR logic for prompt_pre_fetch hook."""
    condition = PluginCondition(tenant_ids={"healthcare"}, prompts={"greeting"})

    payload = PromptPrehookPayload(prompt_id="greeting", args={})
    context = GlobalContext(request_id="req1", tenant_id="healthcare")

    assert payload_matches(payload, "prompt_pre_fetch", [condition], context) is True


def test_resource_pre_fetch_hook():
    """Test AND/OR logic for resource_pre_fetch hook."""
    condition = PluginCondition(tenant_ids={"healthcare"}, resources={"file:///data.txt"})

    payload = ResourcePreFetchPayload(uri="file:///data.txt")
    context = GlobalContext(request_id="req1", tenant_id="healthcare")

    assert payload_matches(payload, "resource_pre_fetch", [condition], context) is True


# ============================================================================
# Test Complex Scenarios
# ============================================================================


def test_complex_defense_in_depth_scenario():
    """Test complex defense-in-depth security scenario with multiple condition objects."""
    # Scenario: PII filter should execute for:
    # (healthcare tenant AND patient_reader tool) OR (prod server AND admin user)
    condition1 = PluginCondition(tenant_ids={"healthcare"}, tools={"patient_reader"})
    condition2 = PluginCondition(server_ids={"prod"}, user_patterns=["admin"])

    # Test 1: Healthcare + patient_reader → should execute
    payload1 = ToolPreInvokePayload(name="patient_reader", args={})
    context1 = GlobalContext(request_id="req1", tenant_id="healthcare")
    assert payload_matches(payload1, "tool_pre_invoke", [condition1, condition2], context1) is True

    # Test 2: Prod + admin user → should execute
    payload2 = ToolPreInvokePayload(name="any_tool", args={})
    context2 = GlobalContext(request_id="req2", server_id="prod", user="admin_alice")
    assert payload_matches(payload2, "tool_pre_invoke", [condition1, condition2], context2) is True

    # Test 3: Healthcare + other tool → should NOT execute
    payload3 = ToolPreInvokePayload(name="other_tool", args={})
    context3 = GlobalContext(request_id="req3", tenant_id="healthcare")
    assert payload_matches(payload3, "tool_pre_invoke", [condition1, condition2], context3) is False

    # Test 4: Prod + regular user → should NOT execute
    payload4 = ToolPreInvokePayload(name="any_tool", args={})
    context4 = GlobalContext(request_id="req4", server_id="prod", user="regular_user")
    assert payload_matches(payload4, "tool_pre_invoke", [condition1, condition2], context4) is False


def test_three_field_and_logic():
    """Test AND logic with three fields in one condition object."""
    condition = PluginCondition(tenant_ids={"healthcare"}, tools={"patient_reader"}, user_patterns=["doctor"])

    payload = ToolPreInvokePayload(name="patient_reader", args={})

    # All three fields match
    context_all_match = GlobalContext(request_id="req1", tenant_id="healthcare", user="doctor_smith")
    assert payload_matches(payload, "tool_pre_invoke", [condition], context_all_match) is True

    # Two fields match, one doesn't
    context_two_match = GlobalContext(request_id="req2", tenant_id="healthcare", user="nurse_jones")  # User pattern doesn't match
    assert payload_matches(payload, "tool_pre_invoke", [condition], context_two_match) is False


def test_multiple_values_in_set_fields():
    """Test that multiple values in set fields work correctly with AND logic."""
    condition = PluginCondition(tenant_ids={"healthcare", "finance", "legal"}, tools={"tool1", "tool2", "tool3"})

    # Test with first tenant and first tool
    payload1 = ToolPreInvokePayload(name="tool1", args={})
    context1 = GlobalContext(request_id="req1", tenant_id="healthcare")
    assert payload_matches(payload1, "tool_pre_invoke", [condition], context1) is True

    # Test with last tenant and last tool
    payload2 = ToolPreInvokePayload(name="tool3", args={})
    context2 = GlobalContext(request_id="req2", tenant_id="legal")
    assert payload_matches(payload2, "tool_pre_invoke", [condition], context2) is True

    # Test with tenant in set but tool not in set
    payload3 = ToolPreInvokePayload(name="other_tool", args={})
    context3 = GlobalContext(request_id="req3", tenant_id="healthcare")
    assert payload_matches(payload3, "tool_pre_invoke", [condition], context3) is False


# ============================================================================
# Test matches() function with AND logic
# ============================================================================


def test_matches_all_fields_match():
    """Test matches() with all GlobalContext fields matching."""
    condition = PluginCondition(server_ids={"srv1"}, tenant_ids={"tenant1"}, user_patterns=["admin"])
    context = GlobalContext(request_id="req1", server_id="srv1", tenant_id="tenant1", user="admin_user")

    assert matches(condition, context) is True


def test_matches_one_field_mismatch():
    """Test matches() fails if one field doesn't match."""
    condition = PluginCondition(server_ids={"srv1"}, tenant_ids={"tenant1"}, user_patterns=["admin"])

    # Server matches, tenant matches, user doesn't
    context = GlobalContext(request_id="req1", server_id="srv1", tenant_id="tenant1", user="regular_user")

    assert matches(condition, context) is False


def test_matches_no_conditions_matches_all():
    """Test matches() with no conditions set matches all."""
    condition = PluginCondition()
    context = GlobalContext(request_id="req1")

    assert matches(condition, context) is True


# ============================================================================
# Test Fail-Fast Optimization
# ============================================================================


def test_fail_fast_within_condition_object():
    """Test that evaluation stops at first non-matching field within a condition object."""
    # This is more of a behavioral test - we can't directly test short-circuiting
    # but we can verify the result is correct
    condition = PluginCondition(server_ids={"srv1"}, tenant_ids={"tenant1"}, tools={"tool1"})  # This will fail

    payload = ToolPreInvokePayload(name="tool1", args={})
    context = GlobalContext(request_id="req1", server_id="srv2", tenant_id="tenant1")  # Doesn't match

    # Should fail fast on server_id mismatch
    assert payload_matches(payload, "tool_pre_invoke", [condition], context) is False


def test_fail_fast_across_condition_objects():
    """Test that evaluation stops at first fully matching condition object."""
    condition1 = PluginCondition(tools={"tool1"})  # This will match
    condition2 = PluginCondition(tools={"tool2"})  # This won't be evaluated

    payload = ToolPreInvokePayload(name="tool1", args={})
    context = GlobalContext(request_id="req1")

    # Should match on first condition and not evaluate second
    assert payload_matches(payload, "tool_pre_invoke", [condition1, condition2], context) is True
