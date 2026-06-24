# -*- coding: utf-8 -*-
"""Regression tests for resource audit_trail.log_action db handling."""

from __future__ import annotations

from typing import TypeVar
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from mcpgateway.db import Resource as DbResource
from mcpgateway.schemas import ResourceCreate, ResourceRead, ResourceUpdate
from mcpgateway.services.resource_service import ResourceService

_R = TypeVar("_R")


def _make_execute_result(*, scalar: _R | None = None, scalars_list: list[_R] | None = None, rowcount: int = 0) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    result.rowcount = rowcount
    scalars_proxy = MagicMock()
    scalars_proxy.all.return_value = scalars_list or []
    result.scalars.return_value = scalars_proxy
    return result


def _assert_no_db_passed(mock_audit: MagicMock) -> None:
    for call in mock_audit.log_action.call_args_list:
        assert "db" not in call.kwargs, f"audit_trail.log_action() was called with db= keyword argument: {call}"
        assert len(call.args) < 23, f"audit_trail.log_action() received too many positional args (db may be positional): {call}"


@pytest.fixture(autouse=True)
def _patch_models(monkeypatch):
    def _fake_validate(d):
        m = MagicMock()
        m.masked.return_value = d
        return m
    monkeypatch.setattr(ResourceRead, "model_validate", staticmethod(_fake_validate))
    yield


@pytest.fixture
def resource_service():
    return ResourceService()


@pytest.fixture
def db():
    return MagicMock()


@pytest.fixture
def resource_db():
    res = MagicMock(spec=DbResource)
    res.id = 1
    res.uri = "res://1"
    res.name = "resource-1"
    res.enabled = True
    res.team_id = None
    return res


class TestResourceAuditNoDb:
    @pytest.mark.asyncio
    async def test_register_resource(self, resource_service, db):
        with patch("mcpgateway.services.resource_service.audit_trail") as mock_audit, patch("mcpgateway.services.resource_service.structured_logger"):
            mock_audit.log_action = MagicMock(return_value=None)
            db.execute = Mock(side_effect=[_make_execute_result(scalar=None), _make_execute_result(scalar=None)])
            db.add = Mock(); db.commit = Mock(); db.refresh = Mock(); db.flush = Mock()
            resource_service._notify_resource_added = AsyncMock()
            await resource_service.register_resource(db, ResourceCreate(uri="https://example.com/resource-1", name="resource-1", mime_type="text/plain", content="x"))
            assert mock_audit.log_action.called
            _assert_no_db_passed(mock_audit)

    @pytest.mark.asyncio
    async def test_update_resource(self, resource_service, db, resource_db):
        with patch("mcpgateway.services.resource_service.audit_trail") as mock_audit, patch("mcpgateway.services.resource_service.structured_logger"):
            mock_audit.log_action = MagicMock(return_value=None)
            db.execute = Mock(return_value=_make_execute_result(scalar=resource_db))
            db.commit = Mock(); db.refresh = Mock(); db.rollback = Mock(); db.expire = Mock()
            await resource_service.update_resource(db, 1, ResourceUpdate(description="updated"))
            assert mock_audit.log_action.called
            _assert_no_db_passed(mock_audit)

    @pytest.mark.asyncio
    async def test_set_resource_state(self, resource_service, db, resource_db):
        with patch("mcpgateway.services.resource_service.audit_trail") as mock_audit, patch("mcpgateway.services.resource_service.structured_logger"):
            mock_audit.log_action = MagicMock(return_value=None)
            db.execute = Mock(return_value=_make_execute_result(scalar=resource_db))
            db.commit = Mock(); db.refresh = Mock(); db.rollback = Mock()
            await resource_service.set_resource_state(db, 1, activate=False)
            assert mock_audit.log_action.called
            _assert_no_db_passed(mock_audit)

    @pytest.mark.asyncio
    async def test_delete_resource(self, resource_service, db, resource_db):
        with patch("mcpgateway.services.resource_service.audit_trail") as mock_audit, patch("mcpgateway.services.resource_service.structured_logger"):
            mock_audit.log_action = MagicMock(return_value=None)
            db.execute = Mock(return_value=_make_execute_result(scalar=resource_db, rowcount=1))
            db.delete = Mock(); db.commit = Mock(); db.rollback = Mock(); db.expire = Mock()
            await resource_service.delete_resource(db, 1)
            assert mock_audit.log_action.called
            _assert_no_db_passed(mock_audit)

    @pytest.mark.asyncio
    async def test_register_resources_bulk(self, resource_service, db):
        with patch("mcpgateway.services.resource_service.audit_trail") as mock_audit, \
             patch("mcpgateway.services.resource_service.structured_logger"), \
             patch("mcpgateway.services.resource_service.get_content_security_service") as mock_cs:
            mock_audit.log_action = MagicMock(return_value=None)
            mock_cs.return_value = MagicMock()  # content security that doesn't raise

            # No existing resources — conflict check returns empty list
            db.execute = Mock(return_value=_make_execute_result(scalars_list=[]))
            db.add_all = Mock()
            db.commit = Mock()
            db.refresh = Mock()
            resource_service._notify_resource_added = AsyncMock()

            resources = [ResourceCreate(uri="https://example.com/bulk-1", name="bulk-1", mime_type="text/plain", content="x")]
            await resource_service.register_resources_bulk(db, resources, created_by="tester")

            assert mock_audit.log_action.called
            _assert_no_db_passed(mock_audit)
