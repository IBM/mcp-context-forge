# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_python_mcp_ingress.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Regression tests for the mounted Python ingress and trusted affinity dispatch.
"""

# Standard
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import httpx
import orjson
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

# First-Party
from mcpgateway import main
from mcpgateway.auth_context import encode_internal_mcp_auth_context
from mcpgateway.db import Base, Tool
from mcpgateway.services import tool_service as tool_module
from mcpgateway.transports import streamablehttp_transport as transport
from mcpgateway.utils.internal_http import post_rpc_in_process


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "origin,host,client,forwarded,affinity,status",
    [
        ("https://denied.example", "allowed.example", "192.0.2.1", False, False, 403),
        ("https://allowed.example", "denied.example", "192.0.2.1", False, False, 403),
        ("https://allowed.example", "allowed.example", "192.0.2.1", False, False, 204),
        ("https://denied.example", "denied.example", "127.0.0.1", True, True, 204),
        ("https://denied.example", "denied.example", "127.0.0.1", True, False, 403),
        ("https://denied.example", "denied.example", "192.0.2.1", True, True, 403),
    ],
)
async def test_registered_mcp_mount_enforces_origin_and_host(monkeypatch, origin, host, client, forwarded, affinity, status):
    """The registered mount rejects invalid public headers before transport dispatch."""
    monkeypatch.setattr(transport.settings, "mcp_allowed_origins", ["https://allowed.example"])
    monkeypatch.setattr(transport.settings, "mcp_allowed_hosts", ["allowed.example"])
    monkeypatch.setattr(transport.settings, "mcpgateway_session_affinity_enabled", affinity)
    downstream = AsyncMock()

    async def respond(scope, receive, send):
        """Return a sentinel response when dispatch reaches the transport."""
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    downstream.side_effect = respond
    monkeypatch.setattr(main.streamable_http_session, "handle_streamable_http", downstream)
    mount = next(route for route in main.app.routes if getattr(route, "path", None) == "/mcp")
    headers = {"origin": origin, "host": host}
    if forwarded:
        headers["x-forwarded-internally"] = "true"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=mount.app, client=(client, 1234)), base_url="http://allowed.example") as caller:
        response = await caller.post("/mcp", headers=headers)
    assert response.status_code == status
    assert downstream.await_count == (1 if status == 204 else 0)


@pytest.fixture
def affinity_application(monkeypatch):
    """Keep application routing and trust checks real while isolating persistence."""
    monkeypatch.setattr(main.settings, "mcpgateway_session_affinity_enabled", True)
    monkeypatch.setattr(main.settings, "use_stateful_sessions", False)
    db = MagicMock()
    monkeypatch.setattr(main, "SessionLocal", lambda: db)
    return db


def _context(**overrides):
    """Encode an authenticated, team-scoped edge identity."""
    context = {"email": "member@example.com", "teams": ["team-a"], "is_authenticated": True, "is_admin": False, "permission_is_admin": False}
    context.update(overrides)
    return encode_internal_mcp_auth_context(context)


@pytest.mark.asyncio
async def test_real_affinity_helper_reaches_application(affinity_application):
    """Real helper trust headers allow a harmless RPC through the receiving application."""
    response = await post_rpc_in_process(
        content=orjson.dumps({"jsonrpc": "2.0", "method": "ping", "id": 1}),
        headers={"x-forwarded-internally": "true"},
        timeout=5,
        auth_context=_context(),
    )
    assert response.status_code == 200
    assert response.json() == {"jsonrpc": "2.0", "result": {}, "id": 1}


@pytest.mark.asyncio
@pytest.mark.parametrize("signature", [None, "forged"])
async def test_receiving_application_rejects_invalid_hmac(monkeypatch, affinity_application, signature):
    """Invalid runtime authentication cannot reach protected tool execution."""
    execute = AsyncMock()
    monkeypatch.setattr(main, "_execute_rpc_tools_call", execute)
    headers = {"x-contextforge-mcp-runtime": "affinity", "x-contextforge-auth-context": _context(), "x-forwarded-internally": "true"}
    if signature is not None:
        headers["x-contextforge-mcp-runtime-auth"] = signature
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app, client=("127.0.0.1", 0)), base_url="http://localhost") as caller:
        response = await caller.post("/_internal/mcp/rpc", headers=headers, json={"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "protected"}, "id": 1})
    assert response.status_code in (401, 403)
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_real_affinity_dispatch_enforces_permission_scope(monkeypatch, affinity_application):
    """An authenticated read-only context cannot execute tools through real internal dispatch."""
    execute = AsyncMock()
    monkeypatch.setattr(main, "_execute_rpc_tools_call", execute)
    response = await post_rpc_in_process(
        content=orjson.dumps({"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "protected"}, "id": 1}),
        headers={"x-forwarded-internally": "true"},
        timeout=5,
        auth_context=_context(scoped_permissions=["tools.read"]),
    )
    assert response.json()["error"]["code"] == -32003
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_real_affinity_dispatch_preserves_identity_and_team_scope(monkeypatch, affinity_application):
    """Real application dispatch retains the edge identity and team scope."""
    execute = AsyncMock(return_value={"content": []})
    monkeypatch.setattr(main, "_execute_rpc_tools_call", execute)
    monkeypatch.setattr(main.PermissionChecker, "has_permission", AsyncMock(return_value=True))
    response = await post_rpc_in_process(
        content=orjson.dumps({"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "protected"}, "id": 1}),
        headers={"x-forwarded-internally": "true"},
        timeout=5,
        auth_context=_context(scoped_permissions=["tools.execute"]),
    )
    assert "result" in response.json()
    request, _, user = execute.await_args.args
    assert user["email"] == "member@example.com"
    assert request.state.token_teams == ["team-a"]


@pytest.mark.asyncio
async def test_real_affinity_dispatch_enforces_rbac(monkeypatch, affinity_application):
    """RBAC denial stops execution even when token permissions allow tools.execute."""
    execute = AsyncMock()
    monkeypatch.setattr(main, "_execute_rpc_tools_call", execute)
    checker = AsyncMock(return_value=False)
    monkeypatch.setattr(main.PermissionChecker, "has_permission", checker)
    response = await post_rpc_in_process(
        content=orjson.dumps({"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "protected"}, "id": 1}),
        headers={"x-forwarded-internally": "true"},
        timeout=5,
        auth_context=_context(scoped_permissions=["tools.execute"]),
    )
    assert response.json()["error"]["code"] == -32003
    checker.assert_awaited_once()
    execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "context",
    [
        {"teams": ["team-b"]},
        {"email": None, "teams": [], "is_authenticated": False},
    ],
)
async def test_real_affinity_dispatch_denies_nonvisible_tool(monkeypatch, affinity_application, context):
    """Wrong-team and public-only contexts cannot execute a team tool through real dispatch."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(
            Tool(
                id="affinity-protected",
                name="affinity-protected",
                original_name="affinity-protected",
                url="http://example.com/tool",
                integration_type="REST",
                request_type="POST",
                input_schema={"type": "object"},
                visibility="team",
                team_id="team-a",
                owner_email="owner@example.com",
                reachable=True,
            )
        )
        db.commit()
        monkeypatch.setattr(main, "SessionLocal", lambda: db)
        monkeypatch.setattr(main.settings, "mcpgateway_tool_cancellation_enabled", False)
        monkeypatch.setattr(main.PermissionChecker, "has_permission", AsyncMock(return_value=True))
        cache = MagicMock()
        cache.get = AsyncMock(return_value=None)
        cache.get_negative = AsyncMock(return_value=None)
        monkeypatch.setattr(tool_module, "_get_tool_lookup_cache", lambda: cache)
        outbound = MagicMock(side_effect=AssertionError("Protected tool reached HTTP dispatch"))
        monkeypatch.setattr(tool_module, "_build_pinned_rest_http_client", outbound)
        response = await post_rpc_in_process(
            content=orjson.dumps({"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "affinity-protected"}, "id": 1}),
            headers={"x-forwarded-internally": "true"},
            timeout=5,
            auth_context=_context(**context),
        )
        assert response.json()["error"]["code"] == -32601
        outbound.assert_not_called()
    engine.dispose()


@pytest.mark.asyncio
async def test_real_affinity_dispatch_accepts_public_only_context(monkeypatch, affinity_application):
    """Validated public-only context retains its restricted visibility through the helper."""
    monkeypatch.setattr(main.settings, "mcp_require_auth", False)
    execute = AsyncMock(return_value={"content": []})
    monkeypatch.setattr(main, "_execute_rpc_tools_call", execute)
    response = await post_rpc_in_process(
        content=orjson.dumps({"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "public-tool"}, "id": 1}),
        headers={"x-forwarded-internally": "true"},
        timeout=5,
        auth_context=_context(email=None, teams=[], is_authenticated=False),
    )
    assert "result" in response.json()
    request, _, user = execute.await_args.args
    assert user["email"] is None
    assert request.state.token_teams == []


@pytest.mark.asyncio
async def test_public_application_requires_authentication(monkeypatch):
    """Public MCP requests without authentication stop before transport dispatch."""
    monkeypatch.setattr(main.settings, "mcp_require_auth", True)
    downstream = AsyncMock()
    monkeypatch.setattr(main.streamable_http_session, "handle_streamable_http", downstream)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://localhost") as caller:
        response = await caller.post("/mcp/", json={"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "protected"}, "id": 1})
    assert response.status_code == 401
    downstream.assert_not_awaited()


@pytest.mark.asyncio
async def test_public_application_requires_server_oauth_when_global_auth_disabled(monkeypatch):
    """An OAuth-enabled server rejects anonymous requests before mounted transport dispatch."""
    monkeypatch.setattr(main.settings, "mcp_require_auth", False)
    downstream = AsyncMock()
    monkeypatch.setattr(main.streamable_http_session, "handle_streamable_http", downstream)
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value.oauth_enabled = True

    @asynccontextmanager
    async def server_db():
        """Return the OAuth-enabled server from isolated persistence."""
        yield db

    monkeypatch.setattr(transport, "get_db", server_db)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://localhost") as caller:
        response = await caller.post("/servers/abc123/mcp/", json={"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "protected"}, "id": 1})
    assert response.status_code == 401
    assert "resource_metadata" in response.headers["www-authenticate"]
    downstream.assert_not_awaited()
