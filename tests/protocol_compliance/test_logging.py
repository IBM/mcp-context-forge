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
        reason=(
            "GAP-001: log emitted during a tool call is a request-tied " "notification and should ride the POST-correlated stream of that " "call; gateway does not relay notifications on that stream."
        ),
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


async def test_logging_set_level_filters_below_threshold(connect, request) -> None:
    """Server honors `logging/setLevel` — messages below the threshold are filtered.

    Spec (server/utilities/logging § setLevel): the client MAY call
    `logging/setLevel` to specify the minimum severity it wants to
    receive. The server MUST only emit `notifications/message` at or
    above that level thereafter. A server that ignores the filter and
    floods the client with debug-level noise is a real regression this
    test pins.
    """
    xfail_on(
        request,
        "gateway_proxy",
        "gateway_virtual",
        reason=(
            "GAP-001: log emitted during a tool call is a request-tied " "notification and should ride the POST-correlated stream of that " "call; gateway does not relay notifications on that stream."
        ),
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

        # Raise the floor to "error" — subsequent info-level emits must be suppressed.
        await client.session.set_logging_level("error")
        await client.call_tool_mcp(name=name, arguments={"level": "info", "message": "filtered-info"})
        filtered_seen = any("filtered-info" in d for _, d in received)

        # Lower to "info" — the same level now comes through.
        received.clear()
        await client.session.set_logging_level("info")
        await client.call_tool_mcp(name=name, arguments={"level": "info", "message": "passed-info"})
        passed_seen = any("passed-info" in d for _, d in received)

    assert not filtered_seen, f"info-level log must be filtered after setLevel('error'); observed: {received}"
    assert passed_seen, f"info-level log must pass after setLevel('info'); observed: {received}"
