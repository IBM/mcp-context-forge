# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_gateway_resources_prompts.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for gateway service resource and prompt fetching functionality.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.schemas import PromptCreate, ResourceCreate, ToolCreate
from mcpgateway.services.gateway_service import GatewayService


class TestGatewayResourcesPrompts:
    """Test suite for resources and prompts functionality in GatewayService."""

    @pytest.mark.asyncio
    async def test_initialize_gateway_with_resources_and_prompts_sse(self):
        """Test _initialize_gateway fetches resources and prompts via SSE transport."""
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
            mock_init_response.capabilities.model_dump.return_value = {"protocolVersion": "0.1.0", "resources": {"listChanged": True}, "prompts": {"listChanged": True}, "tools": {"listChanged": True}}
            mock_session_instance.initialize.return_value = mock_init_response

            # Mock tools response
            mock_tools_response = MagicMock()
            mock_tool = MagicMock()
            mock_tool.model_dump.return_value = {"name": "test_tool", "description": "Test tool", "inputSchema": {}}
            mock_tools_response.tools = [mock_tool]
            mock_session_instance.list_tools.return_value = mock_tools_response

            # Mock resources response
            mock_resources_response = MagicMock()
            mock_resource = MagicMock()
            mock_resource.model_dump.return_value = {"uri": "test://resource", "name": "Test Resource", "description": "A test resource", "mime_type": "text/plain"}
            mock_resources_response.resources = [mock_resource]
            mock_session_instance.list_resources.return_value = mock_resources_response

            # Mock prompts response
            mock_prompts_response = MagicMock()
            mock_prompt = MagicMock()
            mock_prompt.model_dump.return_value = {"name": "test_prompt", "description": "A test prompt", "template": "Test template {{arg}}", "arguments": [{"name": "arg", "type": "string"}]}
            mock_prompts_response.prompts = [mock_prompt]
            mock_session_instance.list_prompts.return_value = mock_prompts_response

            # Execute
            capabilities, tools, resources, prompts = await service._initialize_gateway("http://test.example.com", {"Authorization": "Bearer token"}, "SSE")

            # Verify
            assert capabilities["resources"]["listChanged"] is True
            assert capabilities["prompts"]["listChanged"] is True
            assert len(tools) == 1
            assert len(resources) == 1
            assert len(prompts) == 1
            assert isinstance(tools[0], ToolCreate)
            assert isinstance(resources[0], ResourceCreate)
            assert isinstance(prompts[0], PromptCreate)

            # Verify the methods were called
            mock_session_instance.list_tools.assert_called_once()
            mock_session_instance.list_resources.assert_called_once()
            mock_session_instance.list_prompts.assert_called_once()

    @pytest.mark.asyncio
    async def test_initialize_gateway_resources_prompts_not_supported(self):
        """Test _initialize_gateway when server doesn't support resources/prompts."""
        service = GatewayService()

        with (
            patch("mcpgateway.services.gateway_service.sse_client") as mock_sse_client,
            patch("mcpgateway.services.gateway_service.ClientSession") as mock_session,
            patch("mcpgateway.services.gateway_service.decode_auth") as mock_decode,
        ):
            # Setup mocks
            mock_decode.return_value = {}

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

            # Mock responses - no resources/prompts capabilities
            mock_init_response = MagicMock()
            mock_init_response.capabilities.model_dump.return_value = {"protocolVersion": "0.1.0", "tools": {"listChanged": True}}
            mock_session_instance.initialize.return_value = mock_init_response

            # Mock tools response
            mock_tools_response = MagicMock()
            mock_tool = MagicMock()
            mock_tool.model_dump.return_value = {"name": "test_tool", "description": "Test tool", "inputSchema": {}}
            mock_tools_response.tools = [mock_tool]
            mock_session_instance.list_tools.return_value = mock_tools_response

            # Execute
            capabilities, tools, resources, prompts = await service._initialize_gateway("http://test.example.com", None, "SSE")

            # Verify
            assert "resources" not in capabilities
            assert "prompts" not in capabilities
            assert len(tools) == 1
            assert resources == []
            assert prompts == []

            # Verify list_resources and list_prompts were NOT called
            mock_session_instance.list_resources.assert_not_called()
            mock_session_instance.list_prompts.assert_not_called()

    @pytest.mark.asyncio
    async def test_initialize_gateway_resources_fetch_failure(self):
        """Test _initialize_gateway handles failure to fetch resources gracefully."""
        service = GatewayService()

        with (
            patch("mcpgateway.services.gateway_service.sse_client") as mock_sse_client,
            patch("mcpgateway.services.gateway_service.ClientSession") as mock_session,
            patch("mcpgateway.services.gateway_service.decode_auth") as mock_decode,
        ):
            # Setup mocks
            mock_decode.return_value = {}

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

            # Mock responses with resources capability
            mock_init_response = MagicMock()
            mock_init_response.capabilities.model_dump.return_value = {"protocolVersion": "0.1.0", "resources": {"listChanged": True}, "prompts": {"listChanged": True}, "tools": {"listChanged": True}}
            mock_session_instance.initialize.return_value = mock_init_response

            # Mock tools response - success
            mock_tools_response = MagicMock()
            mock_tool = MagicMock()
            mock_tool.model_dump.return_value = {"name": "test_tool", "description": "Test tool", "inputSchema": {}}
            mock_tools_response.tools = [mock_tool]
            mock_session_instance.list_tools.return_value = mock_tools_response

            # Mock resources response - failure
            mock_session_instance.list_resources.side_effect = Exception("Failed to fetch resources")

            # Mock prompts response - failure
            mock_session_instance.list_prompts.side_effect = Exception("Failed to fetch prompts")

            # Execute
            capabilities, tools, resources, prompts = await service._initialize_gateway("http://test.example.com", None, "SSE")

            # Verify - should return empty lists for resources/prompts on failure
            assert len(tools) == 1
            assert resources == []
            assert prompts == []

            # Verify the methods were called despite failure
            mock_session_instance.list_resources.assert_called_once()
            mock_session_instance.list_prompts.assert_called_once()
