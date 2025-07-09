# -*- coding: utf-8 -*-
"""Unit tests for **mcpgateway.transports.streamablehttp_transport**

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Author: Mihai Criveti

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
from contextlib import asynccontextmanager
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

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
SessionManagerWrapper = tr.SessionManagerWrapper

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


@pytest.mark.asyncio
async def test_event_store_store_event_eviction():
    """Eviction removes from event_index as well."""
    store = InMemoryEventStore(max_events_per_stream=2)
    stream_id = "s"
    eid1 = await store.store_event(stream_id, {"id": 1})
    eid2 = await store.store_event(stream_id, {"id": 2})
    eid3 = await store.store_event(stream_id, {"id": 3})  # should evict eid1
    assert eid1 not in store.event_index
    assert eid2 in store.event_index
    assert eid3 in store.event_index


@pytest.mark.asyncio
async def test_event_store_replay_events_after_not_found(caplog):
    """replay_events_after returns None and logs if event not found."""
    store = InMemoryEventStore()
    sent = []
    result = await store.replay_events_after("notfound", lambda x: sent.append(x))
    assert result is None
    assert sent == []


@pytest.mark.asyncio
async def test_event_store_replay_events_after_multiple():
    """replay_events_after yields all events after the given one."""
    store = InMemoryEventStore(max_events_per_stream=10)
    stream_id = "abc"
    eid1 = await store.store_event(stream_id, {"id": 1})
    eid2 = await store.store_event(stream_id, {"id": 2})
    eid3 = await store.store_event(stream_id, {"id": 3})

    sent = []

    async def collector(msg):
        sent.append(msg)

    await store.replay_events_after(eid1, collector)
    assert len(sent) == 2
    assert sent[0].event_id == eid2
    assert sent[1].event_id == eid3


# ---------------------------------------------------------------------------
# get_db, call_tool & list_tools tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_db_context_manager():
    """Test that get_db yields a db and closes it after use."""
    with patch("mcpgateway.transports.streamablehttp_transport.SessionLocal") as mock_session_local:
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db

        # First-Party
        from mcpgateway.transports.streamablehttp_transport import get_db

        async with get_db() as db:
            assert db is mock_db
            mock_db.close.assert_not_called()
        mock_db.close.assert_called_once()


@pytest.mark.asyncio
async def test_call_tool_success(monkeypatch):
    """Test call_tool returns content on success."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, tool_service, types

    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_content = MagicMock()
    mock_content.type = "text"
    mock_content.text = "hello"
    mock_result.content = [mock_content]

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", AsyncMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_db), __aexit__=AsyncMock())))
    monkeypatch.setattr(tool_service, "invoke_tool", AsyncMock(return_value=mock_result))

    result = await call_tool("mytool", {"foo": "bar"})
    assert isinstance(result, list)
    assert isinstance(result[0], types.TextContent)
    assert result[0].type == "text"
    assert result[0].text == "hello"


@pytest.mark.asyncio
async def test_call_tool_success(monkeypatch):
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, tool_service, types

    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_content = MagicMock()
    mock_content.type = "text"
    mock_content.text = "hello"
    mock_result.content = [mock_content]

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tool_service, "invoke_tool", AsyncMock(return_value=mock_result))

    result = await call_tool("mytool", {"foo": "bar"})
    assert isinstance(result, list)
    assert isinstance(result[0], types.TextContent)
    assert result[0].type == "text"
    assert result[0].text == "hello"


@pytest.mark.asyncio
async def test_call_tool_no_content(monkeypatch, caplog):
    """Test call_tool returns [] and logs warning if no content."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, tool_service

    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_result.content = []

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tool_service, "invoke_tool", AsyncMock(return_value=mock_result))

    with caplog.at_level("WARNING"):
        result = await call_tool("mytool", {"foo": "bar"})
        assert result == []
        assert "No content returned by tool: mytool" in caplog.text


@pytest.mark.asyncio
async def test_call_tool_exception(monkeypatch, caplog):
    """Test call_tool returns [] and logs exception on error."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, tool_service

    mock_db = MagicMock()

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tool_service, "invoke_tool", AsyncMock(side_effect=Exception("fail!")))

    with caplog.at_level("ERROR"):
        result = await call_tool("mytool", {"foo": "bar"})
        assert result == []
        assert "Error calling tool 'mytool': fail!" in caplog.text


@pytest.mark.asyncio
async def test_list_tools_with_server_id(monkeypatch):
    """Test list_tools returns tools for a server_id."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import list_tools, server_id_var, tool_service

    mock_db = MagicMock()
    mock_tool = MagicMock()
    mock_tool.name = "t"
    mock_tool.description = "desc"
    mock_tool.input_schema = {"type": "object"}
    mock_tool.annotations = {}

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tool_service, "list_server_tools", AsyncMock(return_value=[mock_tool]))

    token = server_id_var.set("123")
    result = await list_tools()
    server_id_var.reset(token)
    assert isinstance(result, list)
    assert result[0].name == "t"
    assert result[0].description == "desc"


@pytest.mark.asyncio
async def test_list_tools_no_server_id(monkeypatch):
    """Test list_tools returns tools when no server_id is set."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import list_tools, server_id_var, tool_service

    mock_db = MagicMock()
    mock_tool = MagicMock()
    mock_tool.name = "t"
    mock_tool.description = "desc"
    mock_tool.input_schema = {"type": "object"}
    mock_tool.annotations = {}

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tool_service, "list_tools", AsyncMock(return_value=[mock_tool]))

    # Ensure server_id is None
    token = server_id_var.set(None)
    result = await list_tools()
    server_id_var.reset(token)
    assert isinstance(result, list)
    assert result[0].name == "t"
    assert result[0].description == "desc"


