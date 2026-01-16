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
from fastapi.responses import HTMLResponse
from fastapi import Request
from typing import Dict

# First-Party
from mcpgateway.common.models import ResourceContent
from mcpgateway.plugins.framework import ResourceHookType
from mcpgateway.plugins.framework.models import PluginResult
from mcpgateway.services.resource_service import ResourceNotFoundError, ResourceService
from mcpgateway.plugins.framework import PluginError, PluginErrorModel, PluginViolation, PluginViolationError
from mcpgateway.admin import admin_add_resource

@pytest.fixture
def mock_db():
    """Create a mock database session."""
    return MagicMock(spec=Session)

class FakeForm(dict):
    """Enhanced fake form with better list handling."""
    def getlist(self, key):
        value = self.get(key, [])
        if isinstance(value, list):
            return value
        return [value] if value else []


@pytest.fixture
def mock_request():
    """Create a mock FastAPI request with comprehensive form data."""
    request = MagicMock(spec=Request)

    # FastAPI's Request always has a .scope dict
    request.scope = {"root_path": ""}

    # Comprehensive form data with valid names
    request.form = AsyncMock(
        return_value=FakeForm(
            {
                "name": "test_name",  # Valid tool/server name
                "url": "http://example.com",
                "description": "Test description",
                "icon": "http://example.com/icon.png",
                "uri": "/test/resource",
                "mimeType": "text/plain",
                "mime_type": "text/plain",
                "template": "Template content",
                "content": "Test content",
                "associatedTools": ["1", "2", "3"],
                "associatedResources": "4,5",
                "associatedPrompts": "6",
                "requestType": "SSE",
                "integrationType": "MCP",
                "headers": '{"X-Test": "value"}',
                "input_schema": '{"type": "object"}',
                "jsonpath_filter": "$.",
                "jsonpathFilter": "$.",
                "auth_type": "basic",
                "auth_username": "user",
                "auth_password": "pass",
                "auth_token": "token123",
                "auth_header_key": "X-Auth",
                "auth_header_value": "secret",
                "arguments": '[{"name": "arg1", "type": "string"}]',
                "activate": "true",
                "is_inactive_checked": "false",
                "transport": "HTTP",
                "path": "/api/test",
                "method": "GET",
                "body": '{"test": "data"}',
            }
        )
    )

    # Basic template rendering stub
    request.app = MagicMock()
    request.app.state = MagicMock()
    request.app.state.templates = MagicMock()
    request.app.state.templates.TemplateResponse.return_value = HTMLResponse(content="<html></html>")

    request.query_params = {"include_inactive": "false"}
    return request

