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

# First-Party
from mcpgateway.db import GrpcService as DbGrpcService
from mcpgateway.schemas import GrpcServiceCreate, GrpcServiceUpdate
from mcpgateway.services.grpc_service import (
    GrpcService,
    GrpcServiceError,
    GrpcServiceNameConflictError,
    GrpcServiceNotFoundError,
)

# Check if gRPC is available
try:
    import grpc  # noqa: F401

    GRPC_AVAILABLE = True
except ImportError:
    GRPC_AVAILABLE = False

# Skip all tests in this module if gRPC is not available
pytestmark = pytest.mark.skipif(not GRPC_AVAILABLE, reason="gRPC packages not installed")


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
                metadata={
                    "created_by": "test@example.com",
                    "created_from_ip": "127.0.0.1",
                    "created_via": "ui",
                    "created_user_agent": "test/1.0",
                    "import_batch_id": None,
                    "federation_source": None,
                    "version": 1,
                },
            )

        assert result.name == "test-grpc-service"
        assert result.target == "localhost:50051"
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called()

        # Verify audit metadata was persisted on the DB object
        db_obj = mock_db.add.call_args[0][0]
        assert db_obj.created_by == "test@example.com"
        assert db_obj.created_from_ip == "127.0.0.1"
        assert db_obj.created_via == "ui"
        assert db_obj.created_user_agent == "test/1.0"

    async def test_register_service_name_conflict(self, service, mock_db, sample_service_create, sample_db_service):
        """Test registration with conflicting name."""
        # Mock existing service
        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_db_service

        with pytest.raises(GrpcServiceNameConflictError) as exc_info:
            await service.register_service(mock_db, sample_service_create)

        assert "test-grpc-service" in str(exc_info.value)

    async def test_list_services(self, service, mock_db, sample_db_service):
        """Test listing gRPC services."""
        sample_db_service.team_id = None
        mock_db.commit = MagicMock()

        with patch("mcpgateway.services.grpc_service.unified_paginate", new_callable=AsyncMock) as mock_paginate:
            mock_paginate.return_value = ([sample_db_service], None)
            result, next_cursor = await service.list_services(mock_db, include_inactive=False)

        assert len(result) == 1
        assert result[0].name == "test-grpc-service"
        assert next_cursor is None

    async def test_list_services_with_team_filter(self, service, mock_db, sample_db_service):
        """Test listing services with team filter."""
        sample_db_service.team_id = None
        mock_db.commit = MagicMock()

        with patch("mcpgateway.services.grpc_service.TeamManagementService") as mock_team_service_class:
            mock_team_instance = mock_team_service_class.return_value
            mock_team_instance.build_team_filter_clause = AsyncMock(return_value=None)

            with patch("mcpgateway.services.grpc_service.unified_paginate", new_callable=AsyncMock) as mock_paginate:
                mock_paginate.return_value = ([sample_db_service], None)
                result, next_cursor = await service.list_services(
                    mock_db,
                    include_inactive=False,
                    user_email="test@example.com",
                    team_id="team-123",
                )

            assert len(result) == 1
            assert next_cursor is None
            mock_team_instance.build_team_filter_clause.assert_called_once()

    async def test_list_services_with_team_names(self, service, mock_db, sample_db_service):
        """Test listing services with team name resolution."""
        # Set up service with team_id
        sample_db_service.team_id = "team-123"

        # Mock team query result
        mock_team = MagicMock()
        mock_team.id = "team-123"
        mock_team.name = "Test Team"

        # Mock db.execute to return team data
        mock_execute_result = MagicMock()
        mock_execute_result.all.return_value = [mock_team]
        mock_db.execute.return_value = mock_execute_result
        mock_db.commit = MagicMock()

        with patch("mcpgateway.services.grpc_service.unified_paginate", new_callable=AsyncMock) as mock_paginate:
            mock_paginate.return_value = ([sample_db_service], None)
            result, next_cursor = await service.list_services(mock_db, include_inactive=False)

        assert len(result) == 1
        assert result[0].name == "test-grpc-service"
        assert result[0].team_id == "team-123"
        assert next_cursor is None
        mock_db.commit.assert_called_once()

    async def test_list_services_with_team_id_filter_only(self, service, mock_db, sample_db_service):
        """Test listing services with team_id filter but no user_email."""
        sample_db_service.team_id = "team-456"
        mock_db.commit = MagicMock()

        with patch("mcpgateway.services.grpc_service.unified_paginate", new_callable=AsyncMock) as mock_paginate:
            mock_paginate.return_value = ([sample_db_service], None)
            result, next_cursor = await service.list_services(
                mock_db,
                include_inactive=False,
                team_id="team-456",
            )

        assert len(result) == 1
        assert next_cursor is None

    async def test_list_services_skips_invalid_record(self, service, mock_db):
        """Test that a corrupted DB record is gracefully skipped."""
        bad_svc = MagicMock()
        bad_svc.team_id = None
        mock_db.commit = MagicMock()

        with patch("mcpgateway.services.grpc_service.GrpcServiceRead.model_validate", side_effect=ValueError("bad data")):
            with patch("mcpgateway.services.grpc_service.unified_paginate", new_callable=AsyncMock) as mock_paginate:
                mock_paginate.return_value = ([bad_svc], None)
                result, next_cursor = await service.list_services(mock_db, include_inactive=False)

        assert len(result) == 0
        assert next_cursor is None

    async def test_list_services_pagination(self, service, mock_db):
        """Test multi-page pagination for gRPC services."""
        # Create multiple mock services
        services_page1 = []
        for i in range(10):
            svc = DbGrpcService(
                id=f"svc-{i}",
                name=f"service-{i}",
                slug=f"service-{i}",
                target=f"localhost:5005{i}",
                description=f"Test service {i}",
                reflection_enabled=True,
                tls_enabled=False,
                grpc_metadata={},
                enabled=True,
                reachable=False,
                service_count=0,
                method_count=0,
                discovered_services={},
                tags=["test"],
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                version=1,
                visibility="public",
                team_id=None,
            )
            services_page1.append(svc)

        mock_db.commit = MagicMock()

        # Test page 1
        with patch("mcpgateway.services.grpc_service.unified_paginate", new_callable=AsyncMock) as mock_paginate:
            from mcpgateway.schemas import PaginationMeta, PaginationLinks

            mock_paginate.return_value = {
                "data": services_page1,
                "pagination": PaginationMeta(
                    page=1,
                    per_page=10,
                    total_items=25,
                    total_pages=3,
                    has_next=True,
                    has_prev=False,
                ),
                "links": PaginationLinks(
                    self="/admin/grpc?page=1&per_page=10",
                    first="/admin/grpc?page=1&per_page=10",
                    last="/admin/grpc?page=3&per_page=10",
                    next="/admin/grpc?page=2&per_page=10",
                    prev=None,
                ),
            }

            result = await service.list_services(mock_db, page=1, per_page=10, include_inactive=False)

        assert isinstance(result, dict)
        assert len(result["data"]) == 10
        assert result["pagination"].page == 1
        assert result["pagination"].total_items == 25
        assert result["pagination"].total_pages == 3
        assert result["pagination"].has_next is True
        assert result["pagination"].has_prev is False
        assert result["links"].next == "/admin/grpc?page=2&per_page=10"

        # Test page 2
        services_page2 = []
        for i in range(10, 20):
            svc = DbGrpcService(
                id=f"svc-{i}",
                name=f"service-{i}",
                slug=f"service-{i}",
                target=f"localhost:5005{i}",
                description=f"Test service {i}",
                reflection_enabled=True,
                tls_enabled=False,
                grpc_metadata={},
                enabled=True,
                reachable=False,
                service_count=0,
                method_count=0,
                discovered_services={},
                tags=["test"],
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                version=1,
                visibility="public",
                team_id=None,
            )
            services_page2.append(svc)

        with patch("mcpgateway.services.grpc_service.unified_paginate", new_callable=AsyncMock) as mock_paginate:
            mock_paginate.return_value = {
                "data": services_page2,
                "pagination": PaginationMeta(
                    page=2,
                    per_page=10,
                    total_items=25,
                    total_pages=3,
                    has_next=True,
                    has_prev=True,
                ),
                "links": PaginationLinks(
                    self="/admin/grpc?page=2&per_page=10",
                    first="/admin/grpc?page=1&per_page=10",
                    last="/admin/grpc?page=3&per_page=10",
                    next="/admin/grpc?page=3&per_page=10",
                    prev="/admin/grpc?page=1&per_page=10",
                ),
            }

            result = await service.list_services(mock_db, page=2, per_page=10, include_inactive=False)

        assert isinstance(result, dict)
        assert len(result["data"]) == 10
        assert result["pagination"].page == 2
        assert result["pagination"].has_next is True
        assert result["pagination"].has_prev is True
        assert result["links"].next == "/admin/grpc?page=3&per_page=10"
        assert result["links"].prev == "/admin/grpc?page=1&per_page=10"

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
    async def test_reflect_service_success(self, mock_reflection_grpc, mock_grpc, service, mock_db, sample_db_service):
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

    def test_sync_tools_creates_tools_from_discovered_methods(self, service, mock_db, sample_db_service):
        """Test that _sync_tools_from_reflection creates Tool records for discovered methods."""
        sample_db_service.discovered_services = {
            "test.TestService": {
                "name": "test.TestService",
                "methods": [
                    {
                        "name": "GetItem",
                        "input_type": ".test.GetItemRequest",
                        "output_type": ".test.GetItemResponse",
                        "client_streaming": False,
                        "server_streaming": False,
                    },
                    {
                        "name": "ListItems",
                        "input_type": ".test.ListItemsRequest",
                        "output_type": ".test.ListItemsResponse",
                        "client_streaming": False,
                        "server_streaming": True,
                    },
                ],
            }
        }
        sample_db_service.team_id = None
        sample_db_service.owner_email = "test@example.com"

        # No existing tools
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute.return_value = mock_result

        service._sync_tools_from_reflection(mock_db, sample_db_service)

        # Should have added 2 tools
        assert mock_db.add.call_count == 2

        # Verify tool properties
        calls = mock_db.add.call_args_list
        tool_names = {call[0][0].original_name for call in calls}
        assert tool_names == {"test.TestService.GetItem", "test.TestService.ListItems"}

        # Verify tool fields on first created tool
        for call in calls:
            tool = call[0][0]
            assert tool.integration_type == "gRPC"
            assert tool.grpc_service_id == sample_db_service.id
            assert tool.created_via == "grpc-reflection"
            assert tool.federation_source == sample_db_service.name
            assert tool.url == sample_db_service.target
            assert tool.owner_email == "test@example.com"

    def test_sync_tools_updates_existing_tools(self, service, mock_db, sample_db_service):
        """Test that _sync_tools_from_reflection updates existing tools when description changes."""
        sample_db_service.discovered_services = {
            "test.TestService": {
                "name": "test.TestService",
                "methods": [
                    {
                        "name": "GetItem",
                        "input_type": ".test.GetItemRequest",
                        "output_type": ".test.GetItemResponse",
                        "client_streaming": False,
                        "server_streaming": False,
                    },
                ],
            }
        }
        sample_db_service.target = "new-host:50051"

        # Existing tool with old url
        from mcpgateway.db import Tool as DbTool

        existing_tool = MagicMock(spec=DbTool)
        existing_tool.id = "existing-tool-id"
        existing_tool.original_name = "test.TestService.GetItem"
        existing_tool.original_description = "gRPC method test.TestService.GetItem"
        existing_tool.description = "gRPC method test.TestService.GetItem"
        existing_tool.url = "old-host:50051"
        existing_tool.input_schema = {}

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [existing_tool]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute.return_value = mock_result

        service._sync_tools_from_reflection(mock_db, sample_db_service)

        # Should NOT have added new tools
        mock_db.add.assert_not_called()

        # Existing tool should have been updated
        assert existing_tool.url == "new-host:50051"

    def test_sync_tools_removes_stale_tools(self, service, mock_db, sample_db_service):
        """Test that _sync_tools_from_reflection removes tools for methods no longer discovered."""
        # Service now has no discovered methods
        sample_db_service.discovered_services = {}

        # But there's a stale tool from a previous reflection
        from mcpgateway.db import Tool as DbTool

        stale_tool = MagicMock(spec=DbTool)
        stale_tool.id = "stale-tool-id"
        stale_tool.original_name = "test.TestService.OldMethod"

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [stale_tool]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute.return_value = mock_result

        service._sync_tools_from_reflection(mock_db, sample_db_service)

        # Should have executed delete statements for the stale tool
        # 3 deletes: ToolMetric, server_tool_association, DbTool
        delete_calls = [call for call in mock_db.execute.call_args_list if "DELETE" in str(call) or "delete" in str(call).lower()]
        assert len(delete_calls) == 3
        # At minimum, execute was called for the select + 3 deletes
        assert mock_db.execute.call_count >= 4  # 1 select + 3 deletes

    def test_sync_tools_empty_discovered_services(self, service, mock_db, sample_db_service):
        """Test _sync_tools_from_reflection with empty discovered services and no existing tools."""
        sample_db_service.discovered_services = {}

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute.return_value = mock_result

        service._sync_tools_from_reflection(mock_db, sample_db_service)

        # No tools to add
        mock_db.add.assert_not_called()

    def test_sync_tools_preserves_custom_description(self, service, mock_db, sample_db_service):
        """Test that _sync_tools_from_reflection preserves user-customized descriptions."""
        sample_db_service.discovered_services = {
            "test.TestService": {
                "name": "test.TestService",
                "methods": [
                    {
                        "name": "GetItem",
                        "input_type": ".test.GetItemRequest",
                        "output_type": ".test.GetItemResponse",
                        "client_streaming": False,
                        "server_streaming": False,
                    },
                ],
            }
        }

        from mcpgateway.db import Tool as DbTool

        existing_tool = MagicMock(spec=DbTool)
        existing_tool.id = "tool-id"
        existing_tool.original_name = "test.TestService.GetItem"
        existing_tool.original_description = "old description"
        existing_tool.description = "My custom description"  # User customized
        existing_tool.url = sample_db_service.target
        existing_tool.input_schema = {
            "type": "object",
            "properties": {},
            "x-grpc-input-type": ".test.GetItemRequest",
            "x-grpc-output-type": ".test.GetItemResponse",
            "x-grpc-client-streaming": False,
            "x-grpc-server-streaming": False,
        }

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [existing_tool]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute.return_value = mock_result

        service._sync_tools_from_reflection(mock_db, sample_db_service)

        # original_description should be updated but custom description preserved
        assert existing_tool.original_description == "gRPC method test.TestService.GetItem"
        assert existing_tool.description == "My custom description"

    async def test_delete_service_removes_tools(self, service, mock_db):
        """Test that deleting a gRPC service also removes its associated tools."""
        # Use a MagicMock for the service to avoid SQLAlchemy relationship issues
        mock_service = MagicMock()
        mock_service.id = "svc-id"
        mock_service.name = "test-grpc-service"
        mock_tool1 = MagicMock()
        mock_tool1.id = "tool-1"
        mock_tool2 = MagicMock()
        mock_tool2.id = "tool-2"
        mock_service.tools = [mock_tool1, mock_tool2]

        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_service
        mock_db.commit = MagicMock()

        await service.delete_service(mock_db, "svc-id")

        # Should have executed delete statements for tool metrics, associations, and tools
        # plus the select query and the service delete
        assert mock_db.execute.call_count >= 4  # select + 3 bulk deletes
        mock_db.delete.assert_called_once_with(mock_service)
        mock_db.commit.assert_called()

    async def test_delete_service_no_tools(self, service, mock_db):
        """Test deleting a gRPC service that has no tools."""
        mock_service = MagicMock()
        mock_service.id = "svc-id"
        mock_service.name = "test-grpc-service"
        mock_service.tools = []

        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_service
        mock_db.commit = MagicMock()

        await service.delete_service(mock_db, "svc-id")

        # Only the select query + service delete, no bulk tool deletes
        mock_db.delete.assert_called_once_with(mock_service)
        mock_db.commit.assert_called()

    def test_sync_tools_multiple_services(self, service, mock_db, sample_db_service):
        """Test tool sync with multiple gRPC services discovered."""
        sample_db_service.discovered_services = {
            "pkg.ServiceA": {
                "name": "pkg.ServiceA",
                "methods": [
                    {"name": "MethodA", "input_type": ".pkg.ReqA", "output_type": ".pkg.RespA", "client_streaming": False, "server_streaming": False},
                ],
            },
            "pkg.ServiceB": {
                "name": "pkg.ServiceB",
                "methods": [
                    {"name": "MethodB1", "input_type": ".pkg.ReqB1", "output_type": ".pkg.RespB1", "client_streaming": False, "server_streaming": False},
                    {"name": "MethodB2", "input_type": ".pkg.ReqB2", "output_type": ".pkg.RespB2", "client_streaming": True, "server_streaming": False},
                ],
            },
        }
        sample_db_service.team_id = None
        sample_db_service.owner_email = None

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute.return_value = mock_result

        service._sync_tools_from_reflection(mock_db, sample_db_service)

        # Should have added 3 tools total
        assert mock_db.add.call_count == 3
        tool_names = {call[0][0].original_name for call in mock_db.add.call_args_list}
        assert tool_names == {"pkg.ServiceA.MethodA", "pkg.ServiceB.MethodB1", "pkg.ServiceB.MethodB2"}

    def test_sync_tools_skips_underscore_keys(self, service, mock_db, sample_db_service):
        """Test that _sync_tools_from_reflection skips _-prefixed keys like _file_descriptors."""
        sample_db_service.discovered_services = {
            "_file_descriptors": ["base64data"],
            "test.Svc": {
                "name": "test.Svc",
                "methods": [
                    {"name": "Do", "input_type": ".test.Req", "output_type": ".test.Resp", "client_streaming": False, "server_streaming": False},
                ],
            },
        }
        sample_db_service.team_id = None
        sample_db_service.owner_email = None

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute.return_value = mock_result

        service._sync_tools_from_reflection(mock_db, sample_db_service)

        # Should only create 1 tool, not try to process _file_descriptors
        assert mock_db.add.call_count == 1
        tool = mock_db.add.call_args[0][0]
        assert tool.original_name == "test.Svc.Do"

    def test_sync_tools_updates_matching_description(self, service, mock_db, sample_db_service):
        """Test that when description == original_description, both get updated."""
        sample_db_service.discovered_services = {
            "test.Svc": {
                "name": "test.Svc",
                "methods": [
                    {"name": "Do", "input_type": ".test.Req", "output_type": ".test.Resp", "client_streaming": False, "server_streaming": False},
                ],
            },
        }

        from mcpgateway.db import Tool as DbTool

        existing_tool = MagicMock(spec=DbTool)
        existing_tool.id = "tool-id"
        existing_tool.original_name = "test.Svc.Do"
        existing_tool.original_description = "old desc"
        existing_tool.description = "old desc"  # Matches original, so should be updated
        existing_tool.url = sample_db_service.target
        existing_tool.input_schema = {
            "type": "object",
            "properties": {},
            "x-grpc-input-type": ".test.Req",
            "x-grpc-output-type": ".test.Resp",
            "x-grpc-client-streaming": False,
            "x-grpc-server-streaming": False,
        }

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [existing_tool]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute.return_value = mock_result

        service._sync_tools_from_reflection(mock_db, sample_db_service)

        # Both description and original_description should be updated
        assert existing_tool.description == "gRPC method test.Svc.Do"
        assert existing_tool.original_description == "gRPC method test.Svc.Do"

    async def test_get_service_methods_skips_underscore_keys(self, service, mock_db, sample_db_service):
        """Test that get_service_methods skips _-prefixed keys like _file_descriptors."""
        sample_db_service.discovered_services = {
            "_file_descriptors": ["base64data"],
            "test.TestService": {
                "name": "test.TestService",
                "methods": [
                    {"name": "Hello", "input_type": "test.Req", "output_type": "test.Resp", "client_streaming": False, "server_streaming": False},
                ],
            },
        }
        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_db_service

        result = await service.get_service_methods(mock_db, sample_db_service.id)

        assert len(result) == 1
        assert result[0]["method"] == "Hello"

    @patch("mcpgateway.translate_grpc.GrpcEndpoint")
    async def test_invoke_method_with_stored_descriptors(self, mock_endpoint_cls, service, mock_db, sample_db_service):
        """Test invoke_method uses stored descriptors instead of reflection."""
        import base64

        fake_descriptor_bytes = b"\x0a\x05hello"
        sample_db_service.enabled = True
        sample_db_service.discovered_services = {
            "_file_descriptors": [base64.b64encode(fake_descriptor_bytes).decode("ascii")],
            "test.Svc": {
                "name": "test.Svc",
                "methods": [
                    {"name": "Do", "input_type": ".test.Req", "output_type": ".test.Resp", "client_streaming": False, "server_streaming": False},
                ],
            },
        }
        sample_db_service.tls_enabled = False
        sample_db_service.tls_cert_path = None
        sample_db_service.tls_key_path = None
        sample_db_service.grpc_metadata = {}

        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_db_service

        mock_ep_instance = AsyncMock()
        mock_ep_instance.invoke = AsyncMock(return_value={"result": "ok"})
        mock_ep_instance.close = AsyncMock()
        mock_ep_instance.load_file_descriptors = MagicMock()
        mock_ep_instance._services = {}
        mock_endpoint_cls.return_value = mock_ep_instance

        result = await service.invoke_method(mock_db, sample_db_service.id, "test.Svc.Do", {"key": "value"})

        assert result == {"result": "ok"}
        # Should have been created with reflection_enabled=False
        mock_endpoint_cls.assert_called_once()
        call_kwargs = mock_endpoint_cls.call_args[1]
        assert call_kwargs["reflection_enabled"] is False
        # Should have called load_file_descriptors
        mock_ep_instance.load_file_descriptors.assert_called_once()
        # Should have set _services (excluding _file_descriptors)
        assert "_file_descriptors" not in mock_ep_instance._services
        mock_ep_instance.close.assert_called_once()

    @patch("mcpgateway.translate_grpc.GrpcEndpoint")
    async def test_invoke_method_without_stored_descriptors(self, mock_endpoint_cls, service, mock_db, sample_db_service):
        """Test invoke_method falls back to reflection when no stored descriptors."""
        sample_db_service.enabled = True
        sample_db_service.discovered_services = {
            "test.Svc": {
                "name": "test.Svc",
                "methods": [
                    {"name": "Do", "input_type": ".test.Req", "output_type": ".test.Resp", "client_streaming": False, "server_streaming": False},
                ],
            },
        }
        sample_db_service.tls_enabled = False
        sample_db_service.tls_cert_path = None
        sample_db_service.tls_key_path = None
        sample_db_service.grpc_metadata = {}

        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_db_service

        mock_ep_instance = AsyncMock()
        mock_ep_instance.invoke = AsyncMock(return_value={"result": "ok"})
        mock_ep_instance.close = AsyncMock()
        mock_endpoint_cls.return_value = mock_ep_instance

        result = await service.invoke_method(mock_db, sample_db_service.id, "test.Svc.Do", {})

        assert result == {"result": "ok"}
        # Should have been created with reflection_enabled=True
        call_kwargs = mock_endpoint_cls.call_args[1]
        assert call_kwargs["reflection_enabled"] is True
        mock_ep_instance.close.assert_called_once()

    @patch("mcpgateway.services.grpc_service.grpc")
    @patch("mcpgateway.services.grpc_service.reflection_pb2_grpc")
    @patch("mcpgateway.services.grpc_service.reflection_pb2")
    async def test_perform_reflection_stores_file_descriptor_bytes(self, mock_reflection_pb2, mock_reflection_pb2_grpc, mock_grpc, service, mock_db, sample_db_service):
        """Test that _perform_reflection collects file descriptor bytes into _file_descriptors."""
        import base64

        from google.protobuf.descriptor_pb2 import FileDescriptorProto  # pylint: disable=no-name-in-module

        # Build a real serialized FileDescriptorProto
        fd_proto = FileDescriptorProto()
        fd_proto.name = "test.proto"
        fd_proto.package = "testpkg"
        svc_desc = fd_proto.service.add()
        svc_desc.name = "TestService"
        m = svc_desc.method.add()
        m.name = "DoStuff"
        m.input_type = ".testpkg.Req"
        m.output_type = ".testpkg.Resp"
        proto_bytes = fd_proto.SerializeToString()

        sample_db_service.tls_enabled = False

        # Mock list_services response
        list_resp = MagicMock()
        list_resp.HasField = lambda f: f == "list_services_response"
        svc_info = MagicMock()
        svc_info.name = "testpkg.TestService"
        list_resp.list_services_response.service = [svc_info]

        # Mock file_descriptor response
        fd_resp = MagicMock()
        fd_resp.HasField = lambda f: f == "file_descriptor_response"
        fd_resp.file_descriptor_response.file_descriptor_proto = [proto_bytes]

        mock_stub = MagicMock()
        # First call: list services, second call: file descriptor
        mock_stub.ServerReflectionInfo = MagicMock(side_effect=[iter([list_resp]), iter([fd_resp])])
        mock_reflection_pb2_grpc.ServerReflectionStub.return_value = mock_stub

        mock_grpc.insecure_channel.return_value = MagicMock()

        # Patch _sync_tools_from_reflection to avoid DB operations
        with patch.object(service, "_sync_tools_from_reflection"):
            await service._perform_reflection(mock_db, sample_db_service)

        # Verify _file_descriptors was populated
        discovered = sample_db_service.discovered_services
        assert "_file_descriptors" in discovered
        assert len(discovered["_file_descriptors"]) == 1
        # Verify it's valid base64-encoded proto bytes
        decoded = base64.b64decode(discovered["_file_descriptors"][0])
        assert decoded == proto_bytes
        # Verify service was discovered
        assert "testpkg.TestService" in discovered
        assert discovered["testpkg.TestService"]["methods"][0]["name"] == "DoStuff"
