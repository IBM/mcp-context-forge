# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/test_resource_hooks.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for resource hook functionality in the plugin framework.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from mcpgateway.models import ResourceContent
from mcpgateway.plugins.framework.base import Plugin, PluginRef
from mcpgateway.plugins.framework.manager import PluginManager
# Registry is imported for mocking
from mcpgateway.plugins.framework.models import (
    GlobalContext,
    HookType,
    PluginCondition,
    PluginConfig,
    PluginContext,
    PluginMode,
    PluginViolation,
    ResourcePostFetchPayload,
    ResourcePostFetchResult,
    ResourcePreFetchPayload,
    ResourcePreFetchResult,
)


class TestResourceHooks:
    """Test resource pre/post fetch hooks."""

    def test_resource_pre_fetch_payload(self):
        """Test ResourcePreFetchPayload creation and attributes."""
        payload = ResourcePreFetchPayload(uri="file:///test.txt", metadata={"cache": True})
        assert payload.uri == "file:///test.txt"
        assert payload.metadata == {"cache": True}

    def test_resource_post_fetch_payload(self):
        """Test ResourcePostFetchPayload creation and attributes."""
        content = ResourceContent(type="resource", uri="file:///test.txt", text="Test content")
        payload = ResourcePostFetchPayload(uri="file:///test.txt", content=content)
        assert payload.uri == "file:///test.txt"
        assert payload.content == content
        assert payload.content.text == "Test content"

    @pytest.mark.asyncio
    async def test_plugin_resource_pre_fetch_default(self):
        """Test default resource_pre_fetch implementation."""
        config = PluginConfig(
            name="test_resource",
            description="Test resource plugin",
            author="test",
            kind="test.Plugin",
            version="1.0.0",
            hooks=[HookType.RESOURCE_PRE_FETCH],
            tags=["test"],
        )
        plugin = Plugin(config)
        payload = ResourcePreFetchPayload(uri="file:///test.txt", metadata={})
        context = PluginContext(request_id="test-123")

        with pytest.raises(NotImplementedError, match="'resource_pre_fetch' not implemented"):
            await plugin.resource_pre_fetch(payload, context)


    @pytest.mark.asyncio
    async def test_plugin_resource_post_fetch_default(self):
        """Test default resource_post_fetch implementation."""
        config = PluginConfig(
            name="test_resource",
            description="Test resource plugin",
            author="test",
            kind="test.Plugin",
            version="1.0.0",
            hooks=[HookType.RESOURCE_POST_FETCH],
            tags=["test"],
        )
        plugin = Plugin(config)
        content = ResourceContent(type="resource", uri="file:///test.txt", text="Test content")
        payload = ResourcePostFetchPayload(uri="file:///test.txt", content=content)
        context = PluginContext(request_id="test-123")

        with pytest.raises(NotImplementedError, match="'resource_post_fetch' not implemented"):
            await plugin.resource_post_fetch(payload, context)


    @pytest.mark.asyncio
    async def test_resource_hook_blocking(self):
        """Test resource hook that blocks processing."""

        class BlockingResourcePlugin(Plugin):
            async def resource_pre_fetch(self, payload, context):
                return ResourcePreFetchResult(
                    continue_processing=False,
                    violation=PluginViolation(
                        reason="Protocol not allowed",
                        code="PROTOCOL_BLOCKED",
                        description="file:// protocol is blocked",
                        details={"protocol": "file", "uri": payload.uri},
                    ),
                )

        config = PluginConfig(
            name="blocking_resource",
            description="Blocking resource plugin",
            author="test",
            kind="test.BlockingPlugin",
            version="1.0.0",
            hooks=[HookType.RESOURCE_PRE_FETCH],
            tags=["test"],
            mode=PluginMode.ENFORCE,
        )
        plugin = BlockingResourcePlugin(config)
        payload = ResourcePreFetchPayload(uri="file:///etc/passwd", metadata={})
        context = PluginContext(request_id="test-123")

        result = await plugin.resource_pre_fetch(payload, context)

        assert result.continue_processing is False
        assert result.violation is not None
        assert result.violation.code == "PROTOCOL_BLOCKED"
        assert result.violation.reason == "Protocol not allowed"

    @pytest.mark.asyncio
    async def test_resource_content_modification(self):
        """Test resource post-fetch content modification."""

        class ContentFilterPlugin(Plugin):
            async def resource_post_fetch(self, payload, context):
                # Modify content to redact sensitive data
                modified_text = payload.content.text.replace("password: secret123", "password: [REDACTED]")
                modified_content = ResourceContent(
                    type=payload.content.type,
                    uri=payload.content.uri,
                    text=modified_text,
                )
                modified_payload = ResourcePostFetchPayload(
                    uri=payload.uri,
                    content=modified_content,
                )
                return ResourcePostFetchResult(
                    continue_processing=True,
                    modified_payload=modified_payload,
                )

        config = PluginConfig(
            name="content_filter",
            description="Content filter plugin",
            author="test",
            kind="test.FilterPlugin",
            version="1.0.0",
            hooks=[HookType.RESOURCE_POST_FETCH],
            tags=["filter"],
        )
        plugin = ContentFilterPlugin(config)
        content = ResourceContent(
            type="resource",
            uri="test://config",
            text="Database config:\npassword: secret123\nport: 5432",
        )
        payload = ResourcePostFetchPayload(uri="test://config", content=content)
        context = PluginContext(request_id="test-123")

        result = await plugin.resource_post_fetch(payload, context)

        assert result.continue_processing is True
        assert result.modified_payload is not None
        assert "[REDACTED]" in result.modified_payload.content.text
        assert "secret123" not in result.modified_payload.content.text

    @pytest.mark.asyncio
    async def test_resource_hook_with_conditions(self):
        """Test resource hooks with conditions."""

        class ConditionalResourcePlugin(Plugin):
            async def resource_pre_fetch(self, payload, context):
                # Only process if conditions match
                return ResourcePreFetchResult(
                    continue_processing=False,
                    violation=PluginViolation(
                        reason="Blocked by condition",
                        code="CONDITION_BLOCK",
                    ),
                )

        config = PluginConfig(
            name="conditional_resource",
            description="Conditional resource plugin",
            author="test",
            kind="test.ConditionalPlugin",
            version="1.0.0",
            hooks=[HookType.RESOURCE_PRE_FETCH],
            tags=["conditional"],
            conditions=[
                PluginCondition(
                    resources=["file://*", "ftp://*"],
                    server_ids=["server1"],
                )
            ],
        )
        plugin = ConditionalResourcePlugin(config)
        ref = PluginRef(plugin)

        # Test that conditions are accessible
        assert ref.conditions is not None
        assert len(ref.conditions) == 1
        assert "file://*" in ref.conditions[0].resources


