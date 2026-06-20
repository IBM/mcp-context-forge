# -*- coding: utf-8 -*-
"""JSON-RPC method coverage for A2A 0.3.0.

Location: ./tests/live_gateway/a2a_compliance/v0_3_0/test_jsonrpc_methods.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

These tests use the ``a2a.client.Client`` SDK abstraction and run
across the full ``(target, transport)`` matrix. Gateway-target cells
xfail blanket via A2A-GAP-001 (see conftest's
``pytest_collection_modifyitems``). The reference target exercises
the live ``a2a_echo_agent``.

Methods covered: ``SendMessage``, ``GetTask``, ``ListTasks``,
``CancelTask``. ``GetExtendedAgentCard`` is covered via the
``/extendedAgentCard`` REST endpoint in ``test_well_known.py`` and
not duplicated here.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from a2a.client.client import Client
from a2a.types import (
    CancelTaskRequest,
    GetTaskRequest,
    ListTasksRequest,
    Message,
    Part,
    Role,
    SendMessageRequest,
)
from a2a.utils.errors import TaskNotFoundError

pytestmark = [pytest.mark.a2a, pytest.mark.a2a_v0_3_0, pytest.mark.a2a_jsonrpc]


def _user_message(text: str) -> Message:
    """Build a minimal user-role Message with a single text part."""
    return Message(
        role=Role.ROLE_USER,
        message_id=str(uuid4()),
        parts=[Part(text=text)],
    )


@pytest.mark.asyncio
async def test_send_message_returns_at_least_one_response(client: Client) -> None:
    """``SendMessage`` MUST yield at least one stream response.

    The echo agent completes synchronously, so a single response is
    expected. Streaming agents would yield multiple, but the contract
    is "≥1" not "exactly 1".
    """
    request = SendMessageRequest(message=_user_message("hello a2a"))
    responses = [r async for r in client.send_message(request)]
    assert len(responses) >= 1, f"send_message produced zero responses: {responses!r}"


@pytest.mark.asyncio
async def test_send_message_echoes_input_text(client: Client) -> None:
    """The echo agent's response MUST include the original input text.

    Cross-target invariant: the gateway, when it lands, MUST preserve
    the echoed payload byte-for-byte. Drift here proves a transformation
    layer is corrupting message content.
    """
    payload = f"echo-marker-{uuid4().hex[:8]}"
    request = SendMessageRequest(message=_user_message(payload))
    responses = [r async for r in client.send_message(request)]
    serialized = repr(responses)
    assert payload in serialized, f"echoed payload {payload!r} not found in response stream: {serialized[:500]}"


@pytest.mark.asyncio
async def test_get_task_for_unknown_id_raises(client: Client) -> None:
    """``GetTask`` with an unknown ID MUST raise an A2A client error.

    The exact error code/class can be tightened once the SDK's error
    taxonomy stabilizes; here we just assert an exception (not a
    silently-empty Task) escapes the call. Echo agent returns
    ``TaskNotFoundError`` for unknown IDs.
    """
    request = GetTaskRequest(id=f"nonexistent-task-{uuid4()}")
    with pytest.raises(TaskNotFoundError):
        await client.get_task(request)


@pytest.mark.asyncio
async def test_list_tasks_returns_response(client: Client) -> None:
    """``ListTasks`` MUST return a ListTasksResponse, even if empty.

    A2A 0.3.0 JSONRPC has no ``ListTasks`` method (added in 1.0.0);
    the SDK's ``CompatJsonRpcTransport`` raises ``NotImplementedError``
    explicitly for this call. Skip on that path — there's nothing on
    the wire to validate.
    """
    request = ListTasksRequest()
    try:
        response = await client.list_tasks(request)
    except NotImplementedError as exc:
        pytest.skip(f"list_tasks unsupported on this protocol version: {exc}")
    assert response is not None, "list_tasks returned None"


@pytest.mark.asyncio
async def test_cancel_task_for_unknown_id_raises(client: Client) -> None:
    """``CancelTask`` with an unknown ID MUST raise an A2A client error.

    Same shape as the GetTask unknown-ID guard — silent success would
    mask a federation bug where cancellations are dropped instead of
    routed.
    """
    request = CancelTaskRequest(id=f"nonexistent-task-{uuid4()}")
    with pytest.raises(TaskNotFoundError):
        await client.cancel_task(request)
