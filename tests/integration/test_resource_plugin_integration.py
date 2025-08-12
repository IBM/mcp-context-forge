# -*- coding: utf-8 -*-
"""Integration tests for resource plugin functionality."""

import os
from unittest.mock import MagicMock, patch
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from mcpgateway.db import Base, Resource as DbResource
from mcpgateway.models import ResourceContent
from mcpgateway.schemas import ResourceCreate
from mcpgateway.services.resource_service import ResourceService


class TestResourcePluginIntegration:
    """Integration tests for resource plugins with real database."""

    @pytest.fixture
    def test_db(self):
        """Create a test database."""
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        yield db
        db.close()

    @pytest.fixture
    def resource_service_with_mock_plugins(self):
        """Create ResourceService with mocked plugin manager."""
        with patch.dict(os.environ, {"PLUGINS_ENABLED": "true", "PLUGIN_CONFIG_FILE": "test.yaml"}):
            with patch("mcpgateway.services.resource_service.PluginManager") as MockPluginManager:
                from unittest.mock import AsyncMock
                mock_manager = MagicMock()
                mock_manager._initialized = True
                mock_manager.initialize = AsyncMock()
                MockPluginManager.return_value = mock_manager
                service = ResourceService()
                service._plugin_manager = mock_manager
                return service, mock_manager

    @pytest.mark.asyncio
    async def test_full_resource_lifecycle_with_plugins(self, test_db, resource_service_with_mock_plugins):
        """Test complete resource lifecycle with plugin hooks."""
        service, mock_manager = resource_service_with_mock_plugins

        # Configure mock plugin manager for all operations
        from unittest.mock import AsyncMock
        pre_result = MagicMock()
        pre_result.continue_processing = True
        pre_result.modified_payload = None

        post_result = MagicMock()
        post_result.continue_processing = True
        post_result.modified_payload = None

        mock_manager.resource_pre_fetch = AsyncMock(
            return_value=(pre_result, {"context": "data"})
        )
        mock_manager.resource_post_fetch = AsyncMock(
            return_value=(post_result, None)
        )

        # 1. Create a resource
        resource_data = ResourceCreate(
            uri="test://integration",
            name="Integration Test Resource",
            content="Test content with password: secret123",
            description="Test resource for integration",
            mime_type="text/plain",
            tags=["test", "integration"],
        )

        created = await service.register_resource(test_db, resource_data)
        assert created.uri == "test://integration"
        assert created.name == "Integration Test Resource"

        # 2. Read the resource (should trigger plugins)
        content = await service.read_resource(
            test_db,
            "test://integration",
            request_id="test-123",
            user="testuser",
        )

        assert content is not None
        mock_manager.resource_pre_fetch.assert_called_once()
        mock_manager.resource_post_fetch.assert_called_once()

        # 3. List resources
        resources = await service.list_resources(test_db)
        assert len(resources) == 1
        assert resources[0].uri == "test://integration"

        # 4. Update the resource
        from mcpgateway.schemas import ResourceUpdate

        update_data = ResourceUpdate(
            name="Updated Integration Resource",
            content="Updated content",
        )
        updated = await service.update_resource(test_db, "test://integration", update_data)
        assert updated.name == "Updated Integration Resource"

        # 5. Delete the resource
        await service.delete_resource(test_db, "test://integration")
        resources = await service.list_resources(test_db)
        assert len(resources) == 0

    @pytest.mark.asyncio
    async def test_resource_filtering_integration(self, test_db):
        """Test resource filtering with actual plugin."""
        with patch.dict(
            os.environ,
            {
                "PLUGINS_ENABLED": "true",
                "PLUGIN_CONFIG_FILE": "plugins/config.yaml",
            },
        ):
            # Use real plugin manager but mock its initialization
            with patch("mcpgateway.services.resource_service.PluginManager") as MockPluginManager:
                from mcpgateway.plugins.framework.manager import PluginManager
                from mcpgateway.plugins.framework.models import (
                    ResourcePostFetchPayload,
                    ResourcePostFetchResult,
                    ResourcePreFetchResult,
                )

                # Create a mock that simulates content filtering
                class MockFilterManager:
                    def __init__(self, config_file):
                        self._initialized = False

                    async def initialize(self):
                        self._initialized = True

                    @property
                    def initialized(self) -> bool:
                        return self._initialized

                    async def resource_pre_fetch(self, payload, global_context):
                        # Allow test:// protocol
                        if payload.uri.startswith("test://"):
                            return (
                                ResourcePreFetchResult(
                                    continue_processing=True,
                                    modified_payload=payload,
                                ),
                                {"validated": True},
                            )
                        else:
                            from mcpgateway.plugins.framework.models import PluginViolation

                            return (
                                ResourcePreFetchResult(
                                    continue_processing=False,
                                    violation=PluginViolation(
                                        reason="Protocol not allowed",
                                        description="Protocol is not in the allowed list",
                                        code="PROTOCOL_BLOCKED",
                                        details={"protocol": payload.uri.split(":")[0], "uri": payload.uri}
                                    ),
                                ),
                                None,
                            )

                    async def resource_post_fetch(self, payload, global_context, contexts):
                        # Filter sensitive content
                        if payload.content and payload.content.text:
                            filtered_text = payload.content.text.replace(
                                "password: secret123",
                                "password: [REDACTED]",
                            )
                            filtered_content = ResourceContent(
                                type=payload.content.type,
                                uri=payload.content.uri,
                                text=filtered_text,
                            )
                            modified_payload = ResourcePostFetchPayload(
                                uri=payload.uri,
                                content=filtered_content,
                            )
                            return (
                                ResourcePostFetchResult(
                                    continue_processing=True,
                                    modified_payload=modified_payload,
                                ),
                                None,
                            )
                        return (
                            ResourcePostFetchResult(continue_processing=True),
                            None,
                        )

                MockPluginManager.return_value = MockFilterManager("test.yaml")
                service = ResourceService()

                # Create a resource with sensitive content
                resource_data = ResourceCreate(
                    uri="test://sensitive",
                    name="Sensitive Resource",
                    content="Config:\npassword: secret123\nport: 8080",
                    mime_type="text/plain",
                )

                await service.register_resource(test_db, resource_data)

                # Read the resource - should be filtered
                content = await service.read_resource(test_db, "test://sensitive")
                assert "[REDACTED]" in content.text
                assert "secret123" not in content.text
                assert "port: 8080" in content.text

                # Try to read a blocked protocol
                from mcpgateway.services.resource_service import ResourceError

                blocked_resource = ResourceCreate(
                    uri="file:///etc/passwd",
                    name="Blocked Resource",
                    content="Should not be accessible",
                    mime_type="text/plain",
                )
                await service.register_resource(test_db, blocked_resource)

                with pytest.raises(ResourceError) as exc_info:
                    await service.read_resource(test_db, "file:///etc/passwd")
                assert "Protocol not allowed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_plugin_context_flow(self, test_db, resource_service_with_mock_plugins):
        """Test that context flows correctly through plugin hooks."""
        service, mock_manager = resource_service_with_mock_plugins

        # Track context flow
        contexts_from_pre = {"plugin_data": "test_value", "validated": True}

        def pre_fetch_side_effect(payload, global_context):
            # Verify global context
            assert global_context.request_id == "integration-test-123"
            assert global_context.user == "integration-user"
            assert global_context.server_id == "server-123"
            return (
                MagicMock(continue_processing=True),
                contexts_from_pre,
            )

        def post_fetch_side_effect(payload, global_context, contexts):
            # Verify contexts from pre-fetch
            assert contexts == contexts_from_pre
            assert contexts["plugin_data"] == "test_value"
            return (
                MagicMock(continue_processing=True),
                None,
            )

        mock_manager.resource_pre_fetch.side_effect = pre_fetch_side_effect
        mock_manager.resource_post_fetch.side_effect = post_fetch_side_effect

        # Create and read a resource
        resource = ResourceCreate(
            uri="test://context-test",
            name="Context Test",
            content="Test content",
            mime_type="text/plain",
        )
        await service.register_resource(test_db, resource)

        await service.read_resource(
            test_db,
            "test://context-test",
            request_id="integration-test-123",
            user="integration-user",
            server_id="server-123",
        )

        mock_manager.resource_pre_fetch.assert_called_once()
        mock_manager.resource_post_fetch.assert_called_once()

    @pytest.mark.asyncio
    async def test_template_resource_with_plugins(self, test_db, resource_service_with_mock_plugins):
        """Test resources work with plugins using template-like content."""
        service, mock_manager = resource_service_with_mock_plugins

        # Configure plugin manager
        from unittest.mock import AsyncMock
        # Create proper mock results
        pre_result = MagicMock()
        pre_result.continue_processing = True
        pre_result.modified_payload = None

        post_result = MagicMock()
        post_result.continue_processing = True
        post_result.modified_payload = None

        mock_manager.resource_pre_fetch = AsyncMock(
            return_value=(pre_result, {"context": "data"})
        )
        mock_manager.resource_post_fetch = AsyncMock(
            return_value=(post_result, None)
        )

        # Create a regular resource with template-like content
        resource = ResourceCreate(
            uri="test://data/123",
            name="Resource with ID",
            content="Data for ID: 123",
            mime_type="text/plain",
        )
        await service.register_resource(test_db, resource)

        # Read the resource
        content = await service.read_resource(test_db, "test://data/123")

        assert content.text == "Data for ID: 123"
        mock_manager.resource_pre_fetch.assert_called_once()
        mock_manager.resource_post_fetch.assert_called_once()

    @pytest.mark.asyncio
    async def test_inactive_resource_handling(self, test_db, resource_service_with_mock_plugins):
        """Test that inactive resources are handled correctly with plugins."""
        service, mock_manager = resource_service_with_mock_plugins

        # Configure mock plugin manager
        from unittest.mock import AsyncMock
        pre_result = MagicMock()
        pre_result.continue_processing = True
        pre_result.modified_payload = None

        mock_manager.resource_pre_fetch = AsyncMock(
            return_value=(pre_result, None)
        )
        mock_manager.resource_post_fetch = AsyncMock()

        # Create a resource
        resource = ResourceCreate(
            uri="test://inactive-test",
            name="Inactive Test",
            content="Test content",
            mime_type="text/plain",
        )
        created = await service.register_resource(test_db, resource)

        # Deactivate the resource
        await service.toggle_resource_status(test_db, created.id, activate=False)

        # Try to read inactive resource
        from mcpgateway.services.resource_service import ResourceNotFoundError

        with pytest.raises(ResourceNotFoundError) as exc_info:
            await service.read_resource(test_db, "test://inactive-test")

        assert "exists but is inactive" in str(exc_info.value)
        # Pre-fetch is called but post-fetch should not be called for inactive resources
        mock_manager.resource_pre_fetch.assert_called_once()
        mock_manager.resource_post_fetch.assert_not_called()
