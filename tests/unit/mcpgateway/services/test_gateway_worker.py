"""Unit tests for gateway worker service.

Tests async lifecycle management including:
- Exponential backoff calculation
- Worker stops on deleting status
- Retry metadata visibility
"""

import pytest
from datetime import datetime, timedelta, timezone
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
        """Worker exits retry loop when status=deleting and performs cleanup."""
        worker = GatewayWorker()

        # Create mock gateway with status=deleting
        gateway = MagicMock(spec=DbGateway)
        gateway.id = "test-id"
        gateway.name = "test-gateway"
        gateway.status = "deleting"
        gateway.url = "http://example.com"

        # Mock database session
        db = MagicMock()
        db.delete = MagicMock()
        db.commit = MagicMock()

        # Call retry_gateway_init - should cleanup, not retry
        await worker.retry_gateway_init(gateway, db)

        # Verify core cleanup was called
        db.delete.assert_called_once_with(gateway)
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_worker_loop_exception_handling(self):
        """Worker handles exceptions in main loop without crashing."""
        worker = GatewayWorker()

        # Create properly configured mock gateway
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
        gateway.registration_attempts = 0  # Concrete int value
        gateway.created_at = None

        mock_db = MagicMock()
        mock_db.commit = MagicMock()

        # Mock gateway service to raise exception
        with patch("mcpgateway.services.gateway_service.GatewayService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service._initialize_gateway = AsyncMock(side_effect=Exception("Connection failed"))

            # Should not raise - worker handles exceptions
            await worker.retry_gateway_init(gateway, mock_db)

            # Verify error was handled and retry metadata set
            assert gateway.registration_attempts == 1
            assert gateway.next_retry_at is not None
            assert gateway.last_error is not None

    @pytest.mark.asyncio
    async def test_cleanup_gateway_cache_invalidation(self):
        """Cleanup invalidates all relevant caches."""
        worker = GatewayWorker()

        gateway = MagicMock(spec=DbGateway)
        gateway.id = "test-id"
        gateway.name = "test-gateway"
        gateway.status = "deleting"

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = gateway

        with (
            patch("mcpgateway.services.gateway_worker._evict_upstream_sessions_for_gateway", new_callable=AsyncMock) as mock_evict,
            patch("mcpgateway.services.gateway_worker._get_registry_cache") as mock_reg_cache,
            patch("mcpgateway.services.gateway_worker._get_tool_lookup_cache") as mock_tool_cache,
            patch("mcpgateway.services.gateway_worker.admin_stats_cache") as mock_stats_cache,
            patch("mcpgateway.services.gateway_worker.invalidate_passthrough_header_caches") as mock_passthrough,
        ):
            mock_reg_cache.return_value.invalidate_gateways = AsyncMock()
            mock_tool_cache.return_value.invalidate_gateway = AsyncMock()
            mock_stats_cache.invalidate_tags = AsyncMock()

            await worker.cleanup_gateway(gateway, mock_db)

            # Verify all cache invalidations called
            mock_evict.assert_called_once()
            mock_reg_cache.return_value.invalidate_gateways.assert_called_once()
            mock_tool_cache.return_value.invalidate_gateway.assert_called_once()
            mock_stats_cache.invalidate_tags.assert_called_once()
            mock_passthrough.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_gateway_exception_handling(self):
        """Cleanup handles cache invalidation failures gracefully."""
        worker = GatewayWorker()

        gateway = MagicMock(spec=DbGateway)
        gateway.id = "test-id"
        gateway.name = "test-gateway"
        gateway.status = "deleting"
        gateway.url = "http://localhost:9000"

        # Mock database session
        db = MagicMock()
        db.delete = MagicMock()
        db.commit = MagicMock()

        # Mock cache functions to simulate failure
        with (
            patch("mcpgateway.services.gateway_worker._get_registry_cache") as mock_cache,
            patch("mcpgateway.services.gateway_worker._get_tool_lookup_cache") as mock_tool_cache,
        ):
            mock_cache.side_effect = Exception("Cache unavailable")
            mock_tool_cache.side_effect = Exception("Cache unavailable")

            # Should not raise - logs warning and continues
            await worker.cleanup_gateway(gateway, db)

            # Gateway should still be deleted despite cache errors
            db.delete.assert_called_once_with(gateway)
            db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_gateway_db_exception_handling(self):
        """Cleanup handles database failures and calls set_span_error (line 260)."""
        worker = GatewayWorker()

        gateway = MagicMock(spec=DbGateway)
        gateway.id = "test-id"
        gateway.name = "test-gateway"
        gateway.status = "deleting"
        gateway.url = "http://localhost:9000"

        # Mock database session to fail on commit
        db = MagicMock()
        db.delete = MagicMock()
        db.commit = MagicMock(side_effect=Exception("Database error"))
        db.rollback = MagicMock()

        # Mock set_span_error to verify it's called
        with patch("mcpgateway.services.gateway_worker.set_span_error") as mock_span_error:
            # Should not raise - logs error and calls set_span_error
            await worker.cleanup_gateway(gateway, db)

            # Verify error handling
            db.rollback.assert_called_once()
            mock_span_error.assert_called_once()

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
            next_retry_at=datetime.now(timezone.utc) + timedelta(seconds=32),
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
        gateway.created_at = None

        # Mock database session
        db = MagicMock()
        db.commit = MagicMock()

        # Patch at the point where GatewayService is instantiated in gateway_worker
        with patch("mcpgateway.services.gateway_worker.GatewayService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service._initialize_gateway = AsyncMock(return_value=(
                {"tools": {}},  # capabilities
                [],  # tools
                [],  # resources
                [],  # prompts
                [],  # validation_errors
            ))
            mock_service._update_or_create_tools = MagicMock()
            mock_service._update_or_create_resources = MagicMock()
            mock_service._update_or_create_prompts = MagicMock()

            worker = GatewayWorker()
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

        # Patch at the point where GatewayService is instantiated in gateway_worker
        with patch("mcpgateway.services.gateway_worker.GatewayService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service._initialize_gateway = AsyncMock(side_effect=Exception("Connection refused"))

            worker = GatewayWorker()
            await worker.retry_gateway_init(gateway, db)

            # Verify retry metadata updated
            assert gateway.registration_attempts == 3
            assert gateway.next_retry_at is not None
            assert "Connection refused" in gateway.last_error or "Failed to initialize" in gateway.last_error
            assert gateway.status_message is not None
            db.commit.assert_called()
