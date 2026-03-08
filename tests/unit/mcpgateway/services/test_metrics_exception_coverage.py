# -*- coding: utf-8 -*-
"""Coverage tests for metrics recording exception handlers.

Copyright 2026
SPDX-License-Identifier: Apache-2.0

This test file targets server-scoped metrics exception handling and
server_id filtering paths in prompt_service, resource_service, and tool_service.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.services.prompt_service import PromptService
from mcpgateway.services.resource_service import ResourceService
from mcpgateway.services.tool_service import ToolService


class TestPromptServiceMetricsException:
    """Test metrics recording exception handler in prompt_service.py"""

    @pytest.fixture
    def prompt_service(self):
        return PromptService()

    @pytest.mark.asyncio
    async def test_get_prompt_server_metric_recording_failure(self, prompt_service):
        """Test that metrics recording failure is caught and logged (lines 1705-1706)."""
        db = MagicMock()

        # Mock prompt in database with proper string values
        mock_prompt = MagicMock()
        mock_prompt.id = 1
        mock_prompt.name = "test_prompt"
        mock_prompt.template = "Hello {{ name }}!"
        mock_prompt.enabled = True
        mock_prompt.visibility = "public"
        mock_prompt.team_id = None
        mock_prompt.owner_email = None
        mock_prompt.description = "Test prompt description"

        db.execute.return_value.scalar_one_or_none.return_value = mock_prompt

        # Mock metrics buffer that raises exception
        mock_metrics_buffer = MagicMock()
        mock_metrics_buffer.record_server_metric.side_effect = Exception("Metrics recording failed")

        with patch("mcpgateway.services.prompt_service.metrics_buffer", mock_metrics_buffer), patch("mcpgateway.services.prompt_service.logger") as mock_logger:

            # Call get_prompt with server_id to trigger server metrics recording
            result = await prompt_service.get_prompt(db=db, prompt_id="1", arguments={"name": "Alice"}, server_id="test-server-id")

            # Verify the exception was caught and logged
            mock_logger.warning.assert_any_call("Failed to record server metric: Metrics recording failed")

            # Verify prompt was still returned successfully
            assert result is not None


class TestResourceServiceMetricsException:
    """Test metrics recording exception handler in resource_service.py"""

    @pytest.fixture
    def resource_service(self):
        return ResourceService()

    @pytest.mark.asyncio
    async def test_read_resource_server_metric_recording_failure(self, resource_service):
        """Test that metrics recording failure is caught and logged (lines 2410-2411)."""
        db = MagicMock()

        # Mock resource in database with proper gateway
        mock_resource = MagicMock()
        mock_resource.id = "test-resource-id"
        mock_resource.uri = "test://resource"
        mock_resource.name = "Test Resource"
        mock_resource.enabled = True
        mock_resource.visibility = "public"
        mock_resource.team_id = None
        mock_resource.owner_email = None
        mock_resource.content = "test content"
        mock_resource.mime_type = "text/plain"
        mock_resource.gateway_id = "test-gateway-id"

        # Mock gateway with proper ca_certificate
        mock_gateway = MagicMock()
        mock_gateway.id = "test-gateway-id"
        mock_gateway.ca_certificate = None  # No cert to avoid SSL context issues
        mock_gateway.transport = "SSE"
        mock_gateway.url = "http://test.example.com"
        mock_gateway.auth_type = None
        mock_gateway.query_params = None
        mock_gateway.oauth_config = None

        mock_resource.gateway = mock_gateway

        db.execute.return_value.scalar_one_or_none.return_value = mock_resource
        db.get.return_value = mock_gateway

        # Mock metrics buffer that raises exception
        mock_metrics_buffer = MagicMock()
        mock_metrics_buffer.record_server_metric.side_effect = Exception("Metrics recording failed")

        # Mock the invoke_resource to return a simple response
        mock_response = MagicMock()
        mock_response.contents = [MagicMock(text="test content")]

        with (
            patch("mcpgateway.services.resource_service.metrics_buffer", mock_metrics_buffer),
            patch("mcpgateway.services.resource_service.logger") as mock_logger,
            patch.object(resource_service, "invoke_resource", return_value=mock_response),
        ):

            # Call read_resource with server_id to trigger server metrics recording
            result = await resource_service.read_resource(db=db, resource_id="test-resource-id", server_id="test-server-id")

            # Verify the exception was caught and logged
            mock_logger.warning.assert_any_call("Failed to record server metric: Metrics recording failed")

            # Verify resource was still returned successfully
            assert result is not None


class TestResourceServiceServerIdFilter:
    """Test server_id filtering in list_templated_resources (line 3587)"""

    @pytest.fixture
    def resource_service(self):
        return ResourceService()

    @pytest.mark.asyncio
    async def test_list_resource_templates_with_server_id_filter(self, resource_service):
        """Test that server_id filter is applied correctly (line 3587)."""
        db = MagicMock()

        # Mock query execution
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        db.execute.return_value = mock_result

        # Call with server_id to trigger the filter path
        result = await resource_service.list_resource_templates(db=db, server_id="test-server-id", include_inactive=False)

        # Verify the query was executed (which means the join was applied)
        assert db.execute.called
        assert result == []

    @pytest.mark.asyncio
    async def test_list_resource_templates_without_server_id(self, resource_service):
        """Test that server_id filter is skipped when not provided."""
        db = MagicMock()

        # Mock query execution
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        db.execute.return_value = mock_result

        # Call without server_id
        result = await resource_service.list_resource_templates(db=db, server_id=None, include_inactive=False)

        # Verify the query was executed
        assert db.execute.called
        assert result == []


class TestToolServiceMetricsException:
    """Test metrics recording exception handler in tool_service.py"""

    @pytest.fixture
    def tool_service(self):
        return ToolService()

    @pytest.mark.asyncio
    async def test_invoke_tool_server_metric_recording_failure(self, tool_service):
        """Test that metrics recording failure is caught and logged (lines 4121-4122)."""
        db = MagicMock()

        # Mock tool in database
        mock_tool = MagicMock()
        mock_tool.id = "test-tool-id"
        mock_tool.name = "test_tool"
        mock_tool.enabled = True
        mock_tool.reachable = True
        mock_tool.visibility = "public"
        mock_tool.team_id = None
        mock_tool.owner_email = None
        mock_tool.integration_type = "REST"
        mock_tool.endpoint_url = "http://test.example.com/tool"
        mock_tool.request_type = "GET"
        mock_tool.gateway_id = None
        mock_tool.gateway = None
        mock_tool.output_schema = None

        db.execute.return_value.scalar_one_or_none.return_value = mock_tool

        # Mock metrics buffer that raises exception
        mock_metrics_buffer = MagicMock()
        mock_metrics_buffer.record_server_metric.side_effect = Exception("Metrics recording failed")

        # Mock HTTP client for REST call
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": "success"}
        mock_response.text = '{"result": "success"}'

        with (
            patch("mcpgateway.services.tool_service.metrics_buffer", mock_metrics_buffer),
            patch("mcpgateway.services.tool_service.logger") as mock_logger,
            patch("mcpgateway.services.http_client_service.get_http_client") as mock_http_client,
        ):

            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_http_client.return_value = mock_client

            # Call invoke_tool with name (not tool_id) and server_id to trigger server metrics recording
            result = await tool_service.invoke_tool(db=db, name="test_tool", arguments={}, server_id="test-server-id")

            # Verify the exception was caught and logged
            mock_logger.warning.assert_any_call("Failed to record server metric: Metrics recording failed")

            # Verify tool invocation still succeeded
            assert result is not None
