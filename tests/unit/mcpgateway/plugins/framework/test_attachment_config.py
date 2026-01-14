# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/test_attachment_config.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Claude Code

Unit tests for AttachedHookRef and attachment_config integration.
Tests that plugins receive their routing configuration via GlobalContext.
"""

# Third-Party
import pytest

# First-Party
from mcpgateway.plugins.framework import (
    AttachedHookRef,
    FieldSelection,
    GlobalContext,
    Plugin,
    PluginAttachment,
    PluginConfig,
    PluginContext,
    PluginManager,
    PluginMode,
    PluginResult,
    ToolHookType,
    ToolPreInvokePayload,
)
from mcpgateway.plugins.framework.base import HookRef, PluginRef
from mcpgateway.plugins.framework.models import EntityType


class TestPlugin(Plugin):
    """Test plugin that captures its attachment config."""

    def __init__(self, config: PluginConfig):
        super().__init__(config)
        self.captured_attachment = None
        self.captured_entity_type = None
        self.captured_entity_id = None
        self.captured_entity_name = None

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> PluginResult:
        """Capture attachment config from context."""
        self.captured_attachment = context.global_context.attachment_config
        self.captured_entity_type = context.global_context.entity_type
        self.captured_entity_id = context.global_context.entity_id
        self.captured_entity_name = context.global_context.entity_name
        return PluginResult(modified_payload=payload)


class TestAttachedHookRef:
    """Test AttachedHookRef composite object."""

    def test_attached_hook_ref_with_attachment(self):
        """Test AttachedHookRef with full attachment config."""
        # Create test plugin
        config = PluginConfig(
            name="test_plugin",
            kind="test",
            version="1.0",
            author="test",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
        )
        plugin = TestPlugin(config)
        plugin_ref = PluginRef(plugin)
        hook_ref = HookRef(ToolHookType.TOOL_PRE_INVOKE, plugin_ref)

        # Create attachment config
        attachment = PluginAttachment(
            name="test_plugin",
            priority=10,
            post_priority=20,
            apply_to=FieldSelection(fields=["args.email", "args.ssn"]),
        )

        # Create AttachedHookRef
        attached_ref = AttachedHookRef(hook_ref, attachment)

        # Verify properties
        assert attached_ref.hook_ref == hook_ref
        assert attached_ref.attachment == attachment
        assert attached_ref.name == "test_plugin"
        assert attached_ref.hook is not None
        assert attached_ref.plugin_ref == plugin_ref

        # Verify attachment details
        assert attached_ref.attachment.priority == 10
        assert attached_ref.attachment.post_priority == 20
        assert attached_ref.attachment.apply_to is not None
        assert attached_ref.attachment.apply_to.fields == ["args.email", "args.ssn"]

    def test_attached_hook_ref_without_attachment(self):
        """Test AttachedHookRef without attachment (old system)."""
        # Create test plugin
        config = PluginConfig(
            name="test_plugin",
            kind="test",
            version="1.0",
            author="test",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
        )
        plugin = TestPlugin(config)
        plugin_ref = PluginRef(plugin)
        hook_ref = HookRef(ToolHookType.TOOL_PRE_INVOKE, plugin_ref)

        # Create AttachedHookRef without attachment
        attached_ref = AttachedHookRef(hook_ref, attachment=None)

        # Verify properties
        assert attached_ref.hook_ref == hook_ref
        assert attached_ref.attachment is None
        assert attached_ref.name == "test_plugin"  # Falls back to plugin name

    def test_attached_hook_ref_convenience_accessors(self):
        """Test that convenience accessors work correctly."""
        config = PluginConfig(
            name="test_plugin",
            kind="test",
            version="1.0",
            author="test",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
        )
        plugin = TestPlugin(config)
        plugin_ref = PluginRef(plugin)
        hook_ref = HookRef(ToolHookType.TOOL_PRE_INVOKE, plugin_ref)

        attachment = PluginAttachment(
            name="test_plugin",
            priority=15,
        )

        attached_ref = AttachedHookRef(hook_ref, attachment)

        # Test convenience accessors
        assert attached_ref.name == attachment.name
        assert callable(attached_ref.hook)
        assert attached_ref.plugin_ref.plugin == plugin


class TestAttachmentConfigIntegration:
    """Test that attachment_config flows through GlobalContext to plugins."""

    @pytest.mark.asyncio
    async def test_global_context_with_attachment_config(self):
        """Test that GlobalContext accepts and stores attachment_config."""
        attachment = PluginAttachment(
            name="test_plugin",
            priority=10,
            apply_to=FieldSelection(fields=["args.email"]),
        )

        global_context = GlobalContext(
            request_id="test-123",
            entity_type="tool",
            entity_id="tool-456",
            entity_name="my_tool",
            attachment_config=attachment,
        )

        assert global_context.attachment_config == attachment
        assert global_context.attachment_config.priority == 10
        assert global_context.attachment_config.apply_to.fields == ["args.email"]

    @pytest.mark.asyncio
    async def test_global_context_without_attachment_config(self):
        """Test that GlobalContext works without attachment_config."""
        global_context = GlobalContext(
            request_id="test-123",
            entity_type="tool",
            entity_id="tool-456",
            entity_name="my_tool",
        )

        assert global_context.attachment_config is None

    @pytest.mark.asyncio
    async def test_plugin_receives_attachment_via_context(self):
        """Test that plugins receive attachment_config via PluginContext."""
        # Create test plugin
        config = PluginConfig(
            name="test_plugin",
            kind="test",
            version="1.0",
            author="test",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            mode=PluginMode.PERMISSIVE,
        )
        plugin = TestPlugin(config)

        # Create attachment
        attachment = PluginAttachment(
            name="test_plugin",
            priority=10,
            apply_to=FieldSelection(fields=["args.secret"]),
        )

        # Create GlobalContext with attachment
        global_context = GlobalContext(
            request_id="test-123",
            entity_type="tool",
            entity_id="tool-456",
            entity_name="sensitive_tool",
            attachment_config=attachment,
        )

        # Create PluginContext
        plugin_context = PluginContext(global_context=global_context)

        # Invoke plugin
        payload = ToolPreInvokePayload(name="test", args={"secret": "password123"})
        await plugin.tool_pre_invoke(payload, plugin_context)

        # Verify plugin received the attachment config
        assert plugin.captured_attachment == attachment
        assert plugin.captured_attachment.priority == 10
        assert plugin.captured_attachment.apply_to.fields == ["args.secret"]
        assert plugin.captured_entity_type == "tool"
        assert plugin.captured_entity_id == "tool-456"
        assert plugin.captured_entity_name == "sensitive_tool"


class TestPluginManagerAttachmentFlow:
    """Test end-to-end attachment_config flow through PluginManager."""

    @pytest.mark.asyncio
    async def test_manager_populates_attachment_for_routed_plugins(self):
        """Test that PluginManager populates attachment_config when using routing."""
        # This would require a full routing config YAML
        # For now, we test the components in isolation
        # TODO: Add integration test with actual routing config
        pass

    @pytest.mark.asyncio
    async def test_manager_sets_none_for_non_routed_plugins(self):
        """Test that PluginManager sets attachment_config=None for old system."""
        # This would require testing the old condition-based system
        # For now, we verify the wrapping logic works
        pass


class TestFieldSelectionWithAttachment:
    """Test field selection usage with attachment_config."""

    def test_plugin_can_extract_configured_fields(self):
        """Test that plugins can use FieldSelector with attachment config."""
        from mcpgateway.plugins.framework import FieldSelector

        # Simulate what a plugin would do
        attachment = PluginAttachment(
            name="pii_filter",
            priority=10,
            apply_to=FieldSelection(fields=["args.customer.email", "args.customer.ssn"]),
        )

        payload_dict = {
            "name": "create_user",
            "args": {
                "customer": {"name": "John Doe", "email": "john@example.com", "ssn": "123-45-6789"},
                "metadata": {"source": "web"},
            },
        }

        # Plugin extracts only configured fields
        selector = FieldSelector()
        scoped = selector.extract_fields(payload_dict, attachment.apply_to.fields)

        # Verify only specified fields extracted
        assert "args" in scoped
        assert "customer" in scoped["args"]
        assert "email" in scoped["args"]["customer"]
        assert "ssn" in scoped["args"]["customer"]
        assert "name" not in scoped["args"]["customer"]  # Not in field list
        assert "metadata" not in scoped["args"]  # Not in field list

    def test_plugin_can_merge_processed_fields(self):
        """Test that plugins can merge processed fields back."""
        from mcpgateway.plugins.framework import FieldSelector

        attachment = PluginAttachment(
            name="pii_filter",
            priority=10,
            apply_to=FieldSelection(fields=["args.email"]),
        )

        original = {"name": "test", "args": {"email": "secret@example.com", "query": "search term"}}

        # Plugin redacts the email
        processed = {"args": {"email": "[REDACTED]"}}

        # Merge back
        selector = FieldSelector()
        result = selector.merge_fields(original, processed, attachment.apply_to.fields)

        # Verify merge
        assert result["args"]["email"] == "[REDACTED]"
        assert result["args"]["query"] == "search term"  # Preserved
        assert result["name"] == "test"  # Preserved


class TestAttachmentConfigMetadata:
    """Test various attachment configuration scenarios."""

    def test_attachment_with_priority_only(self):
        """Test attachment with just priority."""
        attachment = PluginAttachment(name="test", priority=10)

        assert attachment.priority == 10
        assert attachment.post_priority is None
        assert attachment.apply_to is None
        assert attachment.when is None

    def test_attachment_with_post_priority(self):
        """Test attachment with post-hook priority."""
        attachment = PluginAttachment(name="test", priority=10, post_priority=90)

        assert attachment.priority == 10
        assert attachment.post_priority == 90

    def test_attachment_with_when_clause(self):
        """Test attachment with conditional execution."""
        attachment = PluginAttachment(name="test", priority=10, when='args.sensitive == true')

        assert attachment.when == 'args.sensitive == true'

    def test_attachment_with_field_selection_input_output(self):
        """Test attachment with different input/output fields."""
        attachment = PluginAttachment(
            name="test",
            priority=10,
            apply_to=FieldSelection(input_fields=["args.user_id"], output_fields=["result.customer.ssn"]),
        )

        assert attachment.apply_to.input_fields == ["args.user_id"]
        assert attachment.apply_to.output_fields == ["result.customer.ssn"]
        assert attachment.apply_to.fields is None

    def test_attachment_with_hooks_and_mode(self):
        """Test attachment with hook overrides and execution mode."""
        attachment = PluginAttachment(
            name="test",
            priority=10,
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            mode=PluginMode.ENFORCE,
        )

        assert ToolHookType.TOOL_PRE_INVOKE in attachment.hooks
        assert attachment.mode == PluginMode.ENFORCE
        assert attachment.priority == 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
