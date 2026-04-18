"""MCP utility compliance tests — progress notifications and cancellation."""

from __future__ import annotations

import asyncio

import pytest
from fastmcp.client import Client

from ._helpers import resolve_tool, xfail_on

pytestmark = [pytest.mark.protocol_compliance, pytest.mark.mcp_utilities]


async def test_progress_notifications_delivered(connect, request) -> None:
    """progress_reporter tool emits progress events observable on the client."""
    xfail_on(
        request,
        "gateway_proxy",
        "gateway_virtual",
        reason="GAP-002: gateway omits progress notifications (see #4205)",
    )
    events: list[tuple[float, float | None, str | None]] = []

    async def on_progress(progress, total, message):
        events.append((progress, total, message))

    async with connect(progress_handler=on_progress) as client:
        name = await resolve_tool(client, "progress_reporter")
        if name is None:
            pytest.skip("progress_reporter tool not advertised on this target")
        result = await client.call_tool_mcp(name=name, arguments={"total_steps": 3})
    assert result.isError is False
    assert len(events) >= 3, f"expected >=3 progress events, got {events}"


async def test_long_running_tool_is_cancellable(connect, request) -> None:
    """A long-running tool call can be cancelled via asyncio.wait_for."""
    xfail_on(
        request,
        "gateway_proxy",
        "gateway_virtual",
        reason="GAP-008: gateway federation drops `long_running` (among other tools)",
    )
    async with connect() as client:
        name = await resolve_tool(client, "long_running")
        assert name is not None, "long_running tool missing on reference target (unexpected)"
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                client.call_tool_mcp(name=name, arguments={"duration_seconds": 10.0}),
                timeout=0.3,
            )


async def test_ping_via_connect(connect) -> None:
    """Ping roundtrips against any target; doubles as a connect-fixture smoke."""
    async with connect() as client:
        await client.ping()
