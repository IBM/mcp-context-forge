# -*- coding: utf-8 -*-
"""Regression tests for tool audit_trail.log_action db handling."""

from __future__ import annotations

from typing import TypeVar
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from mcpgateway.db import Tool as DbTool
from mcpgateway.schemas import ToolCreate, ToolRead, ToolUpdate
from mcpgateway.services.tool_service import ToolError, ToolService

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
    monkeypatch.setattr(ToolRead, "model_validate", staticmethod(_fake_validate))
    yield


@pytest.fixture
def tool_service():
    return ToolService()


@pytest.fixture
def db():
    return MagicMock()


@pytest.fixture
def tool_db():
    tool = MagicMock(spec=DbTool)
    tool.id = "tool-1"
    tool.name = "tool-1"
    tool.enabled = True
    tool.team_id = None
    tool.output_schema = None
    tool.input_schema = {"type": "object"}
    tool.description = "test tool"
    tool.visibility = "public"
    tool.owner_email = "tester@example.com"
    tool.gateway_id = None
    tool.auth_type = None
    tool.auth_value = None
    return tool


class TestToolAuditNoDb:
    @pytest.mark.asyncio
    async def test_register_tool(self, tool_service, db):
        with patch("mcpgateway.services.tool_service.audit_trail") as mock_audit, patch("mcpgateway.services.tool_service.structured_logger"):
            mock_audit.log_action = MagicMock(return_value=None)
            db.execute = Mock(side_effect=[_make_execute_result(scalar=None), _make_execute_result(scalar=None)])
            db.add = Mock(); db.commit = Mock(); db.refresh = Mock(); db.flush = Mock()
            await tool_service.register_tool(db, ToolCreate(name="tool-1", url="https://example.com", request_type="POST", input_schema={"type": "object"}))
            mock_audit.log_action.assert_called_once()
            _assert_no_db_passed(mock_audit, expected_action="create_tool", resource_type="tool")

    @pytest.mark.asyncio
    async def test_register_tool_audit_failure_does_not_block_already_committed_tool(self, tool_service, db):
        """If audit_trail.log_action() raises, the tool row is already committed (db.commit ran first)."""
        with patch("mcpgateway.services.tool_service.audit_trail") as mock_audit, patch("mcpgateway.services.tool_service.structured_logger"):
            mock_audit.log_action = MagicMock(side_effect=Exception("audit backend unavailable"))
            db.execute = Mock(side_effect=[_make_execute_result(scalar=None), _make_execute_result(scalar=None)])
            db.add = Mock(); db.commit = Mock(); db.refresh = Mock(); db.flush = Mock(); db.rollback = Mock()
            with pytest.raises(ToolError):
                await tool_service.register_tool(db, ToolCreate(name="tool-1", url="https://example.com", request_type="POST", input_schema={"type": "object"}))
            db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_tool(self, tool_service, db, tool_db):
        with patch("mcpgateway.services.tool_service.audit_trail") as mock_audit, patch("mcpgateway.services.tool_service.structured_logger"), \
             patch("mcpgateway.services.tool_service.get_for_update", return_value=tool_db), \
             patch("mcpgateway.services.tool_service._get_registry_cache", return_value=AsyncMock()), \
             patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=AsyncMock()):
            mock_audit.log_action = MagicMock(return_value=None)
            db.commit = Mock(); db.refresh = Mock(); db.rollback = Mock(); db.expire = Mock()
            tool_service._notify_tool_updated = AsyncMock()
            await tool_service.update_tool(db, "tool-1", ToolUpdate(description="updated"), user_email="tester@example.com")
            mock_audit.log_action.assert_called_once()
            _assert_no_db_passed(mock_audit, expected_action="update_tool", resource_type="tool")

    @pytest.mark.asyncio
    async def test_set_tool_state(self, tool_service, db, tool_db):
        with patch("mcpgateway.services.tool_service.audit_trail") as mock_audit, patch("mcpgateway.services.tool_service.structured_logger"), \
             patch("mcpgateway.services.tool_service.get_for_update", return_value=tool_db):
            mock_audit.log_action = MagicMock(return_value=None)
            db.commit = Mock(); db.refresh = Mock(); db.rollback = Mock()
            tool_service._notify_tool_state_changed = AsyncMock()
            await tool_service.set_tool_state(db, "tool-1", activate=False, reachable=True)
            mock_audit.log_action.assert_called_once()
            _assert_no_db_passed(mock_audit, expected_action="set_tool_state", resource_type="tool")

    @pytest.mark.asyncio
    async def test_delete_tool(self, tool_service, db, tool_db):
        with patch("mcpgateway.services.tool_service.audit_trail") as mock_audit, patch("mcpgateway.services.tool_service.structured_logger"), \
             patch("mcpgateway.services.tool_service.get_for_update", return_value=tool_db):
            mock_audit.log_action = MagicMock(return_value=None)
            db.execute = Mock(return_value=_make_execute_result(scalar=tool_db, rowcount=1))
            db.delete = Mock(); db.commit = Mock(); db.rollback = Mock(); db.expire = Mock()
            tool_service._notify_tool_deleted = AsyncMock()
            await tool_service.delete_tool(db, "tool-1")
            mock_audit.log_action.assert_called_once()
            _assert_no_db_passed(mock_audit, expected_action="delete_tool", resource_type="tool")
