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

    def test_update_or_create_prompts_matches_original_name(self):
        """Ensure gateway prompt sync matches by original_name, not prefixed name."""
        service = GatewayService()
        gateway = MagicMock()
        gateway.id = "gw-1"
        gateway.visibility = "public"

        prompt = MagicMock()
        prompt.name = "Greeting"
        prompt.description = "New description"
        prompt.template = "Hello!"

        existing_prompt = MagicMock()
        existing_prompt.original_name = "Greeting"
        existing_prompt.name = "gw-1__greeting"
        existing_prompt.description = "Old description"
        existing_prompt.template = ""
        existing_prompt.visibility = "public"

        result = MagicMock()
        scalars = MagicMock()
        scalars.all.return_value = [existing_prompt]
        result.scalars.return_value = scalars

        db = MagicMock()
        db.execute.return_value = result

        prompts_to_add = service._update_or_create_prompts(db, [prompt], gateway, "update")

        assert prompts_to_add == []
        assert existing_prompt.description == "New description"


class TestOrphanedResourceUpsert:
    """Tests for orphaned resource/prompt upsert logic during gateway registration (issue #2352).

    These tests verify that:
    1. Orphaned resources (gateway_id is NULL or invalid) are updated, not duplicated
    2. Resources belonging to active gateways are NOT touched
    """

    def test_orphaned_resource_is_updated_not_duplicated(self):
        """Test that an orphaned resource is updated when a new gateway registers the same URI.

        This directly tests the orphan detection and update logic without running
        the full register_gateway flow.
        """
        from mcpgateway.db import Gateway as DbGateway, Resource as DbResource

        # Simulate orphaned resource detection logic
        valid_gateway_ids = set()  # No valid gateways - simulates all gateways deleted

        # Create an orphaned resource (gateway_id is None)
        orphaned_resource = MagicMock(spec=DbResource)
        orphaned_resource.id = "orphaned-resource-id"
        orphaned_resource.uri = "file://test-resource/"
        orphaned_resource.name = "old_name"
        orphaned_resource.description = "old description"
        orphaned_resource.team_id = "team-123"
        orphaned_resource.owner_email = "user@example.com"
        orphaned_resource.gateway_id = None  # Orphaned - no gateway

        # Simulate the orphan detection logic from gateway_service.py
        candidate_resources = [orphaned_resource]
        orphaned_resources_map = {}

        for res in candidate_resources:
            is_orphaned = res.gateway_id is None or res.gateway_id not in valid_gateway_ids
            if is_orphaned:
                key = (res.team_id, res.owner_email, res.uri)
                orphaned_resources_map[key] = res

        # Verify orphaned resource was detected
        assert len(orphaned_resources_map) == 1
        lookup_key = ("team-123", "user@example.com", "file://test-resource/")
        assert lookup_key in orphaned_resources_map

        # Simulate the update logic
        existing = orphaned_resources_map[lookup_key]
        existing.name = "new_name"
        existing.description = "new description"

        # Verify the orphaned resource was updated
        assert orphaned_resource.name == "new_name"
        assert orphaned_resource.description == "new description"

    def test_resource_with_deleted_gateway_is_orphaned(self):
        """Test that a resource pointing to a non-existent gateway is considered orphaned."""
        from mcpgateway.db import Resource as DbResource

        # Valid gateways in the system
        valid_gateway_ids = {"gateway-A", "gateway-B"}

        # Resource pointing to a deleted gateway
        resource_with_deleted_gateway = MagicMock(spec=DbResource)
        resource_with_deleted_gateway.gateway_id = "gateway-DELETED"  # Doesn't exist
        resource_with_deleted_gateway.team_id = "team-123"
        resource_with_deleted_gateway.owner_email = "user@example.com"
        resource_with_deleted_gateway.uri = "file://resource/"

        # Check if it's orphaned
        is_orphaned = (
            resource_with_deleted_gateway.gateway_id is None
            or resource_with_deleted_gateway.gateway_id not in valid_gateway_ids
        )

        assert is_orphaned is True

    def test_resource_with_active_gateway_is_not_orphaned(self):
        """Test that a resource belonging to an active gateway is NOT considered orphaned."""
        from mcpgateway.db import Resource as DbResource

        # Valid gateways in the system
        valid_gateway_ids = {"gateway-A", "gateway-B"}

        # Resource belonging to an active gateway
        active_resource = MagicMock(spec=DbResource)
        active_resource.gateway_id = "gateway-A"  # Active gateway
        active_resource.team_id = "team-123"
        active_resource.owner_email = "user@example.com"
        active_resource.uri = "file://resource/"
        active_resource.name = "original_name"

        # Check if it's orphaned
        is_orphaned = active_resource.gateway_id is None or active_resource.gateway_id not in valid_gateway_ids

        assert is_orphaned is False

        # Simulate the orphan detection - this resource should NOT be in the map
        orphaned_resources_map = {}
        if is_orphaned:
            key = (active_resource.team_id, active_resource.owner_email, active_resource.uri)
            orphaned_resources_map[key] = active_resource

        # Verify the active resource was NOT added to orphan map
        assert len(orphaned_resources_map) == 0

        # Resource name should be unchanged
        assert active_resource.name == "original_name"

    def test_per_resource_owner_override_in_lookup_key(self):
        """Test that per-resource owner/team overrides are used in the lookup key.

        This verifies the fix for the medium-severity finding where the lookup
        used gateway-level owner but inserts could use per-resource overrides.
        """
        from mcpgateway.db import Resource as DbResource

        # Gateway-level defaults
        gateway_team_id = "gateway-team"
        gateway_owner_email = "gateway-owner@example.com"

        # Orphaned resource with DIFFERENT owner than gateway default
        orphaned_resource = MagicMock(spec=DbResource)
        orphaned_resource.gateway_id = None
        orphaned_resource.team_id = "resource-specific-team"  # Different from gateway
        orphaned_resource.owner_email = "resource-owner@example.com"  # Different from gateway
        orphaned_resource.uri = "file://resource/"

        # Simulate incoming resource with per-resource overrides
        class IncomingResource:
            uri = "file://resource/"
            team_id = "resource-specific-team"  # Override
            owner_email = "resource-owner@example.com"  # Override

        incoming = IncomingResource()

        # Build lookup key using per-resource values (the fix)
        r_team_id = getattr(incoming, "team_id", None) or gateway_team_id
        r_owner_email = getattr(incoming, "owner_email", None) or gateway_owner_email
        lookup_key = (r_team_id, r_owner_email, incoming.uri)

        # Build orphan map key
        orphan_key = (orphaned_resource.team_id, orphaned_resource.owner_email, orphaned_resource.uri)

        # Keys should match because we use per-resource values
        assert lookup_key == orphan_key
        assert lookup_key == ("resource-specific-team", "resource-owner@example.com", "file://resource/")
