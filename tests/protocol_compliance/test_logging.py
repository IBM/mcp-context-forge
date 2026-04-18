"""MCP logging compliance tests — notifications/message delivery."""

from __future__ import annotations

import pytest

from .helpers.compliance import resolve_tool, xfail_on

pytestmark = [pytest.mark.protocol_compliance, pytest.mark.mcp_server_features]


async def test_log_message_reaches_client(connect, request) -> None:
    """log_at_level delivers a logging/message notification to the client."""
    xfail_on(
        request,
        "gateway_proxy",
        "gateway_virtual",
        reason="GAP-001: gateway omits server-initiated logging notifications (see #4205)",
    )
    received: list[tuple[str, str]] = []

    async def log_handler(msg):
        level = getattr(msg, "level", None) or msg.__dict__.get("level", "")
        data = getattr(msg, "data", None) or msg.__dict__.get("data", "")
        received.append((str(level), str(data)))

    async with connect(log_handler=log_handler) as client:
        name = await resolve_tool(client, "log_at_level")
        if name is None:
            pytest.skip("log_at_level tool not advertised on this target")
        result = await client.call_tool_mcp(name=name, arguments={"level": "warning", "message": "probe-log"})
    assert result.isError is False
    assert any("probe-log" in d for _, d in received), f"log data missing in {received}"
