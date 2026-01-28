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
from mcpgateway.schemas import GrpcServiceCreate, GrpcServiceUpdate
from mcpgateway.services.grpc_service import GrpcService, GrpcServiceNameConflictError, GrpcServiceNotFoundError


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