@pytest.mark.asyncio
async def test_list_tools_exception(monkeypatch, caplog):
    """Test list_tools returns [] and logs exception on error."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import list_tools, server_id_var, tool_service

    mock_db = MagicMock()

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tool_service, "list_tools", AsyncMock(side_effect=Exception("fail!")))

    token = server_id_var.set(None)
    with caplog.at_level("ERROR"):
        result = await list_tools()
        assert result == []
        assert "Error listing tools:fail!" in caplog.text
    server_id_var.reset(token)


# ---------------------------------------------------------------------------
# streamable_http_auth tests
# ---------------------------------------------------------------------------


# def _make_scope(path: str, headers: list[tuple[bytes, bytes]] | None = None) -> Scope:  # helper
#     return {
#         "type": "http",
#         "path": path,
#         "headers": headers or [],
#     }


def _make_scope(path: str, headers: list[tuple[bytes, bytes]] | None = None) -> Scope:
    return {
        "type": "http",
        "path": path,
        "headers": headers or [],
        "modified_path": path,
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


@pytest.mark.asyncio
async def test_streamable_http_auth_skips_non_mcp():
    """Auth returns True for non-/mcp paths."""
    scope = _make_scope("/notmcp")
    called = []

    async def send(msg):
        called.append(msg)

    result = await streamable_http_auth(scope, None, send)
    assert result is True
    assert called == []


@pytest.mark.asyncio
async def test_streamable_http_auth_no_authorization():
    """Auth returns False and sends 401 if no Authorization header."""
    scope = _make_scope("/servers/1/mcp")
    called = []

    async def send(msg):
        called.append(msg)

    result = await streamable_http_auth(scope, None, send)
    assert result is False
    assert called and called[0]["type"] == "http.response.start"
    assert called[0]["status"] == tr.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_streamable_http_auth_wrong_scheme(monkeypatch):
    """Auth returns False and sends 401 if Authorization is not Bearer."""

    async def fake_verify(token):
        raise AssertionError("Should not be called")

    monkeypatch.setattr(tr, "verify_credentials", fake_verify)
    scope = _make_scope("/servers/1/mcp", headers=[(b"authorization", b"Basic foobar")])
    called = []

    async def send(msg):
        called.append(msg)

    result = await streamable_http_auth(scope, None, send)
    assert result is False
    assert called and called[0]["type"] == "http.response.start"
    assert called[0]["status"] == tr.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_streamable_http_auth_bearer_no_token(monkeypatch):
    """Auth returns False and sends 401 if Bearer but no token."""

    async def fake_verify(token):
        raise AssertionError("Should not be called")

    monkeypatch.setattr(tr, "verify_credentials", fake_verify)
    scope = _make_scope("/servers/1/mcp", headers=[(b"authorization", b"Bearer")])
    called = []

    async def send(msg):
        called.append(msg)

    result = await streamable_http_auth(scope, None, send)
    assert result is False
    assert called and called[0]["type"] == "http.response.start"
    assert called[0]["status"] == tr.HTTP_401_UNAUTHORIZED


# ---------------------------------------------------------------------------
# Session Manager tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_manager_wrapper_initialization(monkeypatch):
    """Test SessionManagerWrapper initialize and shutdown."""
    # Standard
    from contextlib import asynccontextmanager

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def handle_request(self, scope, receive, send):
            self.called = True

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    wrapper = SessionManagerWrapper()
    await wrapper.initialize()
    await wrapper.shutdown()


@pytest.mark.asyncio
async def test_session_manager_wrapper_handle_streamable_http(monkeypatch):
    """Test handle_streamable_http sets server_id and calls handle_request."""
    # Standard
    from contextlib import asynccontextmanager

    async def send(msg):
        sent.append(msg)

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def handle_request(self, scope, receive, send_func):
            self.called = True
            await send_func("ok")

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    wrapper = SessionManagerWrapper()
    await wrapper.initialize()
    scope = _make_scope("/servers/123/mcp")
    sent = []
    await wrapper.handle_streamable_http(scope, None, send)
    await wrapper.shutdown()
    assert sent == ["ok"]


@pytest.mark.asyncio
async def test_session_manager_wrapper_handle_streamable_http_exception(monkeypatch, caplog):
    """Test handle_streamable_http logs and raises on exception."""
    # Standard
    from contextlib import asynccontextmanager

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def handle_request(self, scope, receive, send):
            self.called = True
            raise RuntimeError("fail")

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    wrapper = SessionManagerWrapper()
    await wrapper.initialize()
    scope = _make_scope("/servers/123/mcp")

    async def send(msg):
        pass

    with pytest.raises(RuntimeError):
        await wrapper.handle_streamable_http(scope, None, send)
    await wrapper.shutdown()
    assert "Error handling streamable HTTP request" in caplog.text