class TestResourceServicePluginIntegration:
    """Test ResourceService integration with plugin framework."""



    @pytest.fixture
    def resource_service(self):
        """Create a ResourceService instance without plugins."""
        with patch.dict(os.environ, {"PLUGINS_ENABLED": "false"}):
            return ResourceService()

    @pytest.fixture
    def resource_service_with_plugins(self):
        """Create a ResourceService instance with plugins enabled."""
        # First-Party
        from mcpgateway.plugins.framework.models import PluginResult

        with patch.dict(os.environ, {"PLUGINS_ENABLED": "true", "PLUGIN_CONFIG_FILE": "test_config.yaml"}):
            with patch("mcpgateway.services.resource_service.PluginManager") as MockPluginManager:
                mock_manager = MagicMock()
                mock_manager._initialized = False
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
                return service

    @pytest.mark.asyncio
    @patch.object(ResourceService, "register_resource")
    async def test_admin_add_resource_with_valid_mime_type(self, mock_register_resource, mock_request, mock_db):
        """Test adding resource with valid MIME type."""
        # Use a valid MIME type
        form_data = FakeForm(
            {
                        "uri": "greetme://morning/{name}",
                        "name": "test_doc",
                        "content": "Test content",
                        "mimeType": "text/plain"
            }
        )

        mock_request.form = AsyncMock(return_value=form_data)

        result = await admin_add_resource(mock_request, mock_db, "test-user")
        # Assert
        mock_register_resource.assert_called_once()
        assert result.status_code == 200

        # Verify template was passed
        call_args = mock_register_resource.call_args[0]
        resource_create = call_args[1]
        assert resource_create.uri_template == "greetme://morning/{name}"

    @pytest.mark.asyncio
    @patch("mcpgateway.services.resource_service.ssl.create_default_context")
    async def test_read_resource_with_pre_fetch_hook(self, mock_ssl, resource_service_with_plugins):
        """Test read_resource executes pre-fetch hook and passes correct context."""

        service = resource_service_with_plugins
        mock_manager = service._plugin_manager

        # Mock DB session
        mock_db: Session = MagicMock()

        # Fake resource content returned from DB
        fake_resource_content = ResourceContent(
            type="resource",
            id="123",
            uri="test://resource",
            text="Test content",
        )

        mock_ctx = MagicMock()
        mock_ssl.return_value = mock_ctx

        # Mock DB row returned by scalar_one_or_none
        mock_db_row = MagicMock()
        mock_db_row.content = fake_resource_content
        mock_db_row.uri = fake_resource_content.uri
        mock_db_row.uri_template = None
        mock_db_row.visibility = "public"
        mock_db_row.owner_email = None
        mock_db_row.team_id = None

        # Configure scalar_one_or_none to always return the mocked row
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_db_row

        # Mock plugin pre-fetch hook to return a modified payload (same URI for simplicity)
        modified_payload = MagicMock()
        modified_payload.uri = fake_resource_content.uri

        async def plugin_side_effect(hook_type, payload, global_context, local_contexts=None, **kwargs):
            if hook_type == ResourceHookType.RESOURCE_PRE_FETCH:
                return PluginResult(
                    continue_processing=True,
                    modified_payload=modified_payload,
                ), {"request_id": "test-123", "user": "testuser"}
            return PluginResult( continue_processing=True, modified_payload=None,), None

        mock_manager.invoke_hook = AsyncMock(side_effect=plugin_side_effect)

        # Call read_resource with URI that will trigger the pre-fetch hook
        result = await service.read_resource(
            mock_db,
            resource_uri="test://resource",
            request_id="test-123",
            user="testuser",
        )

        result_dict = result.model_dump()
        # Verify returned content
        assert result_dict["uri"] == fake_resource_content.uri
        assert result_dict["text"] == fake_resource_content.text

        # Verify DB was queried
        mock_db.execute.assert_called()

        # Verify plugin hooks were invoked
        mock_manager.invoke_hook.assert_awaited()
        assert mock_manager.invoke_hook.call_count >= 1

        # Check first call was pre-fetch and global context was passed correctly
        first_call = mock_manager.invoke_hook.call_args_list[0]

        assert first_call[0][0] == ResourceHookType.RESOURCE_PRE_FETCH # hook_type
        assert first_call[0][1].uri == "test://resource"  # payload.uri
        assert first_call[0][2].request_id == "test-123"


    @pytest.mark.asyncio
    async def test_read_resource_blocked_by_plugin(self, resource_service_with_plugins, mock_db):
        """Test read_resource blocked by pre-fetch hook."""
        import mcpgateway.services.resource_service as resource_service_mod
        resource_service_mod.PLUGINS_AVAILABLE = True
        service = resource_service_with_plugins
        mock_manager = service._plugin_manager

        # Setup mock resource
        mock_resource = MagicMock()
        mock_resource.content = ResourceContent(
            type="resource",
            id="file:///etc/passwd",
            uri="file:///etc/passwd",
            text="Sensitive file content",
        )
        mock_resource.uri = "file:///etc/passwd"  # Ensure uri is set at the top level
        mock_resource.visibility = "public"
        mock_resource.owner_email = None
        mock_resource.team_id = None
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_resource
        mock_db.get.return_value = mock_resource  # Ensure resource_db is not None

        # Setup invoke_hook to raise PluginViolationError
        mock_manager.invoke_hook = AsyncMock(
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
        mock_manager.invoke_hook.assert_called()

    @pytest.mark.asyncio
    @patch("mcpgateway.services.resource_service.ssl.create_default_context")
    async def test_read_resource_uri_modified_by_plugin(self, mock_ssl, mock_db, resource_service_with_plugins):
        """Test read_resource with plugin modifying URI and a mocked SQLAlchemy Session."""

        service = resource_service_with_plugins
        mock_manager = service._plugin_manager

        # Fake resource content returned from DB
        fake_resource_content = ResourceContent(
            type="resource",
            id="123",
            uri="cached://test://resource",
            text="Cached content",
        )

        # Mock DB row that would be returned by scalar_one_or_none()
        mock_db_row = MagicMock()
        mock_db_row.content = fake_resource_content
        mock_db_row.uri = fake_resource_content.uri
        mock_db_row.uri_template = None
        mock_db_row.visibility = "public"
        mock_db_row.owner_email = None
        mock_db_row.team_id = None

        mock_ctx = MagicMock()
        mock_ssl.return_value = mock_ctx

        # Configure scalar_one_or_none to return the mocked row
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_db_row

        # Plugin modifies the URI (can return same or a different URI)
        modified_payload = MagicMock()
        modified_payload.uri = "cached://test://resource"
        modified_payload.gateway.ca_certificate = "-----BEGIN CERTIFICATE-----\nABC\n-----END CERTIFICATE-----"

        async def plugin_side_effect(hook_type, payload, global_context, local_contexts=None, **kwargs):
            if hook_type == ResourceHookType.RESOURCE_PRE_FETCH:
                return PluginResult(
                    continue_processing=True,
                    modified_payload=modified_payload,
                ), {"context": "data"}
            return PluginResult(
                continue_processing=True,
                modified_payload=None,
            ), None

        mock_manager.invoke_hook = AsyncMock(side_effect=plugin_side_effect)
        # Call read_resource with URI that will be processed by plugin
        result = await service.read_resource(mock_db, resource_uri="cached://test://resource")
        result_dict = result.model_dump()
        # Assertions
        assert result_dict["uri"] == fake_resource_content.uri
        assert result_dict["text"] == fake_resource_content.text

        # Verify interactions
        mock_db.execute.assert_called()
        mock_manager.invoke_hook.assert_awaited()



    @pytest.mark.asyncio
    @patch("mcpgateway.services.resource_service.ssl.create_default_context")
    async def test_read_resource_content_filtered_by_plugin(self, mock_ssl, resource_service_with_plugins, mock_db):
        """Test read_resource with content filtering by post-fetch hook."""
        # First-Party
        from mcpgateway.plugins.framework.models import PluginResult
        from mcpgateway.plugins.framework import ResourceHookType

        import mcpgateway.services.resource_service as resource_service_mod
        resource_service_mod.PLUGINS_AVAILABLE = True
        service = resource_service_with_plugins
        mock_manager = service._plugin_manager

        mock_ctx = MagicMock()
        mock_ssl.return_value = mock_ctx

        # Setup mock resource with sensitive data
        mock_resource = MagicMock()
        original_content = ResourceContent(
            type="resource",
            id ="original-1",
            uri="test://config",
            text="password: mysecret123\napi_key: sk-12345",
        )
        mock_resource.content = original_content
        mock_resource.uri = "test://config"  # Ensure uri is set at the top level
        mock_resource.visibility = "public"
        mock_resource.owner_email = None
        mock_resource.team_id = None
        # Return the mock resource for both original and filtered id lookups
        def scalar_one_or_none_side_effect(*args, **kwargs):
            return mock_resource
        mock_db.execute.return_value.scalar_one_or_none.side_effect = scalar_one_or_none_side_effect
        mock_db.get.return_value = mock_resource

        # Setup post-fetch hook to filter content
        filtered_content = ResourceContent(
            type="resource",
            id="filtered-1",
            uri="test://config",
            text="password: [REDACTED]\napi_key: [REDACTED]",
        )
        resource_id = filtered_content.id
        modified_post_payload = MagicMock()
        modified_post_payload.content = filtered_content

        # Use side_effect to return different results based on hook type
        def invoke_hook_side_effect(hook_type, payload, global_context, local_contexts=None, **kwargs):
            if hook_type == ResourceHookType.RESOURCE_PRE_FETCH:
                return (
                    PluginResult(continue_processing=True),
                    {"context": "data"},
                )
            # POST_FETCH
            return (
                PluginResult(
                    continue_processing=True,
                    modified_payload=modified_post_payload,
                ),
                None,
            )

        mock_manager.invoke_hook = AsyncMock(side_effect=invoke_hook_side_effect)

        result = await service.read_resource(mock_db, resource_id)

        # Compare fields instead of object identity
        assert result.text == filtered_content.text
        assert result.uri == filtered_content.uri
        assert result.type == filtered_content.type
        assert "[REDACTED]" in result.text
        assert "mysecret123" not in result.text

    @pytest.mark.asyncio
    async def test_read_resource_plugin_error_handling(self, resource_service_with_plugins, mock_db):
        """Test read_resource handles plugin errors gracefully."""
        import mcpgateway.services.resource_service as resource_service_mod
        resource_service_mod.PLUGINS_AVAILABLE = True
        service = resource_service_with_plugins
        mock_manager = service._plugin_manager

        # Setup mock resource
        mock_resource = MagicMock()
        mock_resource.content = ResourceContent(
            type="resource",
            id="error-1",
            uri="test://resource",
            text="Test content",
        )
        mock_resource.uri = "test://resource"  # Ensure uri is set at the top level
        mock_resource.visibility = "public"
        mock_resource.owner_email = None
        mock_resource.team_id = None
        resource_id = mock_resource.content.id
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_resource
        mock_db.get.return_value = mock_resource  # Ensure resource_db is not None

        # Setup pre-fetch hook to raise an error
        mock_manager.invoke_hook = AsyncMock(side_effect=PluginError(error=PluginErrorModel(message="Plugin error", plugin_name="mock_plugin")))

        with pytest.raises(PluginError) as exc_info:
            await service.read_resource(mock_db, resource_id)


        mock_manager.invoke_hook.assert_called_once()

    @pytest.mark.asyncio
    async def test_read_resource_post_fetch_blocking(self, resource_service_with_plugins, mock_db):
        """Test read_resource blocked by post-fetch hook."""
        # First-Party
        from mcpgateway.plugins.framework.models import PluginResult
        from mcpgateway.plugins.framework import ResourceHookType

        import mcpgateway.services.resource_service as resource_service_mod
        resource_service_mod.PLUGINS_AVAILABLE = True
        service = resource_service_with_plugins
        mock_manager = service._plugin_manager

        # Setup mock resource
        mock_resource = MagicMock()
        mock_resource.content = ResourceContent(
                type="resource",
                id="test://resource",
                uri="test://resource",
                text="Sensitive content",
            )
        mock_resource.uri = "test://resource"  # Ensure uri is set at the top level
        mock_resource.visibility = "public"
        mock_resource.owner_email = None
        mock_resource.team_id = None
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_resource
        mock_db.get.return_value = mock_resource  # Ensure resource_db is not None

        # Use side_effect to allow pre-fetch but block on post-fetch
        def invoke_hook_side_effect(hook_type, payload, global_context, local_contexts=None, **kwargs):
            if hook_type == ResourceHookType.RESOURCE_PRE_FETCH:
                return (
                    PluginResult(continue_processing=True),
                    {"context": "data"},
                )
            # POST_FETCH - raise error
            raise PluginViolationError(
                message="Content contains sensitive data",
                violation=PluginViolation(
                    reason="Content contains sensitive data",
                    description="The resource content was flagged as containing sensitive information",
                    code="SENSITIVE_CONTENT",
                    details={"uri": "test://resource"}
                )
            )

        mock_manager.invoke_hook = AsyncMock(side_effect=invoke_hook_side_effect)

        with pytest.raises(PluginViolationError) as exc_info:
            await service.read_resource(mock_db, "test://resource")

        assert "Content contains sensitive data" in str(exc_info.value)
        # Verify invoke_hook was called at least twice (pre and post)
        assert mock_manager.invoke_hook.call_count == 2

    @pytest.mark.asyncio
    @patch("mcpgateway.services.resource_service.ssl.create_default_context")
    async def test_read_resource_with_template(self, mock_ssl, resource_service_with_plugins, mock_db):
        """Test read_resource with template resource and plugins."""
        import mcpgateway.services.resource_service as resource_service_mod
        resource_service_mod.PLUGINS_AVAILABLE = True
        service = resource_service_with_plugins
        mock_manager = service._plugin_manager

        mock_ctx = MagicMock()
        mock_ssl.return_value = mock_ctx

        # Setup mock resource
        mock_resource = MagicMock()
        mock_template_content = ResourceContent(
            type="resource",
            id="123",
            uri="test://123/data",
            text="Template content for id=123",
        )
        mock_resource.gateway.ca_certificate = "-----BEGIN CERTIFICATE-----\nABC\n-----END CERTIFICATE-----"
        mock_resource.content = mock_template_content
        mock_resource.uri = "test://123/data"  # Ensure uri is set at the top level
        mock_resource.visibility = "public"
        mock_resource.owner_email = None
        mock_resource.team_id = None
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_resource
        mock_db.get.return_value = mock_resource  # Ensure resource_db is not None

        # The default invoke_hook from fixture will work fine for this test
        # since it just returns success with no modifications

        # Use the correct resource id for lookup
        result = await service.read_resource(mock_db, mock_resource.uri)

        assert result == mock_template_content
        # Verify hooks were called
        assert mock_manager.invoke_hook.call_count >= 2  # Pre and post fetch

    @pytest.mark.asyncio
    @patch("mcpgateway.services.resource_service.ssl.create_default_context")
    async def test_read_resource_context_propagation(self,mock_ssl, resource_service_with_plugins, mock_db):
        """Test context propagation from pre-fetch to post-fetch."""
        # First-Party
        from mcpgateway.plugins.framework.models import PluginResult
        from mcpgateway.plugins.framework import ResourceHookType

        import mcpgateway.services.resource_service as resource_service_mod
        resource_service_mod.PLUGINS_AVAILABLE = True
        service = resource_service_with_plugins
        mock_manager = service._plugin_manager

        mock_ctx = MagicMock()
        mock_ssl.return_value = mock_ctx

        # Setup mock resource
        mock_resource = MagicMock()
        mock_resource.content = ResourceContent(
            type="resource",
            id="test://resource",
            uri="test://resource",
            text="Test content",
        )
        mock_resource.gateway.ca_certificate = "-----BEGIN CERTIFICATE-----\nABC\n-----END CERTIFICATE-----"
        mock_resource.uri = "test://resource"  # Ensure uri is set at the top level
        mock_resource.visibility = "public"
        mock_resource.owner_email = None
        mock_resource.team_id = None
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_resource
        mock_db.get.return_value = mock_resource  # Ensure resource_db is not None

        # Capture contexts from pre-fetch
        test_contexts = {"plugin1": {"validated": True}}

        # Use side_effect to return contexts from pre-fetch
        def invoke_hook_side_effect(hook_type, payload, global_context, local_contexts=None, **kwargs):
            if hook_type == ResourceHookType.RESOURCE_PRE_FETCH:
                return (
                    PluginResult(continue_processing=True),
                    test_contexts,
                )
            # POST_FETCH
            return (
                PluginResult(continue_processing=True),
                None,
            )

        mock_manager.invoke_hook = AsyncMock(side_effect=invoke_hook_side_effect)

        # The resource id must match the lookup for plugin logic to trigger
        await service.read_resource(mock_db, mock_resource.content.id)

        # Verify contexts were passed from pre to post
        assert mock_manager.invoke_hook.call_count == 2
        # Check second call (post-fetch) to verify contexts were passed
        post_call_args = mock_manager.invoke_hook.call_args_list[1]
        # The contexts dict should be passed as the 4th positional arg (local_contexts)
        assert post_call_args[0][3] == test_contexts  # Fourth argument is local_contexts

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
    @patch("mcpgateway.services.resource_service.ssl.create_default_context")
    async def test_read_resource_no_request_id(self, mock_ssl,resource_service_with_plugins, mock_db):
        """Test read_resource generates request_id if not provided."""
        import mcpgateway.services.resource_service as resource_service_mod
        resource_service_mod.PLUGINS_AVAILABLE = True
        service = resource_service_with_plugins
        mock_manager = service._plugin_manager

        mock_ctx = MagicMock()
        mock_ssl.return_value = mock_ctx

        # Setup mock resource
        mock_resource = MagicMock()
        mock_resource.content = ResourceContent(type="resource", id="test://resource", uri="test://resource", text="Test")
        mock_resource.uri = "test://resource"  # Ensure uri is set at the top level
        mock_resource.gateway.ca_certificate = "-----BEGIN CERTIFICATE-----\nABC\n-----END CERTIFICATE-----"
        mock_resource.visibility = "public"
        mock_resource.owner_email = None
        mock_resource.team_id = None
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_resource
        mock_db.get.return_value = mock_resource  # Ensure resource_db is not None

        # The default invoke_hook from fixture will work fine

        await service.read_resource(mock_db, "test://resource")

        # Verify request_id was generated - check first call (pre-fetch)
        assert mock_manager.invoke_hook.call_count >= 1, "invoke_hook was not called"
        first_call = mock_manager.invoke_hook.call_args_list[0]
        global_context = first_call[0][2]  # Third positional arg is global_context
        assert global_context.request_id is not None
        assert len(global_context.request_id) > 0
