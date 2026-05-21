# -*- coding: utf-8 -*-
"""Location: ./tests/unit/plugins/test_apiconnect_fam_client.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Shankar N

Unit tests for IBM API Connect Federated API Management Asset Catalog Client.
Tests the HTTP client for IBM API Connect Federated API Management API interactions.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from plugins.apiconnect_fam.fam.client import FAMAssetCatalogClient
from plugins.apiconnect_fam.circuit_breaker import CircuitBreakerError
from plugins.apiconnect_fam.models import ReregistrationReport


class TestFAMAssetCatalogClient:
    """Test FAM client initialization and configuration."""

    def test_client_initialization(self):
        """Test client initializes with correct configuration."""
        client = FAMAssetCatalogClient(
            base_url="https://fam.example.com",
            runtime_id="test-runtime-123",
            username="admin",
            password="secret",
            timeout=60,
            verify_ssl=False,
        )
        
        assert client.base_url == "https://fam.example.com"
        assert client.runtime_id == "test-runtime-123"
        assert client._circuit_breaker_enabled is True

    def test_client_strips_trailing_slash(self):
        """Test client strips trailing slash from base URL."""
        client = FAMAssetCatalogClient(
            base_url="https://fam.example.com/",
            runtime_id="test-runtime-123",
            username="admin",
            password="secret",
        )
        
        assert client.base_url == "https://fam.example.com"

    def test_circuit_breaker_can_be_disabled(self):
        """Test circuit breaker can be disabled."""
        client = FAMAssetCatalogClient(
            base_url="https://fam.example.com",
            runtime_id="test-runtime-123",
            username="admin",
            password="secret",
            circuit_breaker_enabled=False,
        )
        
        assert client._circuit_breaker_enabled is False
        assert client._circuit_breaker is None

    @pytest.mark.asyncio
    async def test_close_closes_http_client(self):
        """Test close method closes HTTP client."""
        client = FAMAssetCatalogClient(
            base_url="https://fam.example.com",
            runtime_id="test-runtime-123",
            username="admin",
            password="secret",
        )
        
        client._http_client = AsyncMock()
        client._http_client.aclose = AsyncMock()
        
        await client.close()
        
        client._http_client.aclose.assert_awaited_once()


class TestFAMClientRuntimeRegistration:
    """Test runtime registration operations."""

    @pytest.fixture
    def client(self):
        """Create a test client."""
        return FAMAssetCatalogClient(
            base_url="https://fam.example.com",
            runtime_id="test-runtime-123",
            username="admin",
            password="secret",
            circuit_breaker_enabled=False,  # Disable for simpler testing
        )

    @pytest.mark.asyncio
    async def test_register_runtime_success_201(self, client):
        """Test successful first-time runtime registration (201 Created)."""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": "runtime-456"}
        
        client._http_client.post = AsyncMock(return_value=mock_response)
        
        report = await client.register_runtime(
            name="Test Runtime",
            description="Test Description",
            runtime_type="MCP_CONTEXT_FORGE",
        )
        
        assert report is not None
        assert report.runtime_id == "runtime-456"
        assert report.status_code == 201
        assert report.last_registration_time is None  # First registration

    @pytest.mark.asyncio
    async def test_register_runtime_success_200(self, client):
        """Test successful re-registration (200 OK)."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "runtime": {"id": "test-runtime-123"},
            "lastRegistrationTime": 1234567890000,
            "lastHeartbeatTime": 1234567891000,
            "lastMetricsTime": 1234567892000,
            "lastAssetSyncTime": 1234567893000,
        }
        
        client._http_client.post = AsyncMock(return_value=mock_response)
        
        report = await client.register_runtime(
            name="Test Runtime",
            description="Test Description",
            runtime_type="MCP_CONTEXT_FORGE",
        )
        
        assert report is not None
        assert report.runtime_id == "test-runtime-123"
        assert report.status_code == 200
        assert report.last_registration_time == 1234567890000
        assert report.last_heartbeat_time == 1234567891000
        assert report.is_reregistration() is True

    @pytest.mark.asyncio
    async def test_register_runtime_handles_409_conflict(self, client):
        """Test registration handles 409 Conflict as re-registration."""
        mock_response = MagicMock()
        mock_response.status_code = 409
        mock_response.json.return_value = {
            "runtime": {"id": "test-runtime-123"},
            "lastRegistrationTime": 1234567890000,
        }
        
        client._http_client.post = AsyncMock(return_value=mock_response)
        
        report = await client.register_runtime(
            name="Test Runtime",
            description="Test Description",
            runtime_type="MCP_CONTEXT_FORGE",
        )
        
        assert report is not None
        assert report.status_code == 409
        assert report.is_reregistration() is True

    @pytest.mark.asyncio
    async def test_register_runtime_handles_http_error(self, client):
        """Test registration handles HTTP errors gracefully."""
        client._http_client.post = AsyncMock(side_effect=httpx.HTTPError("Connection failed"))
        
        report = await client.register_runtime(
            name="Test Runtime",
            description="Test Description",
            runtime_type="MCP_CONTEXT_FORGE",
        )
        
        assert report is None