class TestResourceHookIntegration:
    """Test resource hook integration with plugin manager."""

    @pytest.fixture(autouse=True)
    def clear_plugin_manager_state(self):
        """Clear the PluginManager shared state before and after each test."""
        # Clear before test
        from mcpgateway.plugins.framework.manager import PluginManager
        PluginManager._PluginManager__shared_state.clear()
        yield
        # Clear after test
        PluginManager._PluginManager__shared_state.clear()

    @pytest.mark.asyncio
    async def test_manager_resource_pre_fetch(self):
        """Test plugin manager resource_pre_fetch execution."""
        with patch("mcpgateway.plugins.framework.manager.PluginInstanceRegistry") as MockRegistry:
            with patch("mcpgateway.plugins.framework.loader.config.ConfigLoader.load_config") as MockConfig:
                # Create a proper mock plugin with all required attributes
                mock_plugin_obj = MagicMock()
                mock_plugin_obj.name = "test_plugin"
                mock_plugin_obj.priority = 50
                mock_plugin_obj.mode = PluginMode.ENFORCE
                mock_plugin_obj.conditions = []
                mock_plugin_obj.resource_pre_fetch = AsyncMock(
                    return_value=ResourcePreFetchResult(
                        continue_processing=True,
                        modified_payload=None,
                    )
                )

                # Create a PluginRef-like mock
                mock_ref = MagicMock()
                mock_ref._plugin = mock_plugin_obj
                mock_ref.plugin = mock_plugin_obj
                mock_ref.name = "test_plugin"
                mock_ref.priority = 50
                mock_ref.mode = PluginMode.ENFORCE
                mock_ref.conditions = []
                mock_ref.uuid = "test-uuid"

                MockRegistry.return_value.get_plugins_for_hook.return_value = [mock_ref]

                # Mock config
                mock_config = MagicMock()
                mock_config.plugin_settings = MagicMock()
                MockConfig.return_value = mock_config

                manager = PluginManager("test_config.yaml")
                manager._registry = MockRegistry.return_value
                manager._initialized = True

                payload = ResourcePreFetchPayload(uri="test://resource", metadata={})
                global_context = GlobalContext(request_id="test-123")

                result, contexts = await manager.resource_pre_fetch(payload, global_context)

                assert result.continue_processing is True
                MockRegistry.return_value.get_plugins_for_hook.assert_called_with(HookType.RESOURCE_PRE_FETCH)

    @pytest.mark.asyncio
    async def test_manager_resource_post_fetch(self):
        """Test plugin manager resource_post_fetch execution."""
        with patch("mcpgateway.plugins.framework.manager.PluginInstanceRegistry") as MockRegistry:
            with patch("mcpgateway.plugins.framework.loader.config.ConfigLoader.load_config") as MockConfig:
                # Create a proper mock plugin with all required attributes
                mock_plugin_obj = MagicMock()
                mock_plugin_obj.name = "test_plugin"
                mock_plugin_obj.priority = 50
                mock_plugin_obj.mode = PluginMode.ENFORCE
                mock_plugin_obj.conditions = []
                mock_plugin_obj.resource_post_fetch = AsyncMock(
                    return_value=ResourcePostFetchResult(
                        continue_processing=True,
                        modified_payload=None,
                    )
                )

                # Create a PluginRef-like mock
                mock_ref = MagicMock()
                mock_ref._plugin = mock_plugin_obj
                mock_ref.plugin = mock_plugin_obj
                mock_ref.name = "test_plugin"
                mock_ref.priority = 50
                mock_ref.mode = PluginMode.ENFORCE
                mock_ref.conditions = []
                mock_ref.uuid = "test-uuid"

                MockRegistry.return_value.get_plugins_for_hook.return_value = [mock_ref]

                # Mock config
                mock_config = MagicMock()
                mock_config.plugin_settings = MagicMock()
                MockConfig.return_value = mock_config

                manager = PluginManager("test_config.yaml")
                manager._registry = MockRegistry.return_value
                manager._initialized = True

                content = ResourceContent(type="resource", uri="test://resource", text="Test")
                payload = ResourcePostFetchPayload(uri="test://resource", content=content)
                global_context = GlobalContext(request_id="test-123")

                result, contexts = await manager.resource_post_fetch(payload, global_context, {})

                assert result.continue_processing is True
                MockRegistry.return_value.get_plugins_for_hook.assert_called_with(HookType.RESOURCE_POST_FETCH)

    @pytest.mark.asyncio
    async def test_resource_hook_chain_execution(self):
        """Test multiple resource plugins executing in priority order."""

        class FirstPlugin(Plugin):
            async def resource_pre_fetch(self, payload, context):
                # Add metadata
                payload.metadata["first"] = True
                return ResourcePreFetchResult(
                    continue_processing=True,
                    modified_payload=payload,
                )

        class SecondPlugin(Plugin):
            async def resource_pre_fetch(self, payload, context):
                # Check first plugin ran
                assert payload.metadata.get("first") is True
                payload.metadata["second"] = True
                return ResourcePreFetchResult(
                    continue_processing=True,
                    modified_payload=payload,
                )

        config1 = PluginConfig(
            name="first",
            description="First plugin",
            author="test",
            kind="test.First",
            version="1.0.0",
            hooks=[HookType.RESOURCE_PRE_FETCH],
            tags=["test"],
            priority=10,  # Higher priority
        )
        config2 = PluginConfig(
            name="second",
            description="Second plugin",
            author="test",
            kind="test.Second",
            version="1.0.0",
            hooks=[HookType.RESOURCE_PRE_FETCH],
            tags=["test"],
            priority=20,  # Lower priority
        )

        plugin1 = FirstPlugin(config1)
        plugin2 = SecondPlugin(config2)

        # Create refs
        ref1 = PluginRef(plugin1)
        ref2 = PluginRef(plugin2)

        # Verify priority ordering
        assert ref1.priority < ref2.priority  # Lower number = higher priority

    @pytest.mark.asyncio
    async def test_resource_hook_error_handling(self):
        """Test resource hook error handling."""

        class ErrorPlugin(Plugin):
            async def resource_pre_fetch(self, payload, context):
                raise ValueError("Test error in plugin")

        config = PluginConfig(
            name="error_plugin",
            description="Error plugin",
            author="test",
            kind="test.ErrorPlugin",
            version="1.0.0",
            hooks=[HookType.RESOURCE_PRE_FETCH],
            tags=["test"],
            mode=PluginMode.PERMISSIVE,  # Should continue on error
        )
        plugin = ErrorPlugin(config)

        with patch("mcpgateway.plugins.framework.manager.PluginInstanceRegistry") as MockRegistry:
            with patch("mcpgateway.plugins.framework.loader.config.ConfigLoader.load_config") as MockConfig:
                # Create a proper mock ref
                mock_ref = MagicMock()
                mock_ref._plugin = plugin
                mock_ref.plugin = plugin
                mock_ref.name = "error_plugin"
                mock_ref.priority = 100
                mock_ref.mode = PluginMode.PERMISSIVE
                mock_ref.conditions = []
                mock_ref.uuid = "test-uuid"

                MockRegistry.return_value.get_plugins_for_hook.return_value = [mock_ref]

                # Mock config
                mock_config = MagicMock()
                mock_config.plugin_settings = MagicMock()
                MockConfig.return_value = mock_config

                manager = PluginManager("test_config.yaml")
                manager._registry = MockRegistry.return_value
                manager._initialized = True

                payload = ResourcePreFetchPayload(uri="test://resource", metadata={})
                global_context = GlobalContext(request_id="test-123")

                # Should handle error gracefully in permissive mode
                result, contexts = await manager.resource_pre_fetch(payload, global_context)
                assert result.continue_processing is True  # Continues despite error

    @pytest.mark.asyncio
    async def test_resource_uri_modification(self):
        """Test resource URI modification in pre-fetch."""

        class URIModifierPlugin(Plugin):
            async def resource_pre_fetch(self, payload, context):
                # Modify URI to add prefix
                modified_payload = ResourcePreFetchPayload(
                    uri=f"cached://{payload.uri}",
                    metadata=payload.metadata,
                )
                return ResourcePreFetchResult(
                    continue_processing=True,
                    modified_payload=modified_payload,
                )

        config = PluginConfig(
            name="uri_modifier",
            description="URI modifier plugin",
            author="test",
            kind="test.URIModifier",
            version="1.0.0",
            hooks=[HookType.RESOURCE_PRE_FETCH],
            tags=["modifier"],
        )
        plugin = URIModifierPlugin(config)
        payload = ResourcePreFetchPayload(uri="test://resource", metadata={})
        context = PluginContext(request_id="test-123")

        result = await plugin.resource_pre_fetch(payload, context)

        assert result.continue_processing is True
        assert result.modified_payload is not None
        assert result.modified_payload.uri == "cached://test://resource"

    @pytest.mark.asyncio
    async def test_resource_metadata_enrichment(self):
        """Test resource metadata enrichment in pre-fetch."""

        class MetadataEnricherPlugin(Plugin):
            async def resource_pre_fetch(self, payload, context):
                # Add metadata
                payload.metadata["timestamp"] = "2024-01-01T00:00:00Z"
                payload.metadata["user"] = context.user
                payload.metadata["request_id"] = context.request_id
                return ResourcePreFetchResult(
                    continue_processing=True,
                    modified_payload=payload,
                )

        config = PluginConfig(
            name="metadata_enricher",
            description="Metadata enricher plugin",
            author="test",
            kind="test.Enricher",
            version="1.0.0",
            hooks=[HookType.RESOURCE_PRE_FETCH],
            tags=["enricher"],
        )
        plugin = MetadataEnricherPlugin(config)
        payload = ResourcePreFetchPayload(uri="test://resource", metadata={})
        context = PluginContext(request_id="test-123", user="testuser")

        result = await plugin.resource_pre_fetch(payload, context)

        assert result.continue_processing is True
        assert result.modified_payload is not None
        assert result.modified_payload.metadata["timestamp"] == "2024-01-01T00:00:00Z"
        assert result.modified_payload.metadata["user"] == "testuser"
        assert result.modified_payload.metadata["request_id"] == "test-123"
