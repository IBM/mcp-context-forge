"""Unit tests for gateway worker service.

Tests async lifecycle management including:
- Exponential backoff calculation
- Worker stops on deleting status
- Retry metadata visibility
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from mcpgateway.services.gateway_worker import GatewayWorker
from mcpgateway.db import Gateway as DbGateway


class TestGatewayWorker:
    """Test suite for GatewayWorker."""

    def test_exponential_backoff_schedule(self):
        """Verify backoff: 2s, 4s, 8s, 16s, ..., max 300s."""
        worker = GatewayWorker()

        expected_backoffs = [
            (1, 2),
            (2, 4),
            (3, 8),
            (4, 16),
            (5, 32),
            (6, 64),
            (7, 128),
            (8, 256),
            (9, 300),  # capped
            (10, 300),  # capped
        ]

        for attempt, expected in expected_backoffs:
            actual = worker.calculate_backoff(attempt)
            assert actual == expected, f"Attempt {attempt}: expected {expected}s, got {actual}s"

    @pytest.mark.asyncio
    async def test_worker_stops_on_deleting_status(self):
        """Worker exits retry loop when status=deleting."""
        worker = GatewayWorker()

        # Create mock gateway with status=deleting
        gateway = MagicMock(spec=DbGateway)
        gateway.id = "test-id"
        gateway.name = "test-gateway"
        gateway.status = "deleting"

        # Mock database session
        db = MagicMock()
        db.delete = MagicMock()
        db.commit = MagicMock()

        # Call retry_gateway_init - should cleanup, not retry
        await worker.retry_gateway_init(gateway, db)

        # Verify cleanup was called
        db.delete.assert_called_once_with(gateway)
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_retry_metadata_visibility(self):
        """Client can poll retry progress via gateway fields."""
        # This test verifies the schema includes retry metadata
        # Actual polling is tested in integration tests

        gateway = DbGateway(
            id="test-id",
            name="test-gateway",
            slug="test-gateway",
            url="http://localhost:9000",
            transport="SSE",
            capabilities={},
            status="pending",
            registration_attempts=5,
            next_retry_at=datetime.utcnow() + timedelta(seconds=32),
            last_error="Connection refused",
        )

        # Verify fields are accessible
        assert gateway.status == "pending"
        assert gateway.registration_attempts == 5
        assert gateway.next_retry_at is not None
        assert gateway.last_error == "Connection refused"

    @pytest.mark.asyncio
    async def test_successful_initialization(self):
        """Worker marks gateway as active after successful init."""
        worker = GatewayWorker()

        # Create mock gateway
        gateway = MagicMock(spec=DbGateway)
        gateway.id = "test-id"
        gateway.name = "test-gateway"
        gateway.status = "pending"
        gateway.url = "http://localhost:9000"
        gateway.transport = "SSE"
        gateway.auth_type = None
        gateway.oauth_config = None
        gateway.ca_certificate = None
        gateway.client_cert = None
        gateway.client_key = None
        gateway.registration_attempts = 2

        # Mock database session
        db = MagicMock()
        db.commit = MagicMock()

        # Mock gateway service (imported inside retry_gateway_init)
        with patch("mcpgateway.services.gateway_service.GatewayService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service._initialize_gateway = AsyncMock(return_value=(
                {"tools": {}},  # capabilities
                [],  # tools
                [],  # resources
                [],  # prompts
            ))
            mock_service._update_or_create_tools = MagicMock()
            mock_service._update_or_create_resources = MagicMock()
            mock_service._update_or_create_prompts = MagicMock()

            await worker.retry_gateway_init(gateway, db)

            # Verify gateway marked as active
            assert gateway.status == "active"
            assert gateway.registration_attempts == 3
            assert gateway.next_retry_at is None
            assert gateway.last_error is None
            db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_failed_initialization_increments_attempts(self):
        """Worker increments attempts and sets backoff on failure."""
        worker = GatewayWorker()

        # Create mock gateway
        gateway = MagicMock(spec=DbGateway)
        gateway.id = "test-id"
        gateway.name = "test-gateway"
        gateway.status = "pending"
        gateway.url = "http://localhost:9000"
        gateway.transport = "SSE"
        gateway.auth_type = None
        gateway.oauth_config = None
        gateway.ca_certificate = None
        gateway.client_cert = None
        gateway.client_key = None
        gateway.registration_attempts = 2

        # Mock database session
        db = MagicMock()
        db.commit = MagicMock()

        # Mock gateway service to fail (imported inside retry_gateway_init)
        with patch("mcpgateway.services.gateway_service.GatewayService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service._initialize_gateway = AsyncMock(side_effect=Exception("Connection refused"))

            await worker.retry_gateway_init(gateway, db)

            # Verify retry metadata updated
            assert gateway.registration_attempts == 3
            assert gateway.next_retry_at is not None
            assert gateway.last_error == "Connection refused"
            assert gateway.status_message is not None
            db.commit.assert_called()
