# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_resource_plugin_integration.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Integration tests for resource plugin functionality.
"""

# Standard
import os
from unittest.mock import MagicMock, patch

# Third-Party
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# First-Party
from mcpgateway.db import Base
from mcpgateway.common.models import ResourceContent
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
                # Standard
                from unittest.mock import AsyncMock

                # First-Party
                from mcpgateway.plugins.framework.models import PluginResult

                mock_manager = MagicMock()
                mock_manager._initialized = True
                mock_manager.initialize = AsyncMock()
                # Add default invoke_hook mock that returns success
                mock_manager.invoke_hook = AsyncMock(
                    return_value=(
                        PluginResult(continue_processing=True, modified_payload=None),
                        None  # contexts
                    )
                )
                MockPluginManager.return_value = mock_manager
                service = ResourceService()
                service._plugin_manager = mock_manager
                return service, mock_manager

    @pytest.mark.asyncio
    async def test_full_resource_lifecycle_with_plugins(self, test_db, resource_service_with_mock_plugins):
        """Test complete resource lifecycle with plugin hooks."""
        service, mock_manager = resource_service_with_mock_plugins

        # The default invoke_hook from fixture will work fine for this test

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
            created.id,
            request_id="test-123",
            user="testuser",
        )

        assert content is not None
        # Verify hooks were called (pre and post fetch)
        assert mock_manager.invoke_hook.call_count >= 2

        # 3. List resources
        resources, _ = await service.list_resources(test_db)
        assert len(resources) == 1
        assert resources[0].uri == "test://integration"


        # 4. Update the resource
        # First-Party
        from mcpgateway.schemas import ResourceUpdate

        update_data = ResourceUpdate(
            name="Updated Integration Resource",
            content="Updated content",
        )
        updated = await service.update_resource(test_db, created.id, update_data)
        assert updated.name == "Updated Integration Resource"


        # 5. Delete the resource
        await service.delete_resource(test_db, created.id)
        resources, _ = await service.list_resources(test_db)
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
                # First-Party
                from mcpgateway.plugins.framework import (
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

                    def has_hooks_for(self, hook_type) -> bool:
                        """Return True for resource hooks this mock handles."""
                        # First-Party
                        from mcpgateway.plugins.framework import ResourceHookType

                        return hook_type in (ResourceHookType.RESOURCE_PRE_FETCH, ResourceHookType.RESOURCE_POST_FETCH)

                    async def invoke_hook(self, hook_type, payload, global_context, local_contexts=None, **kwargs):
                        # First-Party
                        from mcpgateway.plugins.framework import ResourceHookType

                        if hook_type == ResourceHookType.RESOURCE_PRE_FETCH:
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
                                # First-Party
                                from mcpgateway.plugins.framework.models import PluginViolation

                                raise PluginViolationError(
                                    message="Protocol not allowed",
                                    violation=PluginViolation(
                                        reason="Protocol not allowed",
                                        description="Protocol is not in the allowed list",
                                        code="PROTOCOL_BLOCKED",
                                        details={"protocol": payload.uri.split(":")[0], "uri": payload.uri},
                                    ),
                                )
                        elif hook_type == ResourceHookType.RESOURCE_POST_FETCH:
                            # Filter sensitive content
                            if payload.content and payload.content.text:
                                filtered_text = payload.content.text.replace(
                                    "password: secret123",
                                    "password: [REDACTED]",
                                )
                                filtered_content = ResourceContent(
                                    id=payload.content.id,
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
                        else:
                            # Other hook types - just return success
                            # First-Party
                            from mcpgateway.plugins.framework.models import PluginResult

                            return (PluginResult(continue_processing=True), None)

                MockPluginManager.return_value = MockFilterManager("test.yaml")
                service = ResourceService()

                # Create a resource with sensitive content
                resource_data = ResourceCreate(
                    uri="test://sensitive",
                    name="Sensitive Resource",
                    content="Config:\npassword: secret123\nport: 8080",
                    mime_type="text/plain",
                )

                create_response = await service.register_resource(test_db, resource_data)


                # Read the resource - should be filtered
                content = await service.read_resource(test_db, create_response.id)
                assert "[REDACTED]" in content.text
                assert "secret123" not in content.text
                assert "port: 8080" in content.text

                # Try to read a blocked protocol
                # First-Party
                from mcpgateway.plugins.framework import PluginViolationError

                blocked_resource = ResourceCreate(
                    uri="file:///etc/passwd",
                    name="Blocked Resource",
                    content="Should not be accessible",
                    mime_type="text/plain",
                )
                await service.register_resource(test_db, blocked_resource)


                # Find the blocked resource by uri to get its id
                blocked, _ = await service.list_resources(test_db)
                blocked_id = None
                for r in blocked:
                    if r.uri == "file:///etc/passwd":
                        blocked_id = r.id
                        break
                assert blocked_id is not None
                with pytest.raises(PluginViolationError) as exc_info:
                    await service.read_resource(test_db, blocked_id)
                assert "Protocol not allowed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_plugin_context_flow(self, test_db, resource_service_with_mock_plugins):
        """Test that context flows correctly through plugin hooks."""
        service, mock_manager = resource_service_with_mock_plugins

        # Track context flow
        # First-Party
        from mcpgateway.plugins.framework.models import PluginResult
        from mcpgateway.plugins.framework import ResourceHookType

        contexts_from_pre = {"plugin_data": "test_value", "validated": True}

        async def invoke_hook_side_effect(hook_type, payload, global_context, local_contexts=None, **kwargs):
            if hook_type == ResourceHookType.RESOURCE_PRE_FETCH:
                # Verify global context
                assert global_context.request_id == "integration-test-123"
                assert global_context.user == "integration-user"
                assert global_context.server_id == "server-123"
                return (
                    PluginResult(continue_processing=True, modified_payload=None),
                    contexts_from_pre,
                )
            elif hook_type == ResourceHookType.RESOURCE_POST_FETCH:
                # Verify contexts from pre-fetch
                assert local_contexts == contexts_from_pre
                assert local_contexts["plugin_data"] == "test_value"
                return (
                    PluginResult(continue_processing=True),
                    None,
                )
            else:
                return (PluginResult(continue_processing=True), None)

        # Standard
        from unittest.mock import AsyncMock

        mock_manager.invoke_hook = AsyncMock(side_effect=invoke_hook_side_effect)

        # Create and read a resource
        resource = ResourceCreate(
            uri="test://context-test",
            name="Context Test",
            content="Test content",
            mime_type="text/plain",
        )
        created = await service.register_resource(test_db, resource)
        await service.read_resource(
            test_db,
            created.id,
            request_id="integration-test-123",
            user="integration-user",
            server_id="server-123",
        )

        # Verify hooks were called
        assert mock_manager.invoke_hook.call_count >= 2

    @pytest.mark.asyncio
    async def test_template_resource_with_plugins(self, test_db, resource_service_with_mock_plugins):
        """Test resources work with plugins using template-like content."""
        service, mock_manager = resource_service_with_mock_plugins

        # The default invoke_hook from fixture will work fine

        # Create a regular resource with template-like content
        resource = ResourceCreate(
            uri="test://data/123",
            name="Resource with ID",
            content="Data for ID: 123",
            mime_type="text/plain",
        )
        created = await service.register_resource(test_db, resource)
        content = await service.read_resource(test_db, created.id)

        assert content.text == "Data for ID: 123"
        # Verify hooks were called
        assert mock_manager.invoke_hook.call_count >= 2

    @pytest.mark.asyncio
    async def test_inactive_resource_handling(self, test_db, resource_service_with_mock_plugins):
        """Test that inactive resources are handled correctly with plugins."""
        service, mock_manager = resource_service_with_mock_plugins

        # The default invoke_hook from fixture will work fine

        # Create a resource
        resource = ResourceCreate(
            uri="test://inactive-test",
            name="Inactive Test",
            content="Test content",
            mime_type="text/plain",
        )
        created = await service.register_resource(test_db, resource)

        # Deactivate the resource
        await service.set_resource_state(test_db, created.id, activate=False)


        # Try to read inactive resource
        # First-Party
        from mcpgateway.services.resource_service import ResourceNotFoundError

        with pytest.raises(ResourceNotFoundError) as exc_info:
            await service.read_resource(test_db, created.id)

        assert "exists but is inactive" in str(exc_info.value)
        # Pre-fetch is called but post-fetch should not be called for inactive resources
        # Only one invoke_hook call (pre-fetch) since error occurs before post-fetch
        assert mock_manager.invoke_hook.call_count == 1
