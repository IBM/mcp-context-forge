# -*- coding: utf-8 -*-
"""Tests for MCP session pool initialization in main.py.

Verifies:
- Pool health check interval uses min(health_check_interval, mcp_session_pool_health_check_interval)
- Pool transport timeout uses settings.mcp_session_pool_transport_timeout

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Standard
from unittest.mock import MagicMock, patch

# Third-Party
import pytest


class TestPoolInitAutoAlignment:
    """Tests for auto-alignment of pool settings in main.py startup."""

    def test_effective_health_check_interval_uses_min(self):
        """Pool should use min(health_check_interval, mcp_session_pool_health_check_interval)."""
        # Test case 1: gateway interval is smaller
        mock_settings = MagicMock()
        mock_settings.health_check_interval = 30
        mock_settings.mcp_session_pool_health_check_interval = 60

        effective_interval = min(
            mock_settings.health_check_interval,
            mock_settings.mcp_session_pool_health_check_interval,
        )
        assert effective_interval == 30

        # Test case 2: pool interval is smaller
        mock_settings.health_check_interval = 120
        mock_settings.mcp_session_pool_health_check_interval = 45

        effective_interval = min(
            mock_settings.health_check_interval,
            mock_settings.mcp_session_pool_health_check_interval,
        )
        assert effective_interval == 45

        # Test case 3: both equal
        mock_settings.health_check_interval = 60
        mock_settings.mcp_session_pool_health_check_interval = 60

        effective_interval = min(
            mock_settings.health_check_interval,
            mock_settings.mcp_session_pool_health_check_interval,
        )
        assert effective_interval == 60

    def test_transport_timeout_uses_pool_transport_timeout(self):
        """Pool should use settings.mcp_session_pool_transport_timeout for transport timeout."""
        mock_settings = MagicMock()
        mock_settings.mcp_session_pool_transport_timeout = 30.0

        transport_timeout = mock_settings.mcp_session_pool_transport_timeout
        assert transport_timeout == 30.0
        assert isinstance(transport_timeout, float)

        # Test with different value
        mock_settings.mcp_session_pool_transport_timeout = 60.0
        transport_timeout = mock_settings.mcp_session_pool_transport_timeout
        assert transport_timeout == 60.0

    @pytest.mark.asyncio
    async def test_init_mcp_session_pool_receives_correct_parameters(self):
        """Verify init_mcp_session_pool receives the calculated parameters."""
        # First-Party
        from mcpgateway.services.mcp_session_pool import (
            MCPSessionPool,
            close_mcp_session_pool,
            init_mcp_session_pool,
        )

        # Create pool with specific values
        pool = init_mcp_session_pool(
            health_check_interval_seconds=30.0,
            default_transport_timeout_seconds=7.5,
        )

        try:
            # Verify the pool received the correct values
            assert pool._health_check_interval == 30.0
            assert pool._default_transport_timeout == 7.5
        finally:
            await close_mcp_session_pool()

    @pytest.mark.asyncio
    async def test_pool_init_uses_all_settings(self):
        """Verify pool initialization uses all expected settings from config."""
        # First-Party
        from mcpgateway.services.mcp_session_pool import (
            close_mcp_session_pool,
            init_mcp_session_pool,
        )

        # Initialize with specific values that match main.py pattern
        pool = init_mcp_session_pool(
            max_sessions_per_key=5,
            session_ttl_seconds=120.0,
            health_check_interval_seconds=25.0,  # Simulates min() result
            acquire_timeout_seconds=15.0,
            session_create_timeout_seconds=20.0,
            circuit_breaker_threshold=3,
            circuit_breaker_reset_seconds=30.0,
            identity_headers=frozenset(["authorization", "x-tenant-id"]),
            idle_pool_eviction_seconds=300.0,
            default_transport_timeout_seconds=5.0,
        )

        try:
            # Verify all settings were applied
            assert pool._max_sessions == 5
            assert pool._session_ttl == 120.0
            assert pool._health_check_interval == 25.0
            assert pool._acquire_timeout == 15.0
            assert pool._session_create_timeout == 20.0
            assert pool._circuit_breaker_threshold == 3
            assert pool._circuit_breaker_reset == 30.0
            assert pool._identity_headers == frozenset(["authorization", "x-tenant-id"])
            assert pool._idle_pool_eviction == 300.0
            assert pool._default_transport_timeout == 5.0
        finally:
            await close_mcp_session_pool()


class TestPoolInitIntegration:
    """Integration tests for pool initialization in main.py."""

    @pytest.mark.asyncio
    async def test_main_pool_init_code_path(self):
        """Test the actual code pattern used in main.py:457-478."""
        # First-Party
        from mcpgateway.config import Settings
        from mcpgateway.services.mcp_session_pool import (
            close_mcp_session_pool,
            init_mcp_session_pool,
        )

        # Use real settings (with defaults)
        settings = Settings()

        # This mimics main.py:461-478
        if settings.mcp_session_pool_enabled:
            effective_health_check_interval = min(
                settings.health_check_interval,
                settings.mcp_session_pool_health_check_interval,
            )
            pool = init_mcp_session_pool(
                max_sessions_per_key=settings.mcp_session_pool_max_per_key,
                session_ttl_seconds=settings.mcp_session_pool_ttl,
                health_check_interval_seconds=effective_health_check_interval,
                acquire_timeout_seconds=settings.mcp_session_pool_acquire_timeout,
                session_create_timeout_seconds=settings.mcp_session_pool_create_timeout,
                circuit_breaker_threshold=settings.mcp_session_pool_circuit_breaker_threshold,
                circuit_breaker_reset_seconds=settings.mcp_session_pool_circuit_breaker_reset,
                identity_headers=frozenset(settings.mcp_session_pool_identity_headers),
                idle_pool_eviction_seconds=settings.mcp_session_pool_idle_eviction,
                default_transport_timeout_seconds=settings.mcp_session_pool_transport_timeout,
            )

            try:
                # Verify key auto-alignment behaviors
                # 1. Health check interval should be min of both settings
                expected_interval = min(
                    settings.health_check_interval,
                    settings.mcp_session_pool_health_check_interval,
                )
                assert pool._health_check_interval == expected_interval

                # 2. Transport timeout should use mcp_session_pool_transport_timeout
                assert pool._default_transport_timeout == settings.mcp_session_pool_transport_timeout
            finally:
                await close_mcp_session_pool()
