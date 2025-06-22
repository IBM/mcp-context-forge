# -*- coding: utf-8 -*-
"""Unit tests for **mcpgateway.transports.streamablehttp_transport**

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Focus areas
-----------
* **InMemoryEventStore** - storing, replaying, and eviction when the per‑stream
  max size is reached.
* **streamable_http_auth** - behaviour on happy path (valid Bearer token) and
  when verification fails (returns 401 and False).

No external MCP server is started; we test the isolated utility pieces that
have no heavy dependencies.
"""

from __future__ import annotations

from typing import List

import pytest
from starlette.types import Scope

# ---------------------------------------------------------------------------
# Import module under test - we only need the specific classes / functions
# ---------------------------------------------------------------------------
from mcpgateway.transports import streamablehttp_transport as tr  # noqa: E402

InMemoryEventStore = tr.InMemoryEventStore  # alias
streamable_http_auth = tr.streamable_http_auth

# ---------------------------------------------------------------------------
# InMemoryEventStore tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_store_store_and_replay():
    store = InMemoryEventStore(max_events_per_stream=10)
    stream_id = "abc"

    # store two events
    eid1 = await store.store_event(stream_id, {"id": 1})
    eid2 = await store.store_event(stream_id, {"id": 2})

    sent: List[tr.EventMessage] = []

    async def collector(msg):
        sent.append(msg)

    returned_stream = await store.replay_events_after(eid1, collector)

    assert returned_stream == stream_id
    # Only the *second* event is replayed
    assert len(sent) == 1 and sent[0].message["id"] == 2
    assert sent[0].event_id == eid2


@pytest.mark.asyncio
async def test_event_store_eviction():
    """Oldest event should be evicted once per‑stream limit is exceeded."""
    store = InMemoryEventStore(max_events_per_stream=1)
    stream_id = "s"

    eid_old = await store.store_event(stream_id, {"x": "old"})
    # Second insert causes eviction of the first (deque maxlen = 1)
    await store.store_event(stream_id, {"x": "new"})

    # The evicted event ID should no longer be replayable
    sent: List[tr.EventMessage] = []

    async def collector(_):
        sent.append(_)

    result = await store.replay_events_after(eid_old, collector)

    assert result is None  # event no longer known
    assert sent == []  # callback not invoked


# ---------------------------------------------------------------------------
# streamable_http_auth tests
# ---------------------------------------------------------------------------


def _make_scope(path: str, headers: list[tuple[bytes, bytes]] | None = None) -> Scope:  # helper
    return {
        "type": "http",
        "path": path,
        "headers": headers or [],
    }


@pytest.mark.asyncio
async def test_auth_all_ok(monkeypatch):
    """Valid Bearer token passes; function returns True and does *not* send."""

    async def fake_verify(token):  # noqa: D401 - stub
        assert token == "good-token"
        return {"ok": True}

    monkeypatch.setattr(tr, "verify_credentials", fake_verify)

    messages = []

    async def send(msg):  # collect ASGI messages for later inspection
        messages.append(msg)

    scope = _make_scope(
        "/servers/1/mcp",
        headers=[(b"authorization", b"Bearer good-token")],
    )

    assert await streamable_http_auth(scope, None, send) is True
    assert messages == []  # nothing sent - auth succeeded


@pytest.mark.asyncio
async def test_auth_failure(monkeypatch):
    """When verify_credentials raises, auth func responds 401 and returns False."""

    async def fake_verify(_):  # noqa: D401 - stub that always fails
        raise ValueError("bad token")

    monkeypatch.setattr(tr, "verify_credentials", fake_verify)

    sent = []

    async def send(msg):
        sent.append(msg)

    scope = _make_scope(
        "/servers/1/mcp",
        headers=[(b"authorization", b"Bearer bad")],
    )

    result = await streamable_http_auth(scope, None, send)

    # First ASGI message should be http.response.start with 401
    assert result is False
    assert sent and sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == tr.HTTP_401_UNAUTHORIZED


# ---------------------------------------------------------------------------
# SamplingHandler tests
# ---------------------------------------------------------------------------

import types as _t  # local alias for creating simple stubs

from mcpgateway.handlers import sampling as sp  # noqa: E402

SamplingHandler = sp.SamplingHandler
SamplingError = sp.SamplingError


@pytest.fixture()
def handler():
    return SamplingHandler()


# ---------------------------------------------------------------------------
# _select_model
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_select_model_by_hint(handler):
    """Model hint should override scoring logic."""

    prefs = _t.SimpleNamespace(
        hints=[_t.SimpleNamespace(name="sonnet")],
        cost_priority=0,
        speed_priority=0,
        intelligence_priority=0,
    )

    assert handler._select_model(prefs) == "claude-3-sonnet"  # pylint: disable=protected-access


# ---------------------------------------------------------------------------
# _validate_message
# ---------------------------------------------------------------------------


def test_validate_message(handler):
    valid_text = {"role": "user", "content": {"type": "text", "text": "hi"}}
    valid_image = {
        "role": "assistant",
        "content": {"type": "image", "data": "xxx", "mime_type": "image/png"},
    }
    invalid = {"role": "user", "content": {"type": "text"}}  # missing text value

    assert handler._validate_message(valid_text)  # pylint: disable=protected-access
    assert handler._validate_message(valid_image)  # pylint: disable=protected-access
    assert not handler._validate_message(invalid)  # pylint: disable=protected-access


# ---------------------------------------------------------------------------
# create_message success + error paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_message_success(monkeypatch, handler):
    # Patch ModelPreferences.parse_obj to return neutral prefs (no hints)
    neutral_prefs = _t.SimpleNamespace(hints=[], cost_priority=0.33, speed_priority=0.33, intelligence_priority=0.34)
    monkeypatch.setattr(sp.ModelPreferences, "parse_obj", lambda _x: neutral_prefs)

    request = {
        "messages": [
            {"role": "user", "content": {"type": "text", "text": "Hello"}},
        ],
        "maxTokens": 5,
        "modelPreferences": {},
    }

    result = await handler.create_message(db=None, request=request)

    assert result.role == sp.Role.ASSISTANT
    assert result.content.text.startswith("You said: Hello")


@pytest.mark.asyncio
async def test_create_message_no_messages(monkeypatch, handler):
    monkeypatch.setattr(sp.ModelPreferences, "parse_obj", lambda _x: _t.SimpleNamespace(hints=[], cost_priority=0, speed_priority=0, intelligence_priority=0))

    request = {"messages": [], "maxTokens": 5, "modelPreferences": {}}

    with pytest.raises(SamplingError):
        await handler.create_message(db=None, request=request)
