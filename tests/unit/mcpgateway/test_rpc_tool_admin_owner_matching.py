# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_rpc_tool_admin_owner_matching.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Regression tests for admin-bypass owner matching on RPC tool execution paths.
"""

# Standard
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import orjson
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway import main as main_mod


class FakeRequest:
    """Minimal request double for direct RPC handler tests."""

    def __init__(self, body: dict | None = None):
        self.body_value = orjson.dumps(body or {})
        self.headers: dict[str, str] = {}
        self.query_params: dict[str, str] = {}
        self.state = SimpleNamespace()

    async def body(self) -> bytes:
        """Return the encoded JSON-RPC body."""
        return self.body_value


@pytest.fixture
def mock_db():
    """Provide a database-session double."""
    return MagicMock(spec=Session)


def test_resolve_tool_execution_auth_context_preserves_admin_identity(
    monkeypatch,
):
    """Unrestricted admin bypass keeps the email for private-row owner matching."""
    request = FakeRequest()
    monkeypatch.setattr(
        main_mod,
        "get_rpc_filter_context",
        lambda _request, _user: ("admin@example.com", None, True),
    )

    assert main_mod._resolve_tool_execution_auth_context(request, {}) == (
        "admin@example.com",
        None,
        True,
    )


def test_resolve_tool_execution_auth_context_defaults_missing_teams_to_public(
    monkeypatch,
):
    """A non-admin with no team claim remains public-only."""
    request = FakeRequest()
    monkeypatch.setattr(
        main_mod,
        "get_rpc_filter_context",
        lambda _request, _user: ("user@example.com", None, False),
    )

    assert main_mod._resolve_tool_execution_auth_context(request, {}) == (
        "user@example.com",
        [],
        False,
    )


@pytest.mark.asyncio
async def test_execute_rpc_tools_call_keeps_admin_email_for_owner_matching(monkeypatch, mock_db):
    """The model-facing tools/call path passes the admin email to visibility."""
    request = FakeRequest({"name": "private-tool"})
    request.state.plugin_context_table = None
    request.state.plugin_global_context = None
    invoke_tool = AsyncMock(return_value={"content": []})

    monkeypatch.setattr(main_mod.settings, "mcpgateway_tool_cancellation_enabled", False)
    monkeypatch.setattr(
        main_mod,
        "get_rpc_filter_context",
        lambda _request, _user: ("admin@example.com", None, True),
    )
    monkeypatch.setattr(main_mod.tool_service, "invoke_tool", invoke_tool)

    await main_mod._execute_rpc_tools_call(
        request,
        mock_db,
        {"email": "admin@example.com"},
        req_id="call-1",
        params={"name": "private-tool", "arguments": {}},
        lowered_request_headers={},
        server_id=None,
    )

    assert invoke_tool.await_args.kwargs["app_user_email"] == "admin@example.com"
    assert invoke_tool.await_args.kwargs["user_email"] == "admin@example.com"
    assert invoke_tool.await_args.kwargs["token_teams"] is None
    assert invoke_tool.await_args.kwargs["require_model_visible"] is True


@pytest.mark.asyncio
async def test_internal_resolve_keeps_admin_email_for_owner_matching(monkeypatch, mock_db):
    """The Rust resolve path passes the admin email to visibility filtering."""
    request = FakeRequest(
        {
            "jsonrpc": "2.0",
            "id": "resolve-1",
            "method": "tools/call",
            "params": {"name": "private-tool", "arguments": {}},
        }
    )
    request.state.plugin_context_table = None
    request.state.plugin_global_context = None
    prepare = AsyncMock(return_value={"plan": {}})

    monkeypatch.setattr(main_mod, "SessionLocal", MagicMock(return_value=mock_db))
    monkeypatch.setattr(main_mod, "_build_internal_mcp_forwarded_user", lambda _request: {"email": "admin@example.com"})
    monkeypatch.setattr(main_mod, "get_internal_mcp_auth_context", lambda _request: None)
    monkeypatch.setattr(main_mod, "_ensure_rpc_permission", AsyncMock())
    monkeypatch.setattr(
        main_mod,
        "get_rpc_filter_context",
        lambda _request, _user: ("admin@example.com", None, True),
    )
    monkeypatch.setattr(main_mod.tool_service, "prepare_rust_mcp_tool_execution", prepare)

    await main_mod.handle_internal_mcp_tools_call_resolve(request)

    assert prepare.await_args.kwargs["app_user_email"] == "admin@example.com"
    assert prepare.await_args.kwargs["user_email"] == "admin@example.com"
    assert prepare.await_args.kwargs["token_teams"] is None
    assert prepare.await_args.kwargs["require_model_visible"] is True


@pytest.mark.asyncio
async def test_legacy_rpc_tool_keeps_admin_email_for_owner_matching(monkeypatch, mock_db):
    """The backward-compatible RPC tool branch also preserves owner identity."""
    request = FakeRequest(
        {
            "jsonrpc": "2.0",
            "id": "legacy-1",
            "method": "private-tool",
            "params": {},
        },
    )
    request.state.plugin_context_table = None
    request.state.plugin_global_context = None
    invoke_tool = AsyncMock(return_value={"content": []})

    monkeypatch.setattr(main_mod.settings, "use_stateful_sessions", False)
    monkeypatch.setattr(main_mod, "_maybe_forward_affinitized_rpc_request", AsyncMock(return_value=None))
    monkeypatch.setattr(main_mod, "_ensure_rpc_permission", AsyncMock())
    monkeypatch.setattr(main_mod, "get_internal_mcp_auth_context", lambda _request: None)
    monkeypatch.setattr(
        main_mod,
        "get_rpc_filter_context",
        lambda _request, _user: ("admin@example.com", None, True),
    )
    monkeypatch.setattr(main_mod.tool_service, "invoke_tool", invoke_tool)

    response = await main_mod._handle_rpc_authenticated(request, mock_db, {"email": "admin@example.com"})

    assert response == {
        "jsonrpc": "2.0",
        "result": {"content": []},
        "id": "legacy-1",
    }
    assert invoke_tool.await_args.kwargs["app_user_email"] == "admin@example.com"
    assert invoke_tool.await_args.kwargs["user_email"] == "admin@example.com"
    assert invoke_tool.await_args.kwargs["token_teams"] is None
    assert invoke_tool.await_args.kwargs["require_model_visible"] is True
