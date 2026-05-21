# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/protocol_compliance/test_notifications.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

MCP notification compliance tests — tools/list_changed and resources/updated.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from .helpers.compliance import resolve_tool, xfail_on

pytestmark = [pytest.mark.protocol_compliance, pytest.mark.mcp_utilities]


def _notification_method(msg) -> str | None:
    """Extract ``method`` from a ServerNotification wrapper."""
    root = getattr(msg, "root", None) or msg
    return getattr(root, "method", None)


async def test_tools_list_changed_notification_delivered(connect, request) -> None:
    """Adding a tool at runtime fires ``notifications/tools/list_changed``.

    Observes the notification directly via the client's message_handler
    (not via state polling), so this asserts the wire-level fire, not
    just the side effect.
    """
    xfail_on(
        request,
        "gateway_proxy",
        "gateway_virtual",
        reason=(
            "GAP-008: gateway federation drops `mutate_tool_list`, so the trigger is "
            "unreachable. Even with federation fixed, the list_changed notification "
            "would still be blocked by the same POST-correlated-stream "
            "notification-relay issue tracked in GAP-001/GAP-002."
        ),
    )
    observed_methods: list[str] = []

    async def msg_handler(msg):
        method = _notification_method(msg)
        if method:
            observed_methods.append(method)

    async with connect(message_handler=msg_handler) as client:
        name = await resolve_tool(client, "mutate_tool_list")
        assert name is not None, "mutate_tool_list missing on reference target (unexpected)"
        await client.call_tool_mcp(name=name, arguments={})
        # Notification is fire-and-forget — give the transport a beat.
        await asyncio.sleep(0.2)

    assert "notifications/tools/list_changed" in observed_methods, "expected notifications/tools/list_changed after runtime tool addition; " f"observed methods: {observed_methods}"


async def test_resources_list_changed_notification_delivered(connect, request) -> None:
    """Adding a resource at runtime fires ``notifications/resources/list_changed``."""
    xfail_on(
        request,
        "gateway_proxy",
        "gateway_virtual",
        reason=(
            "GAP-008: gateway federation drops `mutate_resource_list`, so the trigger "
            "is unreachable. Even with federation fixed, the list_changed "
            "notification would still be blocked by the same POST-correlated-stream "
            "notification-relay issue tracked in GAP-001/GAP-002."
        ),
    )
    observed_methods: list[str] = []

    async def msg_handler(msg):
        method = _notification_method(msg)
        if method:
            observed_methods.append(method)

    async with connect(message_handler=msg_handler) as client:
        name = await resolve_tool(client, "mutate_resource_list")
        assert name is not None, "mutate_resource_list missing on reference target (unexpected)"
        await client.call_tool_mcp(name=name, arguments={})
        await asyncio.sleep(0.2)

    assert "notifications/resources/list_changed" in observed_methods, f"expected notifications/resources/list_changed; observed: {observed_methods}"


async def test_prompts_list_changed_notification_delivered(connect, request) -> None:
    """Adding a prompt at runtime fires ``notifications/prompts/list_changed``."""
    xfail_on(
        request,
        "gateway_proxy",
        "gateway_virtual",
        reason=("GAP-006 (prompts not federated) + GAP-008 (mutate_prompt_list dropped by gateway). " "Both paths make the trigger unreachable via the gateway."),
    )
    observed_methods: list[str] = []

    async def msg_handler(msg):
        method = _notification_method(msg)
        if method:
            observed_methods.append(method)

    async with connect(message_handler=msg_handler) as client:
        name = await resolve_tool(client, "mutate_prompt_list")
        assert name is not None, "mutate_prompt_list missing on reference target (unexpected)"
        await client.call_tool_mcp(name=name, arguments={})
        await asyncio.sleep(0.2)

    assert "notifications/prompts/list_changed" in observed_methods, f"expected notifications/prompts/list_changed; observed: {observed_methods}"


async def test_resources_updated_after_bump(connect, request) -> None:
    """bump_subscribable mutates the counter; a follow-up read reflects the increment."""
    xfail_on(
        request,
        "gateway_proxy",
        "gateway_virtual",
        reason="GAP-008: gateway federation drops `bump_subscribable` (among other tools); " "also GAP-009 for the associated `reference://mutable/counter` resource",
    )
    async with connect() as client:
        name = await resolve_tool(client, "bump_subscribable")
        assert name is not None, "bump_subscribable missing on reference target (unexpected)"
        before_raw = await client.read_resource("reference://mutable/counter")
        before = json.loads(before_raw[0].text)["counter"]
        await client.call_tool_mcp(name=name, arguments={})
        after_raw = await client.read_resource("reference://mutable/counter")
        after = json.loads(after_raw[0].text)["counter"]
    assert after == before + 1
