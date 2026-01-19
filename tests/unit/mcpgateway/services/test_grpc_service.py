# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_grpc_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: MCP Gateway Contributors

Tests for gRPC Service functionality.
"""

# Standard
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

# Third-Party
import pytest
from sqlalchemy.orm import Session

# Check if gRPC is available
try:
    import grpc  # noqa: F401

    GRPC_AVAILABLE = True
except ImportError:
    GRPC_AVAILABLE = False

# Skip all tests in this module if gRPC is not available
pytestmark = pytest.mark.skipif(not GRPC_AVAILABLE, reason="gRPC packages not installed")

# First-Party
from mcpgateway.db import GrpcService as DbGrpcService
from mcpgateway.schemas import GrpcServiceCreate, GrpcServiceUpdate
from mcpgateway.services.grpc_service import (
    GrpcService,
    GrpcServiceError,
    GrpcServiceNameConflictError,
    GrpcServiceNotFoundError,
)


class TestGrpcService:
    """Test suite for gRPC Service."""

    @pytest.fixture
    def service(self):
        """Create gRPC service instance."""
        return GrpcService()

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        return MagicMock(spec=Session)

    @pytest.fixture
    def sample_service_create(self):
        """Sample gRPC service creation data."""
        return GrpcServiceCreate(
            name="test-grpc-service",
            target="localhost:50051",
            description="Test gRPC service",
            reflection_enabled=True,
            tls_enabled=False,
            grpc_metadata={"auth": "Bearer test-token"},
            tags=["test", "grpc"],
        )

    @pytest.fixture
    def sample_db_service(self):
        """Sample database gRPC service."""
        service_id = uuid.uuid4().hex
        return DbGrpcService(
            id=service_id,
            name="test-grpc-service",
            slug="test-grpc-service",
            target="localhost:50051",
            description="Test gRPC service",
            reflection_enabled=True,
            tls_enabled=False,
            tls_cert_path=None,
            tls_key_path=None,
            grpc_metadata={"auth": "Bearer test-token"},
            enabled=True,
            reachable=False,
            service_count=0,
            method_count=0,
            discovered_services={},
            last_reflection=None,
            tags=["test", "grpc"],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            version=1,
            visibility="public",
        )

    async def test_register_service_success(self, service, mock_db, sample_service_create):
        """Test successful service registration."""
        # Mock database queries
        mock_db.execute.return_value.scalar_one_or_none.return_value = None  # No existing service
        mock_db.commit = MagicMock()

        # Mock refresh to set default values on the service
        def mock_refresh(obj):
            if not obj.id:
                obj.id = uuid.uuid4().hex
            if not obj.slug:
                obj.slug = obj.name
            if obj.enabled is None:
                obj.enabled = True
            if obj.reachable is None:
                obj.reachable = False
            if obj.service_count is None:
                obj.service_count = 0
            if obj.method_count is None:
                obj.method_count = 0
            if obj.discovered_services is None:
                obj.discovered_services = {}
            if obj.visibility is None:
                obj.visibility = "public"

        mock_db.refresh = MagicMock(side_effect=mock_refresh)

        # Mock reflection to avoid actual gRPC connection
        with patch.object(service, "_perform_reflection", new_callable=AsyncMock):
            result = await service.register_service(
                mock_db,
                sample_service_create,
                user_email="test@example.com",
                metadata={"ip": "127.0.0.1"},
            )

        assert result.name == "test-grpc-service"
        assert result.target == "localhost:50051"
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called()

    async def test_register_service_name_conflict(self, service, mock_db, sample_service_create, sample_db_service):
        """Test registration with conflicting name."""
        # Mock existing service
        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_db_service

        with pytest.raises(GrpcServiceNameConflictError) as exc_info:
            await service.register_service(mock_db, sample_service_create)

        assert "test-grpc-service" in str(exc_info.value)

    async def test_list_services(self, service, mock_db, sample_db_service):
        """Test listing gRPC services."""
        mock_db.execute.return_value.scalars.return_value.all.return_value = [sample_db_service]

        result = await service.list_services(mock_db, include_inactive=False)

        assert len(result) == 1
        assert result[0].name == "test-grpc-service"

    async def test_list_services_with_team_filter(self, service, mock_db, sample_db_service):
        """Test listing services with team filter."""
        with patch("mcpgateway.services.grpc_service.TeamManagementService") as mock_team_service_class:
            mock_team_instance = mock_team_service_class.return_value
            mock_team_instance.build_team_filter_clause = AsyncMock(return_value=None)
            mock_db.execute.return_value.scalars.return_value.all.return_value = [sample_db_service]

            result = await service.list_services(
                mock_db,
                include_inactive=False,
                user_email="test@example.com",
                team_id="team-123",
            )

            assert len(result) == 1
            mock_team_instance.build_team_filter_clause.assert_called_once()

    async def test_get_service_success(self, service, mock_db, sample_db_service):
        """Test getting a specific service."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_db_service

        result = await service.get_service(mock_db, sample_db_service.id)

        assert result.name == "test-grpc-service"
        assert result.id == sample_db_service.id

    async def test_get_service_not_found(self, service, mock_db):
        """Test getting non-existent service."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        with pytest.raises(GrpcServiceNotFoundError):
            await service.get_service(mock_db, "non-existent-id")

    async def test_update_service_success(self, service, mock_db, sample_db_service):
        """Test successful service update."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_db_service
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()

        update_data = GrpcServiceUpdate(
            description="Updated description",
            enabled=True,
        )

        result = await service.update_service(
            mock_db,
            sample_db_service.id,
            update_data,
            user_email="test@example.com",
        )

        assert result.description == "Updated description"
        mock_db.commit.assert_called()

    async def test_update_service_name_conflict(self, service, mock_db, sample_db_service):
        """Test update with conflicting name."""
        # First call returns the service being updated
        # Second call returns an existing service with the new name
        existing_other = DbGrpcService(
            id=uuid.uuid4().hex,
            name="other-service",
            slug="other-service",
            target="localhost:50052",
            description="Other service",
            reflection_enabled=True,
            tls_enabled=False,
            grpc_metadata={},
            enabled=True,
            reachable=False,
            service_count=0,
            method_count=0,
            discovered_services={},
            tags=[],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            version=1,
            visibility="public",
        )

        mock_db.execute.return_value.scalar_one_or_none.side_effect = [
            sample_db_service,  # First call: get the service
            existing_other,  # Second call: check for name conflict
        ]

        update_data = GrpcServiceUpdate(name="other-service")

        with pytest.raises(GrpcServiceNameConflictError):
            await service.update_service(mock_db, sample_db_service.id, update_data)

    async def test_set_service_state(self, service, mock_db, sample_db_service):
        """Test setting service enabled state."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_db_service
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()

        result = await service.set_service_state(mock_db, sample_db_service.id, activate=False)

        assert result.enabled is False
        mock_db.commit.assert_called()

    async def test_delete_service_success(self, service, mock_db, sample_db_service):
        """Test successful service deletion."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_db_service
        mock_db.commit = MagicMock()

        await service.delete_service(mock_db, sample_db_service.id)

        mock_db.delete.assert_called_once_with(sample_db_service)
        mock_db.commit.assert_called()

    async def test_delete_service_not_found(self, service, mock_db):
        """Test deleting non-existent service."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        with pytest.raises(GrpcServiceNotFoundError):
            await service.delete_service(mock_db, "non-existent-id")

    @patch("mcpgateway.services.grpc_service.grpc")
    @patch("mcpgateway.services.grpc_service.reflection_pb2_grpc")
    async def test_reflect_service_success(
        self, mock_reflection_grpc, mock_grpc, service, mock_db, sample_db_service
    ):
        """Test successful service reflection."""
        # Mock gRPC channel and stub
        mock_channel = MagicMock()
        mock_grpc.insecure_channel.return_value = mock_channel

        # Mock reflection response
        mock_stub = MagicMock()
        mock_reflection_grpc.ServerReflectionStub.return_value = mock_stub

        # Mock service list response
        mock_service = MagicMock()
        mock_service.name = "test.TestService"

        mock_list_response = MagicMock()
        mock_list_response.service = [mock_service]

        mock_response_item = MagicMock()
        mock_response_item.HasField.return_value = True
        mock_response_item.list_services_response = mock_list_response

        mock_stub.ServerReflectionInfo.return_value = [mock_response_item]

        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_db_service
        mock_db.commit = MagicMock()

        result = await service.reflect_service(mock_db, sample_db_service.id)

        assert result.service_count >= 0
        assert result.reachable is True
        mock_db.commit.assert_called()

    async def test_reflect_service_not_found(self, service, mock_db):
        """Test reflecting non-existent service."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        with pytest.raises(GrpcServiceNotFoundError):
            await service.reflect_service(mock_db, "non-existent-id")

    @patch("mcpgateway.services.grpc_service.grpc")
    async def test_reflect_service_connection_error(self, mock_grpc, service, mock_db, sample_db_service):
        """Test reflection with connection error."""
        mock_grpc.insecure_channel.side_effect = Exception("Connection failed")

        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_db_service
        mock_db.commit = MagicMock()

        with pytest.raises(GrpcServiceError):
            await service.reflect_service(mock_db, sample_db_service.id)

    async def test_get_service_methods(self, service, mock_db, sample_db_service):
        """Test getting service methods."""
        # Add discovered services to the sample
        sample_db_service.discovered_services = {
            "test.TestService": {
                "name": "test.TestService",
                "methods": [
                    {
                        "name": "TestMethod",
                        "input_type": "test.TestRequest",
                        "output_type": "test.TestResponse",
                        "client_streaming": False,
                        "server_streaming": False,
                    }
                ],
            }
        }

        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_db_service

        result = await service.get_service_methods(mock_db, sample_db_service.id)

        assert len(result) == 1
        assert result[0]["service"] == "test.TestService"
        assert result[0]["method"] == "TestMethod"
        assert result[0]["full_name"] == "test.TestService.TestMethod"

    async def test_get_service_methods_empty(self, service, mock_db, sample_db_service):
        """Test getting methods from service with no discovery."""
        sample_db_service.discovered_services = {}

        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_db_service

        result = await service.get_service_methods(mock_db, sample_db_service.id)

        assert len(result) == 0

    async def test_register_service_with_tls(self, service, mock_db):
        """Test registering service with TLS configuration."""
        service_data = GrpcServiceCreate(
            name="tls-service",
            target="secure.example.com:443",
            description="Secure gRPC service",
            reflection_enabled=True,
            tls_enabled=True,
            tls_cert_path="/path/to/cert.pem",
            tls_key_path="/path/to/key.pem",
        )

        mock_db.execute.return_value.scalar_one_or_none.return_value = None
        mock_db.commit = MagicMock()

        # Mock refresh to set default values on the service
        def mock_refresh(obj):
            if not obj.id:
                obj.id = uuid.uuid4().hex
            if not obj.slug:
                obj.slug = obj.name
            if obj.enabled is None:
                obj.enabled = True
            if obj.reachable is None:
                obj.reachable = False
            if obj.service_count is None:
                obj.service_count = 0
            if obj.method_count is None:
                obj.method_count = 0
            if obj.discovered_services is None:
                obj.discovered_services = {}
            if obj.visibility is None:
                obj.visibility = "public"

        mock_db.refresh = MagicMock(side_effect=mock_refresh)

        with patch.object(service, "_perform_reflection", new_callable=AsyncMock):
            result = await service.register_service(mock_db, service_data)

        assert result.tls_enabled is True
        assert result.tls_cert_path == "/path/to/cert.pem"
