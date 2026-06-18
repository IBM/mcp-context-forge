# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_gateway_auto_refresh.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for the auto-refresh tools/resources/prompts feature in GatewayService.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import Prompt as DbPrompt
from mcpgateway.db import Resource as DbResource
from mcpgateway.db import Tool as DbTool
from mcpgateway.services.gateway_service import GatewayService


@pytest.fixture(autouse=True)
def mock_logging_services():
    """Mock audit_trail and structured_logger to prevent database writes during tests."""
    with (
        patch("mcpgateway.services.gateway_service.audit_trail") as mock_audit,
        patch("mcpgateway.services.gateway_service.structured_logger") as mock_logger,
    ):
        mock_audit.log_action = MagicMock(return_value=None)
        mock_logger.log = MagicMock(return_value=None)
        yield {"audit_trail": mock_audit, "structured_logger": mock_logger}


@pytest.fixture
def gateway_service():
    """Create a GatewayService instance with mocked dependencies."""
    with patch("mcpgateway.services.gateway_service.SessionLocal"):
        service = GatewayService()
        service.oauth_manager = AsyncMock()
        return service


def _make_mock_gateway(
    gateway_id: str = "gw-123",
    name: str = "test-gateway",
    enabled: bool = True,
    reachable: bool = True,
    oauth_config: Dict[str, Any] | None = None,
) -> MagicMock:
    """Create a mock gateway object."""
    mock = MagicMock(spec=DbGateway)
    mock.id = gateway_id
    mock.name = name
    mock.enabled = enabled
    mock.reachable = reachable
    mock.url = "http://test-server:8000"
    mock.transport = "SSE"
    mock.auth_type = "oauth" if oauth_config else None
    mock.auth_value = None
    mock.oauth_config = oauth_config
    mock.ca_certificate = None
    mock.visibility = "private"
    mock.tools = []
    mock.resources = []
    mock.prompts = []
    return mock


def _make_mock_tool(tool_id: str, name: str, created_via: str = "health_check") -> MagicMock:
    """Create a mock tool object."""
    mock = MagicMock(spec=DbTool)
    mock.id = tool_id
    mock.original_name = name
    mock.created_via = created_via
    return mock


def _make_mock_resource(resource_id: str, uri: str, created_via: str = "health_check") -> MagicMock:
    """Create a mock resource object."""
    mock = MagicMock(spec=DbResource)
    mock.id = resource_id
    mock.uri = uri
    mock.created_via = created_via
    return mock


def _make_mock_prompt(prompt_id: str, name: str, created_via: str = "health_check") -> MagicMock:
    """Create a mock prompt object."""
    mock = MagicMock(spec=DbPrompt)
    mock.id = prompt_id
    mock.original_name = name
    mock.created_via = created_via
    return mock


