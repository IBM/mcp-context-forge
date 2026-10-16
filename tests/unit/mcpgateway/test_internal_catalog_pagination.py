# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_internal_catalog_pagination.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Verify internal catalog error mapping and bodyless Rust compatibility.
"""

# Standard
import json
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
from starlette.requests import Request

# First-Party
from mcpgateway.main import handle_internal_mcp_prompts_list, handle_internal_mcp_resource_templates_list, handle_internal_mcp_resources_list, handle_internal_mcp_tools_list
from mcpgateway.validation.jsonrpc import JSONRPCError

pytestmark = pytest.mark.asyncio


def _make_request(body):
    """Create an internal HTTP request with a JSON body.

    Args:
        body: JSON-RPC request object.

    Returns:
        Request mock with an asynchronous body reader.
    """
    request = MagicMock(spec=Request)
    request.body = AsyncMock(return_value=json.dumps(body).encode())
    return request


@pytest.mark.parametrize(
    "handler,method",
    [
        (handle_internal_mcp_tools_list, "tools/list"),
        (handle_internal_mcp_resources_list, "resources/list"),
        (handle_internal_mcp_resource_templates_list, "resources/templates/list"),
        (handle_internal_mcp_prompts_list, "prompts/list"),
    ],
)
@pytest.mark.parametrize("code,status", [(-32602, 400), (-32003, 403), (-32000, 503), (-32603, 500)])
async def test_internal_catalog_error_status(handler, method, code, status):
    """Distinguish invalid cursors, access denials, capacity, and configuration errors."""
    request = _make_request({"method": method, "params": {}})
    request.headers = {"x-contextforge-server-id": "srv-1", "x-contextforge-mcp-runtime": "rust"}
    with (
        patch("mcpgateway.main._build_internal_mcp_forwarded_user", return_value={"email": "user@example.com"}),
        patch("mcpgateway.main._enforce_internal_mcp_server_scope"),
        patch("mcpgateway.main.SessionLocal", return_value=MagicMock()),
        patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "user@example.com"})),
        patch("mcpgateway.main._catalog_page_for_request", new=AsyncMock(side_effect=JSONRPCError(code, "catalog error"))),
    ):
        response = await handler(request)
    assert response.status_code == status
    assert json.loads(response.body)["code"] == code


async def test_bodyless_rust_tools_bridge_returns_complete_catalog():
    """Keep tools complete when the Rust bridge cannot send client cursors."""
    request = _make_request({})
    request.body = AsyncMock(return_value=b"")
    request.headers = {"x-contextforge-server-id": "srv-1", "x-contextforge-mcp-runtime": "rust"}
    pages = [{"tools": [{"name": "first"}], "nextCursor": "cursor-1"}, {"tools": [{"name": "second"}], "nextCursor": "cursor-2"}, {"tools": [{"name": "third"}]}]
    with (
        patch("mcpgateway.main.SessionLocal", return_value=MagicMock()),
        patch("mcpgateway.main._authorize_internal_mcp_request", new=AsyncMock(return_value={"email": "user@example.com"})) as authorize,
        patch("mcpgateway.main._catalog_page_for_request", new=AsyncMock(side_effect=pages)) as catalog_page,
    ):
        response = await handle_internal_mcp_tools_list(request)
    assert response.status_code == 200
    assert json.loads(response.body) == {"tools": [{"name": "first"}, {"name": "second"}, {"name": "third"}]}
    authorize.assert_awaited_once()
    assert catalog_page.await_count == 3
    assert catalog_page.await_args_list[1].args[-1] == "cursor-1"
    assert catalog_page.await_args_list[2].args[-1] == "cursor-2"
