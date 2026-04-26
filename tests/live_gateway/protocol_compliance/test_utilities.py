# -*- coding: utf-8 -*-
"""Location: ./tests/protocol_compliance/test_utilities.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

MCP utility compliance tests — progress notifications and cancellation.
"""

from __future__ import annotations

import asyncio
import contextlib

import pytest
from fastmcp.client import Client

from .helpers.compliance import resolve_tool, xfail_on

pytestmark = [pytest.mark.protocol_compliance, pytest.mark.mcp_utilities]


async def test_progress_notifications_delivered(connect, request) -> None:
    """progress_reporter tool emits progress events observable on the client."""
    xfail_on(
        request,
        "gateway_proxy",
        "gateway_virtual",
        reason=("GAP-002: gateway does not relay progress notifications on the " "POST-correlated stream of the originating tool call (spec § " "Listening for Messages from the Server)."),
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


async def test_cancellation_notification_reaches_server(connect, request) -> None:
    """An explicit ``notifications/cancelled`` must cause the server to abort the call.

    Spec (basic/utilities/cancellation) says the client SHOULD emit the
    notification when it no longer wants the request's result; the server
    SHOULD stop processing. The reference server's ``long_running`` tool
    catches ``asyncio.CancelledError`` and increments a process-wide
    counter exposed by ``get_cancellation_count``. If the notification is
    delivered end-to-end, the counter increments. If the client emits
    cancelled but the server never sees it (or sees it too late), the
    counter stays flat.

    Note: FastMCP's ``asyncio.wait_for`` timeout path does **not** auto-
    send ``notifications/cancelled`` in the current release — we instead
    use ``client.cancel(request_id)`` explicitly with the in-flight
    request id, so the test asserts the server-side contract rather than
    the client library's quirk. ``test_long_running_tool_is_cancellable``
    (above) still covers the client-side timeout path.
    """
    xfail_on(
        request,
        "gateway_proxy",
        "gateway_virtual",
        reason=(
            "GAP-008: gateway federation drops `long_running`, so the trigger is "
            "unreachable. Even with federation fixed, the notification would need "
            "relay on the POST-correlated stream (same shape as GAP-001/002)."
        ),
    )

    async with connect() as client:
        counter_tool = await resolve_tool(client, "get_cancellation_count")
        long_running_tool = await resolve_tool(client, "long_running")
        assert counter_tool is not None and long_running_tool is not None, "expected cancellation tools on reference target"

        before = await client.call_tool_mcp(name=counter_tool, arguments={})
        before_count = _extract_int_result(before)

        call_task = asyncio.create_task(client.call_tool_mcp(name=long_running_tool, arguments={"duration_seconds": 10.0}))
        # Wait briefly for the request to be dispatched so its id is
        # registered in the session's pending table. 100 ms is generous
        # for in-process + live HTTP alike.
        await asyncio.sleep(0.1)
        pending = list(client.session._response_streams.keys())  # type: ignore[attr-defined]
        assert pending, "no pending request registered after dispatching long_running"
        in_flight_id = pending[-1]

        await client.cancel(in_flight_id, reason="compliance-probe")

        # The task should now resolve (with an error or cancellation).
        with contextlib.suppress(Exception):
            await asyncio.wait_for(call_task, timeout=3.0)

        after = await client.call_tool_mcp(name=counter_tool, arguments={})
        after_count = _extract_int_result(after)

    assert after_count == before_count + 1, (
        f"expected cancellation counter to increment from {before_count} to " f"{before_count + 1}, got {after_count}. notifications/cancelled " f"did not reach the server."
    )


def _extract_int_result(result) -> int:
    """Pull an integer out of a FastMCP tool-call result."""
    if not result.content:
        raise AssertionError(f"empty tool-call result: {result}")
    text = result.content[0].text
    try:
        return int(text)
    except (TypeError, ValueError) as exc:
        raise AssertionError(f"expected integer in tool result, got {text!r}") from exc
