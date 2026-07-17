# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/a2a_compliance/v1_0_0/test_messages_artifacts.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Message and artifact shape compliance for A2A 1.0.0.
These assertions cover the response payload shape — what fields are
populated when the agent successfully echoes a message. The SDK
Client is used for round-trips so the assertions read at the Python
object level rather than the JSON wire level. Wire-level
field-presence assertions live in ``test_agent_card.py``.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from a2a.client.client import Client
from a2a.types import Message, Part, Role, SendMessageRequest

pytestmark = [pytest.mark.a2a, pytest.mark.a2a_v1_0_0, pytest.mark.a2a_messages_artifacts]


def _user_message(text: str) -> Message:
    """Build a minimal user-role Message with a single text part."""
    return Message(
        role=Role.ROLE_USER,
        message_id=str(uuid4()),
        parts=[Part(text=text)],
    )


@pytest.mark.asyncio
async def test_send_message_response_populates_message_or_task(client: Client) -> None:
    """A successful ``send_message`` MUST yield a response containing a Message or Task.

    The streaming response can carry either: a finalized Message (for
    synchronous echo agents like ours) or a Task (for agents that
    enqueue work). Both shapes are valid; the assertion is "at least
    one of them present in the stream".
    """
    request = SendMessageRequest(message=_user_message("hello shape"))
    responses = [r async for r in client.send_message(request)]
    assert responses, "send_message yielded zero responses"

    serialized = repr(responses)
    assert ("message" in serialized.lower()) or ("task" in serialized.lower()), f"response stream should carry a Message or Task; got: {serialized[:500]}"


@pytest.mark.asyncio
async def test_echo_response_carries_text_part(client: Client) -> None:
    """Echo response MUST include the original text content in at least one part.

    The echo agent's contract is to return what it received; the part
    structure (``parts: [Part]``) is preserved end-to-end. If the
    text content is missing from the response stream, either the
    serialization round-trip is dropping fields or the gateway
    federation hop is rewriting parts.
    """
    payload = f"shape-marker-{uuid4().hex[:8]}"
    request = SendMessageRequest(message=_user_message(payload))
    responses = [r async for r in client.send_message(request)]
    serialized = repr(responses)
    assert payload in serialized, f"echoed text {payload!r} not present in response: {serialized[:500]}"
