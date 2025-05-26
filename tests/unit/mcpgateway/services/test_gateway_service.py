# -*- coding: utf-8 -*-
"""

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for the Gateway Service implementation.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import Tool as DbTool
from mcpgateway.schemas import GatewayCreate, GatewayRead, GatewayUpdate
from mcpgateway.services.gateway_service import (
    GatewayConnectionError,
    GatewayError,
    GatewayNameConflictError,
    GatewayNotFoundError,
    GatewayService,
)


@pytest.fixture
def gateway_service():
    """Create a gateway service instance."""
    service = GatewayService()
    service._http_client = AsyncMock()
    return service


@pytest.fixture
def mock_gateway():
    """Create a mock gateway model."""
    gateway = MagicMock(spec=DbGateway)
    gateway.id = 1
    gateway.name = "test_gateway"
    gateway.url = "http://example.com/gateway"
    gateway.description = "A test gateway"
    gateway.capabilities = {
        "prompts": {"listChanged": True},
        "resources": {"listChanged": True},
        "tools": {"listChanged": True},
    }
    gateway.created_at = "2023-01-01T00:00:00"
    gateway.updated_at = "2023-01-01T00:00:00"
    gateway.is_active = True
    gateway.last_seen = "2023-01-01T00:00:00"

    # Set up associated tools
    tool1 = MagicMock(spec=DbTool)
    tool1.id = 101
    tool1.name = "federated_tool"

    gateway.tools = [tool1]
    gateway.federated_tools = []

    return gateway


class TestGatewayService:
    """Tests for the GatewayService class."""

    @pytest.mark.asyncio
    async def test_register_gateway(self, gateway_service, test_db):
        """Test successful gateway registration."""
        # Set up DB behavior
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = None
        test_db.execute = Mock(return_value=mock_scalar)
        test_db.add = Mock()
        test_db.commit = Mock()
        test_db.refresh = Mock()

        # Set up gateway service methods
        gateway_service._notify_gateway_added = AsyncMock()
        gateway_service._initialize_gateway = AsyncMock(
            return_value=(
                {
                    "prompts": {"listChanged": True},
                    "resources": {"listChanged": True},
                    "tools": {"listChanged": True},
                },
                [],
            )
        )

        # Create gateway request
        gateway_create = GatewayCreate(name="test_gateway", url="http://example.com/gateway", description="A test gateway")

        # Call method
        result = await gateway_service.register_gateway(test_db, gateway_create)

        # Verify DB operations
        test_db.add.assert_called_once()
        test_db.commit.assert_called_once()
        test_db.refresh.assert_called_once()

        # Verify gateway initialization
        gateway_service._initialize_gateway.assert_called_once_with("http://example.com/gateway")

        # Verify notification
        gateway_service._notify_gateway_added.assert_called_once()

        # Verify result
        assert result.name == "test_gateway"
        assert result.url == "http://example.com/gateway"
        assert result.description == "A test gateway"
        assert result.is_active is True

    @pytest.mark.asyncio
    async def test_register_gateway_name_conflict(self, gateway_service, mock_gateway, test_db):
        """Test gateway registration with name conflict."""
        # Mock DB to return existing gateway
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = mock_gateway
        test_db.execute = Mock(return_value=mock_scalar)

        # Create gateway request with conflicting name
        gateway_create = GatewayCreate(name="test_gateway", url="http://example.com/new-gateway", description="A new gateway")  # Same name as mock_gateway

        # Should raise conflict error
        with pytest.raises(GatewayNameConflictError) as exc_info:
            await gateway_service.register_gateway(test_db, gateway_create)

        assert "Gateway already exists with name" in str(exc_info.value)
        assert exc_info.value.name == "test_gateway"
        assert exc_info.value.is_active == mock_gateway.is_active
        assert exc_info.value.gateway_id == mock_gateway.id

    @pytest.mark.asyncio
    async def test_register_gateway_connection_error(self, gateway_service, test_db):
        """Test gateway registration with connection error."""
        # Set up DB behavior
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = None
        test_db.execute = Mock(return_value=mock_scalar)
        test_db.rollback = Mock()

        # Set up gateway service methods to fail initialization
        gateway_service._initialize_gateway = AsyncMock(side_effect=GatewayConnectionError("Failed to connect"))

        # Create gateway request
        gateway_create = GatewayCreate(name="test_gateway", url="http://example.com/gateway", description="A test gateway")

        # Should raise error
        with pytest.raises(GatewayError) as exc_info:
            await gateway_service.register_gateway(test_db, gateway_create)

        assert "Failed to register gateway" in str(exc_info.value)

        # Verify rollback
        test_db.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_gateways(self, gateway_service, mock_gateway, test_db):
        """Test listing gateways."""
        # Mock DB to return a list of gateways
        mock_scalar_result = MagicMock()
        mock_scalar_result.all.return_value = [mock_gateway]
        mock_execute = Mock(return_value=mock_scalar_result)
        test_db.execute = mock_execute

        # Call method
        result = await gateway_service.list_gateways(test_db)

        # Verify DB query
        test_db.execute.assert_called_once()

        # Verify result
        assert len(result) == 1
        assert result[0].name == "test_gateway"
        assert result[0].url == "http://example.com/gateway"
        assert result[0].is_active is True

    @pytest.mark.asyncio
    async def test_get_gateway(self, gateway_service, mock_gateway, test_db):
        """Test getting a gateway by ID."""
        # Mock DB get to return gateway
        test_db.get = Mock(return_value=mock_gateway)

        # Call method
        result = await gateway_service.get_gateway(test_db, 1)

        # Verify DB query
        test_db.get.assert_called_once_with(DbGateway, 1)

        # Verify result
        assert result.name == "test_gateway"
        assert result.url == "http://example.com/gateway"
        assert result.description == "A test gateway"
        assert result.is_active is True
        assert result.capabilities == mock_gateway.capabilities

    @pytest.mark.asyncio
    async def test_get_gateway_not_found(self, gateway_service, test_db):
        """Test getting a non-existent gateway."""
        # Mock DB get to return None
        test_db.get = Mock(return_value=None)

        # Should raise NotFoundError
        with pytest.raises(GatewayNotFoundError) as exc_info:
            await gateway_service.get_gateway(test_db, 999)

        assert "Gateway not found: 999" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_gateway_inactive(self, gateway_service, mock_gateway, test_db):
        """Test getting an inactive gateway."""
        # Set gateway to inactive
        mock_gateway.is_active = False

        # Mock DB get to return inactive gateway
        test_db.get = Mock(return_value=mock_gateway)

        # Should raise NotFoundError mentioning inactive status
        with pytest.raises(GatewayNotFoundError) as exc_info:
            await gateway_service.get_gateway(test_db, 1)

        assert "Gateway 'test_gateway' exists but is inactive" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_update_gateway(self, gateway_service, mock_gateway, test_db):
        """Test updating a gateway."""
        # Mock DB get to return gateway
        test_db.get = Mock(return_value=mock_gateway)

        # Mock DB to check for name conflicts
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = None
        test_db.execute = Mock(return_value=mock_scalar)

        test_db.commit = Mock()
        test_db.refresh = Mock()

        # Set up gateway service methods
        gateway_service._notify_gateway_updated = AsyncMock()
        gateway_service._initialize_gateway = AsyncMock(
            return_value=(
                {
                    "prompts": {"listChanged": True, "subscribe": True},
                    "resources": {"listChanged": True, "subscribe": True},
                    "tools": {"listChanged": True, "subscribe": True},
                },
                [],
            )
        )

        # Create update request
        gateway_update = GatewayUpdate(name="updated_gateway", url="http://example.com/updated-gateway", description="An updated gateway")

        # Call method
        result = await gateway_service.update_gateway(test_db, 1, gateway_update)

        # Verify DB operations
        test_db.commit.assert_called_once()
        test_db.refresh.assert_called_once()

        # Verify gateway properties were updated
        assert mock_gateway.name == "updated_gateway"
        assert mock_gateway.url == "http://example.com/updated-gateway"
        assert mock_gateway.description == "An updated gateway"

        # Verify gateway reinitialization
        gateway_service._initialize_gateway.assert_called_once()

        # Verify notification
        gateway_service._notify_gateway_updated.assert_called_once()

        # Verify result
        assert result.name == "updated_gateway"
        assert result.url == "http://example.com/updated-gateway"
        assert result.description == "An updated gateway"

    @pytest.mark.asyncio
    async def test_update_gateway_not_found(self, gateway_service, test_db):
        """Test updating a non-existent gateway."""
        # Mock DB get to return None
        test_db.get = Mock(return_value=None)

        # Create update request
        gateway_update = GatewayUpdate(name="updated_gateway", description="An updated gateway")

        # Should raise NotFoundError
        with pytest.raises(GatewayNotFoundError) as exc_info:
            await gateway_service.update_gateway(test_db, 999, gateway_update)

        assert "Gateway not found: 999" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_update_gateway_name_conflict(self, gateway_service, mock_gateway, test_db):
        """Test updating a gateway with a name that conflicts with another gateway."""
        # Create a second gateway (the one being updated)
        gateway1 = mock_gateway

        # Create a conflicting gateway
        gateway2 = MagicMock(spec=DbGateway)
        gateway2.id = 2
        gateway2.name = "existing_gateway"
        gateway2.is_active = True

        # Mock DB get to return gateway1
        test_db.get = Mock(return_value=gateway1)

        # Mock DB to check for name conflicts and return gateway2
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = gateway2
        test_db.execute = Mock(return_value=mock_scalar)

        test_db.rollback = Mock()

        # Create update request with conflicting name
        gateway_update = GatewayUpdate(
            name="existing_gateway",  # Name that conflicts with gateway2
        )

        # Should raise conflict error
        with pytest.raises(GatewayNameConflictError) as exc_info:
            await gateway_service.update_gateway(test_db, 1, gateway_update)

        assert "Gateway already exists with name" in str(exc_info.value)
        assert exc_info.value.name == "existing_gateway"
        assert exc_info.value.is_active == gateway2.is_active
        assert exc_info.value.gateway_id == gateway2.id

    @pytest.mark.asyncio
    async def test_toggle_gateway_status(self, gateway_service, mock_gateway, test_db):
        """Test toggling gateway active status."""
        # Mock DB get to return gateway
        test_db.get = Mock(return_value=mock_gateway)
        test_db.commit = Mock()
        test_db.refresh = Mock()

        # Set up service methods
        gateway_service._notify_gateway_activated = AsyncMock()
        gateway_service._notify_gateway_deactivated = AsyncMock()
        gateway_service._initialize_gateway = AsyncMock(
            return_value=(
                {
                    "prompts": {"listChanged": True},
                    "resources": {"listChanged": True},
                    "tools": {"listChanged": True},
                },
                [],
            )
        )

        # Mock tool service
        mock_tool_service = AsyncMock()
        gateway_service.tool_service = mock_tool_service

        # Deactivate the gateway (it's active by default)
        result = await gateway_service.toggle_gateway_status(test_db, 1, activate=False)

        # Verify DB operations
        test_db.get.assert_called_once_with(DbGateway, 1)
        test_db.commit.assert_called_once()
        test_db.refresh.assert_called_once()

        # Verify properties were updated
        assert mock_gateway.is_active is False

        # Verify notification
        gateway_service._notify_gateway_deactivated.assert_called_once()
        gateway_service._notify_gateway_activated.assert_not_called()

        # Verify tool service called to toggle associated tools
        assert mock_tool_service.toggle_tool_status.called

        # Verify result
        assert result.is_active is False

    @pytest.mark.asyncio
    async def test_delete_gateway(self, gateway_service, mock_gateway, test_db):
        """Test deleting a gateway."""
        # Mock DB get to return gateway
        test_db.get = Mock(return_value=mock_gateway)
        test_db.delete = Mock()
        test_db.commit = Mock()
        test_db.query = Mock()
        query_mock = Mock()
        filter_mock = Mock()
        test_db.query.return_value = query_mock
        query_mock.filter.return_value = filter_mock
        filter_mock.delete.return_value = None

        # Set up service methods
        gateway_service._notify_gateway_deleted = AsyncMock()

        # Call method
        await gateway_service.delete_gateway(test_db, 1)

        # Verify DB operations
        test_db.get.assert_called_once_with(DbGateway, 1)
        test_db.delete.assert_called_once_with(mock_gateway)
        test_db.commit.assert_called()

        # Verify notification
        gateway_service._notify_gateway_deleted.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_gateway_not_found(self, gateway_service, test_db):
        """Test deleting a non-existent gateway."""
        # Mock DB get to return None
        test_db.get = Mock(return_value=None)

        # Should raise NotFoundError
        with pytest.raises(GatewayNotFoundError) as exc_info:
            await gateway_service.delete_gateway(test_db, 999)

        assert "Gateway not found: 999" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_forward_request(self, gateway_service, mock_gateway):
        """Test forwarding a request to a gateway."""
        # Set up HTTP client response
        mock_response = AsyncMock()
        mock_response.raise_for_status = AsyncMock()
        mock_response.json.return_value = {"jsonrpc": "2.0", "result": {"success": True, "data": "Response data"}, "id": 1}
        gateway_service._http_client.post.return_value = mock_response

        # Call method
        result = await gateway_service.forward_request(mock_gateway, "test_method", {"param": "value"})

        # Verify HTTP request
        gateway_service._http_client.post.assert_called_once_with(
            f"{mock_gateway.url}/rpc",
            json={"jsonrpc": "2.0", "id": 1, "method": "test_method", "params": {"param": "value"}},
            headers=gateway_service._get_auth_headers(),
        )

        # Verify result
        assert result == {"success": True, "data": "Response data"}

        # Verify gateway last_seen updated
        assert mock_gateway.last_seen is not None

    @pytest.mark.asyncio
    async def test_forward_request_error_response(self, gateway_service, mock_gateway):
        """Test forwarding a request that returns an error."""
        # Set up HTTP client response
        mock_response = AsyncMock()
        mock_response.raise_for_status = AsyncMock()
        mock_response.json.return_value = {"jsonrpc": "2.0", "error": {"code": -32000, "message": "Test error"}, "id": 1}
        gateway_service._http_client.post.return_value = mock_response

        # Should raise GatewayError
        with pytest.raises(GatewayError) as exc_info:
            await gateway_service.forward_request(mock_gateway, "test_method", {"param": "value"})

        assert "Gateway error: Test error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_forward_request_connection_error(self, gateway_service, mock_gateway):
        """Test forwarding a request with connection error."""
        # Set up HTTP client to raise exception
        gateway_service._http_client.post.side_effect = Exception("Connection error")

        # Should raise GatewayError
        with pytest.raises(GatewayError) as exc_info:
            await gateway_service.forward_request(mock_gateway, "test_method", {"param": "value"})

        assert "Failed to forward request" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_check_gateway_health(self, gateway_service, mock_gateway):
        """Test checking gateway health."""
        # Set up _initialize_gateway to succeed
        gateway_service._initialize_gateway = AsyncMock()

        # Call method
        result = await gateway_service.check_gateway_health(mock_gateway)

        # Verify result
        assert result is True

        # Verify gateway last_seen updated
        assert mock_gateway.last_seen is not None

    @pytest.mark.asyncio
    async def test_check_gateway_health_failure(self, gateway_service, mock_gateway):
        """Test checking gateway health with failure."""
        # Set up _initialize_gateway to fail
        gateway_service._initialize_gateway = AsyncMock(side_effect=Exception("Health check failed"))

        # Call method
        result = await gateway_service.check_gateway_health(mock_gateway)

        # Verify result
        assert result is False
