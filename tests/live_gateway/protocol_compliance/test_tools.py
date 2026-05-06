# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/protocol_compliance/test_tools.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

MCP tools capability compliance tests.
"""

from __future__ import annotations

import pytest
from fastmcp.client import Client

from .helpers.compliance import resolve_tool, xfail_on

pytestmark = [pytest.mark.protocol_compliance, pytest.mark.mcp_server_features]


async def test_required_tools_advertised(client: Client) -> None:
    """At least echo + add must be advertised (boom is gateway-filtered on some targets)."""
    for bare in ("echo", "add"):
        if await resolve_tool(client, bare) is None:
            pytest.fail(f"required tool {bare!r} not advertised on this target")


async def test_echo_roundtrip(client: Client) -> None:
    name = await resolve_tool(client, "echo")
    if name is None:
        pytest.skip("echo tool not advertised on this target")
    result = await client.call_tool_mcp(name=name, arguments={"message": "ping"})
    assert result.isError is False
    assert "ping" in str(result.content)


async def test_add_returns_sum(client: Client) -> None:
    name = await resolve_tool(client, "add")
    if name is None:
        pytest.skip("add tool not advertised on this target")
    result = await client.call_tool_mcp(name=name, arguments={"a": 2, "b": 3})
    assert result.isError is False
    assert "5" in str(result.content)


async def test_tool_error_is_surfaced_as_is_error(client: Client, request) -> None:
    xfail_on(
        request,
        "gateway_proxy",
        "gateway_virtual",
        reason="GAP-008: gateway federation drops `boom` (among other tools)",
    )
    name = await resolve_tool(client, "boom")
    assert name is not None, "boom tool missing on reference target (unexpected)"
    result = await client.call_tool_mcp(name=name, arguments={})
    assert result.isError is True


async def test_add_rejects_non_numeric_arguments(client: Client) -> None:
    """`tools/call add` with wrong-typed arguments must surface an error.

    The reference server declares ``a: int, b: int`` on ``add``. A spec-
    compliant server must validate against the declared inputSchema and
    either (a) reject the call pre-dispatch with a JSON-RPC error or
    (b) dispatch, catch the body-level TypeError, and return
    ``isError=True``. Returning a successful content payload from
    wrong-typed args would mean the validator layer is bypassed.
    """
    name = await resolve_tool(client, "add")
    if name is None:
        pytest.skip("add tool not advertised on this target")
    # Pass strings where ints are expected. A spec-compliant server may
    # reject pre-dispatch via a JSON-RPC error (surfaced by FastMCP as
    # ``McpError``) or may dispatch and let the tool body's TypeError bubble
    # up to ``isError=True``. Either is acceptable. We narrow to those two
    # expected error families so a transport crash or an asyncio bug
    # doesn't masquerade as "validator rejected".
    from mcp.shared.exceptions import McpError

    try:
        result = await client.call_tool_mcp(name=name, arguments={"a": "not-an-int", "b": []})
    except McpError:
        # Raised at the JSON-RPC envelope layer — the validator rejected
        # before the tool body ran. That's the stricter, equally-spec-valid
        # path.
        return
    assert result.isError is True, f"tools/call must either raise McpError or return isError=True on " f"type-mismatched args; got successful result: {result.content}"