class TestAutoRefreshGatewayToolsResourcesPrompts:
    """Tests for _refresh_gateway_tools_resources_prompts method."""

    @pytest.mark.asyncio
    async def test_refresh_returns_empty_when_gateway_not_found(self, gateway_service):
        """Test that refresh returns empty result when gateway not found."""
        mock_session = MagicMock()
        mock_session.execute.return_value.scalar_one_or_none.return_value = None

        with patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh:
            mock_fresh.return_value.__enter__.return_value = mock_session

            result = await gateway_service._refresh_gateway_tools_resources_prompts("gw-404")

        assert result == {
            "tools_added": 0,
            "tools_removed": 0,
            "tools_updated": 0,
            "resources_added": 0,
            "resources_removed": 0,
            "resources_updated": 0,
            "prompts_added": 0,
            "prompts_removed": 0,
            "prompts_updated": 0,
            "success": True,
            "error": None,
            "validation_errors": [],
        }

    @pytest.mark.asyncio
    async def test_refresh_skips_disabled_gateway(self, gateway_service):
        """Test that refresh skips disabled gateways."""
        mock_gateway = _make_mock_gateway(enabled=False, reachable=True)
        mock_session = MagicMock()
        mock_session.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        with patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh:
            mock_fresh.return_value.__enter__.return_value = mock_session

            result = await gateway_service._refresh_gateway_tools_resources_prompts("gw-123")

        assert result["tools_added"] == 0

    @pytest.mark.asyncio
    async def test_refresh_skips_unreachable_gateway(self, gateway_service):
        """Test that refresh skips unreachable gateways."""
        mock_gateway = _make_mock_gateway(enabled=True, reachable=False)
        mock_session = MagicMock()
        mock_session.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        with patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh:
            mock_fresh.return_value.__enter__.return_value = mock_session

            result = await gateway_service._refresh_gateway_tools_resources_prompts("gw-123")

        assert result["tools_added"] == 0

    @pytest.mark.asyncio
    async def test_refresh_skips_auth_code_gateway_with_empty_response(self, gateway_service):
        """Test that refresh skips auth_code gateways when they return empty (incomplete auth)."""
        mock_gateway = _make_mock_gateway(oauth_config={"grant_type": "authorization_code"})
        mock_session = MagicMock()
        mock_session.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        with (
            patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh,
            patch.object(gateway_service, "_initialize_gateway", new_callable=AsyncMock) as mock_init,
        ):
            mock_fresh.return_value.__enter__.return_value = mock_session
            # Empty response from auth_code gateway
            mock_init.return_value = ({}, [], [], [], [])

            result = await gateway_service._refresh_gateway_tools_resources_prompts("gw-123")

        assert result["tools_added"] == 0
        assert result["tools_removed"] == 0

    @pytest.mark.asyncio
    async def test_refresh_processes_empty_non_auth_code_gateway(self, gateway_service):
        """Test that refresh processes empty responses from non-auth_code gateways."""
        # Gateway with client_credentials OAuth - empty response should trigger cleanup
        mock_gateway = _make_mock_gateway(oauth_config={"grant_type": "client_credentials"})
        mock_gateway.tools = [_make_mock_tool("t1", "old-tool")]
        mock_gateway.resources = []
        mock_gateway.prompts = []

        mock_session = MagicMock()
        mock_session.dirty = set()
        # First call: get gateway metadata; Second call: get gateway with relationships
        mock_session.execute.return_value.scalar_one_or_none.side_effect = [mock_gateway, mock_gateway]

        with (
            patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh,
            patch.object(gateway_service, "_initialize_gateway", new_callable=AsyncMock) as mock_init,
            patch("mcpgateway.services.gateway_service._get_registry_cache") as mock_cache,
            patch("mcpgateway.services.gateway_service._get_tool_lookup_cache") as mock_tool_cache,
        ):
            mock_fresh.return_value.__enter__.return_value = mock_session
            # Empty response from client_credentials gateway
            mock_init.return_value = ({}, [], [], [], [])
            mock_cache.return_value = AsyncMock()
            mock_tool_cache.return_value = AsyncMock()

            result = await gateway_service._refresh_gateway_tools_resources_prompts("gw-123")

        # Old tool should be marked for removal
        assert result["tools_removed"] == 1

    @pytest.mark.asyncio
    async def test_refresh_preserves_user_created_items(self, gateway_service):
        """Test that refresh only removes MCP-discovered items, not user-created ones."""
        mock_gateway = _make_mock_gateway()
        # Mix of MCP-discovered and user-created tools with various created_via values
        mock_gateway.tools = [
            _make_mock_tool("t1", "mcp-tool", created_via="health_check"),  # MCP-discovered, should be removed
            _make_mock_tool("t2", "ui-tool", created_via="ui"),  # User-created via UI, should be preserved
            _make_mock_tool("t3", "api-tool", created_via="api"),  # User-created via API, should be preserved
            _make_mock_tool("t4", "legacy-tool", created_via=None),  # Legacy entry, should be preserved
        ]
        mock_gateway.resources = []
        mock_gateway.prompts = []

        mock_session = MagicMock()
        mock_session.dirty = set()
        mock_session.execute.return_value.scalar_one_or_none.side_effect = [mock_gateway, mock_gateway]

        with (
            patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh,
            patch.object(gateway_service, "_initialize_gateway", new_callable=AsyncMock) as mock_init,
            patch("mcpgateway.services.gateway_service._get_registry_cache") as mock_cache,
            patch("mcpgateway.services.gateway_service._get_tool_lookup_cache") as mock_tool_cache,
        ):
            mock_fresh.return_value.__enter__.return_value = mock_session
            # Empty response - should only remove MCP-discovered tools
            mock_init.return_value = ({}, [], [], [], [])
            mock_cache.return_value = AsyncMock()
            mock_tool_cache.return_value = AsyncMock()

            result = await gateway_service._refresh_gateway_tools_resources_prompts("gw-123")

        # Only MCP-discovered tool (health_check) should be removed
        # ui, api, and None (legacy) should be preserved
        assert result["tools_removed"] == 1

    @pytest.mark.asyncio
    async def test_refresh_passes_pre_auth_headers_to_initialize_gateway(self, gateway_service):
        """Test that pre_auth_headers are passed to _initialize_gateway to avoid double OAuth."""
        mock_gateway = _make_mock_gateway()
        mock_session = MagicMock()
        mock_session.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        pre_auth_headers = {"Authorization": "Bearer pre-fetched-token"}

        with (
            patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh,
            patch.object(gateway_service, "_initialize_gateway", new_callable=AsyncMock) as mock_init,
        ):
            mock_fresh.return_value.__enter__.return_value = mock_session
            mock_init.return_value = ({}, [], [], [], [])

            await gateway_service._refresh_gateway_tools_resources_prompts("gw-123", pre_auth_headers=pre_auth_headers)

        # Verify pre_auth_headers was passed
        mock_init.assert_called_once()
        call_kwargs = mock_init.call_args.kwargs
        assert call_kwargs.get("pre_auth_headers") == pre_auth_headers


