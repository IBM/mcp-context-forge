# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_internal_runtime_trust.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Regression tests for the Python affinity trust boundary.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock

# Third-Party
from fastapi import HTTPException
import orjson
import pytest
from starlette.requests import Request

# First-Party
from mcpgateway.auth_context import _expected_internal_mcp_runtime_auth_header, encode_internal_mcp_auth_context, is_trusted_internal_mcp_request


def _req(path="/_internal/mcp/rpc", *, marker="affinity", hmac="valid", ctx="ctx", client="127.0.0.1", extra=None):
    """Build an internal request with independent trust gates."""
    headers = []
    if marker is not None:
        headers.append((b"x-contextforge-mcp-runtime", marker.encode()))
    if hmac is not None:
        signature = _expected_internal_mcp_runtime_auth_header() if hmac == "valid" else hmac
        headers.append((b"x-contextforge-mcp-runtime-auth", signature.encode()))
    if ctx is not None:
        headers.append((b"x-contextforge-auth-context", ctx.encode()))
    headers.extend(extra or [])
    return Request({"type": "http", "method": "POST", "path": path, "query_string": b"", "headers": headers, "client": (client, 12345) if client else None})


@pytest.mark.parametrize("path", ["/_internal/mcp/rpc", "/_internal/mcp/rpc/"])
@pytest.mark.parametrize("client", ["127.0.0.1", "::1"])
def test_rpc_trusts_authenticated_affinity(path, client):
    """Both loopback families accept the retained affinity route."""
    assert is_trusted_internal_mcp_request(_req(path, client=client)) is True


@pytest.mark.parametrize(
    "overrides",
    [
        {"marker": None, "hmac": None, "ctx": None},
        {"marker": "rust"},
        {"marker": "bogus"},
        {"hmac": None},
        {"hmac": "forged"},
        {"ctx": None},
        {"ctx": ""},
        {"client": "10.0.0.9"},
        {"client": None},
        {"hmac": "forged", "extra": [(b"x-forwarded-for", b"127.0.0.1")]},
    ],
)
@pytest.mark.asyncio
async def test_untrusted_rpc_cannot_reach_dispatch(monkeypatch, overrides):
    """Each failed gate rejects dispatch before database access or execution."""
    # First-Party
    from mcpgateway import main

    db_factory = MagicMock()
    dispatch = AsyncMock()
    monkeypatch.setattr(main, "SessionLocal", db_factory)
    monkeypatch.setattr(main, "_handle_rpc_authenticated", dispatch)
    request = _req(**overrides)
    assert is_trusted_internal_mcp_request(request) is False
    with pytest.raises(HTTPException) as exc:
        await main.handle_internal_mcp_rpc(request)
    assert exc.value.status_code == 403
    db_factory.assert_not_called()
    dispatch.assert_not_awaited()


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("path", ["/_internal/mcp/authenticate", "/_internal/mcp/initialize", "/_internal/mcp/rpc/extra", "/_internal/a2a/authenticate", "/_internal/a2a/tasks/get", "/rpc"])
def test_sidecar_paths_never_gain_internal_trust(monkeypatch, enabled, path):
    """Removed routes gain no trust even with valid affinity headers and A2A enabled."""
    monkeypatch.setattr("mcpgateway.auth_context.settings.mcpgateway_a2a_enabled", enabled)
    assert is_trusted_internal_mcp_request(_req(path)) is False


def test_only_affinity_rpc_routes_remain():
    """The application exposes no retired internal MCP or A2A handler."""
    # First-Party
    from mcpgateway.main import utility_router

    paths = {route.path for route in utility_router.routes if route.path.startswith(("/_internal/mcp", "/_internal/a2a"))}
    assert paths == {"/_internal/mcp/rpc", "/_internal/mcp/rpc/"}


def test_token_scoping_trusts_affinity_with_normalized_path():
    """Token scoping accepts the same gate after removing a deployment root path."""
    # First-Party
    from mcpgateway.middleware.token_scoping import token_scoping_middleware

    req = _req("/gateway/_internal/mcp/rpc")
    assert token_scoping_middleware._is_trusted_internal_mcp_runtime_request(req, "/_internal/mcp/rpc") is True


@pytest.mark.asyncio
@pytest.mark.parametrize("denial", ["permission", "server_scope"])
async def test_affinity_preserves_authorization_denials(monkeypatch, denial):
    """Authenticated affinity calls retain token permissions and server restrictions."""
    # First-Party
    from mcpgateway import main

    context = {"email": "user@example.com", "teams": ["team-a"], "is_authenticated": True, "is_admin": False, "scoped_permissions": ["tools.read"]}
    if denial == "server_scope":
        context["scoped_server_id"] = "allowed-server"
    request = _req(ctx=encode_internal_mcp_auth_context(context))
    request.body = AsyncMock(return_value=orjson.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "protected", "server_id": "other-server"}}))
    db = MagicMock()
    invoke = AsyncMock()
    monkeypatch.setattr(main, "SessionLocal", lambda: db)
    monkeypatch.setattr(main.tool_service, "invoke_tool", invoke)
    response = await main.handle_internal_mcp_rpc(request)
    payload = orjson.loads(response.body) if hasattr(response, "body") else response
    assert payload["error"]["code"] == -32003
    invoke.assert_not_awaited()
    db.close.assert_called()


@pytest.mark.parametrize("header", ["forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-forwarded-port", "x-forwarded-prefix", "x-real-ip", "cf-connecting-ip", "true-client-ip"])
def test_loopback_passthrough_strips_forwarded_headers(header):
    """Client address headers cannot influence internal loopback dispatch."""
    # First-Party
    from mcpgateway.utils.passthrough_headers import filter_loopback_skip_headers

    out = filter_loopback_skip_headers({header: "1.2.3.4", "x-keep": "ok"})
    assert header not in {k.lower() for k in out}
    assert out.get("x-keep") == "ok"
