# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_resource_service_plugins.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for ResourceService plugin integration.
"""

# Standard
import os
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.models import ResourceContent
from mcpgateway.services.resource_service import ResourceNotFoundError, ResourceService
from mcpgateway.plugins.framework import PluginError, PluginErrorModel, PluginViolation, PluginViolationError



class TestResourceServicePluginIntegration:
    """Test ResourceService integration with plugin framework."""

    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        return MagicMock(spec=Session)

    @pytest.fixture
    def resource_service(self):
        """Create a ResourceService instance without plugins."""
        with patch.dict(os.environ, {"PLUGINS_ENABLED": "false"}):
            return ResourceService()

    @pytest.fixture
    def resource_service_with_plugins(self):
        """Create a ResourceService instance with plugins enabled."""
        with patch.dict(os.environ, {"PLUGINS_ENABLED": "true", "PLUGIN_CONFIG_FILE": "test_config.yaml"}):
            with patch("mcpgateway.services.resource_service.PluginManager") as MockPluginManager:
                mock_manager = MagicMock()
                mock_manager._initialized = False
                mock_manager.initialize = AsyncMock()
                MockPluginManager.return_value = mock_manager
                service = ResourceService()
                service._plugin_manager = mock_manager
                return service

    @pytest.mark.asyncio
    async def test_read_resource_without_plugins(self, resource_service, mock_db):
        """Test read_resource without plugin integration."""
        # Setup mock resource
        mock_resource = MagicMock()
        mock_resource.content = ResourceContent(
            type="resource",
            uri="test://resource",
            text="Test content",
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_resource

        result = await resource_service.read_resource(mock_db, "test://resource")

        assert result == mock_resource.content
        assert resource_service._plugin_manager is None

    @pytest.mark.asyncio
    async def test_read_resource_with_pre_fetch_hook(self, resource_service_with_plugins, mock_db):
        """Test read_resource with pre-fetch hook execution."""
        service = resource_service_with_plugins
        mock_manager = service._plugin_manager

        # Setup mock resource
        mock_resource = MagicMock()
        mock_resource.content = ResourceContent(
            type="resource",
            uri="test://resource",
            text="Test content",
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_resource

        # Setup pre-fetch hook response
        mock_manager.resource_pre_fetch = AsyncMock(
            return_value=(
                MagicMock(
                    continue_processing=True,
                    modified_payload=None,
                    violation=None,
                ),
                {"context": "data"},  # contexts
            )
        )

        # Setup post-fetch hook response
        mock_manager.resource_post_fetch = AsyncMock(
            return_value=(
                MagicMock(
                    continue_processing=True,
                    modified_payload=None,
                ),
                None,
            )
        )

        result = await service.read_resource(
            mock_db,
            "test://resource",
            request_id="test-123",
            user="testuser",
        )

        # Verify hooks were called
        mock_manager.initialize.assert_called_once()
        mock_manager.resource_pre_fetch.assert_called_once()
        mock_manager.resource_post_fetch.assert_called_once()

        # Verify context was passed correctly
        call_args = mock_manager.resource_pre_fetch.call_args
        assert call_args[0][0].uri == "test://resource"  # payload
        assert call_args[0][1].request_id == "test-123"  # global_context
        assert call_args[0][1].user == "testuser"

    @pytest.mark.asyncio
    async def test_read_resource_blocked_by_plugin(self, resource_service_with_plugins, mock_db):
        """Test read_resource blocked by pre-fetch hook."""
        service = resource_service_with_plugins
        mock_manager = service._plugin_manager

        # Setup pre-fetch hook to block
        mock_manager.resource_pre_fetch = AsyncMock(
                side_effect=PluginViolationError(message="Protocol not allowed",
                    violation=PluginViolation(
                        reason="Protocol not allowed",
                        code="PROTOCOL_BLOCKED",
                        description="file:// protocol is blocked",
                        details={"protocol": "file", "uri": "file:///etc/passwd"}
                    ),
                ),
        )

        with pytest.raises(PluginViolationError) as exc_info:
            await service.read_resource(mock_db, "file:///etc/passwd")

        assert "Protocol not allowed" in str(exc_info.value)
        mock_manager.resource_pre_fetch.assert_called_once()
        # Post-fetch should not be called if pre-fetch blocks
        mock_manager.resource_post_fetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_read_resource_uri_modified_by_plugin(self, resource_service_with_plugins, mock_db):
        """Test read_resource with URI modification by plugin."""
        service = resource_service_with_plugins
        mock_manager = service._plugin_manager

        # Setup mock resources
        mock_resource = MagicMock()
        mock_resource.content = ResourceContent(
            type="resource",
            uri="cached://test://resource",
            text="Cached content",
        )

        # First call returns None (original URI), second returns the cached resource
        mock_db.execute.return_value.scalar_one_or_none.side_effect = [mock_resource]

        # Setup pre-fetch hook to modify URI
        modified_payload = MagicMock()
        modified_payload.uri = "cached://test://resource"
        mock_manager.resource_pre_fetch = AsyncMock(
            return_value=(
                MagicMock(
                    continue_processing=True,
                    modified_payload=modified_payload,
                ),
                {"context": "data"},
            )
        )

        # Setup post-fetch hook
        mock_manager.resource_post_fetch = AsyncMock(
            return_value=(
                MagicMock(
                    continue_processing=True,
                    modified_payload=None,
                ),
                None,
            )
        )

        result = await service.read_resource(mock_db, "test://resource")

        assert result == mock_resource.content
        # Verify the modified URI was used for lookup
        mock_db.execute.assert_called()

    @pytest.mark.asyncio
    async def test_read_resource_content_filtered_by_plugin(self, resource_service_with_plugins, mock_db):
        """Test read_resource with content filtering by post-fetch hook."""
        service = resource_service_with_plugins
        mock_manager = service._plugin_manager

        # Setup mock resource with sensitive data
        mock_resource = MagicMock()
        original_content = ResourceContent(
            type="resource",
            uri="test://config",
            text="password: mysecret123\napi_key: sk-12345",
        )
        mock_resource.content = original_content
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_resource

        # Setup pre-fetch hook
        mock_manager.resource_pre_fetch = AsyncMock(
            return_value=(
                MagicMock(continue_processing=True),
                {"context": "data"},
            )
        )

        # Setup post-fetch hook to filter content
        filtered_content = ResourceContent(
            type="resource",
            uri="test://config",
            text="password: [REDACTED]\napi_key: [REDACTED]",
        )
        modified_payload = MagicMock()
        modified_payload.content = filtered_content
        mock_manager.resource_post_fetch = AsyncMock(
            return_value=(
                MagicMock(
                    continue_processing=True,
                    modified_payload=modified_payload,
                ),
                None,
            )
        )

        result = await service.read_resource(mock_db, "test://config")

        assert result == filtered_content
        assert "[REDACTED]" in result.text
        assert "mysecret123" not in result.text

    @pytest.mark.asyncio
    async def test_read_resource_plugin_error_handling(self, resource_service_with_plugins, mock_db):
        """Test read_resource handles plugin errors gracefully."""
        service = resource_service_with_plugins
        mock_manager = service._plugin_manager

        # Setup mock resource
        mock_resource = MagicMock()
        mock_resource.content = ResourceContent(
            type="resource",
            uri="test://resource",
            text="Test content",
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_resource

        # Setup pre-fetch hook to raise an error
        mock_manager.resource_pre_fetch = AsyncMock(side_effect=PluginError(error=PluginErrorModel(message="Plugin error", plugin_name="mock_plugin")))

        with pytest.raises(PluginError):
            result = await service.read_resource(mock_db, "test://resource")

        mock_manager.resource_pre_fetch.assert_called_once()

    @pytest.mark.asyncio
    async def test_read_resource_post_fetch_blocking(self, resource_service_with_plugins, mock_db):
        """Test read_resource blocked by post-fetch hook."""
        service = resource_service_with_plugins
        mock_manager = service._plugin_manager

        # Setup mock resource
        mock_resource = MagicMock()
        mock_resource.content = ResourceContent(
            type="resource",
            uri="test://resource",
            text="Sensitive content",
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_resource

        # Setup pre-fetch hook
        mock_manager.resource_pre_fetch = AsyncMock(
            return_value=(
                MagicMock(continue_processing=True),
                {"context": "data"},
            )
        )

        # Setup post-fetch hook to block
        mock_manager.resource_post_fetch = AsyncMock(
            side_effect=PluginViolationError(message="Content contains sensitive data",
                                             violation=PluginViolation(
                        reason="Content contains sensitive data",
                        description="The resource content was flagged as containing sensitive information",
                        code="SENSITIVE_CONTENT",
                        details={"uri": "test://resource"}
                        ))
        )

        with pytest.raises(PluginViolationError) as exc_info:
            await service.read_resource(mock_db, "test://resource")

        assert "Content contains sensitive data" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_read_resource_with_template(self, resource_service_with_plugins, mock_db):
        """Test read_resource with template resource and plugins."""
        service = resource_service_with_plugins
        mock_manager = service._plugin_manager

        # Setup mock resource
        mock_resource = MagicMock()
        mock_template_content = ResourceContent(
            type="resource",
            uri="test://123/data",
            text="Template content for id=123",
        )
        mock_resource.content = mock_template_content
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_resource

        # Setup hooks
        mock_manager.resource_pre_fetch = AsyncMock(
            return_value=(
                MagicMock(continue_processing=True),
                {"context": "data"},
            )
        )
        # Create a mock result with modified_payload explicitly set to None
        mock_post_result = MagicMock()
        mock_post_result.continue_processing = True
        mock_post_result.modified_payload = None

        mock_manager.resource_post_fetch = AsyncMock(
            return_value=(mock_post_result, None)
        )

        result = await service.read_resource(mock_db, "test://123/data")

        assert result == mock_template_content
        mock_manager.resource_pre_fetch.assert_called_once()
        mock_manager.resource_post_fetch.assert_called_once()

    @pytest.mark.asyncio
    async def test_read_resource_context_propagation(self, resource_service_with_plugins, mock_db):
        """Test context propagation from pre-fetch to post-fetch."""
        service = resource_service_with_plugins
        mock_manager = service._plugin_manager

        # Setup mock resource
        mock_resource = MagicMock()
        mock_resource.content = ResourceContent(
            type="resource",
            uri="test://resource",
            text="Test content",
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_resource

        # Capture contexts from pre-fetch
        test_contexts = {"plugin1": {"validated": True}}
        mock_manager.resource_pre_fetch = AsyncMock(
            return_value=(
                MagicMock(continue_processing=True),
                test_contexts,
            )
        )

        # Verify contexts passed to post-fetch
        mock_manager.resource_post_fetch = AsyncMock(
            return_value=(
                MagicMock(continue_processing=True),
                None,
            )
        )

        await service.read_resource(mock_db, "test://resource")

        # Verify contexts were passed from pre to post
        post_call_args = mock_manager.resource_post_fetch.call_args
        assert post_call_args[0][2] == test_contexts  # Third argument is contexts

    @pytest.mark.asyncio
    async def test_read_resource_inactive_resource(self, resource_service, mock_db):
        """Test read_resource with inactive resource."""
        # First query returns None (active), second returns inactive resource
        mock_inactive = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.side_effect = [None, mock_inactive]

        with pytest.raises(ResourceNotFoundError) as exc_info:
            await resource_service.read_resource(mock_db, "test://inactive")

        assert "exists but is inactive" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_plugin_manager_initialization(self):
        """Test plugin manager initialization in ResourceService."""
        with patch.dict(os.environ, {"PLUGINS_ENABLED": "true", "PLUGIN_CONFIG_FILE": "plugins/test.yaml"}):
            with patch("mcpgateway.services.resource_service.PluginManager") as MockPluginManager:
                mock_manager = MagicMock()
                MockPluginManager.return_value = mock_manager

                service = ResourceService()

                assert service._plugin_manager == mock_manager
                MockPluginManager.assert_called_once_with("plugins/test.yaml")

    @pytest.mark.asyncio
    async def test_plugin_manager_initialization_failure(self):
        """Test plugin manager initialization failure handling."""
        with patch.dict(os.environ, {"PLUGINS_ENABLED": "true"}):
            with patch("mcpgateway.services.resource_service.PluginManager") as MockPluginManager:
                MockPluginManager.side_effect = ValueError("Invalid config")

                service = ResourceService()

                assert service._plugin_manager is None  # Should fail gracefully

    @pytest.mark.asyncio
    async def test_read_resource_no_request_id(self, resource_service_with_plugins, mock_db):
        """Test read_resource generates request_id if not provided."""
        service = resource_service_with_plugins
        mock_manager = service._plugin_manager

        # Setup mock resource
        mock_resource = MagicMock()
        mock_resource.content = ResourceContent(type="resource", uri="test://resource", text="Test")
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_resource

        # Setup hooks
        mock_manager.resource_pre_fetch = AsyncMock(
            return_value=(MagicMock(continue_processing=True), None)
        )
        mock_manager.resource_post_fetch = AsyncMock(
            return_value=(MagicMock(continue_processing=True), None)
        )

        await service.read_resource(mock_db, "test://resource")

        # Verify request_id was generated
        call_args = mock_manager.resource_pre_fetch.call_args
        global_context = call_args[0][1]
        assert global_context.request_id is not None
        assert len(global_context.request_id) > 0
