# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/handlers/test_sampling.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for **mcpgateway.transports.streamablehttp_transport**
Focus areas
-----------
* **InMemoryEventStore** - storing, replaying, and eviction when the per-stream
  max size is reached.
* **streamable_http_auth** - behaviour on happy path (valid Bearer token) and
  when verification fails (returns 401 and False).

No external MCP server is started; we test the isolated utility pieces that
have no heavy dependencies.
"""

# Future
from __future__ import annotations

# Standard
from typing import List

# Third-Party
import pytest
from starlette.types import Scope

# First-Party
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
async def test_event_store_no_new_events():
    store = InMemoryEventStore(max_events_per_stream=10)
    stream_id = "stream1"
    eid = await store.store_event(stream_id, {"val": 42})
    sent = []

    async def collector(msg):
        sent.append(msg)

    returned = await store.replay_events_after(eid, collector)
    assert returned == stream_id
    # No new events were stored, so nothing should be sent
    assert sent == []


@pytest.mark.asyncio
async def test_event_store_multiple_replay():
    store = InMemoryEventStore(max_events_per_stream=10)
    stream_id = "stream1"
    # Store three events
    eids = []
    for i in range(3):
        eids.append(await store.store_event(stream_id, {"n": i}))
    sent = []

    async def collector(msg):
        sent.append(msg)

    # Replay after the first event should get the 2nd and 3rd
    returned = await store.replay_events_after(eids[0], collector)
    assert returned == stream_id
    assert [msg.message["n"] for msg in sent] == [1, 2]


@pytest.mark.asyncio
async def test_event_store_cross_streams():
    store = InMemoryEventStore(max_events_per_stream=10)
    s1, s2 = "s1", "s2"
    # Store events in two different streams
    eid1_s1 = await store.store_event(s1, {"val": 1})
    eid1_s2 = await store.store_event(s2, {"val": 2})
    eid2_s1 = await store.store_event(s1, {"val": 3})
    sent = []

    async def collector(msg):
        sent.append(msg)

    # Replay on stream s1 after its first ID
    returned = await store.replay_events_after(eid1_s1, collector)
    assert returned == s1
    # Should only get the event from s1 (val=3), not the s2 event
    assert [msg.message["val"] for msg in sent] == [3]


@pytest.mark.asyncio
async def test_event_store_eviction_of_oldest():
    store = InMemoryEventStore(max_events_per_stream=1)
    stream_id = "s"
    eid_old = await store.store_event(stream_id, {"x": "old"})
    # Storing a second event evicts the first (due to maxlen=1)
    await store.store_event(stream_id, {"x": "new"})
    sent = []

    async def collector(msg):
        sent.append(msg)

    result = await store.replay_events_after(eid_old, collector)
    # The first event ID has been evicted, so it should not be found
    assert result is None
    assert sent == []


@pytest.mark.asyncio
async def test_event_store_eviction():
    """Oldest event should be evicted once per-stream limit is exceeded."""
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
    """When verify_credentials raises and mcp_require_auth=True, auth func responds 401 and returns False."""

    async def fake_verify(_):  # noqa: D401 - stub that always fails
        raise ValueError("bad token")

    monkeypatch.setattr(tr, "verify_credentials", fake_verify)
    # Enable strict auth mode to test 401 behavior
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_require_auth", True)

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


@pytest.mark.asyncio
async def test_auth_valid_token(monkeypatch):
    # Simulate verify_credentials always succeeding
    async def fake_verify(token):
        assert token == "good-token"
        return {"ok": True}

    monkeypatch.setattr(tr, "verify_credentials", fake_verify)

    messages = []

    async def send(msg):
        messages.append(msg)

    scope = _make_scope("/servers/1/mcp", headers=[(b"authorization", b"Bearer good-token")])
    assert await streamable_http_auth(scope, None, send) is True
    assert messages == []  # No response sent on success


@pytest.mark.asyncio
async def test_auth_invalid_token_raises(monkeypatch):
    # Simulate verify_credentials raising (invalid token scenario)
    async def fake_verify(token):
        raise ValueError("bad token")

    monkeypatch.setattr(tr, "verify_credentials", fake_verify)
    # Enable strict auth mode to test 401 behavior
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_require_auth", True)

    sent = []

    async def send(msg):
        sent.append(msg)

    scope = _make_scope("/servers/1/mcp", headers=[(b"authorization", b"Bearer bad-token")])
    result = await streamable_http_auth(scope, None, send)
    assert result is False
    # Expect an HTTP 401 response to be sent
    assert sent and sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == tr.HTTP_401_UNAUTHORIZED


# ---------------------------------------------------------------------------
# SamplingHandler tests
# ---------------------------------------------------------------------------

# Standard
import types as _t  # local alias for creating simple stubs

# First-Party
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


@pytest.mark.asyncio
async def test_select_model_no_suitable_model(handler):
    # Remove all supported models to force error
    handler._supported_models = {}
    prefs = _t.SimpleNamespace(hints=[], cost_priority=0, speed_priority=0, intelligence_priority=0)
    with pytest.raises(SamplingError):
        handler._select_model(prefs)


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


def test_validate_message_missing_image_fields(handler):
    # Missing 'data' field in image content
    invalid_img1 = {"role": "assistant", "content": {"type": "image", "mime_type": "image/png"}}
    # Missing 'mime_type' field
    invalid_img2 = {"role": "assistant", "content": {"type": "image", "data": "AAA"}}
    # Unknown content type
    invalid_img3 = {"role": "user", "content": {"type": "audio", "data": "xxx"}}

    assert not handler._validate_message(invalid_img1)
    assert not handler._validate_message(invalid_img2)
    assert not handler._validate_message(invalid_img3)


@pytest.mark.asyncio
async def test_add_context_returns_messages(handler):
    # Should just return the messages as-is (stub)
    msgs = [{"role": "user", "content": {"type": "text", "text": "hi"}}]
    result = await handler._add_context(None, msgs, "irrelevant")
    assert result == msgs


def test_mock_sample_no_user_message(handler):
    # No user message in the list
    msgs = [{"role": "assistant", "content": {"type": "text", "text": "hi"}}]
    result = handler._mock_sample(msgs)
    assert "I'm not sure" in result


def test_mock_sample_image_message(handler):
    # Last user message is image
    msgs = [{"role": "user", "content": {"type": "image", "data": "xxx", "mime_type": "image/png"}}]
    result = handler._mock_sample(msgs)
    assert "I see the image" in result


def test_validate_message_invalid_role(handler):
    msg = {"role": "system", "content": {"type": "text", "text": "hi"}}
    assert not handler._validate_message(msg)


def test_validate_message_missing_content(handler):
    msg = {"role": "user"}
    assert not handler._validate_message(msg)


def test_validate_message_exception_path(handler):
    # Simulate exception in validation
    class BadDict(dict):
        def get(self, k, d=None):
            raise Exception("fail")

    msg = {"role": "user", "content": BadDict()}
    assert not handler._validate_message(msg)


# ---------------------------------------------------------------------------
# create_message success + error paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_message_success(monkeypatch, handler):
    # Patch ModelPreferences.parse_obj to return neutral prefs (no hints)
    neutral_prefs = _t.SimpleNamespace(hints=[], cost_priority=0.33, speed_priority=0.33, intelligence_priority=0.34)
    monkeypatch.setattr(sp.ModelPreferences, "model_validate", lambda _x: neutral_prefs)

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
async def test_create_message_multiple_user_messages(monkeypatch, handler):
    # Return neutral preferences with no hints
    neutral_prefs = _t.SimpleNamespace(hints=[], cost_priority=0.5, speed_priority=0.3, intelligence_priority=0.2)
    monkeypatch.setattr(sp.ModelPreferences, "model_validate", lambda x: neutral_prefs)

    # Conversation with an assistant message and then a user message
    request = {"messages": [{"role": "assistant", "content": {"type": "text", "text": "Hi"}}, {"role": "user", "content": {"type": "text", "text": "Hello"}}], "maxTokens": 10, "modelPreferences": {}}

    result = await handler.create_message(db=None, request=request)
    assert result.role == sp.Role.ASSISTANT
    # The response should reference the last user message "Hello"
    assert "You said: Hello" in result.content.text


@pytest.mark.asyncio
async def test_create_message_no_messages(monkeypatch, handler):
    monkeypatch.setattr(sp.ModelPreferences, "model_validate", lambda _x: _t.SimpleNamespace(hints=[], cost_priority=0, speed_priority=0, intelligence_priority=0))

    request = {"messages": [], "maxTokens": 5, "modelPreferences": {}}

    with pytest.raises(SamplingError):
        await handler.create_message(db=None, request=request)


@pytest.mark.asyncio
async def test_create_message_raises_on_no_user_message(monkeypatch, handler):
    # Even if there are assistant messages, at least one user message is required
    monkeypatch.setattr(sp.ModelPreferences, "model_validate", lambda x: _t.SimpleNamespace(hints=[], cost_priority=0, speed_priority=0, intelligence_priority=0))
    request = {"messages": [], "maxTokens": 5, "modelPreferences": {}}
    with pytest.raises(SamplingError):
        await handler.create_message(db=None, request=request)


@pytest.mark.asyncio
async def test_create_message_missing_max_tokens(monkeypatch, handler):
    monkeypatch.setattr(sp.ModelPreferences, "model_validate", lambda _x: _t.SimpleNamespace(hints=[], cost_priority=0, speed_priority=0, intelligence_priority=0))
    request = {"messages": [{"role": "user", "content": {"type": "text", "text": "hi"}}]}
    with pytest.raises(SamplingError):
        await handler.create_message(db=None, request=request)


@pytest.mark.asyncio
async def test_create_message_invalid_message(monkeypatch, handler):
    monkeypatch.setattr(sp.ModelPreferences, "model_validate", lambda _x: _t.SimpleNamespace(hints=[], cost_priority=0, speed_priority=0, intelligence_priority=0))
    # Invalid message: missing text
    request = {
        "messages": [{"role": "user", "content": {"type": "text"}}],
        "maxTokens": 5,
        "modelPreferences": {},
    }
    with pytest.raises(SamplingError):
        await handler.create_message(db=None, request=request)


@pytest.mark.asyncio
async def test_create_message_exception_propagation(monkeypatch, handler):
    # Patch _select_model to raise
    monkeypatch.setattr(handler, "_select_model", lambda prefs: (_ for _ in ()).throw(Exception("fail")))
    monkeypatch.setattr(sp.ModelPreferences, "model_validate", lambda _x: _t.SimpleNamespace(hints=[], cost_priority=0, speed_priority=0, intelligence_priority=0))
    request = {
        "messages": [{"role": "user", "content": {"type": "text", "text": "hi"}}],
        "maxTokens": 5,
        "modelPreferences": {},
    }
    with pytest.raises(SamplingError) as exc:
        await handler.create_message(db=None, request=request)
    assert "fail" in str(exc.value)
