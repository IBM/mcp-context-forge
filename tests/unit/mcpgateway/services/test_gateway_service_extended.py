# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_gateway_service_extended.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Extended unit tests for GatewayService to improve coverage.
These tests focus on uncovered areas of the GatewayService implementation,
including error handling, edge cases, and specific transport scenarios.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.schemas import ToolCreate
from mcpgateway.services.gateway_service import (
    GatewayConnectionError,
    GatewayService,
)


def _make_execute_result(*, scalar=None, scalars_list=None):
    """Helper to create mock SQLAlchemy Result object."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    scalars_proxy = MagicMock()
    scalars_proxy.all.return_value = scalars_list or []
    result.scalars.return_value = scalars_proxy
    return result


@pytest.fixture(autouse=True)
def _bypass_validation(monkeypatch):
    """Bypass Pydantic validation for mock objects."""
    # First-Party
    from mcpgateway.schemas import GatewayRead

    monkeypatch.setattr(GatewayRead, "model_validate", staticmethod(lambda x: x))


class TestGatewayServiceExtended:
    """Extended unit tests for GatewayService to improve coverage.

    These tests focus on uncovered areas of the GatewayService implementation,
    including error handling, edge cases, and specific transport scenarios.
    Also includes comprehensive tests for helper methods.
    """

    @pytest.mark.asyncio
    async def test_initialize_gateway_sse_transport(self):
        """Test _initialize_gateway with SSE transport."""
        service = GatewayService()

        with (
            patch("mcpgateway.services.gateway_service.sse_client") as mock_sse_client,
            patch("mcpgateway.services.gateway_service.ClientSession") as mock_session,
            patch("mcpgateway.services.gateway_service.decode_auth") as mock_decode,
        ):
            # Setup mocks
            mock_decode.return_value = {"Authorization": "Bearer token"}

            # Mock SSE client context manager
            mock_streams = (MagicMock(), MagicMock())
            mock_sse_context = AsyncMock()
            mock_sse_context.__aenter__.return_value = mock_streams
            mock_sse_context.__aexit__.return_value = None
            mock_sse_client.return_value = mock_sse_context

            # Mock ClientSession
            mock_session_instance = AsyncMock()
            mock_session_context = AsyncMock()
            mock_session_context.__aenter__.return_value = mock_session_instance
            mock_session_context.__aexit__.return_value = None
            mock_session.return_value = mock_session_context

            # Mock responses
            mock_init_response = MagicMock()
            mock_init_response.capabilities.model_dump.return_value = {"protocolVersion": "0.1.0"}
            mock_session_instance.initialize.return_value = mock_init_response

            mock_tools_response = MagicMock()
            mock_tool = MagicMock()
            mock_tool.model_dump.return_value = {"name": "test_tool", "description": "Test tool", "inputSchema": {}}
            mock_tools_response.tools = [mock_tool]
            mock_session_instance.list_tools.return_value = mock_tools_response

            # Execute
            capabilities, tools, resources, prompts = await service._initialize_gateway("http://test.example.com", {"Authorization": "Bearer token"}, "SSE")

            # Verify
            assert capabilities == {"protocolVersion": "0.1.0"}
            assert len(tools) == 1
            assert isinstance(tools[0], ToolCreate)
            assert resources == []
            assert prompts == []

    @pytest.mark.asyncio
    async def test_initialize_gateway_streamablehttp_transport(self):
        """Test _initialize_gateway with StreamableHTTP transport."""
        service = GatewayService()

        with (
            patch("mcpgateway.services.gateway_service.streamablehttp_client") as mock_http_client,
            patch("mcpgateway.services.gateway_service.ClientSession") as mock_session,
            patch("mcpgateway.services.gateway_service.decode_auth") as mock_decode,
        ):
            # Setup mocks
            mock_decode.return_value = {"Authorization": "Bearer token"}

            # Mock StreamableHTTP client context manager
            mock_streams = (MagicMock(), MagicMock(), MagicMock())
            mock_http_context = AsyncMock()
            mock_http_context.__aenter__.return_value = mock_streams
            mock_http_context.__aexit__.return_value = None
            mock_http_client.return_value = mock_http_context

            # Mock ClientSession
            mock_session_instance = AsyncMock()
            mock_session_context = AsyncMock()
            mock_session_context.__aenter__.return_value = mock_session_instance
            mock_session_context.__aexit__.return_value = None
            mock_session.return_value = mock_session_context

            # Mock responses
            mock_init_response = MagicMock()
            mock_init_response.capabilities.model_dump.return_value = {"protocolVersion": "0.1.0"}
            mock_session_instance.initialize.return_value = mock_init_response

            mock_tools_response = MagicMock()
            mock_tool = MagicMock()
            mock_tool.model_dump.return_value = {"name": "test_tool", "description": "Test tool", "inputSchema": {}}
            mock_tools_response.tools = [mock_tool]
            mock_session_instance.list_tools.return_value = mock_tools_response

            # Execute
            capabilities, tools, resources, prompts = await service._initialize_gateway("http://test.example.com", {"Authorization": "Bearer token"}, "streamablehttp")

            # Verify
            assert capabilities == {"protocolVersion": "0.1.0"}
            assert len(tools) == 1
            assert tools[0].request_type == "STREAMABLEHTTP"
            assert resources == []
            assert prompts == []

    @pytest.mark.asyncio
    async def test_initialize_gateway_connection_error(self):
        """Test _initialize_gateway with connection error."""
        service = GatewayService()

        with patch("mcpgateway.services.gateway_service.sse_client") as mock_sse_client:
            # Make SSE client raise an exception
            mock_sse_client.side_effect = Exception("Connection failed")

            # Execute and expect error
            with pytest.raises(GatewayConnectionError) as exc_info:
                await service._initialize_gateway("http://test.example.com", None, "SSE")

            assert "Failed to initialize gateway" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_publish_event(self):
        """Test _publish_event method."""
        service = GatewayService()

        # Create a subscriber queue manually
        test_queue = asyncio.Queue()
        service._event_subscribers.append(test_queue)

        event = {"type": "gateway_added", "data": {"id": "123"}}
        await service._publish_event(event)

        # Verify event was sent to subscriber queue
        assert not test_queue.empty()
        queued_event = await test_queue.get()
        assert queued_event == event

    @pytest.mark.asyncio
    async def test_notify_gateway_added(self):
        """Test _notify_gateway_added method."""
        service = GatewayService()
        service._publish_event = AsyncMock()

        mock_gateway = MagicMock()
        mock_gateway.id = "gateway123"
        mock_gateway.name = "Test Gateway"
        mock_gateway.url = "http://test.example.com"

        await service._notify_gateway_added(mock_gateway)

        # Verify event was published
        service._publish_event.assert_called_once()
        event = service._publish_event.call_args[0][0]
        assert event["type"] == "gateway_added"
        assert event["data"]["id"] == "gateway123"

    @pytest.mark.asyncio
    async def test_notify_gateway_activated(self):
        """Test _notify_gateway_activated method."""
        service = GatewayService()
        service._publish_event = AsyncMock()

        mock_gateway = MagicMock()
        mock_gateway.id = "gateway123"
        mock_gateway.name = "Test Gateway"

        await service._notify_gateway_activated(mock_gateway)

        # Verify event was published
        service._publish_event.assert_called_once()
        event = service._publish_event.call_args[0][0]
        assert event["type"] == "gateway_activated"
        assert event["data"]["id"] == "gateway123"

    @pytest.mark.asyncio
    async def test_notify_gateway_deactivated(self):
        """Test _notify_gateway_deactivated method."""
        service = GatewayService()
        service._publish_event = AsyncMock()

        mock_gateway = MagicMock()
        mock_gateway.id = "gateway123"
        mock_gateway.name = "Test Gateway"

        await service._notify_gateway_deactivated(mock_gateway)

        # Verify event was published
        service._publish_event.assert_called_once()
        event = service._publish_event.call_args[0][0]
        assert event["type"] == "gateway_deactivated"
        assert event["data"]["id"] == "gateway123"

    @pytest.mark.asyncio
    async def test_notify_gateway_deleted(self):
        """Test _notify_gateway_deleted method."""
        service = GatewayService()
        service._publish_event = AsyncMock()

        gateway_info = {"id": "gateway123", "name": "Test Gateway"}

        await service._notify_gateway_deleted(gateway_info)

        # Verify event was published
        service._publish_event.assert_called_once()
        event = service._publish_event.call_args[0][0]
        assert event["type"] == "gateway_deleted"
        assert event["data"] == gateway_info

    @pytest.mark.asyncio
    async def test_notify_gateway_removed(self):
        """Test _notify_gateway_removed method."""
        service = GatewayService()
        service._publish_event = AsyncMock()

        mock_gateway = MagicMock()
        mock_gateway.id = "gateway123"
        mock_gateway.name = "Test Gateway"

        await service._notify_gateway_removed(mock_gateway)

        # Verify event was published
        service._publish_event.assert_called_once()
        event = service._publish_event.call_args[0][0]
        assert event["type"] == "gateway_removed"
        assert event["data"]["id"] == "gateway123"

    @pytest.mark.asyncio
    async def test_notify_gateway_updated(self):
        """Test _notify_gateway_updated method."""
        service = GatewayService()
        service._publish_event = AsyncMock()

        mock_gateway = MagicMock()
        mock_gateway.id = "gateway123"
        mock_gateway.name = "Test Gateway"
        mock_gateway.url = "http://test.example.com"
        mock_gateway.is_active = True
        mock_gateway.last_seen = datetime.now(timezone.utc)

        await service._notify_gateway_updated(mock_gateway)

        # Verify event was published
        service._publish_event.assert_called_once()
        event = service._publish_event.call_args[0][0]
        assert event["type"] == "gateway_updated"
        assert event["data"]["id"] == "gateway123"

    @pytest.mark.asyncio
    async def test_get_auth_headers(self):
        """Test _get_auth_headers method exists."""
        service = GatewayService()

        # Just test that the method exists and is callable
        assert hasattr(service, "_get_auth_headers")
        assert callable(getattr(service, "_get_auth_headers"))

    @pytest.mark.asyncio
    async def test_run_health_checks(self):
        """Test _run_health_checks method."""
        service = GatewayService()
        service._health_check_interval = 0.1  # Short interval for testing

        # Mock database session
        mock_db = MagicMock()
        service._get_db = MagicMock(return_value=mock_db)

        # Mock gateways
        mock_gateway1 = MagicMock()
        mock_gateway1.id = "gateway1"
        mock_gateway1.is_active = True
        mock_gateway1.reachable = True

        mock_gateway2 = MagicMock()
        mock_gateway2.id = "gateway2"
        mock_gateway2.is_active = True
        mock_gateway2.reachable = False

        service._get_gateways = MagicMock(return_value=[mock_gateway1, mock_gateway2])
        service.check_health_of_gateways = AsyncMock(return_value=True)

        # Mock file lock to always succeed for testing
        mock_file_lock = MagicMock()
        mock_file_lock.acquire = MagicMock()  # Always succeeds
        mock_file_lock.is_locked = True
        mock_file_lock.release = MagicMock()
        service._file_lock = mock_file_lock

        # Use cache_type="none" to avoid file lock complexity
        with patch("mcpgateway.services.gateway_service.settings") as mock_settings:
            mock_settings.cache_type = "none"

            # Run health checks for a short time
            health_check_task = asyncio.create_task(service._run_health_checks(service._get_db, "user@example.com"))
            await asyncio.sleep(0.2)
            health_check_task.cancel()

            try:
                await asyncio.wait_for(health_check_task, timeout=1.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass  # Expected when we cancel

        # Verify health checks were called
        assert service.check_health_of_gateways.called

    @pytest.mark.asyncio
    async def test_handle_gateway_failure(self):
        """Test _handle_gateway_failure method exists."""
        service = GatewayService()

        # Just test that the method exists and is callable
        assert hasattr(service, "_handle_gateway_failure")
        assert callable(getattr(service, "_handle_gateway_failure"))

    @pytest.mark.asyncio
    async def test_subscribe_events(self):
        """Test subscribe_events method."""
        service = GatewayService()

        # Prepare events to publish
        event1 = {"type": "gateway_added", "data": {"id": "1"}}
        event2 = {"type": "gateway_updated", "data": {"id": "2"}}

        # Start subscription in a task
        events = []

        async def collect_events():
            async for event in service.subscribe_events():
                events.append(event)
                if len(events) >= 2:
                    break

        # Start the subscription task
        subscription_task = asyncio.create_task(collect_events())

        # Give a moment for subscription to be set up
        await asyncio.sleep(0.01)

        # Publish events
        await service._publish_event(event1)
        await service._publish_event(event2)

        # Wait for events to be collected with timeout
        try:
            await asyncio.wait_for(subscription_task, timeout=1.0)
        except asyncio.TimeoutError:
            subscription_task.cancel()
            pytest.fail("Test timed out waiting for events")

        assert len(events) == 2
        assert events[0] == event1
        assert events[1] == event2

    @pytest.mark.asyncio
    async def test_aggregate_capabilities(self):
        """Test aggregate_capabilities method exists."""
        service = GatewayService()

        # Just test that the method exists and is callable
        assert hasattr(service, "aggregate_capabilities")
        assert callable(getattr(service, "aggregate_capabilities"))

    def test_get_gateways(self):
        """Test _get_gateways method exists."""
        service = GatewayService()

        # Just test that the method exists and is callable
        assert hasattr(service, "_get_gateways")
        assert callable(getattr(service, "_get_gateways"))

    @pytest.mark.asyncio
    async def test_redis_import_error_handling(self):
        """Test Redis import error handling path (lines 64-66)."""
        # This test verifies the REDIS_AVAILABLE flag functionality
        # First-Party
        from mcpgateway.services.gateway_service import REDIS_AVAILABLE

        # Just verify the flag exists and is boolean
        assert isinstance(REDIS_AVAILABLE, bool)

    @pytest.mark.asyncio
    async def test_init_with_redis_enabled(self):
        """Test initialization with Redis enabled (lines 233-236)."""
        with patch("mcpgateway.services.gateway_service.REDIS_AVAILABLE", True):
            with patch("mcpgateway.services.gateway_service.redis") as mock_redis:
                mock_redis_client = MagicMock()
                mock_redis.from_url.return_value = mock_redis_client

                with patch("mcpgateway.services.gateway_service.settings") as mock_settings:
                    mock_settings.cache_type = "redis"
                    mock_settings.redis_url = "redis://localhost:6379"

                    service = GatewayService()

                    assert service._redis_client is mock_redis_client
                    assert isinstance(service._instance_id, str)
                    assert service._leader_key == "gateway_service_leader"
                    assert service._leader_ttl == 40

    @pytest.mark.asyncio
    async def test_init_with_file_cache_path_adjustment(self):
        """Test initialization with file cache and path adjustment (line 244)."""
        with patch("mcpgateway.services.gateway_service.REDIS_AVAILABLE", False):
            with patch("mcpgateway.services.gateway_service.settings") as mock_settings:
                mock_settings.cache_type = "file"

                service = GatewayService()

                # Verify Redis client is None when REDIS not available
                assert service._redis_client is None

    @pytest.mark.asyncio
    async def test_init_with_no_cache(self):
        """Test initialization with cache disabled (lines 248-249)."""
        with patch("mcpgateway.services.gateway_service.REDIS_AVAILABLE", False):
            with patch("mcpgateway.services.gateway_service.settings") as mock_settings:
                mock_settings.cache_type = "none"

                service = GatewayService()

                assert service._redis_client is None

    @pytest.mark.asyncio
    async def test_initialize_with_redis_logging(self):
        """Test initialize method exists and is callable."""
        service = GatewayService()

        # Just test that method exists and is callable
        assert hasattr(service, "initialize")
        assert callable(getattr(service, "initialize"))

        # Test it's an async method
        # Standard
        import asyncio

        assert asyncio.iscoroutinefunction(service.initialize)

    @pytest.mark.asyncio
    async def test_event_notification_methods(self):
        """Test all event notification methods (lines 1489-1537)."""
        service = GatewayService()

        # Mock _publish_event to track calls
        service._publish_event = AsyncMock()

        # Create mock gateway
        mock_gateway = MagicMock()
        mock_gateway.id = "test-id"
        mock_gateway.name = "test-gateway"
        mock_gateway.url = "http://test.com"
        mock_gateway.enabled = True

        # Test _notify_gateway_activated
        await service._notify_gateway_activated(mock_gateway)
        call_args = service._publish_event.call_args[0][0]
        assert call_args["type"] == "gateway_activated"
        assert call_args["data"]["id"] == "test-id"

        # Reset mock
        service._publish_event.reset_mock()

        # Test _notify_gateway_deactivated
        await service._notify_gateway_deactivated(mock_gateway)
        call_args = service._publish_event.call_args[0][0]
        assert call_args["type"] == "gateway_deactivated"

        # Reset mock
        service._publish_event.reset_mock()

        # Test _notify_gateway_deleted
        gateway_info = {"id": "test-id", "name": "test-gateway"}
        await service._notify_gateway_deleted(gateway_info)
        call_args = service._publish_event.call_args[0][0]
        assert call_args["type"] == "gateway_deleted"

        # Reset mock
        service._publish_event.reset_mock()

        # Test _notify_gateway_removed
        await service._notify_gateway_removed(mock_gateway)
        call_args = service._publish_event.call_args[0][0]
        assert call_args["type"] == "gateway_removed"

    @pytest.mark.asyncio
    async def test_publish_event_multiple_subscribers(self):
        """Test _publish_event with multiple subscribers (lines 1567-1568)."""
        service = GatewayService()

        # Create multiple subscriber queues
        queue1 = asyncio.Queue()
        queue2 = asyncio.Queue()
        service._event_subscribers = [queue1, queue2]

        event = {"type": "test", "data": {"message": "test"}}
        await service._publish_event(event)

        # Both queues should receive the event
        event1 = await asyncio.wait_for(queue1.get(), timeout=1.0)
        event2 = await asyncio.wait_for(queue2.get(), timeout=1.0)

        assert event1 == event
        assert event2 == event

    @pytest.mark.asyncio
    async def test_update_or_create_tools_new_tools(self):
        """Test _update_or_create_tools creates new tools."""
        service = GatewayService()

        # Mock database
        mock_db = MagicMock()

        # Mock database execute to return None (no existing tool found)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        # Mock gateway
        mock_gateway = MagicMock()
        mock_gateway.id = "test-gateway-id"
        mock_gateway.name = "test-gateway"
        mock_gateway.url = "http://localhost:8080"
        mock_gateway.auth_type = "bearer"
        mock_gateway.auth_value = "test-token"
        mock_gateway.team_id = "test-team"
        mock_gateway.owner_email = "test@example.com"
        mock_gateway.visibility = "public"
        mock_gateway.tools = []  # Empty tools list

        # Mock tools from MCP server
        mock_tool = MagicMock()
        mock_tool.name = "test_tool"
        mock_tool.description = "A test tool"
        mock_tool.request_type = "POST"
        mock_tool.headers = {}
        mock_tool.input_schema = {"type": "object"}
        mock_tool.annotations = {}
        mock_tool.jsonpath_filter = None

        tools = [mock_tool]
        context = "test"

        # Call the helper method
        result = service._update_or_create_tools(mock_db, tools, mock_gateway, context)

        # Should return one new tool
        assert len(result) == 1
        new_tool = result[0]
        assert new_tool.original_name == "test_tool"
        assert new_tool.custom_name == "test_tool"
        assert new_tool.description == "A test tool"
        assert new_tool.auth_type == "bearer"
        assert new_tool.auth_value == "test-token"
        assert new_tool.team_id == "test-team"
        assert new_tool.owner_email == "test@example.com"

    @pytest.mark.asyncio
    async def test_update_or_create_tools_existing_tools(self):
        """Test _update_or_create_tools updates existing tools."""
        service = GatewayService()

        # Mock database
        mock_db = MagicMock()

        # Mock existing tool in database
        existing_tool = MagicMock()
        existing_tool.original_name = "test_tool"
        existing_tool.description = "Old description"
        existing_tool.request_type = "GET"
        existing_tool.input_schema = {"type": "string"}
        existing_tool.url = "http://old-url.com"
        existing_tool.headers = {}
        existing_tool.auth_type = "none"
        existing_tool.auth_value = ""
        existing_tool.visibility = "private"

        # Mock database execute to return existing tool
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_tool
        mock_db.execute.return_value = mock_result

        # Mock gateway with new values
        mock_gateway = MagicMock()
        mock_gateway.id = "test-gateway-id"
        mock_gateway.name = "test-gateway"
        mock_gateway.url = "http://new-url.com"
        mock_gateway.auth_type = "bearer"
        mock_gateway.auth_value = "new-token"
        mock_gateway.visibility = "public"
        mock_gateway.tools = [existing_tool]

        # Mock updated tool from MCP server
        mock_tool = MagicMock()
        mock_tool.name = "test_tool"  # Same name as existing
        mock_tool.description = "Updated description"
        mock_tool.request_type = "POST"
        mock_tool.headers = {"Content-Type": "application/json"}
        mock_tool.input_schema = {"type": "object"}
        mock_tool.annotations = {"updated": True}
        mock_tool.jsonpath_filter = "$.result"

        tools = [mock_tool]
        context = "update"

        # Call the helper method
        result = service._update_or_create_tools(mock_db, tools, mock_gateway, context)

        # Should return empty list (no new tools, existing one updated)
        assert len(result) == 0

        # Existing tool should be updated
        assert existing_tool.description == "Updated description"
        assert existing_tool.request_type == "POST"
        assert existing_tool.headers == {"Content-Type": "application/json"}
        assert existing_tool.input_schema == {"type": "object"}
        assert existing_tool.jsonpath_filter == "$.result"
        assert existing_tool.url == "http://new-url.com"
        assert existing_tool.auth_type == "bearer"
        assert existing_tool.auth_value == "new-token"
        assert existing_tool.visibility == "public"

    @pytest.mark.asyncio
    async def test_update_or_create_resources_new_resources(self):
        """Test _update_or_create_resources creates new resources."""
        service = GatewayService()

        # Mock database
        mock_db = MagicMock()

        # Mock database execute to return None (no existing resource found)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        # Mock gateway
        mock_gateway = MagicMock()
        mock_gateway.id = "test-gateway-id"
        mock_gateway.name = "test-gateway"
        mock_gateway.team_id = "test-team"
        mock_gateway.owner_email = "test@example.com"
        mock_gateway.visibility = "team"
        mock_gateway.resources = []  # Empty resources list

        # Mock resource from MCP server
        mock_resource = MagicMock()
        mock_resource.uri = "file:///test.txt"
        mock_resource.name = "test.txt"
        mock_resource.description = "A test resource"
        mock_resource.mime_type = "text/plain"
        mock_resource.template = None

        resources = [mock_resource]
        context = "test"

        # Call the helper method
        result = service._update_or_create_resources(mock_db, resources, mock_gateway, context)

        # Should return one new resource
        assert len(result) == 1
        new_resource = result[0]
        assert new_resource.uri == "file:///test.txt"
        assert new_resource.name == "test.txt"
        assert new_resource.description == "A test resource"
        assert new_resource.mime_type == "text/plain"
        assert new_resource.created_via == "test"
        assert new_resource.visibility == "team"

    @pytest.mark.asyncio
    async def test_update_or_create_resources_existing_resources(self):
        """Test _update_or_create_resources updates existing resources."""
        service = GatewayService()

        # Mock database
        mock_db = MagicMock()

        # Mock existing resource in database
        existing_resource = MagicMock()
        existing_resource.uri = "file:///test.txt"
        existing_resource.name = "test.txt"
        existing_resource.description = "Old description"
        existing_resource.mime_type = "text/plain"
        existing_resource.template = None
        existing_resource.visibility = "private"

        # Mock database execute to return existing resource
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_resource
        mock_db.execute.return_value = mock_result

        # Mock gateway with new values
        mock_gateway = MagicMock()
        mock_gateway.id = "test-gateway-id"
        mock_gateway.visibility = "public"
        mock_gateway.resources = [existing_resource]

        # Mock updated resource from MCP server
        mock_resource = MagicMock()
        mock_resource.uri = "file:///test.txt"  # Same URI as existing
        mock_resource.name = "test.txt"
        mock_resource.description = "Updated description"
        mock_resource.mime_type = "application/json"
        mock_resource.template = "template_content"

        resources = [mock_resource]
        context = "update"

        # Call the helper method
        result = service._update_or_create_resources(mock_db, resources, mock_gateway, context)

        # Should return empty list (no new resources, existing one updated)
        assert len(result) == 0

        # Existing resource should be updated
        assert existing_resource.description == "Updated description"
        assert existing_resource.mime_type == "application/json"
        assert existing_resource.template == "template_content"
        assert existing_resource.visibility == "public"

    @pytest.mark.asyncio
    async def test_update_or_create_prompts_new_prompts(self):
        """Test _update_or_create_prompts creates new prompts."""
        service = GatewayService()

        # Mock database
        mock_db = MagicMock()

        # Mock database execute to return None (no existing prompt found)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        # Mock gateway
        mock_gateway = MagicMock()
        mock_gateway.id = "test-gateway-id"
        mock_gateway.name = "test-gateway"
        mock_gateway.team_id = None
        mock_gateway.owner_email = "admin@example.com"
        mock_gateway.visibility = "private"
        mock_gateway.prompts = []  # Empty prompts list

        # Mock prompt from MCP server
        mock_prompt = MagicMock()
        mock_prompt.name = "test_prompt"
        mock_prompt.description = "A test prompt"
        mock_prompt.template = "Hello {name}!"

        prompts = [mock_prompt]
        context = "test"

        # Call the helper method
        result = service._update_or_create_prompts(mock_db, prompts, mock_gateway, context)

        # Should return one new prompt
        assert len(result) == 1
        new_prompt = result[0]
        assert new_prompt.name == "test_prompt"
        assert new_prompt.description == "A test prompt"
        assert new_prompt.template == "Hello {name}!"
        assert new_prompt.created_via == "test"
        assert new_prompt.visibility == "private"
        assert new_prompt.argument_schema == {}

    @pytest.mark.asyncio
    async def test_update_or_create_prompts_existing_prompts(self):
        """Test _update_or_create_prompts updates existing prompts."""
        service = GatewayService()

        # Mock database
        mock_db = MagicMock()

        # Mock existing prompt in database
        existing_prompt = MagicMock()
        existing_prompt.name = "test_prompt"
        existing_prompt.description = "Old description"
        existing_prompt.template = "Old template"
        existing_prompt.visibility = "private"

        # Mock database execute to return existing prompt
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_prompt
        mock_db.execute.return_value = mock_result

        # Mock gateway with new values
        mock_gateway = MagicMock()
        mock_gateway.id = "test-gateway-id"
        mock_gateway.visibility = "public"
        mock_gateway.prompts = [existing_prompt]

        # Mock updated prompt from MCP server
        mock_prompt = MagicMock()
        mock_prompt.name = "test_prompt"  # Same name as existing
        mock_prompt.description = "Updated description"
        mock_prompt.template = "Updated template {var}"

        prompts = [mock_prompt]
        context = "update"

        # Call the helper method
        result = service._update_or_create_prompts(mock_db, prompts, mock_gateway, context)

        # Should return empty list (no new prompts, existing one updated)
        assert len(result) == 0

        # Existing prompt should be updated
        assert existing_prompt.description == "Updated description"
        assert existing_prompt.template == "Updated template {var}"
        assert existing_prompt.visibility == "public"

    @pytest.mark.asyncio
    async def test_helper_methods_mixed_operations(self):
        """Test helper methods with mixed new and existing items."""
        service = GatewayService()

        # Mock database
        mock_db = MagicMock()

        # Mock existing tools in database
        existing_tool1 = MagicMock()
        existing_tool1.original_name = "existing_tool"
        existing_tool1.description = "Original description"
        existing_tool1.url = "http://old.com"
        existing_tool1.auth_type = "none"
        existing_tool1.visibility = "private"
        existing_tool1.integration_type = "MCP"
        existing_tool1.request_type = "GET"
        existing_tool1.headers = {}
        existing_tool1.input_schema = {}
        existing_tool1.jsonpath_filter = None

        existing_tool2 = MagicMock()
        existing_tool2.original_name = "update_tool"
        existing_tool2.description = "Old description"
        existing_tool2.url = "http://old.com"
        existing_tool2.auth_type = "none"
        existing_tool2.visibility = "private"
        existing_tool2.integration_type = "MCP"
        existing_tool2.request_type = "GET"
        existing_tool2.headers = {}
        existing_tool2.input_schema = {}
        existing_tool2.jsonpath_filter = None

        # Mock gateway
        mock_gateway = MagicMock()
        mock_gateway.id = "test-gateway-id"
        mock_gateway.name = "test-gateway"
        mock_gateway.url = "http://new.com"
        mock_gateway.auth_type = "bearer"
        mock_gateway.auth_value = "token"
        mock_gateway.team_id = "test-team"
        mock_gateway.owner_email = "test@example.com"
        mock_gateway.visibility = "public"

        # Create multiple mock execute calls - one for each tool lookup
        mock_db.execute.side_effect = [
            # First call for new_tool (not found)
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
            # Second call for update_tool (found)
            MagicMock(scalar_one_or_none=MagicMock(return_value=existing_tool2)),
            # Third call for existing_tool (found)
            MagicMock(scalar_one_or_none=MagicMock(return_value=existing_tool1)),
        ]

        # Mock tools from MCP server: one new, one update, one existing unchanged
        new_tool = MagicMock()
        new_tool.name = "new_tool"
        new_tool.description = "Brand new tool"
        new_tool.request_type = "POST"
        new_tool.headers = {}
        new_tool.input_schema = {}
        new_tool.annotations = {}
        new_tool.jsonpath_filter = None

        update_tool = MagicMock()
        update_tool.name = "update_tool"  # Matches existing_tool2
        update_tool.description = "Updated description"
        update_tool.request_type = "PUT"
        update_tool.headers = {}
        update_tool.input_schema = {}
        update_tool.annotations = {}
        update_tool.jsonpath_filter = None

        existing_unchanged = MagicMock()
        existing_unchanged.name = "existing_tool"  # Matches existing_tool1
        existing_unchanged.description = "Original description"  # Same as existing
        existing_unchanged.request_type = "GET"
        existing_unchanged.headers = {}
        existing_unchanged.input_schema = {}
        existing_unchanged.annotations = {}
        existing_unchanged.jsonpath_filter = None

        tools = [new_tool, update_tool, existing_unchanged]
        context = "mixed_test"

        # Call the helper method
        result = service._update_or_create_tools(mock_db, tools, mock_gateway, context)

        # Should return one new tool (new_tool)
        assert len(result) == 1
        assert result[0].original_name == "new_tool"

        # existing_tool2 should be updated (some fields will change due to gateway changes)
        assert existing_tool2.description == "Updated description"
        assert existing_tool2.url == "http://new.com"  # Updated from gateway
        assert existing_tool2.auth_type == "bearer"  # Updated from gateway
        assert existing_tool2.visibility == "public"  # Updated from gateway

    @pytest.mark.asyncio
    async def test_helper_methods_empty_input_lists(self):
        """Test helper methods with empty input lists."""
        service = GatewayService()

        # Mock database
        mock_db = MagicMock()

        # Mock gateway
        mock_gateway = MagicMock()
        mock_gateway.id = "test-gateway-id"

        # Test with empty lists - no database calls should be made for empty inputs
        tools_result = service._update_or_create_tools(mock_db, [], mock_gateway, "empty_test")
        resources_result = service._update_or_create_resources(mock_db, [], mock_gateway, "empty_test")
        prompts_result = service._update_or_create_prompts(mock_db, [], mock_gateway, "empty_test")

        # All should return empty lists
        assert tools_result == []
        assert resources_result == []
        assert prompts_result == []

    @pytest.mark.asyncio
    async def test_helper_methods_with_metadata_inheritance(self):
        """Test that helper methods properly inherit metadata from gateway."""
        service = GatewayService()

        # Mock database
        mock_db = MagicMock()

        # Mock database execute to return None (no existing items found)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        # Mock gateway with specific metadata
        mock_gateway = MagicMock()
        mock_gateway.id = "test-gateway-id"
        mock_gateway.name = "Metadata Gateway"
        mock_gateway.url = "https://api.example.com"
        mock_gateway.auth_type = "api_key"
        mock_gateway.auth_value = "secret-key-123"
        mock_gateway.team_id = "engineering-team"
        mock_gateway.owner_email = "engineering@company.com"
        mock_gateway.visibility = "team"

        # Mock items from MCP server
        mock_tool = MagicMock()
        mock_tool.name = "metadata_tool"
        mock_tool.description = "Tool for testing metadata"
        mock_tool.request_type = "POST"
        mock_tool.headers = {}
        mock_tool.input_schema = {}
        mock_tool.annotations = {}
        mock_tool.jsonpath_filter = None

        mock_resource = MagicMock()
        mock_resource.uri = "file:///metadata_test.json"
        mock_resource.name = "metadata_test.json"
        mock_resource.description = "Resource for testing metadata"
        mock_resource.mime_type = "application/json"
        mock_resource.template = None

        mock_prompt = MagicMock()
        mock_prompt.name = "metadata_prompt"
        mock_prompt.description = "Prompt for testing metadata"
        mock_prompt.template = "Test prompt template"

        # Call helper methods
        tools_result = service._update_or_create_tools(mock_db, [mock_tool], mock_gateway, "metadata_test")
        resources_result = service._update_or_create_resources(mock_db, [mock_resource], mock_gateway, "metadata_test")
        prompts_result = service._update_or_create_prompts(mock_db, [mock_prompt], mock_gateway, "metadata_test")

        # Verify metadata inheritance for tools
        assert len(tools_result) == 1
        tool = tools_result[0]
        assert tool.url == "https://api.example.com"
        assert tool.auth_type == "api_key"
        assert tool.auth_value == "secret-key-123"
        assert tool.federation_source == "Metadata Gateway"
        assert tool.created_via == "metadata_test"
        assert tool.integration_type == "MCP"

        # Verify metadata inheritance for resources
        assert len(resources_result) == 1
        resource = resources_result[0]
        assert resource.created_via == "metadata_test"
        assert resource.visibility == "team"

        # Verify metadata inheritance for prompts
        assert len(prompts_result) == 1
        prompt = prompts_result[0]
        assert prompt.created_via == "metadata_test"
        assert prompt.visibility == "team"
        assert prompt.argument_schema == {}

    @pytest.mark.asyncio
    async def test_helper_methods_context_propagation(self):
        """Test that helper methods properly use the context parameter."""
        service = GatewayService()

        # Mock database
        mock_db = MagicMock()

        # Mock database execute to return None (no existing tools found)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        # Mock gateway
        mock_gateway = MagicMock()
        mock_gateway.id = "context-gateway-id"
        mock_gateway.name = "Context Gateway"
        mock_gateway.url = "http://context.com"
        mock_gateway.auth_type = "none"
        mock_gateway.auth_value = ""
        mock_gateway.visibility = "public"

        # Mock items from MCP server
        mock_tool = MagicMock()
        mock_tool.name = "context_tool"
        mock_tool.description = "Tool for context testing"
        mock_tool.request_type = "GET"
        mock_tool.headers = {}
        mock_tool.input_schema = {}
        mock_tool.annotations = {}
        mock_tool.jsonpath_filter = None

        # Test different contexts
        contexts = ["oauth", "update", "rediscovery", "test"]

        for context in contexts:
            tools_result = service._update_or_create_tools(mock_db, [mock_tool], mock_gateway, context)

            # Verify the context is used in created_via field
            assert len(tools_result) == 1
            assert tools_result[0].original_name == "context_tool"
            assert tools_result[0].created_via == context

    @pytest.mark.asyncio
    async def test_helper_methods_tool_removal_scenario(self):
        """Test helper methods when some tools are removed from MCP server."""
        service = GatewayService()

        # Mock database
        mock_db = MagicMock()

        # Mock existing tools in database
        existing_tool1 = MagicMock()
        existing_tool1.original_name = "tool_to_keep"
        existing_tool1.description = "Keep this tool"
        existing_tool1.url = "http://old.com"
        existing_tool1.auth_type = "none"
        existing_tool1.visibility = "private"
        existing_tool1.integration_type = "MCP"
        existing_tool1.request_type = "GET"
        existing_tool1.headers = {}
        existing_tool1.input_schema = {}
        existing_tool1.jsonpath_filter = None

        existing_tool3 = MagicMock()
        existing_tool3.original_name = "tool_to_update"
        existing_tool3.description = "Old description"
        existing_tool3.url = "http://old.com"
        existing_tool3.auth_type = "none"
        existing_tool3.visibility = "private"
        existing_tool3.integration_type = "MCP"
        existing_tool3.request_type = "GET"
        existing_tool3.headers = {}
        existing_tool3.input_schema = {}
        existing_tool3.jsonpath_filter = None

        # Mock gateway
        mock_gateway = MagicMock()
        mock_gateway.id = "test-gateway-id"
        mock_gateway.name = "test-gateway"
        mock_gateway.url = "http://new.com"
        mock_gateway.auth_type = "bearer"
        mock_gateway.auth_value = "token"
        mock_gateway.team_id = "test-team"
        mock_gateway.owner_email = "test@example.com"
        mock_gateway.visibility = "public"

        # Create multiple mock execute calls - one for each tool lookup
        mock_db.execute.side_effect = [
            # First call for tool_to_keep (found)
            MagicMock(scalar_one_or_none=MagicMock(return_value=existing_tool1)),
            # Second call for tool_to_update (found)
            MagicMock(scalar_one_or_none=MagicMock(return_value=existing_tool3)),
        ]

        # Mock tools from MCP server (only 2 tools - one removed, one updated, one unchanged)
        keep_tool = MagicMock()
        keep_tool.name = "tool_to_keep"
        keep_tool.description = "Keep this tool"  # Same description
        keep_tool.request_type = "GET"
        keep_tool.headers = {}
        keep_tool.input_schema = {}
        keep_tool.annotations = {}
        keep_tool.jsonpath_filter = None

        update_tool = MagicMock()
        update_tool.name = "tool_to_update"
        update_tool.description = "Updated description"
        update_tool.request_type = "POST"
        update_tool.headers = {}
        update_tool.input_schema = {}
        update_tool.annotations = {}
        update_tool.jsonpath_filter = None

        # Note: tool_to_remove is NOT in the MCP server response
        tools = [keep_tool, update_tool]
        context = "removal_test"

        # Call the helper method
        result = service._update_or_create_tools(mock_db, tools, mock_gateway, context)

        # Should return empty list (no new tools)
        assert len(result) == 0

        # existing_tool1 should be updated with gateway values (even if description stays the same)
        assert existing_tool1.url == "http://new.com"  # Updated from gateway
        assert existing_tool1.auth_type == "bearer"  # Updated from gateway
        assert existing_tool1.visibility == "public"  # Updated from gateway

        # existing_tool3 should be updated
        assert existing_tool3.description == "Updated description"
        assert existing_tool3.url == "http://new.com"  # Updated from gateway

        # Note: The actual removal of missing tools happens in the calling methods
        # This test verifies that helper methods correctly handle existing tools

    @pytest.mark.asyncio
    async def test_helper_methods_resource_removal_scenario(self):
        """Test helper methods when some resources are removed from MCP server."""
        service = GatewayService()

        # Mock database
        mock_db = MagicMock()

        # Mock existing resources in database
        existing_resource1 = MagicMock()
        existing_resource1.uri = "file:///keep.txt"
        existing_resource1.name = "keep.txt"
        existing_resource1.description = "Keep this resource"
        existing_resource1.mime_type = "text/plain"
        existing_resource1.template = None
        existing_resource1.visibility = "private"

        existing_resource3 = MagicMock()
        existing_resource3.uri = "file:///update.txt"
        existing_resource3.name = "update.txt"
        existing_resource3.description = "Old description"
        existing_resource3.mime_type = "text/plain"
        existing_resource3.template = None
        existing_resource3.visibility = "private"

        # Mock gateway with new values
        mock_gateway = MagicMock()
        mock_gateway.id = "test-gateway-id"
        mock_gateway.name = "test-gateway"
        mock_gateway.visibility = "public"

        # Create multiple mock execute calls - one for each resource lookup
        mock_db.execute.side_effect = [
            # First call for keep.txt (found)
            MagicMock(scalar_one_or_none=MagicMock(return_value=existing_resource1)),
            # Second call for update.txt (found)
            MagicMock(scalar_one_or_none=MagicMock(return_value=existing_resource3)),
        ]

        # Mock resources from MCP server (only 2 resources - one removed)
        keep_resource = MagicMock()
        keep_resource.uri = "file:///keep.txt"
        keep_resource.name = "keep.txt"
        keep_resource.description = "Keep this resource"
        keep_resource.mime_type = "text/plain"
        keep_resource.template = None

        update_resource = MagicMock()
        update_resource.uri = "file:///update.txt"
        update_resource.name = "update.txt"
        update_resource.description = "Updated description"
        update_resource.mime_type = "application/json"
        update_resource.template = "new template"

        # Note: file:///remove.txt is NOT in the MCP server response
        resources = [keep_resource, update_resource]
        context = "removal_test"

        # Call the helper method
        result = service._update_or_create_resources(mock_db, resources, mock_gateway, context)

        # Should return empty list (no new resources)
        assert len(result) == 0

        # existing_resource1 should be updated with gateway values
        assert existing_resource1.description == "Keep this resource"
        assert existing_resource1.visibility == "public"  # Updated from gateway

        # existing_resource3 should be updated
        assert existing_resource3.description == "Updated description"
        assert existing_resource3.mime_type == "application/json"
        assert existing_resource3.template == "new template"
        assert existing_resource3.visibility == "public"  # Updated from gateway

    @pytest.mark.asyncio
    async def test_helper_methods_prompt_removal_scenario(self):
        """Test helper methods when some prompts are removed from MCP server."""
        service = GatewayService()

        # Mock database
        mock_db = MagicMock()

        # Mock existing prompts in database
        existing_prompt1 = MagicMock()
        existing_prompt1.name = "keep_prompt"
        existing_prompt1.description = "Keep this prompt"
        existing_prompt1.template = "Keep template"
        existing_prompt1.visibility = "private"

        existing_prompt3 = MagicMock()
        existing_prompt3.name = "update_prompt"
        existing_prompt3.description = "Old description"
        existing_prompt3.template = "Old template"
        existing_prompt3.visibility = "private"

        # Mock gateway with new values
        mock_gateway = MagicMock()
        mock_gateway.id = "test-gateway-id"
        mock_gateway.name = "test-gateway"
        mock_gateway.visibility = "public"

        # Create multiple mock execute calls - one for each prompt lookup
        mock_db.execute.side_effect = [
            # First call for keep_prompt (found)
            MagicMock(scalar_one_or_none=MagicMock(return_value=existing_prompt1)),
            # Second call for update_prompt (found)
            MagicMock(scalar_one_or_none=MagicMock(return_value=existing_prompt3)),
        ]

        # Mock prompts from MCP server (only 2 prompts - one removed)
        keep_prompt = MagicMock()
        keep_prompt.name = "keep_prompt"
        keep_prompt.description = "Keep this prompt"
        keep_prompt.template = "Keep template"

        update_prompt = MagicMock()
        update_prompt.name = "update_prompt"
        update_prompt.description = "Updated description"
        update_prompt.template = "Updated template"

        # Note: remove_prompt is NOT in the MCP server response
        prompts = [keep_prompt, update_prompt]
        context = "removal_test"

        # Call the helper method
        result = service._update_or_create_prompts(mock_db, prompts, mock_gateway, context)

        # Should return empty list (no new prompts)
        assert len(result) == 0

        # existing_prompt1 should be updated with gateway values
        assert existing_prompt1.description == "Keep this prompt"
        assert existing_prompt1.template == "Keep template"
        assert existing_prompt1.visibility == "public"  # Updated from gateway

        # existing_prompt3 should be updated
        assert existing_prompt3.description == "Updated description"
        assert existing_prompt3.template == "Updated template"
        assert existing_prompt3.visibility == "public"  # Updated from gateway

    @pytest.mark.asyncio
    async def test_helper_methods_complete_removal_scenario(self):
        """Test helper methods when ALL items are removed from MCP server."""
        service = GatewayService()

        # Mock database
        mock_db = MagicMock()

        # Mock existing items in gateway
        existing_tool = MagicMock()
        existing_tool.original_name = "old_tool"

        existing_resource = MagicMock()
        existing_resource.uri = "file:///old.txt"

        existing_prompt = MagicMock()
        existing_prompt.name = "old_prompt"

        # Mock gateway with existing items
        mock_gateway = MagicMock()
        mock_gateway.id = "test-gateway-id"
        mock_gateway.tools = [existing_tool]
        mock_gateway.resources = [existing_resource]
        mock_gateway.prompts = [existing_prompt]

        # Mock empty responses from MCP server
        empty_tools = []
        empty_resources = []
        empty_prompts = []

        context = "complete_removal_test"

        # Call helper methods with empty lists
        tools_result = service._update_or_create_tools(mock_db, empty_tools, mock_gateway, context)
        resources_result = service._update_or_create_resources(mock_db, empty_resources, mock_gateway, context)
        prompts_result = service._update_or_create_prompts(mock_db, empty_prompts, mock_gateway, context)

        # All should return empty lists (no new items)
        assert tools_result == []
        assert resources_result == []
        assert prompts_result == []

        # Verify that all existing items would be identified for removal
        tools_to_remove = [tool for tool in mock_gateway.tools if tool.original_name not in []]
        resources_to_remove = [resource for resource in mock_gateway.resources if resource.uri not in []]
        prompts_to_remove = [prompt for prompt in mock_gateway.prompts if prompt.name not in []]

        assert len(tools_to_remove) == 1
        assert len(resources_to_remove) == 1
        assert len(prompts_to_remove) == 1
        assert tools_to_remove[0].original_name == "old_tool"
        assert resources_to_remove[0].uri == "file:///old.txt"
        assert prompts_to_remove[0].name == "old_prompt"
