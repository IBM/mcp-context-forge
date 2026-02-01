# -*- coding: utf-8 -*-
"""Tests for GrpcService without requiring grpc packages."""

# Standard
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
import uuid

# Third-Party
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import GrpcService as DbGrpcService
from mcpgateway.schemas import GrpcServiceCreate, GrpcServiceUpdate
from mcpgateway.services.grpc_service import GrpcService, GrpcServiceError, GrpcServiceNameConflictError, GrpcServiceNotFoundError


@pytest.fixture
def service():
    return GrpcService()


@pytest.fixture
def db():
    return MagicMock(spec=Session)


def _mock_execute_scalar(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


@pytest.mark.asyncio
async def test_register_service_no_conflict(service, db):
    db.execute.return_value = _mock_execute_scalar(None)

    def refresh(obj):
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

    db.refresh = MagicMock(side_effect=refresh)

    service_data = GrpcServiceCreate(
        name="svc",
        target="localhost:50051",
        description="desc",
        reflection_enabled=False,
        tls_enabled=False,
    )

    result = await service.register_service(db, service_data, user_email="user@example.com")

    assert result.name == "svc"
    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_register_service_conflict(service, db):
    db.execute.return_value = _mock_execute_scalar(MagicMock(id="s1", enabled=True))
    service_data = GrpcServiceCreate(name="svc", target="localhost:50051", description="desc")

    with pytest.raises(GrpcServiceNameConflictError):
        await service.register_service(db, service_data)


@pytest.mark.asyncio
async def test_update_service_not_found(service, db):
    db.execute.return_value = _mock_execute_scalar(None)

    with pytest.raises(GrpcServiceNotFoundError):
        await service.update_service(db, "missing", GrpcServiceUpdate(description="x"))


@pytest.mark.asyncio
async def test_update_service_success(service, db):
    db_service = DbGrpcService(
        id="svc-1",
        name="svc",
        slug="svc",
        target="localhost:50051",
        description="desc",
        reflection_enabled=False,
        tls_enabled=False,
        grpc_metadata={},
        enabled=True,
        reachable=False,
        service_count=0,
        method_count=0,
        discovered_services={},
        last_reflection=None,
        tags=[],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        version=1,
        visibility="public",
    )
    db.execute.side_effect = [_mock_execute_scalar(db_service), _mock_execute_scalar(None)]
    db.commit = MagicMock()
    db.refresh = MagicMock()

    result = await service.update_service(db, "svc-1", GrpcServiceUpdate(description="updated"))
    assert result.description == "updated"
    assert db.commit.called


@pytest.mark.asyncio
async def test_set_service_state_and_delete(service, db):
    db_service = DbGrpcService(
        id="svc-1",
        name="svc",
        slug="svc",
        target="localhost:50051",
        description="desc",
        reflection_enabled=False,
        tls_enabled=False,
        grpc_metadata={},
        enabled=True,
        reachable=False,
        service_count=0,
        method_count=0,
        discovered_services={},
        last_reflection=None,
        tags=[],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        version=1,
        visibility="public",
    )
    db.execute.return_value = _mock_execute_scalar(db_service)
    db.commit = MagicMock()
    db.refresh = MagicMock()

    result = await service.set_service_state(db, "svc-1", activate=False)
    assert result.enabled is False

    await service.delete_service(db, "svc-1")
    db.delete.assert_called_once()


@pytest.mark.asyncio
async def test_reflect_service_success(service, db):
    db_service = DbGrpcService(
        id="svc-1",
        name="svc",
        slug="svc",
        target="localhost:50051",
        description="desc",
        reflection_enabled=False,
        tls_enabled=False,
        grpc_metadata={},
        enabled=True,
        reachable=False,
        service_count=1,
        method_count=2,
        discovered_services={},
        last_reflection=None,
        tags=[],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        version=1,
        visibility="public",
    )
    db.execute.return_value = _mock_execute_scalar(db_service)

    service._perform_reflection = AsyncMock()
    result = await service.reflect_service(db, "svc-1")
    assert result.id == "svc-1"


@pytest.mark.asyncio
async def test_reflect_service_error(service, db):
    db_service = DbGrpcService(
        id="svc-1",
        name="svc",
        slug="svc",
        target="localhost:50051",
        description="desc",
        reflection_enabled=False,
        tls_enabled=False,
        grpc_metadata={},
        enabled=True,
        reachable=True,
        service_count=0,
        method_count=0,
        discovered_services={},
        last_reflection=None,
        tags=[],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        version=1,
        visibility="public",
    )
    db.execute.return_value = _mock_execute_scalar(db_service)
    db.commit = MagicMock()
    service._perform_reflection = AsyncMock(side_effect=Exception("boom"))

    with pytest.raises(GrpcServiceError):
        await service.reflect_service(db, "svc-1")
    assert db_service.reachable is False


@pytest.mark.asyncio
async def test_get_service_methods(service, db):
    db_service = DbGrpcService(
        id="svc-1",
        name="svc",
        slug="svc",
        target="localhost:50051",
        description="desc",
        reflection_enabled=False,
        tls_enabled=False,
        grpc_metadata={},
        enabled=True,
        reachable=True,
        service_count=0,
        method_count=0,
        discovered_services={
            "pkg.Service": {
                "methods": [
                    {"name": "Ping", "input_type": "PingReq", "output_type": "PingResp", "client_streaming": False, "server_streaming": False}
                ]
            }
        },
        last_reflection=None,
        tags=[],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        version=1,
        visibility="public",
    )
    db.execute.return_value = _mock_execute_scalar(db_service)

    methods = await service.get_service_methods(db, "svc-1")
    assert methods[0]["full_name"] == "pkg.Service.Ping"
