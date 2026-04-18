"""MCP tools capability compliance tests."""

from __future__ import annotations

import pytest
from fastmcp.client import Client

from ._helpers import resolve_tool, xfail_on

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
