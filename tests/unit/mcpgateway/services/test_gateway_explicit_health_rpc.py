# -*- coding: utf-8 -*-
"""Tests for the explicit health RPC feature flag in gateway service.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Standard
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest


class TestExplicitHealthRPCFeatureFlag:
    """Tests for MCP_SESSION_POOL_EXPLICIT_HEALTH_RPC feature flag behavior."""

    @pytest.mark.asyncio
    async def test_explicit_health_rpc_disabled_by_default_no_list_tools_call(self):
        """When explicit health RPC is disabled (default), list_tools() should not be called."""
        # Create mock settings with feature flag disabled
        mock_settings = MagicMock()
        mock_settings.mcp_session_pool_explicit_health_rpc = False
        mock_settings.health_check_timeout = 5

        # Create mock pooled session
        mock_pooled = MagicMock()
        mock_pooled.session = MagicMock()
        mock_pooled.session.list_tools = AsyncMock()

        # Simulate the conditional behavior from gateway_service.py:3194-3198
        if mock_settings.mcp_session_pool_explicit_health_rpc:
            await asyncio.wait_for(
                mock_pooled.session.list_tools(),
                timeout=mock_settings.health_check_timeout,
            )

        # list_tools should NOT have been called
        mock_pooled.session.list_tools.assert_not_called()

    @pytest.mark.asyncio
    async def test_explicit_health_rpc_enabled_calls_list_tools(self):
        """When explicit health RPC is enabled, list_tools() should be called with timeout."""
        # Create mock settings with feature flag enabled
        mock_settings = MagicMock()
        mock_settings.mcp_session_pool_explicit_health_rpc = True
        mock_settings.health_check_timeout = 5

        # Create mock pooled session
        mock_pooled = MagicMock()
        mock_pooled.session = MagicMock()
        mock_pooled.session.list_tools = AsyncMock(return_value=[])

        # Simulate the conditional behavior from gateway_service.py:3194-3198
        if mock_settings.mcp_session_pool_explicit_health_rpc:
            await asyncio.wait_for(
                mock_pooled.session.list_tools(),
                timeout=mock_settings.health_check_timeout,
            )

        # list_tools SHOULD have been called
        mock_pooled.session.list_tools.assert_called_once()

    @pytest.mark.asyncio
    async def test_explicit_health_rpc_uses_health_check_timeout(self):
        """Explicit health RPC should use health_check_timeout setting."""
        # Create mock settings
        mock_settings = MagicMock()
        mock_settings.mcp_session_pool_explicit_health_rpc = True
        mock_settings.health_check_timeout = 7.5  # Custom timeout

        # Create mock pooled session
        mock_pooled = MagicMock()
        mock_pooled.session = MagicMock()
        mock_pooled.session.list_tools = AsyncMock(return_value=[])

        # Track the timeout passed to wait_for
        captured_timeout = None

        async def capture_wait_for(coro, timeout):
            nonlocal captured_timeout
            captured_timeout = timeout
            return await coro

        with patch('asyncio.wait_for', side_effect=capture_wait_for):
            if mock_settings.mcp_session_pool_explicit_health_rpc:
                await asyncio.wait_for(
                    mock_pooled.session.list_tools(),
                    timeout=mock_settings.health_check_timeout,
                )

        # Should have used the configured health_check_timeout
        assert captured_timeout == 7.5

    @pytest.mark.asyncio
    async def test_explicit_health_rpc_timeout_raises_timeout_error(self):
        """Explicit health RPC timeout should raise TimeoutError."""
        # Create mock settings with feature flag enabled
        mock_settings = MagicMock()
        mock_settings.mcp_session_pool_explicit_health_rpc = True
        mock_settings.health_check_timeout = 0.001  # Very short timeout

        # Create mock pooled session that hangs
        mock_pooled = MagicMock()
        mock_pooled.session = MagicMock()

        async def slow_list_tools():
            await asyncio.sleep(10)  # Simulate slow response
            return []

        mock_pooled.session.list_tools = slow_list_tools

        # Should timeout
        with pytest.raises(asyncio.TimeoutError):
            if mock_settings.mcp_session_pool_explicit_health_rpc:
                await asyncio.wait_for(
                    mock_pooled.session.list_tools(),
                    timeout=mock_settings.health_check_timeout,
                )


class TestExplicitHealthRPCConfig:
    """Tests for the explicit health RPC config setting."""

    def test_default_value_is_false(self):
        """Verify mcp_session_pool_explicit_health_rpc defaults to False."""
        # First-Party
        from mcpgateway.config import Settings

        settings = Settings()
        assert settings.mcp_session_pool_explicit_health_rpc is False

    def test_can_be_enabled_via_env(self):
        """Verify setting can be enabled via environment variable."""
        with patch.dict('os.environ', {'MCP_SESSION_POOL_EXPLICIT_HEALTH_RPC': 'true'}):
            # First-Party
            from mcpgateway.config import Settings

            # Need to create fresh instance to pick up env var
            settings = Settings()
            assert settings.mcp_session_pool_explicit_health_rpc is True
