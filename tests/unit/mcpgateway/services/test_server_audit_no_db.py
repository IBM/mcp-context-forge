# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_server_audit_no_db.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Regression tests for server audit_trail.log_action db handling.
"""

from __future__ import annotations

from typing import TypeVar
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from mcpgateway.db import Server as DbServer
from mcpgateway.schemas import ServerCreate, ServerRead, ServerUpdate
from mcpgateway.services.server_service import ServerError, ServerService

_R = TypeVar("_R")
_TEAM_A = "00000000000040008000000000000001"
_TEAM_B = "00000000000040008000000000000002"


def _make_execute_result(*, scalar: _R | None = None, scalars_list: list[_R] | None = None, rowcount: int = 0) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    result.rowcount = rowcount
    scalars_proxy = MagicMock()
    scalars_proxy.all.return_value = scalars_list or []
    result.scalars.return_value = scalars_proxy
    return result


def _assert_no_db_passed(mock_audit: MagicMock, *, expected_action: str | None = None, resource_type: str | None = None) -> None:
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
        return m
    monkeypatch.setattr(ServerRead, "model_validate", staticmethod(_fake_validate))
    yield


@pytest.fixture
def server_service():
    svc = ServerService()
    svc._audit_trail = MagicMock()
    return svc


@pytest.fixture
def db():
    return MagicMock()


@pytest.fixture
def server_db():
    srv = MagicMock(spec=DbServer)
    srv.id = "srv-1"
    srv.name = "server-1"
    srv.enabled = True
    srv.team_id = None
    srv.owner_email = "tester@example.com"
    srv.tools = []
    srv.resources = []
    srv.prompts = []
    srv.a2a_agents = []
    srv.visibility = "public"
    return srv


class TestServerAuditNoDb:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("schema_team", "request_team", "expected_team"),
        [(None, None, None), (None, _TEAM_A, _TEAM_A), (_TEAM_B, None, _TEAM_B), (_TEAM_B, _TEAM_A, _TEAM_B)],
    )
    async def test_register_server(self, server_service, db, schema_team, request_team, expected_team):
        """Server creation audits the persisted team, including schema-derived ownership."""
        server_service._audit_trail.log_action = MagicMock(return_value=None)
        db.execute = Mock(side_effect=[_make_execute_result(scalar=None), _make_execute_result(scalar=None)])
        db.add = Mock()
        db.commit = Mock()
        db.refresh = Mock()
        db.flush = Mock()
        server_service._notify_server_added = AsyncMock()
        await server_service.register_server(db, ServerCreate(name="server-1", description="x", team_id=schema_team), team_id=request_team)
        server_service._audit_trail.log_action.assert_called_once()
        _assert_no_db_passed(server_service._audit_trail, expected_action="create_server", resource_type="server")
        audit_kwargs = server_service._audit_trail.log_action.call_args.kwargs
        assert audit_kwargs["team_id"] == expected_team
        assert audit_kwargs["details"]["team_id"] == expected_team
        assert db.add.call_args.args[0].team_id == expected_team

    @pytest.mark.asyncio
    async def test_register_server_audit_failure_does_not_block_already_committed_server(self, server_service, db):
        """If audit_trail.log_action() raises, the server row is already committed (db.commit ran first)."""
        server_service._audit_trail.log_action = MagicMock(side_effect=Exception("audit backend unavailable"))
        db.execute = Mock(side_effect=[_make_execute_result(scalar=None), _make_execute_result(scalar=None)])
        db.add = Mock()
        db.commit = Mock()
        db.refresh = Mock()
        db.flush = Mock()
        db.rollback = Mock()
        server_service._notify_server_added = AsyncMock()
        with pytest.raises(ServerError):
            await server_service.register_server(db, ServerCreate(name="server-1", description="x"))
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("original_team", "updated_team", "expected_team"), [(None, None, None), ("team-a", None, "team-a"), ("team-a", "team-b", "team-b")])
    async def test_update_server(self, server_service, db, server_db, original_team, updated_team, expected_team):
        """Server updates audit the resulting team after reassignment."""
        server_db.team_id = original_team
        server_service._audit_trail.log_action = MagicMock(return_value=None)
        db.commit = Mock()
        db.refresh = Mock()
        db.rollback = Mock()
        db.expire = Mock()
        server_service._notify_server_updated = AsyncMock()
        with patch("mcpgateway.services.server_service.get_for_update", return_value=server_db):
            await server_service.update_server(db, "srv-1", ServerUpdate(description="updated", team_id=updated_team), user_email="tester@example.com")
        server_service._audit_trail.log_action.assert_called_once()
        _assert_no_db_passed(server_service._audit_trail, expected_action="update_server", resource_type="server")
        assert server_service._audit_trail.log_action.call_args.kwargs["team_id"] == expected_team

    @pytest.mark.asyncio
    @pytest.mark.parametrize("activate", [True, False])
    @pytest.mark.parametrize("team_id", [None, "team-a"])
    async def test_set_server_state_audits_resource_team(self, server_service, db, server_db, activate, team_id):
        """Activation and deactivation audit the resource team through independent sessions."""
        server_db.team_id = team_id
        server_db.enabled = not activate
        server_service._notify_server_activated = AsyncMock()
        server_service._notify_server_deactivated = AsyncMock()
        with patch("mcpgateway.services.server_service.get_for_update", return_value=server_db):
            await server_service.set_server_state(db, "srv-1", activate=activate)
        server_service._audit_trail.log_action.assert_called_once()
        _assert_no_db_passed(server_service._audit_trail, expected_action="activate_server" if activate else "deactivate_server", resource_type="server")
        assert server_service._audit_trail.log_action.call_args.kwargs["team_id"] == team_id

    @pytest.mark.asyncio
    @pytest.mark.parametrize("team_id", [None, "team-a"])
    async def test_delete_server(self, server_service, db, server_db, team_id):
        """Server deletion audits the team captured before the resource is removed."""
        server_db.team_id = team_id
        server_service._audit_trail.log_action = MagicMock(return_value=None)
        db.get = Mock(return_value=server_db)
        db.execute = Mock(return_value=_make_execute_result(scalar=server_db, rowcount=1))
        db.delete = Mock()
        db.commit = Mock()
        db.rollback = Mock()
        db.expire = Mock()
        server_service._notify_server_deleted = AsyncMock()
        await server_service.delete_server(db, "srv-1")
        server_service._audit_trail.log_action.assert_called_once()
        _assert_no_db_passed(server_service._audit_trail, expected_action="delete_server", resource_type="server")
        assert server_service._audit_trail.log_action.call_args.kwargs["team_id"] == team_id

    @pytest.mark.asyncio
    @pytest.mark.parametrize("team_id", [None, "team-a"])
    async def test_get_server_audit_uses_system_user_id(self, server_service, db, server_db, team_id):
        """get_server hardcodes user_id='system' for view_server audit — pin this to catch accidental changes."""
        server_service._audit_trail.log_action = MagicMock(return_value=None)
        server_db.team_id = team_id
        db.execute = Mock(return_value=_make_execute_result(scalar=server_db))
        server_service._check_server_access = AsyncMock(return_value=True)
        server_service.convert_server_to_read = Mock(return_value=MagicMock())
        await server_service.get_server(db, "srv-1")
        server_service._audit_trail.log_action.assert_called_once()
        call_kwargs = server_service._audit_trail.log_action.call_args.kwargs
        assert call_kwargs["user_id"] == "system", "get_server audit must use user_id='system' (intentional system read attribution)"
        assert call_kwargs["action"] == "view_server"
        assert call_kwargs["resource_type"] == "server"
        assert call_kwargs["team_id"] == team_id
        _assert_no_db_passed(server_service._audit_trail)
