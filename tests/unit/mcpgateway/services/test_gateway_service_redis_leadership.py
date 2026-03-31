# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_gateway_service_redis_leadership.py
Copyright 2025

Unit tests for Redis leadership election and heartbeat in GatewayService.
"""

# Standard
import asyncio
from unittest.mock import AsyncMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.services.gateway_service import GatewayService


class TestGatewayServiceRedisLeadership:
    """Test Redis leadership election and heartbeat functionality."""

    @pytest.mark.asyncio
    async def test_initialize_starts_follower_election_when_not_leader(self):
        """Test that initialize starts follower election when leadership is not acquired."""
        service = GatewayService()

        # Set up Redis-related attributes that would normally be set in __init__
        service._leader_key = "test:leader"  # pylint: disable=protected-access
        service._instance_id = "test-instance"  # pylint: disable=protected-access
        service._leader_ttl = 10  # pylint: disable=protected-access
        service._leader_heartbeat_interval = 5  # pylint: disable=protected-access

        # Mock Redis client
        service._redis_client = AsyncMock()  # pylint: disable=protected-access
        service._redis_client.ping = AsyncMock()  # pylint: disable=protected-access
        service._redis_client.set = AsyncMock(return_value=False)  # pylint: disable=protected-access

        with patch("mcpgateway.services.gateway_service.settings") as mock_settings:
            mock_settings.redis_url = "redis://localhost:6379"
            mock_settings.platform_admin_email = "admin@example.com"

            # Mock get_redis_client to return our mock
            with patch("mcpgateway.services.gateway_service.get_redis_client", return_value=service._redis_client):  # pylint: disable=protected-access
                await service.initialize()

                # Verify follower election task was created
                assert hasattr(service, "_follower_election_task")
                assert service._follower_election_task is not None  # pylint: disable=protected-access

                # Clean up - cancel and suppress CancelledError
                if hasattr(service, "_follower_election_task") and service._follower_election_task:  # pylint: disable=protected-access
                    service._follower_election_task.cancel()  # pylint: disable=protected-access
                    try:
                        await service._follower_election_task  # pylint: disable=protected-access
                    except asyncio.CancelledError:
                        pass  # Expected when cancelling
                    except Exception:
                        pass  # Suppress other exceptions during cleanup

    @pytest.mark.asyncio
    async def test_shutdown_cancels_follower_election_task(self):
        """Test that shutdown cancels follower election task."""
        service = GatewayService()
        service._redis_client = AsyncMock()  # pylint: disable=protected-access
        service._event_service = AsyncMock()  # pylint: disable=protected-access
        service._http_client = AsyncMock()  # pylint: disable=protected-access

        # Set up Redis-related attributes
        service._leader_key = "test:leader"  # pylint: disable=protected-access
        service._instance_id = "test-instance"  # pylint: disable=protected-access

        # Create a real asyncio task that we can cancel
        async def dummy_task():
            await asyncio.sleep(100)  # Long sleep to ensure it's running

        service._follower_election_task = asyncio.create_task(dummy_task())  # pylint: disable=protected-access

        await service.shutdown()

        # Verify follower election task was cancelled
        assert service._follower_election_task.cancelled()  # pylint: disable=protected-access
