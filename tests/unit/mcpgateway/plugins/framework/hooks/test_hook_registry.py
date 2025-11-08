# -*- coding: utf-8 -*-
"""
Copyright 2025 © IBM Corporation
SPDX-License-Identifier: Apache-2.0

Test suite for hook registry functionality.
"""

# Third-Party
import pytest

# First-Party
from mcpgateway.plugins.framework import (
    get_hook_registry,
    AgentHookType,
    PromptHookType,
    ResourceHookType,
    ToolHookType,
    PromptPrehookPayload,
    PromptPrehookResult,
    PromptPosthookPayload,
    PromptPosthookResult,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
)


class TestHookRegistry:
    """Test cases for the HookRegistry class."""

    @pytest.fixture
    def registry(self):
        """Provide a hook registry instance."""
        return get_hook_registry()

    def test_mcp_hooks_are_registered(self, registry):
        """Test that all MCP hooks are registered."""
        assert registry.is_registered(PromptHookType.PROMPT_PRE_FETCH)
        assert registry.is_registered(PromptHookType.PROMPT_POST_FETCH)
        assert registry.is_registered(ToolHookType.TOOL_PRE_INVOKE)
        assert registry.is_registered(ToolHookType.TOOL_POST_INVOKE)
        assert registry.is_registered(ResourceHookType.RESOURCE_PRE_FETCH)
        assert registry.is_registered(ResourceHookType.RESOURCE_POST_FETCH)

    def test_get_payload_type(self, registry):
        """Test retrieving payload types from registry."""
        payload_type = registry.get_payload_type(PromptHookType.PROMPT_PRE_FETCH)
        assert payload_type == PromptPrehookPayload

        payload_type = registry.get_payload_type(PromptHookType.PROMPT_POST_FETCH)
        assert payload_type == PromptPosthookPayload

        payload_type = registry.get_payload_type(ToolHookType.TOOL_PRE_INVOKE)
        assert payload_type == ToolPreInvokePayload

    def test_get_result_type(self, registry):
        """Test retrieving result types from registry."""
        result_type = registry.get_result_type(PromptHookType.PROMPT_PRE_FETCH)
        assert result_type == PromptPrehookResult

        result_type = registry.get_result_type(PromptHookType.PROMPT_POST_FETCH)
        assert result_type == PromptPosthookResult

        result_type = registry.get_result_type(ToolHookType.TOOL_PRE_INVOKE)
        assert result_type == ToolPreInvokeResult

    def test_get_unregistered_hook_returns_none(self, registry):
        """Test that unregistered hooks return None."""
        assert registry.get_payload_type("unknown_hook") is None
        assert registry.get_result_type("unknown_hook") is None
        assert not registry.is_registered("unknown_hook")

    def test_json_to_payload_with_dict(self, registry):
        """Test converting dictionary to payload."""
        payload_dict = {"prompt_id": "test", "args": {"key": "value"}}
        payload = registry.json_to_payload(PromptHookType.PROMPT_PRE_FETCH, payload_dict)

        assert isinstance(payload, PromptPrehookPayload)
        assert payload.prompt_id == "test"
        assert payload.args["key"] == "value"

    def test_json_to_payload_with_json_string(self, registry):
        """Test converting JSON string to payload."""
        payload_json = '{"prompt_id": "test", "args": {"key": "value"}}'
        payload = registry.json_to_payload(PromptHookType.PROMPT_PRE_FETCH, payload_json)

        assert isinstance(payload, PromptPrehookPayload)
        assert payload.prompt_id == "test"
        assert payload.args["key"] == "value"

    def test_json_to_result_with_dict(self, registry):
        """Test converting dictionary to result."""
        result_dict = {"continue_processing": True, "modified_payload": None}
        result = registry.json_to_result(PromptHookType.PROMPT_PRE_FETCH, result_dict)

        assert isinstance(result, PromptPrehookResult)
        assert result.continue_processing is True

    def test_json_to_result_with_json_string(self, registry):
        """Test converting JSON string to result."""
        result_json = '{"continue_processing": false, "modified_payload": null}'
        result = registry.json_to_result(PromptHookType.PROMPT_PRE_FETCH, result_json)

        assert isinstance(result, PromptPrehookResult)
        assert result.continue_processing is False

    def test_json_to_payload_unregistered_hook_raises_error(self, registry):
        """Test that converting payload for unregistered hook raises ValueError."""
        with pytest.raises(ValueError, match="No payload type registered for hook"):
            registry.json_to_payload("unknown_hook", {})

    def test_json_to_result_unregistered_hook_raises_error(self, registry):
        """Test that converting result for unregistered hook raises ValueError."""
        with pytest.raises(ValueError, match="No result type registered for hook"):
            registry.json_to_result("unknown_hook", {})

    def test_get_registered_hooks(self, registry):
        """Test retrieving all registered hook types."""
        hooks = registry.get_registered_hooks()

        assert isinstance(hooks, list)
        assert len(hooks) >= 8  # At least the 6 MCP hooks
        assert PromptHookType.PROMPT_PRE_FETCH in hooks
        assert PromptHookType.PROMPT_POST_FETCH in hooks
        assert ToolHookType.TOOL_PRE_INVOKE in hooks
        assert ToolHookType.TOOL_POST_INVOKE in hooks
        assert ResourceHookType.RESOURCE_PRE_FETCH in hooks
        assert ResourceHookType.RESOURCE_POST_FETCH in hooks
        assert AgentHookType.AGENT_POST_INVOKE in hooks
        assert AgentHookType.AGENT_PRE_INVOKE in hooks

    def test_registry_is_singleton(self):
        """Test that get_hook_registry returns the same instance."""
        registry1 = get_hook_registry()
        registry2 = get_hook_registry()

        assert registry1 is registry2
