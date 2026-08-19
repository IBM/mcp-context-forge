# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_api_debug.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for credential-free unified debugger history.
"""

# Standard
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# Third-Party
from fastapi import HTTPException
import pytest
from sqlalchemy import select
from starlette.requests import Request

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import APIDebugHistory, ToolMetric
from mcpgateway.db import Tool as DbTool
from mcpgateway.routers import api_debug
from mcpgateway.schemas import APIDebugInvokeRequest, ToolResult
from mcpgateway.services.tool_service import TextContent


def test_redact_masks_credentials_and_bounds_nested_preview():
    preview = api_debug._redact(  # pylint: disable=protected-access
        {
            "authorization": "Bearer value",
            "nested": {"api_key": "value", "safe": "visible"},
            "items": list(range(150)),
            "long": "x" * 600,
        }
    )

    assert preview["authorization"] == "********"
    assert preview["nested"] == {"api_key": "********", "safe": "visible"}
    assert len(preview["items"]) == 100
    assert preview["long"].endswith("…")


def test_history_is_bounded_per_owner_and_expires(test_db, monkeypatch):
    @contextmanager
    def use_test_session():
        try:
            yield test_db
            test_db.commit()
        except Exception:
            test_db.rollback()
            raise

    monkeypatch.setattr(api_debug, "fresh_db_session", use_test_session)
    monkeypatch.setattr(settings, "mcpgateway_api_debug_max_history", 2)
    monkeypatch.setattr(settings, "mcpgateway_api_debug_retention_days", 7)
    test_db.add(
        APIDebugHistory(
            owner_email="owner@example.com",
            protocol="REST",
            request_preview={},
            result_metadata={},
            is_success=True,
            created_at=datetime.now(timezone.utc) - timedelta(days=8),
        )
    )
    test_db.commit()

    for index in range(3):
        api_debug._record_history(  # pylint: disable=protected-access
            "owner@example.com",
            None,
            "SQL",
            {"arguments": {"index": index}, "headers": {"authorization": "********"}},
            {"content_items": 1},
            1.0,
            "OK",
            None,
            True,
        )

    rows = list(test_db.execute(select(APIDebugHistory).where(APIDebugHistory.owner_email == "owner@example.com").order_by(APIDebugHistory.created_at.desc())).scalars())
    assert len(rows) == 2
    assert [row.request_preview["arguments"]["index"] for row in rows] == [2, 1]
    assert all("response" not in row.result_metadata for row in rows)


def test_history_persistence_is_best_effort(monkeypatch):
    @contextmanager
    def broken_session():
        raise RuntimeError("database unavailable")
        yield  # pragma: no cover

    monkeypatch.setattr(api_debug, "fresh_db_session", broken_session)

    api_debug._record_history(  # pylint: disable=protected-access
        "owner@example.com",
        "tool-1",
        "REST",
        {},
        {},
        1.0,
        "OK",
        None,
        True,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("protocol", "expected_metadata"),
    [
        ("REST", None),
        ("gRPC", {"grpc_metadata": {"x-tenant": "alpha"}, "capture_grpc_call_metadata": True}),
    ],
)
async def test_invoke_forwards_deadline_and_keeps_grpc_metadata_protocol_scoped(monkeypatch, protocol, expected_metadata):
    monkeypatch.setattr(settings, "mcpgateway_api_debug_enabled", True)
    monkeypatch.setattr(api_debug, "get_token_teams_from_request", lambda _request: ["team-1"])
    monkeypatch.setattr(api_debug, "_record_history", MagicMock())
    invoke_tool = AsyncMock(return_value=ToolResult(content=[TextContent(type="text", text='{"ok":true}')]))
    monkeypatch.setattr(api_debug.tool_service, "invoke_tool", invoke_tool)
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = SimpleNamespace(id="tool-1", name="debug-tool", integration_type=protocol)
    request = Request({"type": "http", "method": "POST", "path": "/admin/debug/invoke", "headers": []})
    payload = APIDebugInvokeRequest(
        tool_id="tool-1",
        arguments={"name": "Ada"},
        headers={"x-request-id": "request-1"},
        metadata={"x-tenant": "alpha"},
        deadline_seconds=2.5,
    )

    response = await api_debug._invoke(payload, request, db, {"email": "owner@example.com"})  # pylint: disable=protected-access

    assert response["status_code"] == "OK"
    call = invoke_tool.await_args
    assert call.kwargs["timeout_override"] == 2.5
    assert call.kwargs["meta_data"] == expected_metadata
    assert call.kwargs["token_teams"] == ["team-1"]


@pytest.mark.asyncio
async def test_invoke_hides_tools_outside_token_scope(monkeypatch):
    monkeypatch.setattr(settings, "mcpgateway_api_debug_enabled", True)
    monkeypatch.setattr(api_debug, "get_token_teams_from_request", lambda _request: [])
    invoke_tool = AsyncMock()
    monkeypatch.setattr(api_debug.tool_service, "invoke_tool", invoke_tool)
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = None
    request = Request({"type": "http", "method": "POST", "path": "/admin/debug/invoke", "headers": []})

    with pytest.raises(HTTPException) as exc_info:
        await api_debug._invoke(APIDebugInvokeRequest(tool_id="private-tool"), request, db, {"email": "other@example.com"})  # pylint: disable=protected-access

    assert exc_info.value.status_code == 404
    invoke_tool.assert_not_awaited()


@pytest.mark.asyncio
async def test_stats_exclude_metrics_for_tools_outside_token_scope(test_db, monkeypatch):
    monkeypatch.setattr(settings, "mcpgateway_api_debug_enabled", True)
    tool = DbTool(
        original_name="private-tool",
        custom_name="private-tool",
        custom_name_slug="private-tool",
        display_name="Private Tool",
        url="https://example.com/tool",
        original_description="private",
        description="private",
        integration_type="REST",
        input_schema={"type": "object"},
        annotations={},
        created_by="owner@example.com",
        owner_email="owner@example.com",
        visibility="private",
    )
    test_db.add(tool)
    test_db.flush()
    test_db.add(ToolMetric(tool_id=tool.id, response_time=0.1, is_success=True, protocol="REST", status_code="OK"))
    test_db.commit()
    request = Request({"type": "http", "method": "GET", "path": "/admin/debug/stats", "headers": []})
    request.state.token_teams = []

    hidden = await api_debug.api_call_stats.__wrapped__(request, db=test_db, user={"email": "other@example.com"})
    owner_public_only = await api_debug.api_call_stats.__wrapped__(request, db=test_db, user={"email": "owner@example.com"})
    request.state.token_teams = ["team-1"]
    visible = await api_debug.api_call_stats.__wrapped__(request, db=test_db, user={"email": "owner@example.com"})

    assert hidden["total_calls"] == 0
    assert owner_public_only["total_calls"] == 0
    assert visible["total_calls"] == 1


@pytest.mark.asyncio
async def test_history_respects_retention_cutoff(test_db, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from unittest.mock import MagicMock

    email = "hist-retention@example.com"
    monkeypatch.setattr(api_debug, "get_current_user_with_permissions", MagicMock())
    monkeypatch.setattr(api_debug, "get_user_email", lambda _u: email)
    monkeypatch.setattr(settings, "mcpgateway_api_debug_enabled", True)
    monkeypatch.setattr(settings, "mcpgateway_api_debug_max_history", 10)
    monkeypatch.setattr(settings, "mcpgateway_api_debug_retention_days", 7)
    now = datetime.now(timezone.utc)
    test_db.add(APIDebugHistory(
        owner_email=email, protocol="REST",
        request_preview={}, result_metadata={}, is_success=True,
        created_at=now - timedelta(days=8),
    ))
    test_db.add(APIDebugHistory(
        owner_email=email, protocol="REST",
        request_preview={}, result_metadata={}, is_success=True,
        created_at=now,
    ))
    test_db.commit()

    items = await api_debug.debug_history(db=test_db, user={"email": email})
    assert len(items) == 1
    assert items[0].created_at.date() == now.date()


@pytest.mark.asyncio
async def test_stats_includes_debug_breakdown(test_db, monkeypatch):
    monkeypatch.setattr(settings, "mcpgateway_api_debug_enabled", True)
    tool = DbTool(
        original_name="metric-tool-debug", custom_name="metric-tool-debug",
        custom_name_slug="metric-tool-debug", display_name="Metric Tool Debug",
        url="https://example.com/tool", original_description="desc",
        description="desc", integration_type="REST",
        input_schema={"type": "object"}, annotations={},
        created_by="breakdown@example.com", owner_email="breakdown@example.com",
        visibility="private",
    )
    test_db.add(tool)
    test_db.flush()
    test_db.add(ToolMetric(tool_id=tool.id, response_time=0.1, is_success=True, protocol="REST", status_code="OK", is_debug=True))
    test_db.add(ToolMetric(tool_id=tool.id, response_time=0.2, is_success=True, protocol="REST", status_code="OK", is_debug=False))
    test_db.commit()
    from starlette.requests import Request
    request = Request({"type": "http", "method": "GET", "path": "/admin/debug/stats", "headers": []})
    request.state.token_teams = ["*"]

    stats = await api_debug.api_call_stats.__wrapped__(request, db=test_db, user={"email": "breakdown@example.com"})
    assert stats["total_calls"] == 2
    assert stats["debug_distribution"] == {"debug": 1, "regular": 1}


@pytest.mark.asyncio
async def test_stats_filter_is_debug_flag(test_db, monkeypatch):
    monkeypatch.setattr(settings, "mcpgateway_api_debug_enabled", True)
    tool = DbTool(
        original_name="filter-tool-dbg", custom_name="filter-tool-dbg",
        custom_name_slug="filter-tool-dbg", display_name="Filter Tool Dbg",
        url="https://example.com/tool", original_description="desc",
        description="desc", integration_type="REST",
        input_schema={"type": "object"}, annotations={},
        created_by="flagfilter@example.com", owner_email="flagfilter@example.com",
        visibility="private",
    )
    test_db.add(tool)
    test_db.flush()
    test_db.add(ToolMetric(tool_id=tool.id, response_time=0.1, is_success=True, protocol="REST", status_code="OK", is_debug=True))
    test_db.add(ToolMetric(tool_id=tool.id, response_time=0.2, is_success=True, protocol="REST", status_code="OK", is_debug=False))
    test_db.commit()
    from starlette.requests import Request
    request = Request({"type": "http", "method": "GET", "path": "/admin/debug/stats", "headers": []})
    request.state.token_teams = ["*"]

    debug_only = await api_debug.api_call_stats.__wrapped__(request, db=test_db, user={"email": "flagfilter@example.com"}, is_debug=True)
    regular_only = await api_debug.api_call_stats.__wrapped__(request, db=test_db, user={"email": "flagfilter@example.com"}, is_debug=False)
    assert debug_only["total_calls"] == 1
    assert regular_only["total_calls"] == 1