class TestFAMClientHeartbeat:
    """Test heartbeat operations."""

    @pytest.fixture
    def client(self):
        """Create a test client."""
        return FAMAssetCatalogClient(
            base_url="https://fam.example.com",
            runtime_id="test-runtime-123",
            username="admin",
            password="secret",
            circuit_breaker_enabled=False,
        )

    @pytest.mark.asyncio
    async def test_send_heartbeat_success(self, client):
        """Test successful heartbeat."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        
        client._http_client.post = AsyncMock(return_value=mock_response)
        
        result = await client.send_heartbeat("test-runtime-123")
        
        assert result is True
        client._http_client.post.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_heartbeat_handles_error(self, client):
        """Test heartbeat handles errors gracefully."""
        client._http_client.post = AsyncMock(side_effect=httpx.HTTPError("Connection failed"))
        
        result = await client.send_heartbeat("test-runtime-123")
        
        assert result is False


class TestFAMClientServerOperations:
    """Test server CRUD operations."""

    @pytest.fixture
    def client(self):
        """Create a test client."""
        return FAMAssetCatalogClient(
            base_url="https://fam.example.com",
            runtime_id="test-runtime-123",
            username="admin",
            password="secret",
            circuit_breaker_enabled=False,
        )

    @pytest.fixture
    def mock_server(self):
        """Create a mock server object."""
        server = MagicMock()
        server.id = "server-123"
        server.name = "Test Server"
        return server

    @pytest.mark.asyncio
    async def test_create_server_success(self, client, mock_server):
        """Test successful server creation."""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.raise_for_status = MagicMock()
        
        client._http_client.post = AsyncMock(return_value=mock_response)
        
        result = await client.create_server(mock_server)
        
        assert result is True

    @pytest.mark.asyncio
    async def test_create_server_handles_409_conflict(self, client, mock_server):
        """Test server creation treats 409 Conflict as success."""
        mock_response = MagicMock()
        mock_response.status_code = 409
        
        client._http_client.post = AsyncMock(return_value=mock_response)
        
        result = await client.create_server(mock_server)
        
        assert result is True  # 409 is treated as success

    @pytest.mark.asyncio
    async def test_update_server_success(self, client, mock_server):
        """Test successful server update."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        
        client._http_client.put = AsyncMock(return_value=mock_response)
        
        result = await client.update_server(mock_server)
        
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_server_success(self, client):
        """Test successful server deletion."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        
        client._http_client.delete = AsyncMock(return_value=mock_response)
        
        result = await client.delete_server("server-123")
        
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_server_handles_404(self, client):
        """Test server deletion treats 404 as success."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        
        client._http_client.delete = AsyncMock(return_value=mock_response)
        
        result = await client.delete_server("server-123")
        
        assert result is True  # 404 is acceptable for delete


class TestFAMClientCircuitBreaker:
    """Test circuit breaker integration."""

    @pytest.fixture
    def client(self):
        """Create a test client with circuit breaker enabled."""
        return FAMAssetCatalogClient(
            base_url="https://fam.example.com",
            runtime_id="test-runtime-123",
            username="admin",
            password="secret",
            circuit_breaker_enabled=True,
            circuit_breaker_failure_threshold=2,
            circuit_breaker_recovery_timeout=10.0,
        )

    @pytest.mark.asyncio
    async def test_circuit_breaker_opens_on_failures(self, client):
        """Test circuit breaker opens after threshold failures."""
        client._http_client.post = AsyncMock(side_effect=httpx.HTTPError("Connection failed"))
        
        # First failure
        result1 = await client.send_heartbeat("test-runtime-123")
        assert result1 is False
        
        # Second failure - should open circuit
        result2 = await client.send_heartbeat("test-runtime-123")
        assert result2 is False
        
        # Third attempt - circuit should be open
        result3 = await client.send_heartbeat("test-runtime-123")
        assert result3 is False

    def test_get_circuit_breaker_stats(self, client):
        """Test circuit breaker statistics retrieval."""
        stats = client.get_circuit_breaker_stats()
        
        assert stats["enabled"] is True
        assert stats["state"] == "closed"
        assert stats["failure_count"] == 0
        assert stats["failure_threshold"] == 2

    def test_get_circuit_breaker_stats_when_disabled(self):
        """Test circuit breaker stats when disabled."""
        client = FAMAssetCatalogClient(
            base_url="https://fam.example.com",
            runtime_id="test-runtime-123",
            username="admin",
            password="secret",
            circuit_breaker_enabled=False,
        )
        
        stats = client.get_circuit_breaker_stats()
        
        assert stats["enabled"] is False
        assert stats["state"] == "N/A"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])