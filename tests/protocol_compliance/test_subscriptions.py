# -*- coding: utf-8 -*-
"""Location: ./tests/protocol_compliance/test_subscriptions.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Resource subscription compliance tests.

MCP 2025-11-25 § Server / Resources specifies:
- ``resources/subscribe`` registers interest in a specific URI.
- The server MUST emit ``notifications/resources/updated`` with that URI
  to every subscriber when the resource changes.
- ``resources/unsubscribe`` cancels the registration.

The reference server exposes a mutable ``reference://mutable/counter``
resource and a ``bump_subscribable`` tool that increments it + sends the
updated-notification. These tests subscribe, bump, and assert the
notification lands at the client's message handler within a short
window.
"""

from __future__ import annotations

import asyncio

import pytest
from fastmcp.client import Client

from .helpers.compliance import resolve_tool, xfail_on

pytestmark = [pytest.mark.protocol_compliance, pytest.mark.mcp_server_features]


_SUBSCRIBABLE_URI = "reference://mutable/counter"


def _extract_resource_updated_uri(msg) -> str | None:
    """Return the URI from a ResourceUpdatedNotification, or None otherwise."""
    root = getattr(msg, "root", None) or msg
    method = getattr(root, "method", None)
    if method != "notifications/resources/updated":
        return None
    params = getattr(root, "params", None)
    if params is None:
        return None
    return str(getattr(params, "uri", "")) or None


async def test_resources_updated_notification_delivered_to_subscriber(connect, request) -> None:
    """After subscribe + bump, the client's message_handler observes the notification.

    Skipped / xfailed against gateway targets until the gateway relays
    server→client subscription notifications (tracked via the #4205 family
    of gaps — the GET-stream channel is required for this delivery path).
    """
    xfail_on(
        request,
        "gateway_proxy",
        "gateway_virtual",
        reason=("GAP-011: subscription updates require the server→client SSE channel " "that the gateway currently closes (405 on GET /mcp/); see #4205."),
    )

    observed_uris: list[str] = []

    async def msg_handler(msg):
        uri = _extract_resource_updated_uri(msg)
        if uri is not None:
            observed_uris.append(uri)

    async with connect(message_handler=msg_handler) as client:
        tool = await resolve_tool(client, "bump_subscribable")
        if tool is None:
            pytest.skip("bump_subscribable not advertised on this target")
        await client.session.subscribe_resource(_SUBSCRIBABLE_URI)
        await client.call_tool_mcp(name=tool, arguments={})
        # Notification is fire-and-forget; give the transport a beat to deliver.
        await asyncio.sleep(0.2)

    assert _SUBSCRIBABLE_URI in observed_uris, f"expected a resources/updated notification for {_SUBSCRIBABLE_URI!r} " f"after bump_subscribable; observed: {observed_uris}"


async def test_subscribe_unsubscribe_roundtrip(connect) -> None:
    """``resources/subscribe`` + ``resources/unsubscribe`` are accepted cleanly.

    This is the wire-level roundtrip assertion; notification delivery is
    tested separately (and xfailed on gateway targets where the
    server→client stream is currently unavailable — see the first test).

    The MCP spec around whether a server MUST stop sending updates after
    unsubscribe is a SHOULD (per-session filtering), not a MUST — most
    server implementations broadcast to every active session. This test
    asserts only what's strictly required: the subscribe+unsubscribe
    roundtrip succeeds without an McpError.
    """
    async with connect() as client:
        await client.session.subscribe_resource(_SUBSCRIBABLE_URI)
        await client.session.unsubscribe_resource(_SUBSCRIBABLE_URI)
