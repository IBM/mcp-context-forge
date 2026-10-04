# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_gateway_audit_no_db.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Regression tests for gateway audit_trail.log_action db handling.
"""

from __future__ import annotations

from typing import Any, TypeVar
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from mcpgateway.db import Gateway as DbGateway
from mcpgateway.schemas import GatewayCreate, GatewayRead, GatewayUpdate
from mcpgateway.services.gateway_service import GatewayService

_R = TypeVar("_R")


def _make_execute_result(*, scalar: _R | None = None, scalars_list: list[_R] | None = None, rowcount: int = 0) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    result.rowcount = rowcount
    scalars_proxy = MagicMock()
    scalars_proxy.all.return_value = scalars_list or []
    result.scalars.return_value = scalars_proxy
    return result


def _assert_no_db_passed(mock_audit: MagicMock, *, expected_action: str | None = None, resource_type: str | None = None) -> None:
    """Assert that none of the log_action calls received a ``db`` argument."""
    calls = mock_audit.log_action.call_args_list
    for call in calls:
        assert "db" not in call.kwargs, f"audit_trail.log_action() was called with db= keyword argument: {call}"
        assert len(call.args) < 23, f"audit_trail.log_action() received too many positional args (db may be positional): {call}"
    if expected_action is not None:
        actions = [call.kwargs.get("action") for call in calls]
        assert expected_action in actions, f"expected action {expected_action!r} not found in calls: {actions}"
    if resource_type is not None:
        for call in calls:
            assert call.kwargs.get("resource_type") == resource_type, f"unexpected resource_type in call: {call}"


@pytest.fixture(autouse=True)
def _patch_models(monkeypatch):
    def _fake_validate(d):
        m = MagicMock()
        m.masked.return_value = m
        m.skipped_tools = []
        return m
    monkeypatch.setattr(GatewayRead, "model_validate", staticmethod(_fake_validate))
    yield


@pytest.fixture
def gateway_service():
    return GatewayService()


@pytest.fixture
def db():
    return MagicMock()


@pytest.fixture
def gateway_db():
    gw = MagicMock(spec=DbGateway)
    gw.id = "gw-1"
    gw.name = "gateway-1"
    gw.url = "https://example.com"
    gw.team_id = None
    gw.enabled = True
    gw.reachable = True
    gw.tools = []
    gw.resources = []
    gw.prompts = []
    gw.auth_value = None
    gw.oauth_config = None
    gw.transport = "SSE"
    return gw


class TestGatewayAuditNoDb:
    @pytest.mark.asyncio
    async def test_register_gateway(self, gateway_service, db):
        with patch("mcpgateway.services.gateway_service.audit_trail") as mock_audit, patch("mcpgateway.services.gateway_service.structured_logger"):
            mock_audit.log_action = MagicMock(return_value=None)
            db.execute = Mock(side_effect=[_make_execute_result(scalar=None), _make_execute_result(scalars_list=[])])
            db.add = Mock(); db.commit = Mock(); db.refresh = Mock(); db.flush = Mock(); db.add_all = Mock()
            gateway_service._initialize_gateway = AsyncMock(return_value=({"prompts": {}, "resources": {}, "tools": {}}, [], [], [], []))
            gateway_service._notify_gateway_added = AsyncMock()
            await gateway_service.register_gateway(db, GatewayCreate(name="g", url="https://example.com", transport="SSE"))
            mock_audit.log_action.assert_called_once()
            _assert_no_db_passed(mock_audit, expected_action="create_gateway", resource_type="gateway")

    @pytest.mark.asyncio
    async def test_register_gateway_audit_failure_does_not_block_already_committed_gateway(self, gateway_service, db):
        """If audit_trail.log_action() raises, the gateway row is already committed (db.commit ran first)."""
        with patch("mcpgateway.services.gateway_service.audit_trail") as mock_audit, patch("mcpgateway.services.gateway_service.structured_logger"):
            mock_audit.log_action = MagicMock(side_effect=Exception("audit backend unavailable"))
            db.execute = Mock(side_effect=[_make_execute_result(scalar=None), _make_execute_result(scalars_list=[])])
            db.add = Mock(); db.commit = Mock(); db.refresh = Mock(); db.flush = Mock(); db.add_all = Mock()
            gateway_service._initialize_gateway = AsyncMock(return_value=({"prompts": {}, "resources": {}, "tools": {}}, [], [], [], []))
            gateway_service._notify_gateway_added = AsyncMock()
            with pytest.raises(Exception, match="audit backend unavailable"):
                await gateway_service.register_gateway(db, GatewayCreate(name="g", url="https://example.com", transport="SSE"))
            db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_register_gateway_async_lifecycle_audit_trail(self, gateway_service, db):
        """Async gateway creation (pending) must also log an audit trail entry."""
        with patch("mcpgateway.services.gateway_service.audit_trail") as mock_audit, patch("mcpgateway.services.gateway_service.structured_logger"):
            mock_audit.log_action = MagicMock(return_value=None)
            db.execute = Mock(return_value=_make_execute_result(scalar=None))
            db.add = Mock(); db.commit = Mock(); db.refresh = Mock(); db.flush = Mock(); db.add_all = Mock()
            monkeypatch = pytest.MonkeyPatch()
            monkeypatch.setattr("mcpgateway.services.gateway_service.settings.gateway_async_lifecycle_enabled", True)
            gateway_service._prepare_gateway_registration = AsyncMock(
                return_value=MagicMock(
                    slug_name="g",
                    normalized_url="https://example.com",
                    auth_type=None,
                    auth_value=None,
                    authentication_headers=None,
                    auth_query_params_encrypted=None,
                    auth_query_params_decrypted=None,
                    init_url="https://example.com",
                    oauth_config=None,
                    ca_certificate=None,
                    init_client_cert=None,
                    init_client_key=None,
                    gateway_mode="cache",
                )
            )
            gateway_service._encrypt_client_key = AsyncMock(return_value=None)
            gateway_service.convert_gateway_to_read = MagicMock(return_value=MagicMock(skipped_tools=[]))
            try:
                await gateway_service.register_gateway(
                    db,
                    GatewayCreate(name="g", url="https://example.com", transport="SSE"),
                    created_by="test-user",
                    created_from_ip="127.0.0.1",
                    created_via="api",
                    created_user_agent="test-agent",
                )
                mock_audit.log_action.assert_called_once()
                call_kwargs = mock_audit.log_action.call_args.kwargs
                assert call_kwargs.get("action") == "create_gateway"
                assert call_kwargs.get("resource_type") == "gateway"
                assert call_kwargs.get("user_id") == "test-user"
                assert call_kwargs.get("client_ip") == "127.0.0.1"
                assert call_kwargs.get("user_agent") == "test-agent"
                _assert_no_db_passed(mock_audit, expected_action="create_gateway", resource_type="gateway")
            finally:
                monkeypatch.undo()

    @pytest.mark.parametrize("async_lifecycle", [False, True])
    @pytest.mark.asyncio
    async def test_update_gateway(self, gateway_service, db, gateway_db, monkeypatch, async_lifecycle):
        monkeypatch.setattr("mcpgateway.services.gateway_service.settings.gateway_async_lifecycle_enabled", async_lifecycle)
        with patch("mcpgateway.services.gateway_service.audit_trail") as mock_audit, patch("mcpgateway.services.gateway_service.structured_logger"):
            mock_audit.log_action = MagicMock(return_value=None)
            db.execute = Mock(return_value=_make_execute_result(scalar=gateway_db))
            db.commit = Mock(); db.refresh = Mock(); db.rollback = Mock(); db.expire = Mock(); db.delete = Mock(); db.add_all = Mock(); db.flush = Mock()
            gateway_service._notify_gateway_updated = AsyncMock()
            gateway_service._update_or_create_tools = AsyncMock(return_value=[])
            gateway_service._update_or_create_resources = AsyncMock(return_value=[])
            gateway_service._update_or_create_prompts = AsyncMock(return_value=[])
            await gateway_service.update_gateway(db, "gw-1", GatewayUpdate(description="updated"))
            mock_audit.log_action.assert_called_once()
            _assert_no_db_passed(mock_audit, expected_action="update_gateway", resource_type="gateway")

    @pytest.mark.asyncio
    async def test_set_gateway_state(self, gateway_service, db, gateway_db):
        with patch("mcpgateway.services.gateway_service.audit_trail") as mock_audit, patch("mcpgateway.services.gateway_service.structured_logger"):
            mock_audit.log_action = MagicMock(return_value=None)
            db.execute = Mock(return_value=_make_execute_result(scalar=gateway_db))
            db.commit = Mock(); db.refresh = Mock(); db.rollback = Mock()
            gateway_service._initialize_gateway = AsyncMock(return_value=({}, [], [], [], []))
            gateway_service._notify_gateway_activated = AsyncMock(); gateway_service._notify_gateway_deactivated = AsyncMock(); gateway_service._notify_gateway_offline = AsyncMock()
            await gateway_service.set_gateway_state(db, "gw-1", activate=False, reachable=True)
            mock_audit.log_action.assert_called_once()
            _assert_no_db_passed(mock_audit, expected_action="set_gateway_state", resource_type="gateway")

    @pytest.mark.parametrize("async_lifecycle", [False, True])
    @pytest.mark.asyncio
    async def test_delete_gateway(self, gateway_service, db, gateway_db, monkeypatch, async_lifecycle):
        monkeypatch.setattr("mcpgateway.services.gateway_service.settings.gateway_async_lifecycle_enabled", async_lifecycle)
        with patch("mcpgateway.services.gateway_service.audit_trail") as mock_audit, patch("mcpgateway.services.gateway_service.structured_logger"):
            mock_audit.log_action = MagicMock(return_value=None)
            db.execute = Mock(return_value=_make_execute_result(scalar=gateway_db, rowcount=1))
            db.delete = Mock(); db.commit = Mock(); db.rollback = Mock(); db.expire = Mock()
            gateway_service._notify_gateway_deleted = AsyncMock()
            await gateway_service.delete_gateway(db, "gw-1")
            mock_audit.log_action.assert_called_once()
            _assert_no_db_passed(mock_audit, expected_action="delete_gateway", resource_type="gateway")