class TestInitializeGatewayPreAuthHeaders:
    """Tests for _initialize_gateway with pre_auth_headers."""

    @pytest.mark.asyncio
    async def test_pre_auth_headers_bypass_oauth_token_fetch(self, gateway_service):
        """Test that pre_auth_headers bypass OAuth token fetch."""
        pre_auth_headers = {"Authorization": "Bearer pre-fetched-token"}

        with (patch.object(gateway_service, "connect_to_sse_server", new_callable=AsyncMock) as mock_connect,):
            mock_connect.return_value = ({}, [], [], [], [])

            await gateway_service._initialize_gateway(
                url="http://test:8000",
                auth_type="oauth",
                oauth_config={"grant_type": "client_credentials"},
                pre_auth_headers=pre_auth_headers,
            )

        # OAuth manager should NOT have been called
        gateway_service.oauth_manager.get_access_token.assert_not_called()

        # SSE server should have been called with pre_auth_headers
        mock_connect.assert_called_once()
        call_args = mock_connect.call_args
        assert call_args[0][1] == pre_auth_headers  # Second positional arg is authentication


class TestCacheInvalidationPerType:
    """Tests for per-type cache invalidation on updates."""

    @pytest.mark.asyncio
    async def test_tool_add_invalidates_tool_cache(self, gateway_service):
        """Test that tool additions invalidate the tools cache."""
        mock_gateway = _make_mock_gateway()
        mock_gateway.tools = []
        mock_gateway.resources = []
        mock_gateway.prompts = []

        mock_session = MagicMock()
        mock_session.dirty = set()  # No dirty objects initially
        mock_session.execute.return_value.scalar_one_or_none.side_effect = [mock_gateway, mock_gateway]

        mock_tool_schema = MagicMock()
        mock_tool_schema.name = "new-tool"

        new_tool = _make_mock_tool("t1", "new-tool")
        mock_cache = AsyncMock()
        mock_tool_lookup_cache = AsyncMock()

        with (
            patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh,
            patch.object(gateway_service, "_initialize_gateway", new_callable=AsyncMock) as mock_init,
            patch.object(gateway_service, "_update_or_create_tools", new_callable=AsyncMock, return_value=([new_tool], [])),  # Returns (tools_to_add, restored_tool_names)
            patch.object(gateway_service, "_update_or_create_resources", return_value=[]),
            patch.object(gateway_service, "_update_or_create_prompts", return_value=[]),
            patch("mcpgateway.services.gateway_service._get_registry_cache") as get_cache,
            patch("mcpgateway.services.gateway_service._get_tool_lookup_cache") as get_tool_cache,
        ):
            mock_fresh.return_value.__enter__.return_value = mock_session
            mock_init.return_value = ({}, [mock_tool_schema], [], [], [])
            get_cache.return_value = mock_cache
            get_tool_cache.return_value = mock_tool_lookup_cache

            result = await gateway_service._refresh_gateway_tools_resources_prompts("gw-123")

        # Tools cache should be invalidated due to addition
        assert result["tools_added"] == 1
        mock_cache.invalidate_tools.assert_called_once()
        # Resources and prompts cache should NOT be invalidated (no changes)
        mock_cache.invalidate_resources.assert_not_called()
        mock_cache.invalidate_prompts.assert_not_called()

    @pytest.mark.asyncio
    async def test_restored_tools_invalidate_lookup_cache(self, gateway_service):
        """Test that restored tools (unreachable -> reachable) invalidate the lookup cache.

        Covers lines 5422-5425 in gateway_service.py (Bug #4915 fix).
        When a tool is restored (reachable changes from False to True), its negative
        cache entry must be invalidated so it becomes invokable immediately.
        """
        mock_gateway = _make_mock_gateway()
        mock_gateway.tools = []
        mock_gateway.resources = []
        mock_gateway.prompts = []

        mock_session = MagicMock()
        # Simulate one tool being updated (reachable status changed)
        mock_updated_tool = MagicMock(spec=DbTool)
        # Start with empty dirty set, add tool after _update_or_create_tools
        mock_session.dirty = set()
        mock_session.execute.return_value.scalar_one_or_none.side_effect = [mock_gateway, mock_gateway]

        mock_tool_schema = MagicMock()
        mock_tool_schema.name = "restored-tool"

        mock_cache = AsyncMock()
        mock_tool_lookup_cache = AsyncMock()

        def mock_update_or_create_tools_side_effect(*args, **kwargs):
            # Simulate tool being marked as dirty when updated
            mock_session.dirty.add(mock_updated_tool)
            return ([], ["restored-tool"])

        with (
            patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh,
            patch.object(gateway_service, "_initialize_gateway", new_callable=AsyncMock) as mock_init,
            # Return empty tools_to_add but include restored tool name (tool was updated, not added)
            patch.object(gateway_service, "_update_or_create_tools", new_callable=AsyncMock, side_effect=mock_update_or_create_tools_side_effect),
            patch.object(gateway_service, "_update_or_create_resources", return_value=[]),
            patch.object(gateway_service, "_update_or_create_prompts", return_value=[]),
            patch("mcpgateway.services.gateway_service._get_registry_cache") as get_cache,
            patch("mcpgateway.services.gateway_service._get_tool_lookup_cache") as get_tool_cache,
        ):
            mock_fresh.return_value.__enter__.return_value = mock_session
            mock_init.return_value = ({}, [mock_tool_schema], [], [], [])
            get_cache.return_value = mock_cache
            get_tool_cache.return_value = mock_tool_lookup_cache

            result = await gateway_service._refresh_gateway_tools_resources_prompts("gw-123")

        # Verify tool was marked as updated
        assert result["tools_updated"] == 1

        # Verify gateway-wide cache invalidation happened
        mock_tool_lookup_cache.invalidate_gateway.assert_called_once_with("gw-123")

        # Verify specific tool cache invalidation for restored tool (lines 5423-5424)
        mock_tool_lookup_cache.invalidate.assert_called_once_with("restored-tool", gateway_id="gw-123")

    @pytest.mark.asyncio
    async def test_multiple_restored_tools_invalidate_lookup_cache(self, gateway_service):
        """Test that multiple restored tools all have their cache entries invalidated.

        Ensures lines 5423-5425 loop is fully covered with multiple iterations.
        Tests the logger.debug statement at line 5425.
        """
        mock_gateway = _make_mock_gateway()
        mock_gateway.tools = []
        mock_gateway.resources = []
        mock_gateway.prompts = []

        mock_session = MagicMock()
        # Start with empty dirty set
        mock_session.dirty = set()
        mock_session.execute.return_value.scalar_one_or_none.side_effect = [mock_gateway, mock_gateway]

        mock_tool_schemas = [MagicMock(name=f"restored-tool-{i}") for i in range(3)]
        for i, schema in enumerate(mock_tool_schemas):
            schema.name = f"restored-tool-{i}"

        mock_cache = AsyncMock()
        mock_tool_lookup_cache = AsyncMock()

        restored_names = ["restored-tool-0", "restored-tool-1", "restored-tool-2"]
        mock_updated_tools = [MagicMock(spec=DbTool) for _ in range(3)]

        def mock_update_or_create_tools_side_effect(*args, **kwargs):
            # Simulate three tools being marked as dirty when updated
            for tool in mock_updated_tools:
                mock_session.dirty.add(tool)
            return ([], restored_names)

        with (
            patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh,
            patch.object(gateway_service, "_initialize_gateway", new_callable=AsyncMock) as mock_init,
            # Return empty tools_to_add but include all restored tool names
            patch.object(gateway_service, "_update_or_create_tools", new_callable=AsyncMock, side_effect=mock_update_or_create_tools_side_effect),
            patch.object(gateway_service, "_update_or_create_resources", return_value=[]),
            patch.object(gateway_service, "_update_or_create_prompts", return_value=[]),
            patch("mcpgateway.services.gateway_service._get_registry_cache") as get_cache,
            patch("mcpgateway.services.gateway_service._get_tool_lookup_cache") as get_tool_cache,
        ):
            mock_fresh.return_value.__enter__.return_value = mock_session
            mock_init.return_value = ({}, mock_tool_schemas, [], [], [])
            get_cache.return_value = mock_cache
            get_tool_cache.return_value = mock_tool_lookup_cache

            result = await gateway_service._refresh_gateway_tools_resources_prompts("gw-123")

        # Verify tools were marked as updated
        assert result["tools_updated"] == 3

        # Verify gateway-wide cache invalidation happened
        mock_tool_lookup_cache.invalidate_gateway.assert_called_once_with("gw-123")

        # Verify each restored tool had its cache invalidated (lines 5423-5424 loop)
        assert mock_tool_lookup_cache.invalidate.call_count == 3
        for tool_name in restored_names:
            mock_tool_lookup_cache.invalidate.assert_any_call(tool_name, gateway_id="gw-123")
